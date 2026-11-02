# Command guide

Run these commands from the repository root with the environment activated.
Each Python module supports `--help`.

## Data construction

| Command | Purpose |
|---|---|
| `python -m generate.generate_profiles` | Generate calibrated synthetic profiles |
| `python -m generate.generate_scenarios` | Generate profile-conditioned domain tasks |
| `python -m generate.build_targets` | Rebuild population targets from statistical sources |
| `python -m generate.discover_tools` | Discover MCP tool schemas |
| `python -m generate.build_tool_pool` | Build the planning tool pool |
| `python -m generate.resample_profiles` | Sample an existing candidate pool |
| `python -m generate.analyze_profiles` | Summarize profile distributions |
| `python -m generate.benchmark_provider` | Measure profile-generation provider throughput |

## Agent trajectories

| Command | Purpose |
|---|---|
| `python -m agent.run_scenario` | Run one profile-conditioned task |
| `python -m agent.run_scenarios` | Collect trajectories in a batch |
| `python -m agent.package_trajectories` | Package trajectories as JSONL |
| `python -m agent.review_trajectories` | Summarize completion and tool outcomes |
| `python -m agent.serve_api` | Serve the agent runtime through FastAPI |
| `python -m agent.serve_mcp` | Expose one MCP server over loopback HTTP |
| `python -m agent.benchmark_mcp` | Measure MCP availability and concurrency |

## Privacy inference

| Command | Purpose |
|---|---|
| `python -m attack.run_attacks` | Run one-shot or two-stage profile inference |
| `python -m attack.run_channels` | Compare observation channels |
| `python -m attack.run_view_scopes` | Compare single-server and cross-domain views |
| `python -m attack.watchdog` | Restart a stalled resumable inference batch |

## Evaluation

| Command | Purpose |
|---|---|
| `python -m eval.build_records` | Convert predictions into attribute-level evaluation records |
| `python -m eval.include_failures` | Include exhausted prediction failures in the denominator |
| `python -m eval.run_judge` | Score predictions with the semantic judge |
| `python -m eval.semantic_asr` | Aggregate semantic attack success rates |
| `python -m eval.compare_attacks` | Compare paired inference protocols |
| `python -m eval.analyze_privacy` | Summarize inference results and paired comparisons |
| `python -m eval.analyze_channels` | Summarize channel experiments |
| `python -m eval.analyze_tools` | Analyze leakage across tools and servers |
| `python -m eval.analyze_models` | Compare attacker models |
| `python -m eval.compare_judges` | Compare semantic scoring across models |
| `python -m eval.reproduce_results` | Rebuild the reported tables and figures |

Reproduction reads the downloaded records under `artifacts/` and writes to
`artifacts/results/`. Use `--input-root` and `--output-root` to change these
locations. It does not call a model.

## Environment and download

```bash
PYTHON=python3.10 bash scripts/setup_environment.sh
hf auth login
python scripts/download_data.py
```

Pass `--locked` to the setup script to install the recorded reference environment.
Downloading requires approval on the Hugging Face dataset page.
