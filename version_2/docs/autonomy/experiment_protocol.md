# Experiment Protocol

Every experiment needs:

- run id;
- hypothesis;
- baseline;
- exact command;
- expected output directory;
- config snapshot;
- Git metadata;
- stdout/stderr log;
- result summary;
- next action.

Decision labels:

- `promote` - passed switch-level gate and improves or clarifies baseline;
- `diagnostic` - useful failure or partial result;
- `rerun` - environment or transient failure invalidated the run;
- `debug` - contract or model failure blocks evidence;
- `retire` - superseded by a stronger validated result.
