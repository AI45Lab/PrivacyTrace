# Repository layout

The repository is organized by ownership and artifact lifetime.

## Source packages

| Path | Responsibility |
|---|---|
| `privacy_trace/` | Profile and scenario synthesis, privacy inference, and scoring |
| `privacy_trace/profiles/` | Profile schema, proposals, calibration, LLM calls, checkpoints, and generation workflow |
| `privacy_trace/population_targets/` | Statistical source readers and demographic, income, employment, and health target builders |
| `agent_env/` | Task models, simulator, PydanticAI adapter, MCP process lifecycle, orchestration, and trajectory evaluation |
| `llm/` | OpenAI-compatible provider configuration and request normalization |

Source packages never import from `scripts/` or `artifacts/`.

### Profile synthesis

`privacy_trace.profile_generator` remains the public import and command-line
entry point. Implementation is organized within `privacy_trace/profiles/`:

| Module | Responsibility |
|---|---|
| `schema.py`, `targets.py` | Attribute options, generation settings, target loading, and distribution comparisons |
| `population.py` | Candidate proposals, IPF calibration, and weighted sampling |
| `llm.py` | Provider configuration, per-key scheduling, and request accounting |
| `checkpoint.py` | Completed-batch storage and resume state |
| `validation.py`, `prompts.py` | Identifier validation and generation prompts |
| `pipeline.py` | Coordinate synthesis stages through the population, LLM, and checkpoint components |
| `storage.py`, `cli.py` | Output files and command-line handling |

`SyntheticProfileGenerator` owns the three components explicitly; it retains
its existing generation and sampling methods for callers and subclasses.

### Population calibration inputs

The entry point `scripts/rebuild_official_ipf_targets.py` delegates to
`privacy_trace/population_targets/`. Source-specific transformations live in
`demographics.py`, `income.py`, `employment.py`, and `health.py`. `constants.py`
and `common.py` hold shared categories and numerical helpers. `constraints.py`
and `reports.py` update the target document and provenance outputs;
`pipeline.py` coordinates these phases and `cli.py` defines arguments.

Add a statistical source to its domain builder rather than to the CLI script.

## MCP catalog

`mcp_servers/commands.json` is the launch catalog. `mcp_servers/` contains the
vendored server sources and the pinned adapters used by that catalog.
Generated `.venv`, `node_modules`, `build`, `dist`, and cache directories are
recreated by `mcp_servers/install.py` and are not source.

## Project website

The static Nerfies-based project page lives alongside the documentation in
`docs/`: `index.html`, CSS/JS, `assets/`, and `vendor/`. Deployment is hosted
separately under `SowingG2333/PrivacyTrace-website` with GitHub Pages.
See [website setup](README.md) for local preview and resource links.

## Configuration and reproducibility inputs

- `config/` contains runtime policy and MCP tool snapshots, never credentials.
- `data/targets/` contains calibrated demographic targets.
- `data/catalogs/` contains reproducible lookup catalogs.
- `data/sources/` contains the compact official-source derivatives required to
  rebuild targets.
- `.env` and `.env.mcp` contain local credentials and are ignored.

## Local artifacts

Full experiment data are not included in this code repository. Downloaded or
newly generated data are stored locally under `artifacts/`:

```text
artifacts/
├── profile_pool/           # retained candidate pool and 1k sampled profiles
├── profile_runs/           # newly generated profile runs
├── scenario/               # generated/audited scenarios
├── trajectories/           # Agent trajectories and batch summaries
└── privacy_attacks/        # inferred profiles and evaluation outputs
```

No source module depends on a diagnostic or report artifact. If a snapshot is
required to rebuild configuration, it belongs in `config/`, as with
`scenario_tool_discovery_base.json`.

## Entry points

Operational commands live in `scripts/`. Reusable logic remains in source
packages, so importing a module does not start a server or mutate artifacts.
See `scripts/README.md` for commands grouped by workflow.

## Dependency direction

```text
scripts
  ├─ privacy_trace
  └─ agent_env
       ├─ llm
       ├─ PydanticAI / FastMCP
       └─ mcp_servers/commands.json

config + data → source packages → artifacts
```

The custom MCP-Bench executor, server managers, benchmark runner, task
synthesis package, and bundled benchmark task data are intentionally absent.
PydanticAI is the only evaluated Agent runtime.

## Development checks

Run the existing unit tests from the repository root:

```bash
python -m unittest discover -s tests -q
```
