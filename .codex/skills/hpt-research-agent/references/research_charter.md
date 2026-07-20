# Research Charter

Goal: deliver a one-month IEEE Transactions-level first draft for an
RL-based controller for Hybrid Power Transformer fault ride-through.

Primary claim to prove: an RL controller can improve HPT FRT performance over
traditional dq/PI-style control while preserving current, DC-link, and
recovery constraints in switch-level Simulink validation.

Research questions:

1. Does RL beat the strongest available conventional baseline under known
   LVRT/HVRT scenarios?
2. Does it generalize across fault depth, duration, topology, and grid
   conditions?
3. Which constraints limit transfer from Python proxy training to switch-level
   Simulink?
4. What interface and dataset contracts are required to make the result
   reproducible?

Non-negotiable evidence:

- topology1 and topology2 Simulink smoke tests;
- conventional dq baseline;
- SAC or specialist RL comparison;
- proxy-to-switch alignment report;
- failure-case analysis;
- reproducible run manifests and logs.
