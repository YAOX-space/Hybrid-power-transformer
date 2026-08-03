# MATLAB And Simulink Tooling

## Purpose

Use official MathWorks MCP tools and Model-Based Design skills when available,
while preserving the repository's reproducible campaign interfaces.

Primary upstream references:

- https://github.com/matlab/matlab-agentic-toolkit
- https://github.com/matlab/matlab-mcp-server
- https://github.com/matlab/simulink-agentic-toolkit

## MATLAB MCP Tools

Use `detect_matlab_toolboxes` once per session when MATLAB capability matters.
Record MATLAB, Simulink, Simscape Electrical, and test-tool availability in the
run metadata when they affect reproducibility.

Use the narrowest tool:

| Need | Tool |
| --- | --- |
| Version and toolbox inventory | `detect_matlab_toolboxes` |
| Static analysis of an edited `.m` file | `check_matlab_code` |
| Short introspection or parameter query | `evaluate_matlab_code` |
| Execute a maintained MATLAB runner | `run_matlab_file` |
| Execute MATLAB unit tests | `run_matlab_test_file` |

Inspect errors and warnings. Do not automatically rewrite unrelated Code
Analyzer findings during a scoped experiment fix.

## Simulink Model Tools

When the Simulink Agentic Toolkit MCP extension is exposed:

1. Use `model_overview` to identify hierarchy and interfaces.
2. Use `model_read`, `model_query_params`, and `model_resolve_params` before
   assuming topology, solver, logging, or workspace values.
3. Use `model_edit` for model structure and parameter changes.
4. Use `model_check` after edits.
5. Use `model_read_diagnostics` after compilation or simulation failures.
6. Use `model_test` for persistent Gherkin requirements when Simulink Test is
   installed.

If these tools are not callable, use the installed Simulink skills and run
targeted MATLAB inspection scripts. Do not claim that a `.slx` connection is
correct merely from a builder script or screenshot.

## Repository Execution Hierarchy

Use MCP for short interactive work. Use canonical repository entry points for
campaigns, sweeps, collectors, training, and paper evidence because they save
the required artifacts.

Current canonical interfaces are listed in
`version_2/docs/autonomy/current_research_state.json` and the README files
under `version_2/sac/` and `version_2/simulink/`.

Fallback order for execution:

1. official MCP tool;
2. repository campaign using its configured MATLAB runner;
3. MATLAB Engine for Python;
4. `matlab -batch` for isolated, reproducible noninteractive runs.

Do not replace a working campaign with ad hoc `evaluate_matlab_code` calls for
long experiments. MCP output alone does not provide run metadata or evidence
retention.

## Windows Notes

- The official MCP server may require `WINDIR` in the Codex MCP environment.
- Existing-session mode requires the MATLAB MCP Server Toolbox and
  `shareMATLABSession()`.
- Use absolute paths for MCP script inputs.
- Keep long artifact names bounded because MATLAB and Simulink generated paths
  can exceed Windows path limits.

## Validation Pattern

For a MATLAB edit:

1. inspect the source and callers;
2. run Code Analyzer;
3. apply the scoped edit;
4. rerun Code Analyzer;
5. run the smallest MATLAB test or smoke case;
6. run the affected switch-level evaluator if behavior changed;
7. capture tool version, command, output, and artifacts.

For a Simulink edit, also inspect the model itself, check it after editing,
read diagnostics, and retain a persistent regression test for the repaired
contract.
