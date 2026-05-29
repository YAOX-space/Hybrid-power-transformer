# Fault Diagnosis Method Comparison: raw_switching_hpt_v2_fixed_all_v2

## Summary

- Dataset: `raw_switching_hpt_v2_fixed_all_v2`
- Best overall method: `Ensemble_RF+MSFFN(α=0.90)` (Ensemble), Accuracy 97.83%, Macro F1 97.57%
- Best AI method: `AI-MSFFN`, Accuracy 92.61%, Macro F1 91.26%
- Current AI accuracy gap to best method: 5.22 percentage points

## Ranked Results

| Rank | Method | Family | Accuracy | Macro F1 | Weighted F1 | Window Latency |
|---:|---|---|---:|---:|---:|---:|
| 1 | Ensemble_RF+MSFFN(α=0.90) | Ensemble | 97.83% | 97.57% | 97.82% | 5.0 ms |
| 2 | random_forest | Traditional | 97.71% | 97.34% | 97.70% | 5.0 ms |
| 3 | AI-MSFFN | AI | 92.61% | 91.26% | 92.59% | 5.0 ms |
| 4 | svm_rbf | Traditional | 91.09% | 89.53% | 90.99% | 5.0 ms |
| 5 | elm | Traditional | 90.67% | 88.71% | 90.30% | 5.0 ms |
| 6 | threshold_centroid | Traditional | 59.50% | 36.34% | 50.40% | 5.0 ms |

## Interpretation

- If traditional feature models win, the dataset still contains stable statistical signatures that shallow models can exploit.
- If AI wins on larger cross-condition data, it indicates the sequence model is learning transient dynamics rather than only handcrafted statistics.
- For the current FRT-controlled data, fault responses are intentionally suppressed by control action, so diagnosis becomes harder and requires more data or stronger temporal models.

## Recommended Next AI Comparisons

| Candidate | Why it matters |
|---|---|
| CNN-LSTM | Local waveform features plus temporal state memory |
| TCN | Fast causal temporal convolution for 5 ms online diagnosis |
| Transformer encoder | Better long-range transient attention after fault onset |
| Multi-task AI | Predict fault class, fault phase/switch, and FRT control mode together |
