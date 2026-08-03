# HPT Expert Workspaces

`version_2/experts` is the canonical home for fault-family actor checkpoints,
switch-level results, and promotion manifests. New family campaigns must not
write checkpoints to root `data/models` or results to root `lab/results`.

## Twelve-Expert Taxonomy

The directory contains exactly twelve expert workspaces:

```text
2 topologies x 2 categories (LVRT/HVRT) x 3 phase families
```

The phase families are:

- `balanced`: ABC faults;
- `single_phase`: A/B/C faults share one phase-equivariant expert family;
- `two_phase`: AB/BC/CA faults share one phase-equivariant expert family.

Every expert directory has:

- `data/raw_switch_level/`: immutable Simulink trajectory exports;
- `data/train/`: family training split;
- `data/validation/`: model-selection split;
- `data/holdout/`: untouched final family evaluation split;
- `data/support_anchor/`: behavior-support or safety-anchor datasets;
- `proxy/model/`: family-specific learned proxy artifacts;
- `proxy/alignment/`: proxy-versus-Simulink calibration and holdout evidence;
- `models/`: candidate and promoted actor checkpoints plus sidecars;
- `results/`: training traces and switch-level validation runs;
- `manifests/`: model hashes, provenance, and promotion records;
- `expert.json`: the current model/result pointers for that family.

`registry.json` is the machine-readable index. Resolve a family with:

```powershell
py -3 -m version_2.sac.expert_workspace --resolve topology2 LVRT a
```

## Evidence Status

The twelve copied checkpoints are not all claimed to be final SAC family
actors. Eleven are retained as historical Stage-6 representative checkpoints.
The current promoted family actor is `topology2_single_phase_lvrt`, with a
local switch-level voltage-survival boundary-expansion claim. Read each
`model_manifest.json` and `expert.json` before using a checkpoint.

The two physical switch-level plants remain shared under
`version_2/simulink/topoloty1` and `version_2/simulink/topology2`; they are not
duplicated twelve times. The per-expert `models/` directories store controller
checkpoints, not copies of the plant.

## Legacy Storage

Root `data/models` and `lab/results` contain historical experiments and remain
available for provenance. They are not canonical destinations for new
fault-family work. `migration_sources_20260803.json` records the exact source
of every representative artifact copied into this layout. The twelve current
checkpoint ZIP files are tracked with Git LFS; bulk run subdirectories remain
local/ignored while their compact indexes and evidence rows are versioned.
