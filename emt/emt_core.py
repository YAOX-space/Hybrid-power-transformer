"""
emt_core.py — Electromagnetic-transient (EMT) nodal solver, EMTP-style.

Switching-level circuit simulator built on the trapezoidal companion-model nodal
method (the same family of method SimPowerSystems uses internally). Goal: a Python-
native, switching-level model that reproduces the Simulink HPT model's behaviour
(accuracy over speed — fixed 1 µs step, full bridge switching, no averaging).

Components (all stamped into a nodal conductance matrix G with a history/source RHS):
  - R                resistor
  - L                inductor          (trapezoidal Norton companion)
  - C                capacitor         (trapezoidal Norton companion)
  - CoupledL         k-winding mutual inductance (transformers)
  - VSourceTh        EMF behind series R(+L)  → Norton, so pure nodal (no MNA)
  - Switch           IGBT + antiparallel diode (+ snubber R), gate-controlled,
                     with iterative diode/valve consistency resolution

Node 'gnd' (or 0) is the reference and is eliminated from the solve.
Every voltage source has a series impedance (true for the HPT grid: Z_grid), so the
whole network is solvable by plain nodal analysis (G·V = I) — no ideal sources.

Sign convention for a 2-terminal companion element between (n1,n2):
    i(n1→n2) = g·(V[n1]-V[n2]) + c        (c = history/source constant)
  conductance stamp: G[n1,n1]+=g, G[n2,n2]+=g, G[n1,n2]-=g, G[n2,n1]-=g
  RHS stamp:         I[n1]-=c,  I[n2]+=c
"""
from __future__ import annotations
import numpy as np


class Circuit:
    def __init__(self, dt: float):
        self.dt = float(dt)
        self._names = {}          # node name -> index (ground excluded)
        self._n = 0
        self.comps = []
        self.t = 0.0
        self._G0 = None           # static conductance (R/L/C/coupledL), precomputed
        self._built = False

    # ── node management ────────────────────────────────────────────────────────
    def node(self, name) -> int:
        if name in ('gnd', 0, '0', None):
            return -1
        if name not in self._names:
            self._names[name] = self._n
            self._n += 1
        return self._names[name]

    # ── component factories ─────────────────────────────────────────────────────
    def add_R(self, n1, n2, R):
        self.comps.append(R_(self.node(n1), self.node(n2), R))

    def add_L(self, n1, n2, L, i0=0.0):
        c = L_(self.node(n1), self.node(n2), L, self.dt, i0); self.comps.append(c); return c

    def add_C(self, n1, n2, C, v0=0.0):
        c = C_(self.node(n1), self.node(n2), C, self.dt, v0); self.comps.append(c); return c

    def add_coupledL(self, pairs, Lmat, i0=None):
        idx = [(self.node(a), self.node(b)) for (a, b) in pairs]
        c = CoupledL_(idx, np.asarray(Lmat, float), self.dt, i0); self.comps.append(c); return c

    def add_vsource_th(self, n1, n2, efunc, R, L=0.0):
        """EMF efunc(t) from n1->n2 behind series R (and optional L). Norton form."""
        c = VSourceTh_(self.node(n1), self.node(n2), efunc, R, L, self.dt); self.comps.append(c); return c

    def add_switch(self, a, k, ron=1e-3, roff=1e6, rsnub=1e5, is_diode=True):
        """IGBT(a->k) + antiparallel diode(k->a) + snubber R across. Gate set per step."""
        c = Switch_(self.node(a), self.node(k), ron, roff, rsnub, is_diode); self.comps.append(c); return c

    def add_fault(self, a, k, ron):
        """Gated fault branch / breaker (pure gated resistor, no diode action)."""
        c = Switch_(self.node(a), self.node(k), ron, 1e7, 1e7, is_diode=False)
        self.comps.append(c); return c

    # ── assembly ────────────────────────────────────────────────────────────────
    def build(self):
        N = self._n
        G0 = np.zeros((N, N))
        for c in self.comps:
            if isinstance(c, (R_, L_, C_, CoupledL_, VSourceTh_)):
                c.stamp_G(G0)
        self._G0 = G0
        self._V = np.zeros(N)
        self._built = True

    def _solve(self, gates):
        """One nodal solve with current switch states; returns node voltages V (len N)."""
        N = self._n
        G = self._G0.copy()
        I = np.zeros(N)
        for c in self.comps:
            if isinstance(c, Switch_):
                c.stamp_G(G)
            c.stamp_I(I, self.t)
        # solve G V = I
        V = np.linalg.solve(G, I)
        return V

    def step(self, gates: dict | None = None, max_switch_iter=60):
        """Advance one dt. gates: {switch_obj: 0/1}. Resolves diodes iteratively."""
        if not self._built:
            self.build()
        self.t += self.dt
        # apply gates
        if gates:
            for sw, g in gates.items():
                sw.gate = int(g)
        # set initial valve states from gates
        for c in self.comps:
            if isinstance(c, Switch_):
                c.set_initial_state()
        # iterative switch/diode resolution
        for _ in range(max_switch_iter):
            V = self._solve(gates)
            changed = False
            for c in self.comps:
                if isinstance(c, Switch_):
                    if c.update_state(V):
                        changed = True
            if not changed:
                break
        # commit history for stateful elements
        for c in self.comps:
            c.commit(V)
        self._V = V
        return V

    def v(self, name):
        i = self.node(name)
        return 0.0 if i < 0 else self._V[i]

    def vdiff(self, n1, n2):
        return self.v(n1) - self.v(n2)


# ── helpers ────────────────────────────────────────────────────────────────────
def _stampG(G, i, j, g):
    if i >= 0: G[i, i] += g
    if j >= 0: G[j, j] += g
    if i >= 0 and j >= 0:
        G[i, j] -= g; G[j, i] -= g

def _stampI(I, i, j, c):
    if i >= 0: I[i] -= c
    if j >= 0: I[j] += c

def _vd(V, i, j):
    vi = V[i] if i >= 0 else 0.0
    vj = V[j] if j >= 0 else 0.0
    return vi - vj


# ── components ───────────────────────────────────────────────────────────────────
class R_:
    def __init__(self, n1, n2, R): self.n1, self.n2, self.g = n1, n2, 1.0/R
    def stamp_G(self, G): _stampG(G, self.n1, self.n2, self.g)
    def stamp_I(self, I, t): pass
    def commit(self, V): pass

class L_:
    def __init__(self, n1, n2, L, dt, i0):
        self.n1, self.n2 = n1, n2
        self.g = dt/(2*L); self.iL = i0; self.vprev = 0.0
        self.hist = i0 + self.g*0.0
    def stamp_G(self, G): _stampG(G, self.n1, self.n2, self.g)
    def stamp_I(self, I, t): _stampI(I, self.n1, self.n2, self.hist)
    def commit(self, V):
        v = _vd(V, self.n1, self.n2)
        self.iL = self.g*v + self.hist
        self.hist = self.iL + self.g*v          # I_hist for next step

class C_:
    def __init__(self, n1, n2, C, dt, v0):
        self.n1, self.n2 = n1, n2
        self.g = 2*C/dt; self.iC = 0.0; self.vprev = v0
        self.J = self.g*v0 + 0.0
    def stamp_G(self, G): _stampG(G, self.n1, self.n2, self.g)
    def stamp_I(self, I, t): _stampI(I, self.n1, self.n2, -self.J)   # const = -J
    def commit(self, V):
        v = _vd(V, self.n1, self.n2)
        self.iC = self.g*v - self.J
        self.J = self.g*v + self.iC             # J for next step
        self.vprev = v

class CoupledL_:
    """k coupled windings; current i = Gm·v + hist, Gm = (dt/2)·L^{-1}."""
    def __init__(self, idx, Lmat, dt, i0):
        self.idx = idx; self.k = len(idx)
        self.Gm = (dt/2.0)*np.linalg.inv(Lmat)
        self.i = np.zeros(self.k) if i0 is None else np.asarray(i0, float).copy()
        self.hist = self.i.copy()
    def stamp_G(self, G):
        for a in range(self.k):
            ia, ib = self.idx[a]
            for b in range(self.k):
                ja, jb = self.idx[b]
                g = self.Gm[a, b]
                if g == 0: continue
                for (r, s) in ((ia, ja), (ib, jb)):
                    if r >= 0 and s >= 0: G[r, s] += g
                for (r, s) in ((ia, jb), (ib, ja)):
                    if r >= 0 and s >= 0: G[r, s] -= g
    def stamp_I(self, I, t):
        for a in range(self.k):
            ia, ib = self.idx[a]
            _stampI(I, ia, ib, self.hist[a])
    def commit(self, V):
        v = np.array([_vd(V, a, b) for (a, b) in self.idx])
        self.i = self.Gm @ v + self.hist
        self.hist = self.i + self.Gm @ v

class VSourceTh_:
    """EMF e(t) (+ terminal at n1) behind a SERIES RESISTANCE R only (Norton form).
    Branch current i(n1->n2) = (v - e)/R = g*(V1-V2) - g*e, g=1/R.
    Grid series inductance, if any, is added separately as an explicit L_ via an
    internal node in the model assembly (keeps every companion validated/simple)."""
    def __init__(self, n1, n2, efunc, R, L=0.0, dt=0.0):
        assert L == 0.0, "VSourceTh_ is R-only; add grid L as a separate L_ element"
        self.n1, self.n2, self.efunc = n1, n2, efunc
        self.R = R; self.g = 1.0/R; self.i = 0.0
    def stamp_G(self, G): _stampG(G, self.n1, self.n2, self.g)
    def stamp_I(self, I, t):
        self._e = self.efunc(t)
        _stampI(I, self.n1, self.n2, -self.g*self._e)   # c = -g*e
    def commit(self, V):
        v = _vd(V, self.n1, self.n2)
        self.i = (v - self._e)/self.R

class Switch_:
    """IGBT(a->k) with antiparallel diode(k->a) + snubber R. gate in {0,1}.
    is_diode=False → plain gated resistor (breaker/fault): on iff gate==1."""
    def __init__(self, a, k, ron, roff, rsnub, is_diode=True):
        self.a, self.k = a, k
        self.ron, self.roff, self.gsnub = ron, roff, 1.0/rsnub
        self.gate = 0; self.on = False; self.is_diode = is_diode
    def set_initial_state(self):
        self.on = (self.gate == 1)
    def g(self):
        return (1.0/self.ron if self.on else 1.0/self.roff) + self.gsnub
    def stamp_G(self, G): _stampG(G, self.a, self.k, self.g())
    def stamp_I(self, I, t): pass
    def update_state(self, V):
        prev = self.on
        if not self.is_diode:
            self.on = (self.gate == 1)  # pure gated resistor
            return self.on != prev
        if self.gate == 1:
            self.on = True              # IGBT on → bidirectional
        else:
            # diode k->a conducts if forward biased: V[k] > V[a]  ⇒ v < 0
            self.on = (_vd(V, self.a, self.k) < 0.0)
        return self.on != prev
    def commit(self, V):
        self._v = _vd(V, self.a, self.k)
    def current(self):
        return self._v * (1.0/self.ron if self.on else 1.0/self.roff)
