# Literature: Diagnosis-Driven Reward Shaping & Hyperparameter Tuning for RL — 2026-06-27

Scope: justify the **closed loop** we use to improve the 4-expert SAC (Mode 5 / mi=12) under the
"no multi-model hybrid" constraint:

```
certify (frt-v2 full-320) → error-analysis of failure clusters → modify reward terms / targeted
sampling → retrain affected expert(s) → re-certify
```

> Verification note: refs marked ✅ were confirmed by web search (2026-06-27); refs marked ◇ are
> canonical works cited from domain knowledge — **re-check exact venue/year/pages on IEEE Xplore /
> arXiv before submission.** Flagged non-archival (blog) sources are for orientation only.

---

## 1. Reward-shaping foundations (principled shaping)
- ✅ **Ng, Harada, Russell (1999). "Policy Invariance Under Reward Transformations: Theory and
  Application to Reward Shaping." ICML.** Potential-based reward shaping (PBRS):
  `F(s,s') = γΦ(s') − Φ(s)` is the *only* additive shaping form that provably leaves the optimal
  policy unchanged. → Use to argue our added reward terms are principled, not goal-distorting.
- ◇ Wiewiora (2003): PBRS ≡ Q-value initialization. ◇ Harutyunyan et al. (AAAI 2015): express
  arbitrary reward as potential-based advice.

## 2. Reward hacking / specification gaming (the discipline guardrail)
- ◇ **Amodei, Olah, Steinhardt, Christiano, Schulman, Mané (2016). "Concrete Problems in AI Safety."
  arXiv:1606.06565.** Names reward hacking + negative side effects.
- ◇ **Krakovna et al. (2020, DeepMind). "Specification gaming: the flip side of AI ingenuity."**
- ✅ Weng (2024). "Reward Hacking in RL" (blog, non-archival — orientation). ✅ Empirical studies on
  detecting/mitigating reward hacking (arXiv:2507.05619). → Justify "re-certify every change, keep
  reward faithful to the 5 frt-v2 criteria, watch regressions" (cf. the mi=17 negative result).

## 3. Reward design as a diagnose-and-revise loop (closest to what we do)
- ✅ **Ma, Liang, Wang, et al. (2023). "Eureka: Human-Level Reward Design via Coding LLMs."
  arXiv:2310.12931 (ICLR 2024).** Core mechanism = **"reward reflection"**: after training, analyze
  per-component reward statistics / failure behavior → reflect → rewrite the reward → retrain
  (evolutionary). → **This is the automated form of our manual loop.** Single most relevant
  methodology citation.
- Takeaway: Eureka exists *because* manual reward design is brittle and trial-and-error — supports
  framing our contribution as making that implicit loop explicit, criteria-aligned, reproducible.

## 4. Failure-driven curriculum & targeted sampling (the "oversample deep-sym" half)
- ◇ **Schaul, Quan, Antonoglou, Silver (2016). "Prioritized Experience Replay." ICLR.** Replay
  high-error (failing) transitions more often.
- ◇ **Narvekar et al. (2020). "Curriculum Learning for RL: A Framework and Survey." JMLR.**
- ◇ Florensa et al. (2017/2018): automatic / reverse curriculum. → Justify over-weighting failure
  clusters (weak-grid deep swell, deep sym) in retraining.
- ⚠️ Surveys warn of **catastrophic forgetting**: over-sampling hard cases can degrade easy ones —
  exactly the regression risk we must monitor.

## 5. Hyperparameter optimization for RL (reward weights as hyperparameters)
- ✅ **Parker-Holder et al. (2022). "Automated Reinforcement Learning (AutoRL): A Survey and Open
  Problems." JAIR.**
- ◇ **Jaderberg et al. (2017). "Population Based Training of Neural Networks."** ✅ Parker-Holder et
  al. PB2 (NeurIPS 2020/2021): online HPO as time-varying GP-bandit.
- ✅ **Eimer, Lindauer, Raileanu (2023). "Hyperparameters in RL and How To Tune Them." ICML.** →
  Treat reward weights (−15, −30, …) as hyperparameters; tune by small sweep, not by hand-picking.

## 6. Domain: RL reward design for grid converters / FRT (closest to our application)
- ✅ **"Deep Reinforcement Learning for Power Converter Control: A Comprehensive Review" (2025).**
  States explicitly that reward-function and state-action design are the central difficulty in DRL
  converter control. → Domain backing for "reward design is the lever."
- ✅ Multiple grid-converter / voltage-control DRL papers use **barrier-function reward reshaping**:
  *steeper penalty gradients in the violation region* (accelerate voltage/DC recovery), *gentler in
  the safe region* (avoid excess reactive / losses). → **Direct precedent for our proposed
  Vdc-undershoot reward** (steeper as Vdc → 0.75 cliff) and the wrong-sign reactive penalty.
- ◇ Grid-forming / STATCOM DRL papers encoding LVRT/HVRT, reactive priority, DC-bus survival into
  rewards (mostly IEEE Trans. PWRD / TPEL / TSG). → cite 1–2 as the "how others encode grid-code in
  rewards" anchor.

---

## Conclusions

**(a) What our loop is called.** No single standard name. It is the combination of
**iterative reward shaping / reward engineering** (reward side) + **failure-driven automatic
curriculum / hard-example mining** (sampling side). The closest *formal* naming is Eureka's
**"reward reflection"** — we do the human-in-the-loop version with error analysis instead of an LLM.

**(b) Established or ad-hoc?** The *components* are established with theory (PBRS theorem, PER,
curriculum surveys, AutoRL/PBT). The *complete manual loop* (error-analysis → reward edit →
re-certify) is largely **ad-hoc engineering practice, under-formalized** — which is precisely why
Eureka/AutoRL try to automate it. Our contribution can be framed as making it **explicit,
criteria-aligned, and reproducible** for a grid-code-constrained FRT controller.

**(c) Top 5 to cite.**
1. Ng, Harada, Russell 1999 — shaping is principled (policy invariance).
2. Eureka, Ma et al. 2023 — formal diagnose→revise reward loop (we do the manual version).
3. Eimer et al. 2023 (and/or Parker-Holder et al. 2022) — reward weights as tunable hyperparameters.
4. DRL-for-Power-Converter review 2025 + one barrier-function reward-reshaping FRT/voltage paper —
   same technique in our domain.
5. Krakovna 2020 / Amodei 2016 — reward hacking → justify our re-certify + criteria-faithful
   discipline.

## BibTeX placeholders (fill exact fields before submission)
```bibtex
@inproceedings{ng1999policy, title={Policy Invariance Under Reward Transformations: Theory and Application to Reward Shaping}, author={Ng, Andrew Y. and Harada, Daishi and Russell, Stuart}, booktitle={ICML}, year={1999}}
@article{ma2023eureka, title={Eureka: Human-Level Reward Design via Coding Large Language Models}, author={Ma, Yecheng Jason and others}, journal={arXiv:2310.12931}, year={2023}, note={ICLR 2024}}
@inproceedings{schaul2016per, title={Prioritized Experience Replay}, author={Schaul, Tom and Quan, John and Antonoglou, Ioannis and Silver, David}, booktitle={ICLR}, year={2016}}
@article{narvekar2020curriculum, title={Curriculum Learning for Reinforcement Learning Domains: A Framework and Survey}, author={Narvekar, Sanmit and others}, journal={JMLR}, year={2020}}
@article{parkerholder2022autorl, title={Automated Reinforcement Learning (AutoRL): A Survey and Open Problems}, author={Parker-Holder, Jack and others}, journal={JAIR}, year={2022}}
@inproceedings{eimer2023hyperparameters, title={Hyperparameters in Reinforcement Learning and How To Tune Them}, author={Eimer, Theresa and Lindauer, Marius and Raileanu, Roberta}, booktitle={ICML}, year={2023}}
@article{amodei2016concrete, title={Concrete Problems in AI Safety}, author={Amodei, Dario and others}, journal={arXiv:1606.06565}, year={2016}}
@misc{krakovna2020specification, title={Specification gaming: the flip side of AI ingenuity}, author={Krakovna, Victoria and others}, year={2020}, note={DeepMind}}
```
