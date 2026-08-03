# Family Proxy

This expert uses a calibrated physics proxy, not a standalone neural-network
plant model. `model/hpt_proxy_calibration.json` is the portable runtime
configuration. `alignment/` contains its switch-level calibration sources.

These artifacts support calibration-point behavior. They do not yet establish
untouched trajectory-rollout holdout alignment.
