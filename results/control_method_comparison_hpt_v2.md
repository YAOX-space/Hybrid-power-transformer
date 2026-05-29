# HPT v2 Control Method Comparison

## Scope

Only corrected HPT v2 switching-level Simulink results are included. All valid controllers use the same fixed 350-scenario table.

Best measured controller: `dq double-loop baseline`.

## Valid Controllers

| Controller | Family | Mean Pass | Worst Pass | V2min | VdcMin | VdcMax | I2Max | Max Recovery |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| Rule-based FRT | Traditional control | 60.57% | 0.0% | 0.2536 | 0.4694 | 1.1549 | 3.4308 | 9.3 ms |
| dq double-loop baseline | Traditional control | 64.0% | 14.0% | 0.2536 | 0.4698 | 1.1549 | 3.4346 | 9.3 ms |
| PPO/DRL controller | AI control | 59.43% | 2.0% | 0.2537 | 0.4236 | 1.155 | 3.4143 | 9.3 ms |
| MSFFN→FAHC pipeline | AI control | 61.71% | 14.0% | 0.2536 | 0.4698 | 1.1549 | 3.4346 | 9.3 ms |

## Honest Conclusion

AI control (PPO/DRL) has not beaten traditional control on the fixed HPT v2 scenario table. The dq double-loop baseline is the strongest measured controller.

## Excluded (Legacy) — Do Not Cite

| Controller | Reason |
|---|---|
| DNN-FRT (legacy, invalid) | EXCLUDED — imitation policy trained on old topology; 0.29% pass rate on HPT v2 |

## Next AI-Control Steps

| Track | Baseline to beat | Metrics |
|---|---|---|
| Ride-through control | dq double-loop 64.0% | LVRT pass, VdcMin/VdcMax, I2Max, recovery time |
| Fault detection | Random Forest 95.68% | Accuracy, macro F1, 5 ms latency |
| Full AI strategy | PPO/DRL with trained MSFFN | Same physical metrics on identical scenarios |
