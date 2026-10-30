# Download data

Dataset: https://huggingface.co/datasets/SowingG/PrivacyTrace

Request access on the dataset page. After the authors approve your request:

```bash
pip install -r requirements-data.txt
hf auth login
python scripts/download_data.py
```

The downloader restores data under `artifacts/` in the code repository.
Use `--output /path/to/data` to choose a different location.
For already downloaded archives, use `--local-dir /path/to/archives`.

The three archives contain profiles/scenarios, Agent trajectories, and
attack/evaluation results. See the dataset page for file descriptions and
access terms.
