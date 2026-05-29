# Fault Diagnosis Method Comparison: raw_switching_hpt_v2_fixed_all

## Summary

- Dataset: `raw_switching_hpt_v2_fixed_all`
- Best overall method: `random_forest` (Traditional), Accuracy 95.68%, Macro F1 94.74%
- Best AI method: `AI-MSFFN`, Accuracy 84.57%, Macro F1 84.00%
- Current AI accuracy gap to best method: 11.11 percentage points

## Ranked Results

| Rank | Method | Family | Accuracy | Macro F1 | Weighted F1 | Window Latency |
|---:|---|---|---:|---:|---:|---:|
| 1 | random_forest | Traditional | 95.68% | 94.74% | 95.67% | 5.0 ms |
| 2 | elm | Traditional | 88.83% | 86.21% | 88.21% | 5.0 ms |
| 3 | svm_rbf | Traditional | 87.68% | 86.12% | 87.56% | 5.0 ms |
| 4 | AI-MSFFN | AI | 84.57% | 84.00% | 84.94% | 5.0 ms |
| 5 | AI-CNN_LSTM | AI | 82.79% | 79.85% | 83.07% | 5.0 ms |
| 6 | threshold_centroid | Traditional | 58.48% | 36.37% | 49.40% | 5.0 ms |

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
