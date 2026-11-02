"""Shared downloads, data parsing, and margin-calibration helpers."""

from __future__ import annotations

import csv
import io
import math
import re
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path


def download(url: str, path: Path, *, headers: dict[str, str] | None = None) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and path.stat().st_size > 200:
        return path
    request_headers = {
        "User-Agent": "Mozilla/5.0",
        "Referer": "https://www.un.org/development/desa/pd/content/international-migrant-stock",
    }
    request_headers.update(headers or {})
    request = urllib.request.Request(url, headers=request_headers)
    with urllib.request.urlopen(request, timeout=240) as response:
        path.write_bytes(response.read())
    return path


def read_zipped_csv(path: Path) -> list[dict[str, str]]:
    with zipfile.ZipFile(path) as archive:
        name = next(name for name in archive.namelist() if name.endswith(".csv"))
        text = io.TextIOWrapper(archive.open(name), encoding="utf-8-sig")
        return list(csv.DictReader(text))


def overlap_fraction(low: int, high: int, target_low: int, target_high: int) -> float:
    overlap = max(0, min(high, target_high) - max(low, target_low) + 1)
    return overlap / (high - low + 1)


def parse_age_range(label: str) -> tuple[int, int] | None:
    match = re.fullmatch(r"\s*(\d+)\s*-\s*(\d+)\s*", label)
    if match:
        return int(match.group(1)), int(match.group(2))
    match = re.fullmatch(r"\s*(\d+)\s*\+\s*", label)
    if match:
        return int(match.group(1)), 120
    return None


def normalize(values: dict[str, float]) -> dict[str, float]:
    total = sum(max(0.0, value) for value in values.values())
    if total <= 0:
        raise ValueError("Cannot normalize an empty distribution")
    return {key: max(0.0, value) / total for key, value in values.items()}


def rake_matrix(
    prior: dict[tuple[str, str], float],
    row_targets: dict[str, float],
    column_targets: dict[str, float],
    *,
    tolerance: float = 1e-10,
    max_iterations: int = 2_000,
) -> dict[tuple[str, str], float]:
    """Rake a non-negative two-dimensional prior to exact row/column margins."""

    rows = list(row_targets)
    columns = list(column_targets)
    row_total = sum(row_targets.values())
    column_total = sum(column_targets.values())
    if not math.isclose(row_total, column_total, rel_tol=0, abs_tol=1e-9):
        raise ValueError(
            f"Raking margins disagree: rows={row_total}, columns={column_total}"
        )
    scale = max(row_total, 1.0)
    epsilon = scale * 1e-12
    values = {
        (row, column): (
            max(0.0, float(prior.get((row, column), 0.0))) + epsilon
            if row_targets[row] > 0 and column_targets[column] > 0
            else 0.0
        )
        for row in rows
        for column in columns
    }

    for _ in range(max_iterations):
        for row in rows:
            current = sum(values[(row, column)] for column in columns)
            target = row_targets[row]
            factor = target / current if current > 0 else 0.0
            for column in columns:
                values[(row, column)] *= factor
        for column in columns:
            current = sum(values[(row, column)] for row in rows)
            target = column_targets[column]
            factor = target / current if current > 0 else 0.0
            for row in rows:
                values[(row, column)] *= factor
        maximum_error = max(
            [
                abs(sum(values[(row, column)] for column in columns) - row_targets[row])
                for row in rows
            ]
            + [
                abs(sum(values[(row, column)] for row in rows) - column_targets[column])
                for column in columns
            ]
        )
        if maximum_error <= tolerance:
            return values
    raise RuntimeError(
        f"Raking did not converge after {max_iterations} iterations; "
        f"max error={maximum_error}"
    )


def calibrate_probabilities_to_mean(
    probabilities: dict[str, float],
    weights: dict[str, float],
    target_mean: float,
) -> dict[str, float]:
    """Apply one logit intercept shift while preserving probability ordering."""

    target_mean = min(1.0, max(0.0, target_mean))
    normalized_weights = normalize(weights)
    if target_mean <= 0:
        return {key: 0.0 for key in probabilities}
    if target_mean >= 1:
        return {key: 1.0 for key in probabilities}

    logits = {}
    for key, probability in probabilities.items():
        probability = min(1.0 - 1e-9, max(1e-9, float(probability)))
        logits[key] = math.log(probability / (1.0 - probability))

    low, high = -40.0, 40.0
    calibrated: dict[str, float] = {}
    for _ in range(200):
        shift = (low + high) / 2.0
        calibrated = {
            key: 1.0 / (1.0 + math.exp(-(logit + shift)))
            for key, logit in logits.items()
        }
        mean = sum(normalized_weights[key] * calibrated[key] for key in probabilities)
        if mean < target_mean:
            low = shift
        else:
            high = shift
    return calibrated


def grouped_education_margins(
    education_targets: dict[str, float],
    country: str,
    mapping: dict[str, str],
) -> dict[str, float]:
    groups = list(dict.fromkeys(mapping.values()))
    values = {group: 0.0 for group in groups}
    for education_level, group in mapping.items():
        values[group] += education_targets[f"{country} | {education_level}"]
    return values
