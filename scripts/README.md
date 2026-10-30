# Command guide

Run commands from the repository root with `python scripts/<name>.py`.
Use `--help` on workflow commands to see their options. Generated outputs belong
under `artifacts/`; source inputs remain under `config/` and `data/`.

## Main workflow

| Command | Purpose |
|---|---|
| `download_data.py` | Download the approved Hugging Face dataset |
| `run_agent_scenario.py` | Run a single profile-conditioned task |
| `run_agent_scenarios.py` | Collect trajectories with isolated workers and shared MCP servers |
| `package_trajectories.py` | Combine trajectory files into the dataset JSONL format |
| `run_privacy_attacks.py` | Run one-shot or two-stage profile inference |
| `run_semantic_judge.py` | Score unresolved predictions with the semantic judge |
| `build_paper_results.py` | Rebuild the paper's result tables and figures |

Profile and scenario construction also have module entry points:

```bash
python -m privacy_trace.profile_generator --help
python -m privacy_trace.scenario_generator --help
```

## Data construction

| Command | Purpose |
|---|---|
| `discover_scenario_tools.py` | Discover MCP tool schemas |
| `build_scenario_tool_pool.py` | Construct a planning pool from tool snapshots |
| `rebuild_official_ipf_targets.py` | Rebuild calibration targets from statistical sources |
| `resample_profile_pool.py` | Calibrate and sample an existing candidate pool |
| `analyze_profile_distribution.py` | Summarize candidate and sampled profile distributions |

Reusable profile code lives in `privacy_trace/profiles/`. Statistical target
builders live in `privacy_trace/population_targets/`; the rebuild script is
an entry point to those builders.

## Runtime and provider tools

| Command | Purpose |
|---|---|
| `serve_agent_api.py` | Serve the agent runtime through FastAPI |
| `serve_shared_mcp.py` | Serve one MCP catalog entry for reuse within a batch |
| `benchmark_mcp_concurrency.py` | Measure MCP availability and concurrency |
| `benchmark_profile_provider.py` | Measure profile-generation provider throughput |
| `run_privacy_recovery_watchdog.py` | Restart a stalled, resumable inference batch |
| `review_trajectory_dataset.py` | Summarize trajectory completion and tool outcomes |

## Experiment variants

| Command | Purpose |
|---|---|
| `run_channel_experiments.py` | Compare observation channels |
| `run_view_scope_experiments.py` | Construct and evaluate linked cross-domain views |

## Analysis

| Command | Purpose |
|---|---|
| `analyze_attack_comparison.py` | Compare paired inference protocols |
| `analyze_channel_experiments.py` | Summarize channel experiments |
| `analyze_model_generalization_first_pass.py` | Analyze first-pass results across attacker models |
| `analyze_privacy_experiments.py` | Aggregate inference results and paired comparisons |
| `analyze_privacy_tool_leakage.py` | Analyze leakage across tools and servers |
| `analyze_semantic_asr.py` | Aggregate semantic ASR |
| `analyze_semantic_model_comparison.py` | Compare semantic scoring across attacker models |

## Existing-run maintenance

| Command | Purpose |
|---|---|
| `build_privacy_eval_records.py` | Normalize predictions into attribute-level evaluation records |
| `materialize_failed_evaluations.py` | Include exhausted generation failures in the evaluation denominator |
| `backfill_two_stage_failure_checkpoints.py` | Add missing Stage-1 failure checkpoints to older runs |
| `relativize_project_paths.py` | Convert saved workspace paths to portable project paths |

## Historical experiment utilities

These preserve the original experiment's fixed paths and run settings. Use the
workflow commands above for new experiments.

| Script | Purpose |
|---|---|
| `run_channel_ablation_followup.py` | Continue the original channel-ablation run |
| `monitor_channel_ablation.py` | Monitor that run's supervisor |
| `analyze_channel_semantic_asr.py` | Analyze its first-pass semantic scores |
| `build_repro_audit_bundle.py` | Collect its records for offline analysis |
