"""Rebuild population targets by coordinating the source-specific builders."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone

from .common import (
    download,
)
from .constants import (
    ILO_AGE_MARITAL_EMPLOYMENT_RATE_URL,
    ILO_AGE_OCCUPATION_URL,
    ILO_EMPLOYMENT_AGE_EDUCATION_URL,
    ILO_EMPLOYMENT_RATE_BY_AGE_URL,
    ILO_EMPLOYMENT_RATE_BY_EDUCATION_URL,
    ILO_EMPLOYMENT_RATE_URL,
    ILO_OCCUPATION_EDUCATION_URL,
    ILO_OCCUPATION_URL,
    ILO_WORKING_AGE_AGE_EDUCATION_URL,
    IMS_URL,
    PEW_RELIGION_URL,
    WELFARE_AGE_TYPES,
    WELFARE_EDUCATION_TYPES,
    WORLD_BANK_WELFARE_PROFILE_URL,
    WPP_URL,
    WUP_CITY_URL,
)
from .constraints import (
    constraint,
    update_income_constraint_and_metadata,
    update_rebuild_constraints,
    upsert_constraint,
)
from .demographics import (
    build_country_age_sex_targets,
    build_country_relationship_targets,
    build_education_targets,
    build_ethnicity_targets,
    build_migration_status_by_sex_targets,
    build_migration_targets,
    build_population_targets,
    build_relationship_targets,
    direct_ethnicity_distributions,
    fetch_wdi_education,
    load_ims,
    load_marital_rows,
    load_pew_religion,
    load_wpp,
    load_wup_city_catalog,
)
from .employment import (
    build_age_stage_occupation_targets,
    build_ilo_joint_targets,
    build_occupation_targets,
    build_relationship_employment_targets,
    load_ilo_rds,
)
from .health import (
    build_health_targets,
)
from .income import (
    build_age_income_targets,
    build_education_income_targets,
    build_income_targets,
    fetch_pip_rows,
    load_world_bank_welfare_profile,
)
from .reports import (
    render_values_doc,
    update_rebuild_metadata,
    write_income_audit,
    write_rebuild_outputs,
)


def rebuild_targets(args: argparse.Namespace) -> None:
    args.cache_dir.mkdir(parents=True, exist_ok=True)
    data = json.loads(args.target.read_text(encoding="utf-8"))
    obsolete_constraints = {
        "current_country_x_current_city",
        "physical_condition",
        "sex_x_mental_condition",
        ("current_country_x_age_group_x_sex_x_relationship_status_x_employment_status"),
    }
    data["constraints"] = [
        item for item in data["constraints"] if item["name"] not in obsolete_constraints
    ]
    for metadata_key in ("constraint_quality", "static_target_status"):
        for name in obsolete_constraints:
            data["metadata"].get(metadata_key, {}).pop(name, None)
    if args.income_only:
        country_mass = constraint(data, "country_population")["targets"]
        pip_rows = fetch_pip_rows(args.cache_dir)
        income_targets, income_audit = build_income_targets(country_mass, pip_rows)
        welfare_rows = load_world_bank_welfare_profile(
            download(
                WORLD_BANK_WELFARE_PROFILE_URL,
                args.cache_dir / "world_bank_pppr_2024_reproducibility.zip",
            )
        )
        education_income_targets, education_income_audit = (
            build_education_income_targets(
                country_mass=country_mass,
                education_targets=constraint(data, "country_x_education")["targets"],
                income_targets=income_targets,
                welfare_rows=welfare_rows,
            )
        )
        age_income_targets, age_income_audit = build_age_income_targets(
            country_mass=country_mass,
            country_age_sex_targets=constraint(
                data, "current_country_x_age_group_x_sex"
            )["targets"],
            income_targets=income_targets,
            welfare_rows=welfare_rows,
        )
        update_income_constraint_and_metadata(data, income_targets)
        upsert_constraint(
            data,
            name=("current_country_x_welfare_education_group_x_income_level"),
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
        metadata = data["metadata"]
        metadata["sources"]["education_income_joint"] = (
            "World Bank Global distribution of welfare 2022 education-"
            "conditioned $2.15/$6.85 poverty rates, combined with WDI "
            "education and PIP median-relative income margins."
        )
        metadata["constraint_quality"][
            "current_country_x_welfare_education_group_x_income_level"
        ] = (
            "world_bank_source_backed_derived: education-conditioned "
            "$2.15/$6.85 welfare-rank dependence transferred by maximum "
            "entropy to PIP median-relative income bands"
        )
        metadata["constraint_quality"]["current_country_x_age_stage_x_income_level"] = (
            "world_bank_source_backed_derived: youth/adult-conditioned "
            "$2.15/$6.85 welfare-rank dependence transferred by maximum "
            "entropy to PIP median-relative income bands"
        )
        metadata["static_target_status"][
            "current_country_x_welfare_education_group_x_income_level"
        ] = "ready_world_bank_source_backed_maximum_entropy"
        metadata["static_target_status"][
            "current_country_x_age_stage_x_income_level"
        ] = "ready_world_bank_source_backed_maximum_entropy"
        metadata.setdefault("schema_option_set", {})["welfare_education_group"] = list(
            WELFARE_EDUCATION_TYPES
        )
        metadata["schema_option_set"]["age_stage"] = list(WELFARE_AGE_TYPES)
        metadata.setdefault("official_rebuild", {})["education_income_joint_inputs"] = (
            education_income_audit
        )
        metadata["official_rebuild"]["age_income_joint_inputs"] = age_income_audit
        data["metadata"]["created_utc"] = datetime.now(timezone.utc).date().isoformat()
        data["metadata"]["official_rebuild"]["generated_utc"] = datetime.now(
            timezone.utc
        ).isoformat()
        args.target.write_text(
            json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
        render_values_doc(data, args.values_doc)
        write_income_audit(
            args.audit,
            income_audit,
            education_income_audit,
            age_income_audit,
        )
        return
    wpp = load_wpp(download(WPP_URL, args.cache_dir / "wpp2024_age5_sex.csv.gz"))
    country_mass, age_sex_mass = build_population_targets(wpp)
    city_catalog, city_size_targets = load_wup_city_catalog(
        download(
            WUP_CITY_URL,
            args.cache_dir / "wup2025_cities_population.xlsx",
        ),
        country_mass,
    )
    education_rows = fetch_wdi_education(args.cache_dir)
    education_targets, education_audit = build_education_targets(
        country_mass,
        education_rows,
    )
    religion_targets, religion_audit = load_pew_religion(
        download(
            PEW_RELIGION_URL,
            args.cache_dir / "pew_religious_composition_2010_2020.zip",
        ),
        country_mass,
    )
    ims = load_ims(
        download(IMS_URL, args.cache_dir / "ims2020_destination_origin.xlsx")
    )
    ilo_headers = {
        "User-Agent": "R/4.5 Rilostat/2.5.0",
        "Accept-Encoding": "gzip",
        "Referer": "https://rplumber.ilo.org/",
    }
    occupation_rows = load_ilo_rds(
        download(
            ILO_OCCUPATION_URL,
            args.cache_dir / "ilo_emp_occupation_2025.rds",
            headers=ilo_headers,
        )
    )
    employment_rows = load_ilo_rds(
        download(
            ILO_EMPLOYMENT_RATE_URL,
            args.cache_dir / "ilo_employment_rate_2025.rds",
            headers=ilo_headers,
        )
    )
    age_employment_rate_rows = load_ilo_rds(
        download(
            ILO_EMPLOYMENT_RATE_BY_AGE_URL,
            args.cache_dir / "ilo_employment_rate_by_age_observed.rds",
            headers=ilo_headers,
        )
    )
    working_age_education_rows = load_ilo_rds(
        download(
            ILO_WORKING_AGE_AGE_EDUCATION_URL,
            args.cache_dir / "ilo_working_age_population_by_age_education.rds",
            headers=ilo_headers,
        )
    )
    employment_age_education_rows = load_ilo_rds(
        download(
            ILO_EMPLOYMENT_AGE_EDUCATION_URL,
            args.cache_dir / "ilo_employment_by_age_education.rds",
            headers=ilo_headers,
        )
    )
    education_employment_rate_rows = load_ilo_rds(
        download(
            ILO_EMPLOYMENT_RATE_BY_EDUCATION_URL,
            args.cache_dir / "ilo_employment_rate_by_education.rds",
            headers=ilo_headers,
        )
    )
    occupation_education_rows = load_ilo_rds(
        download(
            ILO_OCCUPATION_EDUCATION_URL,
            args.cache_dir / "ilo_employment_by_occupation_education.rds",
            headers=ilo_headers,
        )
    )
    age_occupation_rows = load_ilo_rds(
        download(
            ILO_AGE_OCCUPATION_URL,
            args.cache_dir / "ilo_employment_by_age_occupation.rds",
            headers=ilo_headers,
        )
    )
    age_marital_employment_rate_rows = load_ilo_rds(
        download(
            ILO_AGE_MARITAL_EMPLOYMENT_RATE_URL,
            args.cache_dir / "ilo_employment_rate_by_age_marital_status.rds",
            headers=ilo_headers,
        )
    )
    migration_targets, migration_audit = build_migration_targets(country_mass, wpp, ims)
    migration_status_targets, migration_status_audit = (
        build_migration_status_by_sex_targets(wpp, ims)
    )
    marital_rates, marital_years = load_marital_rows(args.cache_dir)
    relationship_targets = build_relationship_targets(age_sex_mass, wpp, marital_rates)
    country_relationship_targets = build_country_relationship_targets(
        wpp, marital_rates
    )
    pip_rows = fetch_pip_rows(args.cache_dir)
    income_targets, income_audit = build_income_targets(country_mass, pip_rows)
    ethnicity_distributions = direct_ethnicity_distributions(ims, wpp)
    ethnicity_targets = build_ethnicity_targets(country_mass, ethnicity_distributions)
    occupation_targets, occupation_audit = build_occupation_targets(
        wpp, occupation_rows, employment_rows
    )
    country_age_sex_targets = build_country_age_sex_targets(wpp)
    ilo_joint_targets, ilo_joint_audit = build_ilo_joint_targets(
        wpp=wpp,
        country_mass=country_mass,
        education_targets=education_targets,
        occupation_targets=occupation_targets,
        age_rate_rows=age_employment_rate_rows,
        working_age_education_rows=working_age_education_rows,
        employment_age_education_rows=employment_age_education_rows,
        education_rate_rows=education_employment_rate_rows,
        occupation_education_rows=occupation_education_rows,
    )
    age_stage_occupation_targets, age_stage_occupation_audit = (
        build_age_stage_occupation_targets(
            age_employment_targets=ilo_joint_targets["country_age_sex_employment"],
            occupation_targets=occupation_targets,
            age_occupation_rows=age_occupation_rows,
        )
    )
    relationship_employment_targets, relationship_employment_audit = (
        build_relationship_employment_targets(
            country_relationship_targets=country_relationship_targets,
            age_employment_targets=ilo_joint_targets["country_age_sex_employment"],
            age_marital_rate_rows=age_marital_employment_rate_rows,
        )
    )
    welfare_rows = load_world_bank_welfare_profile(
        download(
            WORLD_BANK_WELFARE_PROFILE_URL,
            args.cache_dir / "world_bank_pppr_2024_reproducibility.zip",
        )
    )
    education_income_targets, education_income_audit = build_education_income_targets(
        country_mass=country_mass,
        education_targets=education_targets,
        income_targets=income_targets,
        welfare_rows=welfare_rows,
    )
    age_income_targets, age_income_audit = build_age_income_targets(
        country_mass=country_mass,
        country_age_sex_targets=country_age_sex_targets,
        income_targets=income_targets,
        welfare_rows=welfare_rows,
    )
    (
        physical_targets,
        physical_audit,
        mental_targets,
        mental_audit,
    ) = build_health_targets(
        gbd_path=args.ihme_gbd,
        wpp=wpp,
        country_age_sex_targets=country_age_sex_targets,
    )
    update_rebuild_constraints(
        data,
        age_income_targets=age_income_targets,
        age_sex_mass=age_sex_mass,
        age_stage_occupation_targets=age_stage_occupation_targets,
        city_size_targets=city_size_targets,
        country_age_sex_targets=country_age_sex_targets,
        country_mass=country_mass,
        country_relationship_targets=country_relationship_targets,
        education_income_targets=education_income_targets,
        education_targets=education_targets,
        ethnicity_targets=ethnicity_targets,
        ilo_joint_targets=ilo_joint_targets,
        income_targets=income_targets,
        mental_targets=mental_targets,
        migration_status_targets=migration_status_targets,
        migration_targets=migration_targets,
        occupation_targets=occupation_targets,
        physical_targets=physical_targets,
        relationship_employment_targets=relationship_employment_targets,
        relationship_targets=relationship_targets,
        religion_targets=religion_targets,
    )
    update_rebuild_metadata(
        data,
        age_income_audit=age_income_audit,
        age_stage_occupation_audit=age_stage_occupation_audit,
        education_income_audit=education_income_audit,
        ilo_joint_audit=ilo_joint_audit,
        marital_years=marital_years,
        mental_audit=mental_audit,
        migration_audit=migration_audit,
        migration_status_audit=migration_status_audit,
        physical_audit=physical_audit,
        relationship_employment_audit=relationship_employment_audit,
    )
    write_rebuild_outputs(
        data,
        age_income_audit=age_income_audit,
        age_stage_occupation_audit=age_stage_occupation_audit,
        args=args,
        city_catalog=city_catalog,
        education_audit=education_audit,
        education_income_audit=education_income_audit,
        ethnicity_distributions=ethnicity_distributions,
        ilo_joint_audit=ilo_joint_audit,
        income_audit=income_audit,
        marital_years=marital_years,
        mental_audit=mental_audit,
        migration_audit=migration_audit,
        migration_status_audit=migration_status_audit,
        occupation_audit=occupation_audit,
        physical_audit=physical_audit,
        relationship_employment_audit=relationship_employment_audit,
        religion_audit=religion_audit,
    )
