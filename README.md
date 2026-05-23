# 多端口混合式柔性配电变压器 — 仿真与AI控制研究
# Multi-Port Hybrid Power Transformer: Simulation & AI Control Research

**Project**: 课题2 — 多端口柔性混合配变的研制及在交直流微网示范应用  
**Specs**: 400 kVA total, ≥120 kVA PE converter, 10 kV/400 V, ±20% regulation, <5 ms response

---

## Project Structure

```
summer/
├── simulink/                   ← MATLAB/Simulink models & scripts
│   ├── parameters.m            ← All system parameters (run first)
│   ├── build_hpt_model.m       ← Builds hpt_main_model.slx programmatically
│   ├── design_pi_controller.m  ← Builds PI baseline controller subsystem
│   └── hpt_main_model.slx      ← [generated] Main Simulink HPT model
│
├── data_collection/
│   └── run_scenarios.m         ← Runs 9 scenario types, saves .mat files
│
├── data/
│   ├── raw/                    ← .mat simulation output files
│   ├── processed/              ← .npz numpy arrays, scalers
│   └── models/                 ← Saved AI model checkpoints
│       └── drl/                ← PPO agent checkpoints (MATLAB)
│
├── ai/                         ← Python AI modules
│   ├── requirements.txt
│   ├── data_loader.py          ← Data loading, windowing, normalization
│   ├── dnn_controller.py       ← Method A: DNN multi-mode controller
│   ├── drl_trainer.m           ← Method B: PPO via MATLAB RL Toolbox
│   ├── lstm_fault_detector.py  ← Method C: LSTM fault classification
│   ├── cwt_cnn_localizer.py    ← Method D: CWT+CNN IGBT fault localization
│   ├── frt_controller.py       ← Method E: Fault ride-through RL controller
│   └── evaluate.py             ← Unified benchmark comparison
│
└── results/
    ├── benchmark_results.json
    └── benchmark_plots.pdf
```

---

## Quick Start

### Step 1 — Build the Simulink Model (MATLAB)
```matlab
cd simulink
run('parameters.m')        % load all system parameters
run('build_hpt_model.m')   % creates hpt_main_model.slx
run('design_pi_controller.m')  % creates hpt_controller.slx
open('hpt_main_model.slx') % inspect & wire remaining connections
```

### Step 2 — Generate Training Data (MATLAB)
```matlab
cd data_collection
run('run_scenarios.m')     % runs ~2600 simulations, saves to data/raw/
```

### Step 3 — Install Python Dependencies
```bash
cd ai
pip install -r requirements.txt
```

### Step 4 — Train AI Methods (Python)

**Method C: LSTM Fault Detector** (recommended first — fastest to train)
```bash
python lstm_fault_detector.py --train
python lstm_fault_detector.py --eval
```

**Method A: DNN Controller**
```bash
python dnn_controller.py --synthetic   # generate training data (no MATLAB needed)
python dnn_controller.py --train
```

**Method D: CWT+CNN IGBT Localizer**
```bash
python cwt_cnn_localizer.py --train
```

**Method E: FRT RL Controller**
```bash
python frt_controller.py --train-rl --episodes 5000
python frt_controller.py --demo
```

**Method B: PPO DRL (MATLAB)**
```matlab
cd ai
run('drl_trainer.m')       % requires Reinforcement Learning Toolbox
```

### Step 5 — Evaluate All Methods
```bash
python evaluate.py --all
python evaluate.py --plot
```

---

## HPT Topology

```
10 kV Grid
    │
    ├─[T_se series]─── VSC_se ─┐
    │  (injects V_se)          │
    │                          C_dc
    └─[Main Transformer]       │
           │                   │
        400 V Bus ─[T_sh]── VSC_sh ─┘
                    (maintains V_dc, reactive comp)
           │
          Load / DC Port
```

**VSC_sh** (shunt): Maintains DC bus voltage + reactive power compensation  
**VSC_se** (series): Injects series voltage for ±20% regulation + power flow control

---

## AI Methods Overview

| Method | Purpose | Key Result |
|--------|---------|-----------|
| **A: DNN Controller** | Multi-mode control (replaces outer PI loops) | ~30–60 ms settling vs ~100 ms PI |
| **B: DRL (PPO)** | Adaptive control + automatic mode switching | ~20–50 ms, no manual tuning |
| **C: LSTM Detector** | Fault classification, 5 fault types | >95% accuracy, <5 ms latency |
| **D: CWT+CNN** | IGBT fault localization (which switch failed) | Identifies 12 specific locations |
| **E: FRT Controller** | Post-fault energy redistribution | <100 ms recovery |

---

## Fault Types

| ID | Label | Description |
|----|-------|-------------|
| 0 | normal | Normal operation |
| 1 | igbt_oc_sh | IGBT open-circuit in VSC_sh |
| 2 | igbt_oc_se | IGBT open-circuit in VSC_se |
| 3 | cap_fault | DC capacitor disconnection |
| 4 | sc_1ph | Single-phase short circuit |
| 5 | sc_3ph | Three-phase short circuit |
| 6 | cascade | Cascade fault (IGBT → DC overvoltage) |

---

## References

- Tang Aihong et al., *基于多控制模式的混合式电力变压器潮流计算模型*, CSEE 2025
- Song Xing, *混合式电力变压器多工作模式控制策略研究*, WUT Master Thesis 2023
- Kamal et al., *Deep Learning-based Control of Multi-Port SST*, 2025
- Shang et al., *Hybrid Power Transformer Voltage Control for PV*, EEPE 2024
