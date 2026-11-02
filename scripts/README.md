# Setup and download

```bash
PYTHON=python3.10 bash scripts/setup_environment.sh
source .venv/bin/activate
hf auth login
python scripts/download_data.py
```

Workflow commands live with their implementations in `generate/`,
`agent/`, `attack/`, and `eval/`. See the
[command guide](../docs/commands.md).
