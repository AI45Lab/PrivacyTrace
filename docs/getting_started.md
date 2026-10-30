# Environment and construction

Use Python 3.10 on Linux for the recorded reference environment. Supported
dependency ranges are in `requirements.txt`; the historical snapshot is in
`requirements-lock.txt`. The setup helper creates `.venv/` without changing
system Python:

```bash
PYTHON=python3.10 bash scripts/setup_environment.sh
source .venv/bin/activate
```

Add `--locked` to install the recorded dependency snapshot. The environment
also includes the Hugging Face download client.

## Configure services

Copy `.env.example` to `.env` for your model endpoints. Copy `.env.mcp.example`
to `.env.mcp` and supply only the credentials needed by the servers you enable.
Do not commit either local file. Model names in historical records identify the
experiment; availability of the original provider build is not guaranteed.

Live MCP execution additionally needs Node.js (22 or newer recommended) for
Node adapters, and `uv` for isolated Python servers:

```bash
python -m pip install uv
python mcp_servers/install.py --install-dependencies
```

Seven upstream projects have no explicit redistribution license and their
sources are omitted. Inspect `THIRD_PARTY_NOTICES.md` before explicitly opting
into their pinned-source fetch:

```bash
python mcp_servers/install.py --fetch-external --accept-unlicensed-upstream
python mcp_servers/install.py --install-dependencies
```

## Two workflows

**Construct new records:** follow the four commands in the root README. Profile
generation defaults to `artifacts/profile_runs/latest/`; the scenario and
trajectory commands pass that profile path explicitly. Outputs are local and
ignored by Git. Review each stage before proceeding.

**Reproduce frozen results:** obtain approved external data using
`docs/data_access.md`, then run:

```bash
python scripts/build_paper_results.py --input-root . --output-root reproduced_results
```

If data were extracted elsewhere, pass that directory as `--input-root`. It
must contain `artifacts/profile_pool/`, `artifacts/scenario/`,
`artifacts/trajectories/`, and `artifacts/privacy_experiments/`.

Generating new model outputs is not equivalent to reproducing the frozen
results: provider builds, tool responses, and sampling can change.
