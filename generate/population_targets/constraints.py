"""Constraint lookup and updates to the target document."""

from __future__ import annotations

from typing import Any

from .constants import (
    COUNTRY_CODES,
)


def constraint(data: dict[str, Any], name: str) -> dict[str, Any]:
    return next(item for item in data["constraints"] if item["name"] == name)


def upsert_constraint(
    data: dict[str, Any],
    *,
    name: str,
    fields: list[str],
    targets: dict[str, float],
) -> None:
    try:
        item = constraint(data, name)
    except StopIteration:
        item = {"name": name, "fields": fields, "targets": {}}
        data["constraints"].append(item)
    item["fields"] = fields
    item["targets"] = rounded(targets)


def rounded(values: dict[str, float]) -> dict[str, float]:
    return {key: round(value, 10) for key, value in values.items()}


def update_income_constraint_and_metadata(
    data: dict[str, Any],
    income_targets: dict[str, float],
) -> None:
    constraint(data, "country_x_income_level")["targets"] = rounded(income_targets)
    metadata = data["metadata"]
    metadata["title"] = (
        f"PrivacyTrace IPF target constraints for the built-in "
        f"{len(COUNTRY_CODES)}-country generator universe"
    )
    metadata["country_universe"] = list(COUNTRY_CODES)
    metadata["sources"]["income"] = (
        "World Bank Poverty and Inequality Platform (PIP), latest non-interpolated "
        "national observation where available, 2021 PPP welfare distribution. "
        "Bands follow the OECD relative-income classification: below 75%, "
        "75%-100%, 100%-150%, 150%-200%, and at least 200% of the national median."
    )
    metadata["constraint_quality"]["country_x_income_level"] = (
        "source_backed_derived: World Bank PIP 2021 PPP national welfare "
        "distribution; bands relative to the country median"
    )
    metadata["static_target_status"]["country_x_income_level"] = (
        "ready_official_source_backed_derived"
    )
    official_rebuild = metadata.setdefault("official_rebuild", {})
    official_rebuild.pop("income_band_definition_2021_ppp_usd_per_day", None)
    official_rebuild["income_band_definition_relative_to_country_median"] = {
        "low": "<0.75x median",
        "lower-middle": "0.75x-1.00x median",
        "middle": "1.00x-1.50x median",
        "upper-middle": "1.50x-2.00x median",
        "high": ">=2.00x median",
    }
    official_rebuild["income_semantics"] = (
        "Relative position in the current country's national household per-capita "
        "welfare distribution. PIP welfare is income for some countries and "
        "consumption for others; it is not individual labor income."
    )


def update_rebuild_constraints(
    data: dict[str, Any],
    *,
    age_income_targets,
    age_sex_mass,
    age_stage_occupation_targets,
    city_size_targets,
    country_age_sex_targets,
    country_mass,
    country_relationship_targets,
    education_income_targets,
    education_targets,
    ethnicity_targets,
    ilo_joint_targets,
    income_targets,
    mental_targets,
    migration_status_targets,
    migration_targets,
    occupation_targets,
    physical_targets,
    relationship_employment_targets,
    relationship_targets,
    religion_targets,
) -> None:
    constraint(data, "country_population")["targets"] = rounded(country_mass)
    constraint(data, "age_x_sex")["targets"] = rounded(age_sex_mass)
    upsert_constraint(
        data,
        name="current_country_x_age_group_x_sex",
        fields=["current_country", "age_group", "sex"],
        targets=country_age_sex_targets,
    )
    constraint(data, "country_x_education")["targets"] = rounded(education_targets)
    constraint(data, "country_x_religion")["targets"] = rounded(religion_targets)
    upsert_constraint(
        data,
        name="current_country_x_current_city_size",
        fields=["current_country", "current_city_size"],
        targets=city_size_targets,
    )
    constraint(data, "current_country_x_citizenship_country")["targets"] = rounded(
        migration_targets
    )
    constraint(data, "current_country_x_birth_country")["targets"] = rounded(
        migration_targets
    )
    upsert_constraint(
        data,
        name="current_country_x_sex_x_birth_migration_status",
        fields=[
            "current_country",
            "sex",
            "birth_migration_status",
        ],
        targets=migration_status_targets,
    )
    upsert_constraint(
        data,
        name="current_country_x_sex_x_citizenship_migration_status",
        fields=[
            "current_country",
            "sex",
            "citizenship_migration_status",
        ],
        targets=migration_status_targets,
    )
    try:
        old_ethnicity = constraint(data, "citizenship_country_x_ethnicity")
    except StopIteration:
        old_ethnicity = constraint(data, "current_country_x_ethnicity")
    old_ethnicity["name"] = "current_country_x_ethnicity"
    old_ethnicity["fields"] = ["current_country", "ethnicity"]
    old_ethnicity["targets"] = rounded(ethnicity_targets)
    update_income_constraint_and_metadata(data, income_targets)
    constraint(data, "age_x_sex_x_relationship_status")["targets"] = rounded(
        relationship_targets
    )
    upsert_constraint(
        data,
        name=("current_country_x_age_group_x_sex_x_relationship_status"),
        fields=[
            "current_country",
            "age_group",
            "sex",
            "relationship_status",
        ],
        targets=country_relationship_targets,
    )
    upsert_constraint(
        data,
        name=("current_country_x_relationship_status_x_employment_status"),
        fields=[
            "current_country",
            "relationship_status",
            "employment_status",
        ],
        targets=relationship_employment_targets,
    )
    upsert_constraint(
        data,
        name="current_country_x_sex_x_occupation",
        fields=["current_country", "sex", "occupation_group"],
        targets=occupation_targets,
    )
    upsert_constraint(
        data,
        name="current_country_x_age_group_x_sex_x_ilo_education_group",
        fields=[
            "current_country",
            "age_group",
            "sex",
            "ilo_education_group",
        ],
        targets=ilo_joint_targets["country_age_sex_education"],
    )
    upsert_constraint(
        data,
        name="current_country_x_age_group_x_sex_x_employment_status",
        fields=[
            "current_country",
            "age_group",
            "sex",
            "employment_status",
        ],
        targets=ilo_joint_targets["country_age_sex_employment"],
    )
    upsert_constraint(
        data,
        name="current_country_x_sex_x_ilo_education_group_x_employment_status",
        fields=[
            "current_country",
            "sex",
            "ilo_education_group",
            "employment_status",
        ],
        targets=ilo_joint_targets["country_sex_education_employment"],
    )
    upsert_constraint(
        data,
        name="current_country_x_ilo_education_group_x_occupation_group",
        fields=[
            "current_country",
            "ilo_education_group",
            "occupation_group",
        ],
        targets=ilo_joint_targets["country_education_occupation"],
    )
    upsert_constraint(
        data,
        name=("current_country_x_age_stage_x_sex_x_occupation_group"),
        fields=[
            "current_country",
            "age_stage",
            "sex",
            "occupation_group",
        ],
        targets=age_stage_occupation_targets,
    )
    upsert_constraint(
        data,
        name="current_country_x_welfare_education_group_x_income_level",
        fields=[
            "current_country",
            "welfare_education_group",
            "income_level",
        ],
        targets=education_income_targets,
    )
    upsert_constraint(
        data,
        name="current_country_x_age_stage_x_income_level",
        fields=[
            "current_country",
            "age_stage",
            "income_level",
        ],
        targets=age_income_targets,
    )
    upsert_constraint(
        data,
        name=("current_country_x_age_group_x_sex_x_physical_condition"),
        fields=[
            "current_country",
            "age_group",
            "sex",
            "physical_condition",
        ],
        targets=physical_targets,
    )
    upsert_constraint(
        data,
        name=("current_country_x_age_group_x_sex_x_mental_condition"),
        fields=[
            "current_country",
            "age_group",
            "sex",
            "mental_condition",
        ],
        targets=mental_targets,
    )
