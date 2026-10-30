#!/usr/bin/env bash
set -euo pipefail

project_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
python_bin="${PYTHON:-python3}"
requirements_file="requirements.txt"
if [[ "$#" -gt 1 ]]; then
  echo "Usage: PYTHON=python3.10 bash scripts/setup_environment.sh [--locked]" >&2
  exit 2
fi
if [[ "${1:-}" == "--locked" ]]; then
  requirements_file="requirements-lock.txt"
elif [[ "$#" != 0 ]]; then
  echo "Usage: PYTHON=python3.10 bash scripts/setup_environment.sh [--locked]" >&2
  exit 2
fi
cd "$project_root"
"$python_bin" -c 'import sys; assert sys.version_info >= (3, 10), "Python 3.10 or newer is required"'
"$python_bin" -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -r "$requirements_file" -r requirements-data.txt
echo "Environment ready. Activate with: source .venv/bin/activate"
echo "MCP server dependencies are installed separately; see docs/getting_started.md."
