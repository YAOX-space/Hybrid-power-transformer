# Fault Diagnosis Method Comparison: raw_switching_hpt_v2

## Summary

- Dataset: `raw_switching_hpt_v2`
- Best overall method: `elm` (Traditional), Accuracy 88.10%, Macro F1 82.66%
- Best AI method: `AI-CNN_LSTM`, Accuracy 80.48%, Macro F1 72.39%
- Current AI accuracy gap to best method: 7.62 percentage points

## Ranked Results

| Rank | Method | Family | Accuracy | Macro F1 | Weighted F1 | Window Latency |
|---:|---|---|---:|---:|---:|---:|
| 1 | elm | Traditional | 88.10% | 82.66% | 87.55% | 5.0 ms |
| 2 | svm_rbf | Traditional | 86.19% | 82.05% | 86.18% | 5.0 ms |
| 3 | random_forest | Traditional | 86.19% | 80.13% | 85.72% | 5.0 ms |
| 4 | AI-CNN_LSTM | AI | 80.48% | 72.39% | 80.19% | 5.0 ms |
| 5 | AI-TCN | AI | 75.71% | 69.23% | 75.81% | 5.0 ms |
| 6 | AI-CNN | AI | 75.71% | 67.86% | 75.59% | 5.0 ms |
| 7 | threshold_centroid | Traditional | 60.00% | 38.10% | 51.60% | 5.0 ms |

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
