"""ILOSTAT panels and joint employment and education targets."""

from __future__ import annotations

import math
from collections import defaultdict
from pathlib import Path
from typing import Any

from .common import (
    calibrate_probabilities_to_mean,
    grouped_education_margins,
    normalize,
    rake_matrix,
)
from .constants import (
    AGE_GROUPS,
    COUNTRY_CODES,
    ILO_AGE_CODES,
    ILO_AGE_STAGE_CODES,
    ILO_EDUCATION_DETAILED_TO_GROUP,
    ILO_EDUCATION_GROUPS,
    ILO_EDUCATION_LEVEL_TO_GROUP,
    ILO_MARITAL_STATUS_TO_RELATIONSHIP,
    ILO_OBSERVED_OCCUPATION_TO_GROUP,
    ILO_SEX_CODES,
    OCCUPATION_CODES,
    OCCUPATIONS,
    RELATIONSHIPS,
)


def _ilo_candidate_groups(frame: Any) -> list[tuple[int, float, str, Any]]:
    candidates = []
    for (time_value, source), group in frame.groupby(["time", "source"]):
        year = int(time_value)
        if year > 2025:
            continue
        best = float(group["best_source"].max())
        candidates.append((year, best, str(source), group))
    return sorted(candidates, key=lambda item: (item[0], item[1]), reverse=True)


def _education_code_mapping(mode: str) -> dict[str, str]:
    if mode == "aggregate":
        return {
            code: group
            for group, codes in ILO_EDUCATION_GROUPS.items()
            for code in codes
        }
    prefix = "EDU_ISCED11_" if mode == "isced11" else "EDU_ISCED97_"
    return {
        code: group
        for code, group in ILO_EDUCATION_DETAILED_TO_GROUP.items()
        if code.startswith(prefix)
    }


def select_ilo_age_education_panel(
    frame: Any,
    iso3: str,
) -> tuple[dict[tuple[str, str, str], float], dict[str, Any]] | None:
    """Select the latest complete sex × 10-year-age × education panel."""

    subset = frame[
        (frame["ref_area"] == iso3)
        & (frame["sex"].isin(ILO_SEX_CODES))
        & (frame["classif1"].isin(ILO_AGE_CODES))
    ]
    required = {
        (age_group, sex, education_group)
        for age_group in AGE_GROUPS
        for sex in ILO_SEX_CODES.values()
        for education_group in ILO_EDUCATION_GROUPS
    }
    for year, best, source, candidate in _ilo_candidate_groups(subset):
        for mode in ("aggregate", "isced11", "isced97"):
            code_mapping = _education_code_mapping(mode)
            rows = candidate[candidate["classif2"].isin(code_mapping)]
            values: dict[tuple[str, str, str], float] = defaultdict(float)
            present: set[tuple[str, str, str]] = set()
            for row in rows.itertuples(index=False):
                key = (
                    ILO_AGE_CODES[str(row.classif1)],
                    ILO_SEX_CODES[str(row.sex)],
                    code_mapping[str(row.classif2)],
                )
                values[key] += max(0.0, float(row.obs_value))
                present.add(key)
            if present == required:
                return dict(values), {
                    "year": year,
                    "source": source,
                    "best_source": bool(best),
                    "education_classification": mode,
                }
    return None


def select_ilo_age_rate_panel(
    frame: Any,
    iso3: str,
) -> tuple[dict[tuple[str, str], float], dict[str, Any]] | None:
    """Select the latest complete sex × 10-year-age employment-rate panel."""

    subset = frame[
        (frame["ref_area"] == iso3)
        & (frame["sex"].isin(ILO_SEX_CODES))
        & (frame["classif1"].isin(ILO_AGE_CODES))
    ]
    required = {
        (age_group, sex) for age_group in AGE_GROUPS for sex in ILO_SEX_CODES.values()
    }
    for year, best, source, candidate in _ilo_candidate_groups(subset):
        values: dict[tuple[str, str], float] = {}
        for row in candidate.itertuples(index=False):
            key = (
                ILO_AGE_CODES[str(row.classif1)],
                ILO_SEX_CODES[str(row.sex)],
            )
            values[key] = min(1.0, max(0.0, float(row.obs_value) / 100.0))
        if set(values) == required:
            return values, {
                "year": year,
                "source": source,
                "best_source": bool(best),
            }
    return None


def load_ilo_rds(path: Path) -> Any:
    """Read an ILOSTAT bulk RDS without requiring an R installation."""

    try:
        import rdata
        from rdata.conversion import DEFAULT_CLASS_MAP
    except ImportError as exc:
        raise RuntimeError(
            "The official ILOSTAT bulk files require the 'rdata' package. "
            "Install project requirements and rerun."
        ) from exc

    def forgiving_factor(values: Any, attrs: dict[str, Any]) -> list[Any]:
        raw_levels = attrs.get("levels")
        levels = [] if raw_levels is None else list(raw_levels)
        output = []
        for code in values:
            try:
                index = int(code) - 1
            except (TypeError, ValueError):
                output.append(None)
                continue
            output.append(levels[index] if 0 <= index < len(levels) else None)
        return output

    constructors = dict(DEFAULT_CLASS_MAP)
    constructors.update(factor=forgiving_factor, ordered=forgiving_factor)
    return rdata.read_rds(path, constructor_dict=constructors)


def build_occupation_targets(
    wpp: dict[str, Any],
    occupation_rows: Any,
    employment_rows: Any,
) -> tuple[dict[str, float], dict[str, Any]]:
    """Build current-country × sex × occupation from ILOSTAT 2025.

    ILOSTAT supplies employment-to-population ratios and the distribution of
    employed persons by ISCO group.  The complement of the former is the
    explicit ``None`` category in this single-valued profile field.
    """

    sex_codes = {"male": "SEX_M", "female": "SEX_F"}
    adult_population = {
        (country, sex): sum(
            wpp["age_sex"][(country, 2025, age_group, sex)] for age_group in AGE_GROUPS
        )
        for country in COUNTRY_CODES
        for sex in sex_codes
    }
    population_total = sum(adult_population.values())
    targets: dict[str, float] = {}
    audit: dict[str, Any] = {}

    for country, info in COUNTRY_CODES.items():
        for sex, sex_code in sex_codes.items():
            rate_match = employment_rows[
                (employment_rows["ref_area"] == info["iso3"])
                & (employment_rows["time"] == "2025")
                & (employment_rows["sex"] == sex_code)
                & (employment_rows["classif1"] == "AGE_YTHADULT_YGE15")
            ]
            if len(rate_match) != 1:
                raise RuntimeError(
                    f"Expected one ILOSTAT employment-rate row for {country}/{sex}; "
                    f"found {len(rate_match)}."
                )
            employed_share = min(
                1.0, max(0.0, float(rate_match.iloc[0]["obs_value"]) / 100.0)
            )

            group_counts: dict[str, float] = {}
            for code, label in OCCUPATION_CODES.items():
                match = occupation_rows[
                    (occupation_rows["ref_area"] == info["iso3"])
                    & (occupation_rows["time"] == "2025")
                    & (occupation_rows["sex"] == sex_code)
                    & (occupation_rows["classif1"] == code)
                ]
                if len(match) != 1:
                    raise RuntimeError(
                        f"Expected one ILOSTAT occupation row for "
                        f"{country}/{sex}/{code}; found {len(match)}."
                    )
                group_counts[label] = float(match.iloc[0]["obs_value"])
            employed_distribution = normalize(group_counts)
            population_mass = adult_population[(country, sex)] / population_total
            targets[f"{country} | {sex} | None"] = population_mass * (
                1.0 - employed_share
            )
            for label, share in employed_distribution.items():
                targets[f"{country} | {sex} | {label}"] = (
                    population_mass * employed_share * share
                )
            audit[f"{country} | {sex}"] = {
                "employment_to_population_ratio_age_15_plus": employed_share,
                "occupation_distribution_among_employed": employed_distribution,
                "population_weight_scope": "UN WPP 2025 ages 18-80",
            }
    return targets, audit


def select_ilo_education_rate_panel(
    frame: Any,
    iso3: str,
) -> tuple[dict[tuple[str, str], float], dict[str, Any]] | None:
    subset = frame[(frame["ref_area"] == iso3) & (frame["sex"].isin(ILO_SEX_CODES))]
    required = {
        (sex, education_group)
        for sex in ILO_SEX_CODES.values()
        for education_group in ILO_EDUCATION_GROUPS
    }
    aggregate_mapping = _education_code_mapping("aggregate")
    subset = subset[subset["classif1"].isin(aggregate_mapping)]
    for year, best, source, candidate in _ilo_candidate_groups(subset):
        values = {
            (
                ILO_SEX_CODES[str(row.sex)],
                aggregate_mapping[str(row.classif1)],
            ): min(1.0, max(0.0, float(row.obs_value) / 100.0))
            for row in candidate.itertuples(index=False)
        }
        if set(values) == required:
            return values, {
                "year": year,
                "source": source,
                "best_source": bool(best),
            }
    return None


def select_ilo_occupation_education_panel(
    frame: Any,
    iso3: str,
) -> tuple[dict[tuple[str, str], float], dict[str, Any]] | None:
    subset = frame[
        (frame["ref_area"] == iso3)
        & (frame["classif1"].isin(ILO_OBSERVED_OCCUPATION_TO_GROUP))
        & (frame["sex"].isin(["SEX_T", *ILO_SEX_CODES]))
    ]
    required = {
        (education_group, occupation_group)
        for education_group in ILO_EDUCATION_GROUPS
        for occupation_group in set(ILO_OBSERVED_OCCUPATION_TO_GROUP.values())
    }
    for year, best, source, candidate in _ilo_candidate_groups(subset):
        for mode in ("aggregate", "isced11", "isced97"):
            education_mapping = _education_code_mapping(mode)
            rows = candidate[candidate["classif2"].isin(education_mapping)]
            for sex_mode in ("total", "sum_sexes"):
                if sex_mode == "total":
                    selected = rows[rows["sex"] == "SEX_T"]
                else:
                    selected = rows[rows["sex"].isin(ILO_SEX_CODES)]
                    if set(selected["sex"]) != set(ILO_SEX_CODES):
                        continue
                values: dict[tuple[str, str], float] = defaultdict(float)
                present: set[tuple[str, str]] = set()
                for row in selected.itertuples(index=False):
                    key = (
                        education_mapping[str(row.classif2)],
                        ILO_OBSERVED_OCCUPATION_TO_GROUP[str(row.classif1)],
                    )
                    values[key] += max(0.0, float(row.obs_value))
                    present.add(key)
                if present == required:
                    return dict(values), {
                        "year": year,
                        "source": source,
                        "best_source": bool(best),
                        "education_classification": mode,
                        "sex_aggregation": sex_mode,
                    }
    return None


def select_ilo_age_stage_occupation_panel(
    frame: Any,
    iso3: str,
) -> tuple[dict[tuple[str, str, str], float], dict[str, Any]] | None:
    subset = frame[
        (frame["ref_area"] == iso3)
        & (frame["sex"].isin(ILO_SEX_CODES))
        & (frame["classif1"].isin(ILO_AGE_STAGE_CODES))
        & (frame["classif2"].isin(ILO_OBSERVED_OCCUPATION_TO_GROUP))
    ]
    required = {
        (stage, sex, occupation)
        for stage in ILO_AGE_STAGE_CODES.values()
        for sex in ILO_SEX_CODES.values()
        for occupation in set(ILO_OBSERVED_OCCUPATION_TO_GROUP.values())
    }
    for year, best, source, candidate in _ilo_candidate_groups(subset):
        values: dict[tuple[str, str, str], float] = defaultdict(float)
        present: set[tuple[str, str, str]] = set()
        for row in candidate.itertuples(index=False):
            value = float(row.obs_value)
            if not math.isfinite(value):
                continue
            key = (
                ILO_AGE_STAGE_CODES[str(row.classif1)],
                ILO_SEX_CODES[str(row.sex)],
                ILO_OBSERVED_OCCUPATION_TO_GROUP[str(row.classif2)],
            )
            values[key] += max(0.0, value)
            present.add(key)
        if present == required:
            return dict(values), {
                "year": year,
                "source": source,
                "best_source": bool(best),
            }
    return None


def select_ilo_age_marital_rate_panel(
    frame: Any,
    iso3: str,
) -> tuple[dict[tuple[str, str, str], float], dict[str, Any]] | None:
    subset = frame[
        (frame["ref_area"] == iso3)
        & (frame["sex"].isin(ILO_SEX_CODES))
        & (frame["classif1"].isin(ILO_AGE_CODES))
        & (frame["classif2"].isin(ILO_MARITAL_STATUS_TO_RELATIONSHIP))
    ]
    for year, best, source, candidate in _ilo_candidate_groups(subset):
        values: dict[tuple[str, str, str], float] = {}
        for row in candidate.itertuples(index=False):
            value = float(row.obs_value)
            if not math.isfinite(value):
                continue
            values[
                (
                    ILO_AGE_CODES[str(row.classif1)],
                    ILO_SEX_CODES[str(row.sex)],
                    ILO_MARITAL_STATUS_TO_RELATIONSHIP[str(row.classif2)],
                )
            ] = min(1.0, max(0.0, value / 100.0))
        covered_bases = {(age_group, sex) for age_group, sex, _ in values}
        if len(values) >= 24 and len(covered_bases) == 12:
            return values, {
                "year": year,
                "source": source,
                "best_source": bool(best),
                "direct_cells": len(values),
            }
    return None


def build_age_stage_occupation_targets(
    *,
    age_employment_targets: dict[str, float],
    occupation_targets: dict[str, float],
    age_occupation_rows: Any,
) -> tuple[dict[str, float], dict[str, Any]]:
    panels: dict[str, dict[tuple[str, str, str], float]] = {}
    metadata: dict[str, dict[str, Any]] = {}
    global_prior: dict[tuple[str, str, str], float] = defaultdict(float)
    for country, info in COUNTRY_CODES.items():
        selected = select_ilo_age_stage_occupation_panel(
            age_occupation_rows, info["iso3"]
        )
        if selected:
            panel, panel_metadata = selected
            panels[country] = panel
            metadata[country] = panel_metadata
            normalized_panel = normalize(
                {
                    f"{stage} | {sex} | {occupation}": value
                    for (stage, sex, occupation), value in panel.items()
                }
            )
            for key, value in normalized_panel.items():
                stage, sex, occupation = key.split(" | ")
                global_prior[(stage, sex, occupation)] += value
        else:
            metadata[country] = {
                "proxy": "global observed ILO age-stage occupation panel"
            }
    if not global_prior:
        raise RuntimeError("No ILO age-stage occupation panels are available.")

    targets: dict[str, float] = {}
    for country in COUNTRY_CODES:
        panel = panels.get(country, global_prior)
        for sex in ("female", "male"):
            employed_rows = {
                stage: sum(
                    age_employment_targets[
                        f"{country} | {age_group} | {sex} | employed"
                    ]
                    for age_group in AGE_GROUPS
                    if (
                        (stage == "youth" and age_group == "18-24")
                        or (stage == "adult" and age_group != "18-24")
                    )
                )
                for stage in ("youth", "adult")
            }
            not_employed_rows = {
                stage: sum(
                    age_employment_targets[
                        f"{country} | {age_group} | {sex} | not employed"
                    ]
                    for age_group in AGE_GROUPS
                    if (
                        (stage == "youth" and age_group == "18-24")
                        or (stage == "adult" and age_group != "18-24")
                    )
                )
                for stage in ("youth", "adult")
            }
            employed_columns = {
                occupation: occupation_targets[f"{country} | {sex} | {occupation}"]
                for occupation in OCCUPATIONS
                if occupation != "None"
            }
            prior = {
                (stage, occupation): panel.get(
                    (stage, sex, occupation),
                    global_prior.get((stage, sex, occupation), 0.0),
                )
                for stage in ("youth", "adult")
                for occupation in employed_columns
            }
            raked = rake_matrix(
                prior,
                employed_rows,
                employed_columns,
            )
            for (stage, occupation), value in raked.items():
                targets[f"{country} | {stage} | {sex} | {occupation}"] = value
            for stage, value in not_employed_rows.items():
                targets[f"{country} | {stage} | {sex} | None"] = value
    return targets, metadata


def build_relationship_employment_targets(
    *,
    country_relationship_targets: dict[str, float],
    age_employment_targets: dict[str, float],
    age_marital_rate_rows: Any,
) -> tuple[dict[str, float], dict[str, Any]]:
    panels: dict[str, dict[tuple[str, str, str], float]] = {}
    audit: dict[str, Any] = {}
    global_values: dict[tuple[str, str, str], list[float]] = defaultdict(list)
    for country, info in COUNTRY_CODES.items():
        selected = select_ilo_age_marital_rate_panel(
            age_marital_rate_rows, info["iso3"]
        )
        if selected:
            panel, metadata = selected
            panels[country] = panel
            audit[country] = metadata
            for key, value in panel.items():
                global_values[key].append(value)
        else:
            audit[country] = {
                "proxy": "global observed ILO age-sex-marital employment rates"
            }
    global_rates = {
        key: sum(values) / len(values)
        for key, values in global_values.items()
        if values
    }
    if not global_rates:
        raise RuntimeError("No ILO age-marital employment-rate panels are available.")

    targets: dict[str, float] = {}
    for country in COUNTRY_CODES:
        panel = panels.get(country, {})
        fallback_cells = 0
        for age_group in AGE_GROUPS:
            for sex in ("female", "male"):
                relationship_masses = {
                    relationship: country_relationship_targets[
                        f"{country} | {age_group} | {sex} | {relationship}"
                    ]
                    for relationship in RELATIONSHIPS
                }
                base_mass = sum(relationship_masses.values())
                employed_mass = age_employment_targets[
                    f"{country} | {age_group} | {sex} | employed"
                ]
                raw_rates: dict[str, float] = {}
                for relationship in RELATIONSHIPS:
                    key = (age_group, sex, relationship)
                    value = panel.get(key)
                    if value is None and relationship == "in relationship":
                        value = panel.get((age_group, sex, "married"))
                    if value is None:
                        value = global_rates.get(key)
                    if value is None and relationship == "in relationship":
                        value = global_rates.get((age_group, sex, "married"))
                    if value is None:
                        value = 0.5
                    if key not in panel:
                        fallback_cells += 1
                    raw_rates[relationship] = value
                calibrated = calibrate_probabilities_to_mean(
                    raw_rates,
                    relationship_masses,
                    employed_mass / base_mass,
                )
                for relationship, mass in relationship_masses.items():
                    employed = mass * calibrated[relationship]
                    employed_key = f"{country} | {relationship} | employed"
                    not_employed_key = f"{country} | {relationship} | not employed"
                    targets[employed_key] = targets.get(employed_key, 0.0) + employed
                    targets[not_employed_key] = (
                        targets.get(not_employed_key, 0.0) + mass - employed
                    )
        audit[country]["fallback_cells"] = fallback_cells
    return targets, audit


def build_ilo_joint_targets(
    *,
    wpp: dict[str, Any],
    country_mass: dict[str, float],
    education_targets: dict[str, float],
    occupation_targets: dict[str, float],
    age_rate_rows: Any,
    working_age_education_rows: Any,
    employment_age_education_rows: Any,
    education_rate_rows: Any,
    occupation_education_rows: Any,
) -> tuple[dict[str, dict[str, float]], dict[str, Any]]:
    """Build mutually consistent ILO education/employment/occupation margins."""

    education_age_targets: dict[str, float] = {}
    age_employment_targets: dict[str, float] = {}
    education_employment_targets: dict[str, float] = {}
    education_occupation_targets: dict[str, float] = {}
    audit: dict[str, Any] = {}

    age_education_panels: dict[str, dict[tuple[str, str, str], float]] = {}
    employment_age_education_panels: dict[str, dict[tuple[str, str, str], float]] = {}
    occupation_education_panels: dict[str, dict[tuple[str, str], float]] = {}
    panel_metadata: dict[str, dict[str, Any]] = {}

    for country, info in COUNTRY_CODES.items():
        age_education = select_ilo_age_education_panel(
            working_age_education_rows, info["iso3"]
        )
        employment_age_education = select_ilo_age_education_panel(
            employment_age_education_rows, info["iso3"]
        )
        occupation_education = select_ilo_occupation_education_panel(
            occupation_education_rows, info["iso3"]
        )
        if age_education:
            age_education_panels[country], age_education_meta = age_education
        else:
            age_education_meta = {"proxy": "independence"}
        if employment_age_education:
            (
                employment_age_education_panels[country],
                employment_age_education_meta,
            ) = employment_age_education
        else:
            employment_age_education_meta = {"proxy": "not available"}
        if occupation_education:
            (
                occupation_education_panels[country],
                occupation_education_meta,
            ) = occupation_education
        else:
            occupation_education_meta = {"proxy": "global observed panel"}
        panel_metadata[country] = {
            "working_age_population_age_education": age_education_meta,
            "employment_age_education": employment_age_education_meta,
            "occupation_education": occupation_education_meta,
        }

    global_occupation_education_prior: dict[tuple[str, str], float] = defaultdict(float)
    for panel in occupation_education_panels.values():
        normalized_panel = normalize(
            {
                f"{education} | {occupation}": value
                for (
                    education,
                    occupation,
                ), value in panel.items()
            }
        )
        for key, value in normalized_panel.items():
            education, occupation = key.split(" | ")
            global_occupation_education_prior[(education, occupation)] += value

    education_age_tables: dict[str, dict[tuple[str, str, str], float]] = {}
    age_employment_tables: dict[str, dict[tuple[str, str, str], float]] = {}
    education_employment_tables: dict[str, dict[tuple[str, str, str], float]] = {}

    for country, info in COUNTRY_CODES.items():
        row_targets = {
            f"{age_group} | {sex}": wpp["age_sex"][(country, 2025, age_group, sex)]
            / sum(
                wpp["age_sex"][(name, 2025, group, gender)]
                for name in COUNTRY_CODES
                for group in AGE_GROUPS
                for gender in ("female", "male")
            )
            for age_group in AGE_GROUPS
            for sex in ("female", "male")
        }
        education_margins = grouped_education_margins(
            education_targets,
            country,
            ILO_EDUCATION_LEVEL_TO_GROUP,
        )
        panel = age_education_panels.get(country)
        prior = {
            (
                f"{age_group} | {sex}",
                education_group,
            ): (panel.get((age_group, sex, education_group), 0.0) if panel else 1.0)
            for age_group in AGE_GROUPS
            for sex in ("female", "male")
            for education_group in ILO_EDUCATION_GROUPS
        }
        raked = rake_matrix(prior, row_targets, education_margins)
        education_age_tables[country] = {
            (
                *row_key.split(" | "),
                education_group,
            ): value
            for (row_key, education_group), value in raked.items()
        }
        for (
            age_group,
            sex,
            education_group,
        ), value in education_age_tables[country].items():
            education_age_targets[
                f"{country} | {age_group} | {sex} | {education_group}"
            ] = value

        age_rate_panel = select_ilo_age_rate_panel(age_rate_rows, info["iso3"])
        if age_rate_panel is None:
            raise RuntimeError(
                f"ILOSTAT has no complete age employment-rate panel for {country}."
            )
        raw_age_rates, age_rate_metadata = age_rate_panel
        for sex in ("female", "male"):
            age_weights = {
                age_group: wpp["age_sex"][(country, 2025, age_group, sex)]
                for age_group in AGE_GROUPS
            }
            country_sex_occupation = {
                occupation: occupation_targets[f"{country} | {sex} | {occupation}"]
                for occupation in OCCUPATIONS
            }
            sex_total = sum(country_sex_occupation.values())
            desired_employed_share = 1.0 - country_sex_occupation["None"] / sex_total
            calibrated_rates = calibrate_probabilities_to_mean(
                {
                    age_group: raw_age_rates[(age_group, sex)]
                    for age_group in AGE_GROUPS
                },
                age_weights,
                desired_employed_share,
            )
            for age_group in AGE_GROUPS:
                mass = row_targets[f"{age_group} | {sex}"]
                employed = mass * calibrated_rates[age_group]
                not_employed = mass - employed
                age_employment_tables.setdefault(country, {})[
                    (age_group, sex, "employed")
                ] = employed
                age_employment_tables[country][(age_group, sex, "not employed")] = (
                    not_employed
                )
                age_employment_targets[
                    f"{country} | {age_group} | {sex} | employed"
                ] = employed
                age_employment_targets[
                    f"{country} | {age_group} | {sex} | not employed"
                ] = not_employed

        education_rate_panel = select_ilo_education_rate_panel(
            education_rate_rows, info["iso3"]
        )
        if education_rate_panel:
            raw_education_rates, education_rate_metadata = education_rate_panel
        else:
            working_panel = age_education_panels.get(country)
            employed_panel = employment_age_education_panels.get(country)
            if not working_panel or not employed_panel:
                raw_education_rates = {
                    (sex, education_group): 0.5
                    for sex in ("female", "male")
                    for education_group in ILO_EDUCATION_GROUPS
                }
                education_rate_metadata = {"proxy": "neutral before margin calibration"}
            else:
                raw_education_rates = {}
                for sex in ("female", "male"):
                    for education_group in ILO_EDUCATION_GROUPS:
                        working = sum(
                            working_panel[(age_group, sex, education_group)]
                            for age_group in AGE_GROUPS
                        )
                        employed = sum(
                            employed_panel[(age_group, sex, education_group)]
                            for age_group in AGE_GROUPS
                        )
                        raw_education_rates[(sex, education_group)] = (
                            min(1.0, max(0.0, employed / working))
                            if working > 0
                            else 0.5
                        )
                education_rate_metadata = {
                    "derived_from_count_panels": {
                        "working_age": panel_metadata[country][
                            "working_age_population_age_education"
                        ],
                        "employment": panel_metadata[country][
                            "employment_age_education"
                        ],
                    }
                }

        for sex in ("female", "male"):
            sex_education_margins = {
                education_group: sum(
                    education_age_tables[country][(age_group, sex, education_group)]
                    for age_group in AGE_GROUPS
                )
                for education_group in ILO_EDUCATION_GROUPS
            }
            sex_total = sum(sex_education_margins.values())
            employed_total = sum(
                age_employment_tables[country][(age_group, sex, "employed")]
                for age_group in AGE_GROUPS
            )
            calibrated_education_rates = calibrate_probabilities_to_mean(
                {
                    education_group: raw_education_rates[(sex, education_group)]
                    for education_group in ILO_EDUCATION_GROUPS
                },
                sex_education_margins,
                employed_total / sex_total,
            )
            for education_group, mass in sex_education_margins.items():
                employed = mass * calibrated_education_rates[education_group]
                not_employed = mass - employed
                education_employment_tables.setdefault(country, {})[
                    (sex, education_group, "employed")
                ] = employed
                education_employment_tables[country][
                    (sex, education_group, "not employed")
                ] = not_employed
                education_employment_targets[
                    f"{country} | {sex} | {education_group} | employed"
                ] = employed
                education_employment_targets[
                    f"{country} | {sex} | {education_group} | not employed"
                ] = not_employed

        education_rows = {
            education_group: sum(
                education_age_tables[country][(age_group, sex, education_group)]
                for age_group in AGE_GROUPS
                for sex in ("female", "male")
            )
            for education_group in ILO_EDUCATION_GROUPS
        }
        occupation_columns = {
            occupation_group: sum(
                occupation_targets[f"{country} | {sex} | {occupation_group}"]
                for sex in ("female", "male")
            )
            for occupation_group in OCCUPATIONS
        }
        observed_occupation_education = occupation_education_panels.get(
            country, global_occupation_education_prior
        )
        not_employed_by_education = {
            education_group: sum(
                education_employment_tables[country][
                    (sex, education_group, "not employed")
                ]
                for sex in ("female", "male")
            )
            for education_group in ILO_EDUCATION_GROUPS
        }
        employed_education_rows = {
            education_group: (
                education_rows[education_group]
                - not_employed_by_education[education_group]
            )
            for education_group in ILO_EDUCATION_GROUPS
        }
        employed_occupation_columns = {
            occupation_group: value
            for occupation_group, value in occupation_columns.items()
            if occupation_group != "None"
        }
        occupation_prior = {}
        for education_group in ILO_EDUCATION_GROUPS:
            for occupation_group in OCCUPATIONS:
                if occupation_group == "None":
                    continue
                occupation_prior[(education_group, occupation_group)] = (
                    observed_occupation_education.get(
                        (education_group, occupation_group), 0.0
                    )
                )
        raked_occupation = rake_matrix(
            occupation_prior,
            employed_education_rows,
            employed_occupation_columns,
        )
        for education_group, value in not_employed_by_education.items():
            education_occupation_targets[f"{country} | {education_group} | None"] = (
                value
            )
        for (
            education_group,
            occupation_group,
        ), value in raked_occupation.items():
            education_occupation_targets[
                f"{country} | {education_group} | {occupation_group}"
            ] = value

        audit[country] = {
            **panel_metadata[country],
            "age_employment_rate": age_rate_metadata,
            "education_employment_rate": education_rate_metadata,
            "raking_margins": (
                "UN WPP 2025 age-sex; WDI education; ILOSTAT 2025 modelled "
                "country-sex employment and occupation"
            ),
        }

    return {
        "country_age_sex_education": education_age_targets,
        "country_age_sex_employment": age_employment_targets,
        "country_sex_education_employment": education_employment_targets,
        "country_education_occupation": education_occupation_targets,
    }, audit
