"""Health target construction from IHME prevalence inputs."""

from __future__ import annotations

import csv
import math
from pathlib import Path
from typing import Any

from .common import (
    overlap_fraction,
)
from .constants import (
    AGE_GROUPS,
    COUNTRY_CODES,
    GBD_AGE_ID_TO_RANGE,
    GBD_LOCATION_ID_TO_COUNTRY,
    GBD_SEX_ID_TO_SEX,
    MENTAL_CAUSE_IDS,
    MENTAL_CONDITION_STATISTICS,
    PHYSICAL_CAUSE_IDS,
    PHYSICAL_CONDITION_STATISTICS,
)


def load_ihme_gbd_2023(
    path: Path,
) -> tuple[dict[tuple[str, int, str, int], float], dict[str, Any]]:
    """Load and strictly validate the project's IHME GBD 2023 query export."""

    if not path.exists():
        raise FileNotFoundError(
            f"IHME GBD 2023 CSV not found: {path}. "
            "Pass --ihme-gbd with the verified prevalence export."
        )
    expected_cause_ids = {
        cause_id
        for mapping in (PHYSICAL_CAUSE_IDS, MENTAL_CAUSE_IDS)
        for cause_ids in mapping.values()
        for cause_id in cause_ids
    }
    rates: dict[tuple[str, int, str, int], float] = {}
    cause_names: dict[int, str] = {}
    observed_locations: set[int] = set()
    observed_ages: set[int] = set()
    observed_sexes: set[int] = set()
    observed_causes: set[int] = set()
    row_count = 0
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        required = {
            "population_group_id",
            "measure_id",
            "location_id",
            "sex_id",
            "age_id",
            "cause_id",
            "cause_name",
            "metric_id",
            "year",
            "val",
        }
        missing_columns = required - set(reader.fieldnames or [])
        if missing_columns:
            raise ValueError(
                f"IHME GBD CSV is missing columns: {sorted(missing_columns)}"
            )
        for row in reader:
            row_count += 1
            if (
                int(row["population_group_id"]) != 1
                or int(row["measure_id"]) != 5
                or int(row["metric_id"]) != 3
                or int(row["year"]) != 2023
            ):
                raise ValueError(
                    "IHME GBD CSV must contain all-population prevalence rates "
                    "for year 2023 only."
                )
            location_id = int(row["location_id"])
            age_id = int(row["age_id"])
            sex_id = int(row["sex_id"])
            cause_id = int(row["cause_id"])
            if location_id not in GBD_LOCATION_ID_TO_COUNTRY:
                raise ValueError(f"Unexpected IHME location_id: {location_id}")
            if age_id not in GBD_AGE_ID_TO_RANGE:
                raise ValueError(f"Unexpected IHME age_id: {age_id}")
            if sex_id not in GBD_SEX_ID_TO_SEX:
                raise ValueError(f"Unexpected IHME sex_id: {sex_id}")
            if cause_id not in expected_cause_ids:
                raise ValueError(f"Unexpected IHME cause_id: {cause_id}")
            value = float(row["val"])
            if not math.isfinite(value) or not 0.0 <= value <= 100_000.0:
                raise ValueError(
                    f"Invalid prevalence rate for cause_id={cause_id}: {value}"
                )
            key = (
                GBD_LOCATION_ID_TO_COUNTRY[location_id],
                age_id,
                GBD_SEX_ID_TO_SEX[sex_id],
                cause_id,
            )
            if key in rates:
                raise ValueError(f"Duplicate IHME GBD cell: {key}")
            rates[key] = value
            cause_names[cause_id] = row["cause_name"].strip()
            observed_locations.add(location_id)
            observed_ages.add(age_id)
            observed_sexes.add(sex_id)
            observed_causes.add(cause_id)

    dimensions = (
        ("locations", observed_locations, set(GBD_LOCATION_ID_TO_COUNTRY)),
        ("ages", observed_ages, set(GBD_AGE_ID_TO_RANGE)),
        ("sexes", observed_sexes, set(GBD_SEX_ID_TO_SEX)),
        ("causes", observed_causes, expected_cause_ids),
    )
    for label, observed, expected in dimensions:
        if observed != expected:
            raise ValueError(
                f"IHME GBD {label} mismatch; "
                f"missing={sorted(expected - observed)}, "
                f"unexpected={sorted(observed - expected)}"
            )
    expected_rows = math.prod(
        len(values)
        for values in (
            GBD_LOCATION_ID_TO_COUNTRY,
            GBD_AGE_ID_TO_RANGE,
            GBD_SEX_ID_TO_SEX,
            expected_cause_ids,
        )
    )
    if row_count != expected_rows or len(rates) != expected_rows:
        raise ValueError(
            f"IHME GBD query is incomplete: expected {expected_rows} cells, "
            f"read {row_count} rows and {len(rates)} unique cells."
        )
    return rates, {
        "row_count": row_count,
        "unique_cell_count": len(rates),
        "location_count": len(observed_locations),
        "age_count": len(observed_ages),
        "sex_count": len(observed_sexes),
        "cause_count": len(observed_causes),
        "measure": "Prevalence",
        "metric": "Rate per 100,000",
        "year": 2023,
        "cause_names_by_id": {
            str(cause_id): cause_names[cause_id] for cause_id in sorted(cause_names)
        },
    }


def build_one_label_health_targets(
    *,
    rates: dict[tuple[str, int, str, int], float],
    wpp: dict[str, Any],
    country_age_sex_targets: dict[str, float],
    condition_cause_ids: dict[str, tuple[int, ...]],
    condition_statistics: dict[str, Any],
) -> tuple[dict[str, float], dict[str, Any]]:
    """Build country × age × sex × representative-condition targets.

    GBD prevalences are overlapping marginals.  Within every demographic cell,
    the probability of at least one selected condition is approximated with
    ``1-product(1-p_i)`` and allocated across labels in proportion to the raw
    mapped prevalences.  This keeps the source's relative condition rates while
    respecting the schema's one-label representation.
    """

    targets: dict[str, float] = {}
    prevalence_audit: dict[str, dict[str, float]] = {}
    selected_envelopes: list[float] = []
    weighted_raw_prevalence = {condition: 0.0 for condition in condition_cause_ids}
    for country in COUNTRY_CODES:
        for age_group, (target_low, target_high) in AGE_GROUPS.items():
            for sex in ("female", "male"):
                population_denominator = 0.0
                weighted_rates = {condition: 0.0 for condition in condition_cause_ids}
                for age_id, (source_low, source_high) in GBD_AGE_ID_TO_RANGE.items():
                    fraction = overlap_fraction(
                        source_low,
                        source_high,
                        target_low,
                        target_high,
                    )
                    if fraction <= 0:
                        continue
                    population = (
                        wpp["age5_sex"][(country, 2025, source_low, source_high, sex)]
                        * fraction
                    )
                    population_denominator += population
                    for condition, cause_ids in condition_cause_ids.items():
                        source_rate = sum(
                            rates[(country, age_id, sex, cause_id)]
                            for cause_id in cause_ids
                        )
                        weighted_rates[condition] += source_rate * population
                if population_denominator <= 0:
                    raise RuntimeError(
                        f"No WPP population support for {country}/{age_group}/{sex}"
                    )
                prevalence_per_100k = {
                    condition: value / population_denominator
                    for condition, value in weighted_rates.items()
                }
                probabilities = {
                    condition: min(1.0, max(0.0, value / 100_000.0))
                    for condition, value in prevalence_per_100k.items()
                }
                probability_sum = sum(probabilities.values())
                none_probability = math.prod(
                    1.0 - probability for probability in probabilities.values()
                )
                selected_envelope = 1.0 - none_probability
                selected_envelopes.append(selected_envelope)
                demographic_key = f"{country} | {age_group} | {sex}"
                demographic_mass = country_age_sex_targets[demographic_key]
                targets[f"{demographic_key} | None"] = (
                    demographic_mass * none_probability
                )
                for condition, probability in probabilities.items():
                    allocation = (
                        selected_envelope * probability / probability_sum
                        if probability_sum > 0
                        else 0.0
                    )
                    targets[f"{demographic_key} | {condition}"] = (
                        demographic_mass * allocation
                    )
                    weighted_raw_prevalence[condition] += (
                        demographic_mass * prevalence_per_100k[condition]
                    )
                prevalence_audit[demographic_key] = {
                    condition: round(value, 8)
                    for condition, value in prevalence_per_100k.items()
                }

    return targets, {
        "single_label_semantics": (
            "IHME GBD 2023 cause prevalences are overlapping marginals, while "
            "the profile schema stores one representative condition. Within "
            "each country-age-sex cell, child causes mapped to one schema label "
            "are summed first. The probability of at least one selected label "
            "is then approximated as 1-product(1-p_i), and that envelope is "
            "allocated in proportion to the mapped prevalence rates."
        ),
        "age_aggregation": (
            "IHME five-year age-specific rates are population-weighted with "
            "UN WPP 2025 sex-specific populations. Ages 18-24 use 2/5 of "
            "15-19 plus all of 20-24; ages 65-80 use all of 65-79 plus 1/5 "
            "of 80-84."
        ),
        "condition_statistics": condition_statistics,
        "condition_cause_ids": {
            condition: list(cause_ids)
            for condition, cause_ids in condition_cause_ids.items()
        },
        "population_weighted_raw_prevalence_per_100k": {
            condition: round(value, 8)
            for condition, value in weighted_raw_prevalence.items()
        },
        "population_weighted_selected_condition_share": sum(
            value for key, value in targets.items() if not key.endswith(" | None")
        ),
        "selected_condition_envelope_range": {
            "minimum": min(selected_envelopes),
            "maximum": max(selected_envelopes),
        },
        "country_age_sex_prevalence_per_100k": prevalence_audit,
    }


def build_health_targets(
    *,
    gbd_path: Path,
    wpp: dict[str, Any],
    country_age_sex_targets: dict[str, float],
) -> tuple[dict[str, float], dict[str, Any], dict[str, float], dict[str, Any]]:
    rates, dataset_audit = load_ihme_gbd_2023(gbd_path)
    physical_targets, physical_audit = build_one_label_health_targets(
        rates=rates,
        wpp=wpp,
        country_age_sex_targets=country_age_sex_targets,
        condition_cause_ids=PHYSICAL_CAUSE_IDS,
        condition_statistics=PHYSICAL_CONDITION_STATISTICS,
    )
    mental_targets, mental_audit = build_one_label_health_targets(
        rates=rates,
        wpp=wpp,
        country_age_sex_targets=country_age_sex_targets,
        condition_cause_ids=MENTAL_CAUSE_IDS,
        condition_statistics=MENTAL_CONDITION_STATISTICS,
    )
    physical_audit["ihme_query_validation"] = dataset_audit
    mental_audit["ihme_query_validation"] = dataset_audit
    return physical_targets, physical_audit, mental_targets, mental_audit
