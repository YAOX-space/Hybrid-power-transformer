@echo off
set HPT_RAW_DIR=e:\research_space\Hybrid-power-transformer\data\raw_switching_hpt_v2_fixed_dq
cd /d e:\research_space\Hybrid-power-transformer
"e:\research_space\Hybrid-power-transformer\.venv\Scripts\python.exe" ai\msffn_fault_detector.py --train --epochs 80 --patience 15 --device auto > results\msffn_fixed_dq_train_stdout.log 2> results\msffn_fixed_dq_train_stderr.log
