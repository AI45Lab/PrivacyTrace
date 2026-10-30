<h1 align="center">PrivacyTrace</h1>

<h3 align="center">How Much Can Tool Calls Reveal About You?<br>Privacy Leakage from Tool-Call Traces</h3>

<p align="center">
  <a href="https://sowingg2333.github.io/PrivacyTrace-website/"><img alt="Website: Project page" src="https://img.shields.io/badge/Website-Project%20page-447EB2?logo=githubpages&amp;logoColor=white"></a>
  <a href="https://github.com/AI45Lab/PrivacyTrace"><img alt="Code: GitHub" src="https://img.shields.io/badge/Code-GitHub-24292F?logo=github&amp;logoColor=white"></a>
  <a href="https://huggingface.co/datasets/SowingG/PrivacyTrace"><img alt="Data: Hugging Face" src="https://img.shields.io/badge/Data-Hugging%20Face-FFD21E?logo=huggingface&amp;logoColor=white"></a>
  <img alt="Paper on arXiv: coming soon" src="https://img.shields.io/badge/arXiv-Coming%20soon-B31B1B?logo=arxiv&amp;logoColor=white">
</p>

<p align="center">
  <a href="#quick-start">Quick start</a> ·
  <a href="docs/data_access.md">Data access</a> ·
  <a href="#construct-a-new-dataset">Dataset construction</a> ·
  <a href="#selected-results">Results</a>
</p>

PrivacyTrace measures user-profile inference from MCP tool-call traces, without
access to user conversations. It pairs population-calibrated synthetic profiles
with real tool executions across travel, health, shopping, and career learning.

<p align="center">
  <img src="figure/privacy-side-channel.png" alt="Private user–agent interactions produce observable tool-call traces that can support inference of user attributes." width="100%">
</p>

## The benchmark

| Synthetic profiles | Personal attributes | Agent trajectories | MCP servers | Tool records |
|:---:|:---:|:---:|:---:|:---:|
| **1,000** | **17** | **4,000** | **25** | **67,950** |

This repository contains the environment, data-construction pipeline, agent
runtime, privacy inference attacks, evaluation code, and aggregate results.
Full experiment records are hosted on
[Hugging Face](https://huggingface.co/datasets/SowingG/PrivacyTrace), with
**manual approval for downloads**.

## Quick start

### 1. Set up the environment

The reference environment uses Python 3.10 on Linux:

```bash
git clone https://github.com/AI45Lab/PrivacyTrace.git
cd PrivacyTrace
PYTHON=python3.10 bash scripts/setup_environment.sh
source .venv/bin/activate
```

The setup installs the supported dependencies and the optional HF download
client. Use `--locked` to install the recorded reference environment instead.
Model and MCP requests require your own credentials; copy `.env.example` to
`.env` and `.env.mcp.example` to `.env.mcp` and configure the services you use.
Both local credential files are ignored by Git.

MCP dependencies are optional for offline analysis. Install the licensed
components only when running live tools:

```bash
python mcp_servers/install.py --install-dependencies
```

See [getting started](docs/getting_started.md) for Node.js/uv requirements and
the separately acknowledged upstream components.

### 2. Download data and reproduce results

Download the data from [Hugging Face](https://huggingface.co/datasets/SowingG/PrivacyTrace).
Request access on the dataset page. Downloads require manual approval by
the authors. Once approved:

```bash
hf auth login
python scripts/download_data.py
```

With approved data installed at the repository root:

```bash
python scripts/build_paper_results.py --input-root . --output-root reproduced_results
```

This rebuilds the reported tables and figures from frozen records without
calling a model. Reference aggregates are in `results/paper/`.

## Construct a new dataset

<p align="center">
  <img src="figure/benchmark-overview.png" alt="PrivacyTrace pipeline: synthetic profiles and scenarios, agent trajectories through real MCP tools, and prior-based, one-shot, and two-stage inference." width="100%">
</p>

Generate profiles, build tasks, collect trajectories, and run privacy inference
with your configured model endpoints:

```bash
# 1. Generate calibrated synthetic profiles.
python -m privacy_trace.profile_generator --count 1000

# 2. Build four domain tasks per profile.
python -m privacy_trace.scenario_generator \
  --n 1000 \
  --input artifacts/profile_runs/latest/profiles.jsonl \
  --output artifacts/scenario/cases.jsonl

# 3. Collect Agent trajectories.
python scripts/run_agent_scenarios.py \
  --profiles artifacts/profile_runs/latest/profiles.jsonl \
  --scenarios artifacts/scenario/cases.jsonl \
  --domains travel health shopping career_learning

# 4. Package trajectories and run privacy inference.
python scripts/package_trajectories.py --source-dir artifacts/trajectory_runs/latest
python scripts/run_privacy_attacks.py \
  --input artifacts/trajectories/trajectories.jsonl \
  --output-dir artifacts/privacy_attacks/run \
  --attack-mode two_stage
```

Domain and tool snapshots are included under `config/`. Refresh discovery
snapshots only when intentionally changing the tool catalog. Detailed contracts
are documented in [docs/](docs/) and [scripts/README.md](scripts/README.md).

## Selected results

| Observation | Semantic ASR |
|---|---:|
| Prior-based guessing | 17.97% |
| Full tool trace, single-domain views | **26.25%** |
| Linked four-domain, profile-level views | **32.77%** |

Full-trace inference improves over prior-based guessing by **8.28 percentage
points**. The single-domain comparison uses 4,000 views × 17 attributes; the
four-domain comparison uses 1,000 profile-level views × 17 attributes.
Semantic ASR is the percentage of correctly inferred attribute slots.
See [the result tables](results/paper/data/) for complete analyses.

## Repository structure

| Path | Contents |
|---|---|
| `privacy_trace/` | Profile synthesis, task construction, privacy inference, scoring |
| `privacy_trace/profiles/` | Profile schema, sampling, calibration, LLM calls, and generation workflow |
| `privacy_trace/population_targets/` | Official-source demographic, income, employment, and health targets |
| `agent_env/` | User Simulator, PydanticAI Agent, MCP lifecycle, trajectory recording |
| `llm/` | Provider configuration and multi-key request handling |
| `config/` | Domain definitions, policies, and frozen tool schemas |
| `data/` | Public statistical reference inputs and calibration targets |
| `mcp_servers/` | Licensed snapshots, adapters, and provenance manifest |
| `scripts/` | Environment setup, construction, download, evaluation, and analysis |
| `examples/` | Small illustrative schema fixtures, excluded from paper results |
| `results/paper/` | Frozen aggregate tables and figures |

The Nerfies-based project website is included under [`docs/`](docs/).
It is deployed through GitHub Pages under
[SowingG2333/PrivacyTrace-website](https://github.com/SowingG2333/PrivacyTrace-website);
see [website setup](docs/README.md). See [the code layout](docs/repository_layout.md)
for module responsibilities and [the command guide](scripts/README.md) for entry points.

## Data

Profiles are synthetic; tool responses come from public MCP services.
See [DATA_CARD.md](DATA_CARD.md) for the dataset description and
[the download guide](docs/data_access.md) for access instructions.

## License

To be specified. Third-party components retain their original licenses; see
[THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).
