# legacy_pre_audit — frt-v1 results (INVALIDATED 2026-06-22)

All `.mat/.txt` here were produced under **metrics_version = frt-v1**, which the 2026-06-22 audit
(`docs/AUDIT_2026-06-22.md`) found defective: Simulink time via `linspace` on a variable-step solver
(C1); `connect` mixed steady ±7% into the ride envelope with a calibrated-residual reference (C2);
`limit` checked only iq and normalised a PEAK dq current by an RMS base (C3); fault-resistance
calibration ran the dq controller (mode 4) not Mode 0/no-HLC (C4); HVRT used a static 1.35 bound (H3);
the I2≤3 pu constraint was not implemented (H4).

**Therefore the headline scores derived from these files — Mode 5 = 82.2%, Mode 6 = 96.25%,
Mode 2 = 79.7%, Mode 1 = 64.1%, Mode 3 = 44.4%, Mode 4 = 81.2%, dq-legacy = 27.5% — are
`legacy frt-v1` and MUST NOT be compared with frt-v2 results.** Post-fix scores are PENDING the
re-validation commands in `docs/CHANGE_REPORT_2026-06-22.md`.

Files retained verbatim for provenance; do not edit.
