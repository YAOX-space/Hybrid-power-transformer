LEGACY frt-v1 switching spot-check MATs — INVALIDATED (2026-06-22 audit).
No metrics_version; S*_sw_result.mat have NO real time vector (linspace-reconstructed); crit.frt is
the legacy frt-v1 verdict and MUST NOT be trusted. fill_spotcheck.py refuses these by default; they
are readable ONLY with HPT_ALLOW_LEGACY_FRT=1 and outputs stay in this folder (no active CSV/fig7,
no FRT PASS). Re-running run_spotcheck.m under the frt-v2 criteria (P1) will regenerate versioned MATs.
