"""Profile output files and generation diagnostics."""

from __future__ import annotations

import copy
import shutil
from pathlib import Path
from typing import Any, Iterable

from agent_env.recovery import atomic_write_json, atomic_write_jsonl

from .pipeline import (
    SyntheticProfileGenerator,
)
from .schema import (
    FULL_SCHEMA_FIELDS,
    PROJECT_ROOT,
)


def write_profiles(path: Path, profiles: list[dict[str, Any]], jsonl: bool) -> None:
    if jsonl:
        atomic_write_jsonl(path, profiles)
    else:
        atomic_write_json(path, profiles)


def write_pii_diagnostics(
    directory: Path, generator: SyntheticProfileGenerator
) -> dict[str, int]:
    directory.mkdir(parents=True, exist_ok=True)
    records = generator.diagnostic_records()
    initial = [record["initial"] for record in records]
    repaired = [
        {
            "candidate_id": record["candidate_id"],
            **{field: record["repaired"].get(field) for field in FULL_SCHEMA_FIELDS},
            "accepted": record["accepted"],
            "final_issues": record["final_issues"],
        }
        for record in records
    ]
    errors = [
        {
            "candidate_id": record["candidate_id"],
            "repair_history": {
                field: history
                for field, history in record["repair_history"].items()
                if history
            },
            "accepted": record["accepted"],
            "final_issues": record["final_issues"],
        }
        for record in records
        if any(record["repair_history"].values()) or record["final_issues"]
    ]
    write_profiles(directory / "pii_initial.jsonl", initial, jsonl=True)
    write_profiles(directory / "pii_repaired.jsonl", repaired, jsonl=True)
    write_profiles(directory / "pii_errors.jsonl", errors, jsonl=True)
    summary = {
        "records": len(records),
        "accepted": sum(record["accepted"] for record in records),
        "rejected": sum(not record["accepted"] for record in records),
        "records_with_initial_or_repair_errors": len(errors),
        "pii_validation": generator.pii_metrics_report(),
        "llm_usage": copy.deepcopy(generator.llm._llm_usage),
    }
    atomic_write_json(directory / "pii_metrics.json", summary)
    return {
        "initial": len(initial),
        "repaired": len(repaired),
        "errors": len(errors),
    }


def prune_old_profile_generation_runs(
    current_paths: Iterable[Path],
    *,
    root: Path | None = None,
) -> list[Path]:
    """Delete superseded run entries while preserving all current-run outputs."""

    retention_root = (root or PROJECT_ROOT / "artifacts/profile_generation").resolve()
    if not retention_root.is_dir():
        return []

    preserved_entries: set[str] = set()
    for path in current_paths:
        resolved = path.resolve()
        try:
            relative = resolved.relative_to(retention_root)
        except ValueError:
            continue
        if relative.parts:
            preserved_entries.add(relative.parts[0])
    if not preserved_entries:
        return []

    removed: list[Path] = []
    for entry in retention_root.iterdir():
        if entry.name in preserved_entries:
            continue
        if entry.is_dir() and not entry.is_symlink():
            shutil.rmtree(entry)
        else:
            entry.unlink()
        removed.append(entry)
    return removed
