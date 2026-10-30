"""Population constraints and distribution comparisons."""

from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path
from typing import Any

from .schema import (
    REAL_TARGETS_PATH,
    SKELETON_IPF_BUCKET_FIELDS,
    IPFConstraint,
    candidate_key,
    normalize,
)


def build_default_targets() -> list[IPFConstraint]:
    if REAL_TARGETS_PATH.exists():
        return load_targets(REAL_TARGETS_PATH)
    raise FileNotFoundError(
        f"Default real target constraints not found: {REAL_TARGETS_PATH}. "
        "Pass --targets with a real constraint file."
    )


def load_targets(path: Path) -> list[IPFConstraint]:
    with open(path, "r", encoding="utf-8") as handle:
        data = json.load(handle)

    constraints = []
    raw_constraints = data.get("constraints")
    if not isinstance(raw_constraints, list):
        raise ValueError("Target JSON must contain a 'constraints' array.")

    for item in raw_constraints:
        name = item.get("name")
        fields = item.get("fields")
        targets = item.get("targets")
        if (
            not isinstance(name, str)
            or not isinstance(fields, list)
            or not isinstance(targets, dict)
        ):
            raise ValueError("Each constraint must contain name, fields, and targets.")
        constraints.append(
            IPFConstraint(
                name=name,
                fields=tuple(str(field) for field in fields),
                targets=normalize(
                    {str(key): float(value) for key, value in targets.items()}
                ),
            )
        )
    return constraints


def skeleton_ipf_coverage(constraints: list[IPFConstraint]) -> dict[str, bool]:
    constraint_fields = {
        field for constraint in constraints for field in constraint.fields
    }
    return {
        skeleton_field: bool(bucket_fields & constraint_fields)
        for skeleton_field, bucket_fields in SKELETON_IPF_BUCKET_FIELDS.items()
    }


def validate_skeleton_ipf_coverage(constraints: list[IPFConstraint]) -> None:
    coverage = skeleton_ipf_coverage(constraints)
    missing = [field for field, covered in coverage.items() if not covered]
    if missing:
        raise ValueError(
            "Every skeleton field must participate in IPF. Missing fields: "
            + ", ".join(missing)
        )


def targets_to_json(constraints: list[IPFConstraint]) -> dict[str, Any]:
    return {
        "constraints": [
            {
                "name": constraint.name,
                "fields": list(constraint.fields),
                "targets": constraint.targets,
            }
            for constraint in constraints
        ]
    }


def weighted_distribution(
    candidates: list[dict[str, Any]], weights: list[float], fields: tuple[str, ...]
) -> dict[str, float]:
    totals: dict[str, float] = defaultdict(float)
    total_weight = 0.0
    for candidate, weight in zip(candidates, weights):
        if weight <= 0:
            continue
        totals[candidate_key(candidate, fields)] += weight
        total_weight += weight
    if total_weight <= 0:
        return {}
    return {key: value / total_weight for key, value in totals.items()}


def distribution_l1(current: dict[str, float], target: dict[str, float]) -> float:
    keys = set(current) | set(target)
    return sum(abs(current.get(key, 0.0) - target.get(key, 0.0)) for key in keys)
