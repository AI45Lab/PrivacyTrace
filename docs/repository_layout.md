# Code organization

The repository is organized by the stages used to build and evaluate PrivacyTrace.

| Directory | Responsibility |
|---|---|
| `generate/` | Profile synthesis, population calibration, task generation, and tool discovery |
| `agent/` | User simulator, PydanticAI agent, MCP lifecycle, and trajectory collection |
| `attack/` | Observer views, profile inference, and channel/scope experiments |
| `eval/` | Semantic judging, record aggregation, and result reproduction |
| `llm/` | Provider configuration and API clients |

Each stage includes its own command-line entry points. For example:

```bash
python -m generate.generate_profiles --help
python -m agent.run_scenarios --help
python -m attack.run_attacks --help
python -m eval.run_judge --help
```

Profile implementation details live in `generate/profiles/`.
Official statistical source readers live in `generate/population_targets/`.
The MCP launch catalog is `mcp_servers/commands.json`; server sources and adapters
are under `mcp_servers/`.

`config/` holds domain settings, runtime policies, and frozen tool schemas.
`data/` holds population reference inputs and calibration targets.
`examples/` contains small illustrative task records.

Downloaded and generated records stay under the ignored `artifacts/` directory:

```text
artifacts/
├── profile_pool/       # released synthetic profiles
├── profile_runs/       # new profile-generation runs
├── scenario/           # task scenarios
├── trajectory_runs/    # individual trajectory runs
├── trajectories/       # packaged trajectory data
├── privacy_attack/    # predictions and evaluation outputs
└── results/            # reproduced tables and figures
```

The project website has a separate repository:
[SowingG2333/PrivacyTrace-website](https://github.com/SowingG2333/PrivacyTrace-website).

See [the command guide](commands.md) for available entry points.
Run unit tests with `python -m unittest discover -s tests -q`.
