#!/usr/bin/env python3
"""Download PrivacyTrace data from Hugging Face."""
from __future__ import annotations
import argparse
import gzip
from pathlib import Path
import shutil
import tarfile
from huggingface_hub import snapshot_download


def unpack(archive: Path, output: Path) -> None:
    with tarfile.open(archive, 'r:gz') as handle:
        for member in handle.getmembers():
            target = (output / member.name).resolve()
            if not target.is_relative_to(output.resolve()) or not (member.isfile() or member.isdir()):
                raise ValueError(f'Unsafe archive entry: {member.name}')
        handle.extractall(output)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument('--local-dir', type=Path, help='Use previously downloaded archives.')
    args = parser.parse_args()
    output = args.output.resolve()
    folder = args.local_dir or output / '.downloads'
    if args.local_dir is None:
        snapshot_download('SowingG/PrivacyTrace', repo_type='dataset',
                          allow_patterns=['privacytrace-*.gz'], local_dir=folder)
    output.mkdir(parents=True, exist_ok=True)
    unpack(folder / 'privacytrace-profiles-scenarios.tar.gz', output)
    unpack(folder / 'privacytrace-evaluations.tar.gz', output)
    target = output / 'artifacts/trajectories/trajectories.jsonl'
    target.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(folder / 'privacytrace-trajectories.jsonl.gz', 'rb') as source, target.open('wb') as dest:
        shutil.copyfileobj(source, dest)
    print(f'Data saved to {output / "artifacts"}')


if __name__ == '__main__':
    main()
