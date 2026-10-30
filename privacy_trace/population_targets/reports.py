"""Target provenance, documentation, and output files."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .constants import (
    COUNTRY_CODES,
    ILO_AGE_MARITAL_EMPLOYMENT_RATE_URL,
    ILO_AGE_OCCUPATION_URL,
    ILO_EDUCATION_GROUPS,
    ILO_EMPLOYMENT_AGE_EDUCATION_URL,
    ILO_EMPLOYMENT_RATE_BY_AGE_URL,
    ILO_EMPLOYMENT_RATE_BY_EDUCATION_URL,
    ILO_EMPLOYMENT_RATE_URL,
    ILO_OCCUPATION_EDUCATION_URL,
    ILO_OCCUPATION_URL,
    ILO_WORKING_AGE_AGE_EDUCATION_URL,
    IMS_URL,
    OCCUPATIONS,
    OECD_MIDDLE_INCOME_URL,
    PEW_RELIGION_URL,
    WELFARE_AGE_TYPES,
    WELFARE_EDUCATION_TYPES,
    WORLD_BANK_WELFARE_PROFILE_URL,
    WPP_URL,
    WUP_CITY_URL,
)


def render_values_doc(data: dict[str, Any], path: Path) -> None:
    quality = data["metadata"]["constraint_quality"]
    statuses = data["metadata"]["static_target_status"]
    lines = [
        "# 当前 IPF 约束值",
        "",
        "来源文件：`data/targets/demographic_targets_2025.json`",
        "",
        "本文件由 `scripts/rebuild_official_ipf_targets.py` 自动生成。除非另有说明，"
        f"所有数值均为完整 {len(COUNTRY_CODES)} 国、18–80 岁抽样框中的联合比例。",
        "",
        "## 状态",
        "",
        "| 约束 | 状态 | 来源/处理 |",
        "| --- | --- | --- |",
    ]
    for item in data["constraints"]:
        name = item["name"]
        lines.append(f"| `{name}` | `{statuses[name]}` | {quality[name]} |")
    lines.extend(["", "## 数值", ""])
    for item in data["constraints"]:
        name = item["name"]
        lines.extend(
            [
                f"### `{name}`",
                "",
                "字段：" + ", ".join(f"`{field}`" for field in item["fields"]),
                "",
                f"状态：`{statuses[name]}`",
                "",
                f"说明：{quality[name]}",
                "",
                "| 目标 key | 比例 | 百分比 |",
                "| --- | ---: | ---: |",
            ]
        )
        for key, value in item["targets"].items():
            lines.append(f"| `{key}` | {value:.10f} | {value * 100:.6f}% |")
        lines.append("")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")


def write_income_audit(
    path: Path,
    income_audit: dict[str, Any],
    education_income_audit: dict[str, Any] | None = None,
    age_income_audit: dict[str, Any] | None = None,
) -> None:
    if path.exists():
        audit = json.loads(path.read_text(encoding="utf-8"))
    else:
        audit = {}
    audit["generated_utc"] = datetime.now(timezone.utc).isoformat()
    audit.setdefault("source_urls", {})["world_bank_pip_api"] = (
        "https://api.worldbank.org/pip/v1"
    )
    audit["source_urls"]["oecd_relative_income_classification"] = OECD_MIDDLE_INCOME_URL
    if education_income_audit is not None:
        audit["source_urls"]["world_bank_global_welfare_profile_2022"] = (
            WORLD_BANK_WELFARE_PROFILE_URL
        )
        audit["education_income_joint"] = education_income_audit
    if age_income_audit is not None:
        audit["source_urls"]["world_bank_global_welfare_profile_2022"] = (
            WORLD_BANK_WELFARE_PROFILE_URL
        )
        audit["age_income_joint"] = age_income_audit
    audit["income"] = income_audit
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(audit, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )


def update_rebuild_metadata(
    data: dict[str, Any],
    *,
    age_income_audit,
    age_stage_occupation_audit,
    education_income_audit,
    ilo_joint_audit,
    marital_years,
    mental_audit,
    migration_audit,
    migration_status_audit,
    physical_audit,
    relationship_employment_audit,
) -> None:
    metadata = data["metadata"]
    metadata["created_utc"] = datetime.now(timezone.utc).date().isoformat()
    metadata["important_caveat"] = (
        "All IPF constraints now use official or intergovernmental statistical inputs, "
        "except country_x_religion, which remains authority-backed Pew data. Health "
        "targets use an IHME GBD 2023 prevalence query by country, age and sex. "
        "Derived constraints retain their transformations and proxy semantics in "
        "official_rebuild."
    )
    metadata["sources"].update(
        {
            "current_city": (
                "UN DESA World Urbanization Prospects 2025 File 21, DEGURBA "
                "cities with at least 50,000 inhabitants in 2025."
            ),
            "education": (
                "World Bank API, WDI educational-attainment cumulative "
                "indicators for population age 25+, latest non-null observation."
            ),
            "education_employment_occupation_joint": (
                "ILOSTAT annual observed working-age population by sex, age "
                "and education; employment-to-population ratios by sex, age "
                "or education; and employment by sex, occupation and education."
            ),
            "age_occupation_joint": (
                "ILOSTAT observed employment by sex, youth/adult age stage "
                "and ISCO-08 occupation, raked to the modelled 2025 "
                "employment and occupation margins."
            ),
            "relationship_employment_joint": (
                "ILOSTAT observed employment-to-population ratios by sex, "
                "10-year age band and marital status, calibrated to the "
                "UNData relationship and ILO 2025 employment margins."
            ),
            "education_income_joint": (
                "World Bank Global distribution of welfare 2022 education-"
                "conditioned $2.15/$6.85 poverty rates, combined with WDI "
                "education and PIP median-relative income margins."
            ),
            "age_income_joint": (
                "World Bank Global distribution of welfare 2022 youth/adult-"
                "conditioned $2.15/$6.85 poverty rates, combined with UN WPP "
                "age-stage and PIP median-relative income margins."
            ),
            "religion": (
                "Pew Research Center Religious Composition by Country, "
                "2010-2020 dataset, 2020 percentages."
            ),
            "relationship_status": (
                "UNSD Demographic Statistics Database / UNData table 23, latest "
                "available national observation by country, age and sex."
            ),
            "ethnicity": (
                "UNData table 26 and official national census population-group "
                "tables; UN DESA International Migrant Stock 2020 regional-origin "
                "mapping where no compatible national ethnicity table exists."
            ),
            "birth_country": (
                "UN DESA International Migrant Stock 2020 destination-origin "
                f"matrix, conditioned on the generator's supported "
                f"{len(COUNTRY_CODES)}-country universe."
            ),
            "citizenship_country": (
                "UN DESA International Migrant Stock 2020 destination-origin "
                f"matrix, conditioned on the generator's supported "
                f"{len(COUNTRY_CODES)}-country universe."
            ),
            "occupation": (
                "ILOSTAT modelled estimates, 2025: employment by sex and ISCO-08 "
                "occupation (EMP_2EMP_SEX_OCU_NB_A) plus employment-to-population "
                "ratio by sex (EMP_2WAP_SEX_AGE_RT_A)."
            ),
            "physical_condition": (
                "IHME Global Burden of Disease 2023 prevalence rates for 26 "
                "countries, two sexes and five-year age groups, mapped to 22 "
                "physical-condition labels and population-weighted with UN WPP 2025."
            ),
            "mental_condition": (
                "IHME Global Burden of Disease 2023 prevalence rates for 26 "
                "countries, two sexes and five-year age groups, mapped to 16 "
                "mental/substance-use labels and population-weighted with UN WPP 2025."
            ),
        }
    )
    metadata["constraint_quality"].update(
        {
            "current_country_x_citizenship_country": (
                "official_derived: UN DESA IMS 2020; direct where destination data "
                "type contains C, official migration-origin proxy where it contains B"
            ),
            "current_country_x_birth_country": (
                "official_derived: UN DESA IMS 2020; direct where destination data "
                "type contains B, official migration-origin proxy where it contains C"
            ),
            "current_country_x_sex_x_birth_migration_status": (
                "official_derived: UN DESA IMS 2020 destination-origin-sex "
                "matrix, reduced to local/foreign status within supported countries"
            ),
            "current_country_x_sex_x_citizenship_migration_status": (
                "official_derived_proxy: same IMS 2020 sex-specific matrix; "
                "direct where destination basis includes citizenship, birth proxy otherwise"
            ),
            "current_country_x_ethnicity": (
                "official_derived: UNData table 26, national censuses, and documented "
                "regional-origin mapping for countries without compatible ethnicity tables"
            ),
            "age_x_sex_x_relationship_status": (
                "source_backed: latest UNData table 23 marital-status observations "
                "combined with UN WPP 2025 age-sex weights"
            ),
            "current_country_x_age_group_x_sex": (
                "official_modelled: UN WPP 2024 medium projection for 2025, ages 18-80"
            ),
            "current_country_x_age_group_x_sex_x_relationship_status": (
                "official_source_backed: country-specific UNData table 23 "
                "marital-status rates combined with UN WPP 2025 age-sex weights"
            ),
            "current_country_x_relationship_status_x_employment_status": (
                "official_raked: ILOSTAT observed age-sex-marital employment "
                "rates logit-calibrated to consistent UN relationship and "
                "ILO employment margins, then aggregated by country and "
                "relationship status"
            ),
            "current_country_x_sex_x_occupation": (
                "official_modelled_derived: ILOSTAT 2025 employment ratio and "
                "employment by ISCO-08 group, combined with UN WPP adult weights"
            ),
            "current_country_x_age_group_x_sex_x_ilo_education_group": (
                "official_raked: ILOSTAT observed age-sex-education structure "
                "raked to WPP 2025 age-sex and WDI education margins"
            ),
            "current_country_x_age_group_x_sex_x_employment_status": (
                "official_raked: ILOSTAT observed 10-year age employment curves "
                "logit-calibrated to 2025 modelled country-sex employment margins"
            ),
            "current_country_x_sex_x_ilo_education_group_x_employment_status": (
                "official_raked: ILOSTAT education-specific employment rates "
                "calibrated to the consistent education and employment margins"
            ),
            "current_country_x_ilo_education_group_x_occupation_group": (
                "official_raked: ILOSTAT observed occupation by education, "
                "raked to consistent country education and occupation margins"
            ),
            "current_country_x_age_stage_x_sex_x_occupation_group": (
                "official_raked: ILOSTAT observed youth/adult occupation by "
                "sex, raked to consistent age-employment and occupation margins"
            ),
            "current_country_x_welfare_education_group_x_income_level": (
                "world_bank_source_backed_derived: education-conditioned "
                "$2.15/$6.85 welfare-rank dependence transferred by maximum "
                "entropy to PIP median-relative income bands"
            ),
            "current_country_x_age_stage_x_income_level": (
                "world_bank_source_backed_derived: youth/adult-conditioned "
                "$2.15/$6.85 welfare-rank dependence transferred by maximum "
                "entropy to PIP median-relative income bands"
            ),
            "current_country_x_current_city_size": (
                "official_derived: UN WUP 2025 city populations aggregated "
                "to seven population-size classes within each country"
            ),
            "current_country_x_age_group_x_sex_x_physical_condition": (
                "ihme_gbd_2023_country_age_sex_derived: cause-specific prevalence "
                "rates population-weighted to project age bands and converted to "
                "one representative physical label with an explicit overlap approximation"
            ),
            "current_country_x_age_group_x_sex_x_mental_condition": (
                "ihme_gbd_2023_country_age_sex_derived: cause-specific prevalence "
                "rates population-weighted to project age bands and converted to "
                "one representative mental/substance-use label"
            ),
        }
    )
    metadata["constraint_quality"].pop("citizenship_country_x_ethnicity", None)
    metadata["static_target_status"].update(
        {
            "current_country_x_citizenship_country": "ready_official_derived_proxy_mixed_basis",
            "current_country_x_birth_country": "ready_official_derived_proxy_mixed_basis",
            "current_country_x_sex_x_birth_migration_status": "ready_official_derived",
            "current_country_x_sex_x_citizenship_migration_status": "ready_official_derived_proxy_mixed_basis",
            "current_country_x_ethnicity": "ready_official_derived",
            "age_x_sex_x_relationship_status": "ready_official_source_backed",
            "current_country_x_age_group_x_sex": "ready_official_modelled",
            "current_country_x_age_group_x_sex_x_relationship_status": "ready_official_source_backed",
            "current_country_x_relationship_status_x_employment_status": "ready_official_raked",
            "current_country_x_sex_x_occupation": "ready_official_modelled_derived",
            "current_country_x_age_group_x_sex_x_ilo_education_group": "ready_official_raked",
            "current_country_x_age_group_x_sex_x_employment_status": "ready_official_raked",
            "current_country_x_sex_x_ilo_education_group_x_employment_status": "ready_official_raked",
            "current_country_x_ilo_education_group_x_occupation_group": "ready_official_raked",
            "current_country_x_age_stage_x_sex_x_occupation_group": "ready_official_raked",
            "current_country_x_welfare_education_group_x_income_level": "ready_world_bank_source_backed_maximum_entropy",
            "current_country_x_age_stage_x_income_level": "ready_world_bank_source_backed_maximum_entropy",
            "current_country_x_current_city_size": "ready_official_derived",
            "current_country_x_age_group_x_sex_x_physical_condition": (
                "ready_ihme_gbd_2023_country_age_sex_derived"
            ),
            "current_country_x_age_group_x_sex_x_mental_condition": (
                "ready_ihme_gbd_2023_country_age_sex_derived"
            ),
        }
    )
    metadata["static_target_status"].pop("citizenship_country_x_ethnicity", None)
    metadata["replacement_notes"]["added"] = [
        "current_country_x_citizenship_country",
        "current_country_x_birth_country",
        "current_country_x_sex_x_birth_migration_status",
        "current_country_x_sex_x_citizenship_migration_status",
        "current_country_x_ethnicity",
        "country_x_income_level",
        "current_country_x_age_group_x_sex",
        "age_x_sex_x_relationship_status",
        "current_country_x_age_group_x_sex_x_relationship_status",
        "current_country_x_relationship_status_x_employment_status",
        "current_country_x_current_city_size",
        "current_country_x_sex_x_occupation",
        "current_country_x_age_group_x_sex_x_ilo_education_group",
        "current_country_x_age_group_x_sex_x_employment_status",
        "current_country_x_sex_x_ilo_education_group_x_employment_status",
        "current_country_x_ilo_education_group_x_occupation_group",
        "current_country_x_age_stage_x_sex_x_occupation_group",
        "current_country_x_welfare_education_group_x_income_level",
        "current_country_x_age_stage_x_income_level",
        "current_country_x_age_group_x_sex_x_physical_condition",
        "current_country_x_age_group_x_sex_x_mental_condition",
    ]
    from privacy_trace.profiles.schema import (
        MENTAL_CONDITIONS as SCHEMA_MENTAL_CONDITIONS,
    )
    from privacy_trace.profiles.schema import (
        OCCUPATIONS as DETAILED_OCCUPATIONS,
    )
    from privacy_trace.profiles.schema import (
        PHYSICAL_CONDITIONS as SCHEMA_PHYSICAL_CONDITIONS,
    )

    metadata.setdefault("schema_option_set", {}).update(
        {
            "citizenship": list(COUNTRY_CODES),
            "current_country": list(COUNTRY_CODES),
            "birth_country": list(COUNTRY_CODES),
            "occupation": DETAILED_OCCUPATIONS,
            "occupation_group": OCCUPATIONS,
            "employment_status": ["employed", "not employed"],
            "age_stage": list(WELFARE_AGE_TYPES),
            "ilo_education_group": list(ILO_EDUCATION_GROUPS),
            "welfare_education_group": list(WELFARE_EDUCATION_TYPES),
            "birth_migration_status": ["local", "foreign"],
            "citizenship_migration_status": ["local", "foreign"],
            "physical_condition": SCHEMA_PHYSICAL_CONDITIONS,
            "mental_condition": SCHEMA_MENTAL_CONDITIONS,
        }
    )
    metadata["schema_option_set"].pop("physical_condition_group", None)
    metadata["schema_option_set"].pop("mental_condition_group", None)
    metadata["official_rebuild"] = {
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "migration_universe": (
            "For birth and citizenship country, each destination row is conditioned "
            f"on native/same-country plus foreign origins among the {len(COUNTRY_CODES)} countries "
            "representable by the current generator."
        ),
        "age_scope_caveat": (
            "Migration, income, and some ethnicity inputs have no consistent age "
            "18-80 slice. Their conditional distributions are applied to the adult "
            "frame while WPP controls the adult country and age-sex marginals."
        ),
        "migration_basis_by_destination": migration_audit,
        "migration_status_by_sex": migration_status_audit,
        "income_band_definition_relative_to_country_median": metadata[
            "official_rebuild"
        ]["income_band_definition_relative_to_country_median"],
        "income_semantics": metadata["official_rebuild"]["income_semantics"],
        "relationship_mapping": {
            "single": ["Single (never married)"],
            "in relationship": ["In consensual union"],
            "married": ["Married"],
            "divorced": ["Divorced and not remarried", "Married but separated"],
            "widowed": ["Widowed and not remarried"],
        },
        "relationship_source_years": marital_years,
        "ilo_joint_constraint_inputs": ilo_joint_audit,
        "ilo_age_stage_occupation_inputs": age_stage_occupation_audit,
        "ilo_relationship_employment_inputs": relationship_employment_audit,
        "education_income_joint_inputs": education_income_audit,
        "age_income_joint_inputs": age_income_audit,
        "education_income_semantics": (
            "Four World Bank education groups are crossed with the project's "
            "five PIP median-relative welfare bands. Observed education-specific "
            "headcounts at $2.15 and $6.85 define three welfare-rank intervals; "
            "maximum entropy is used only inside those intervals. Country WDI "
            "education and PIP income margins remain exact. Missing country "
            "education rows use the World Bank OHI regional relation and are "
            "flagged per country."
        ),
        "age_income_semantics": (
            "World Bank youth [15-24] and adult [25+] welfare profiles are "
            "mapped to the generator's age_stage youth [18-24] and adult "
            "[25-80]. The source's youth band therefore includes ages 15-17 "
            "that are outside the generator. Country age-stage and PIP income "
            "margins remain exact; missing country rows use the OHI relation "
            "and are flagged per country."
        ),
        "ethnicity_conditioning_change": (
            "Changed from citizenship_country x ethnicity to current_country x "
            "ethnicity because official census population-group tables describe "
            "resident populations, not citizens abroad."
        ),
        "occupation_semantics": (
            "None means not employed under the ILOSTAT employment-to-population "
            "measure. Employed profiles use the eight ISCO-08 groups available in "
            "the modelled 2025 bulk table, then receive one of 115 concise concrete "
            "job labels mapped to that group. These display labels are not "
            "independently calibrated. The ILO age-15-plus employment ratio is "
            "applied to the generator's WPP-weighted age-18-to-80 frame."
        ),
        "age_stage_occupation_semantics": (
            "ILOSTAT youth [15-24] and adult [25+] occupation counts are "
            "mapped to generator ages 18-24 and 25-80. Observed dependence "
            "is raked to the existing country-sex occupation and age-stage "
            "employment margins; China and Japan use the pooled observed "
            "ILOSTAT dependence and are explicitly flagged."
        ),
        "relationship_employment_semantics": (
            "ILOSTAT marital-status employment-rate shapes are calibrated "
            "within every country-age-sex cell to the UNData relationship "
            "shares and the ILO employment margin. Missing consensual-union "
            "cells use the same-country married rate first, then the pooled "
            "ILOSTAT rate; every fallback count is recorded."
        ),
        "city_sampling_semantics": (
            "IPF calibrates current country by WUP city population-size class. "
            "The concrete city is sampled within the selected class in "
            "proportion to its WUP 2025 population."
        ),
        "physical_condition_semantics": physical_audit["single_label_semantics"],
        "mental_condition_semantics": mental_audit["single_label_semantics"],
    }


def write_rebuild_outputs(
    data: dict[str, Any],
    *,
    age_income_audit,
    age_stage_occupation_audit,
    args,
    city_catalog,
    education_audit,
    education_income_audit,
    ethnicity_distributions,
    ilo_joint_audit,
    income_audit,
    marital_years,
    mental_audit,
    migration_audit,
    migration_status_audit,
    occupation_audit,
    physical_audit,
    relationship_employment_audit,
    religion_audit,
) -> None:
    args.target.write_text(
        json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    args.city_catalog.parent.mkdir(parents=True, exist_ok=True)
    args.city_catalog.write_text(
        json.dumps(city_catalog, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    render_values_doc(data, args.values_doc)
    audit = {
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "ihme_gbd_input": {
            "path": str(args.ihme_gbd.resolve()),
            "size_bytes": args.ihme_gbd.stat().st_size,
            "sha256": hashlib.sha256(args.ihme_gbd.read_bytes()).hexdigest(),
        },
        "source_urls": {
            "wpp_2024_age_sex": WPP_URL,
            "wup_2025_city_population": WUP_CITY_URL,
            "ims_2020_destination_origin": IMS_URL,
            "undata_marital_status_table_23": "https://data.un.org/Data.aspx?d=POP&f=tableCode%3A23",
            "undata_ethnicity_table_26": "https://data.un.org/Data.aspx?d=POP&f=tableCode%3A26",
            "world_bank_pip_api": "https://api.worldbank.org/pip/v1",
            "oecd_relative_income_classification": OECD_MIDDLE_INCOME_URL,
            "ilostat_employment_by_occupation_2025": ILO_OCCUPATION_URL,
            "ilostat_employment_to_population_2025": ILO_EMPLOYMENT_RATE_URL,
            "ilostat_employment_rate_by_age_observed": (ILO_EMPLOYMENT_RATE_BY_AGE_URL),
            "ilostat_working_age_population_by_age_education": (
                ILO_WORKING_AGE_AGE_EDUCATION_URL
            ),
            "ilostat_employment_by_age_education": (ILO_EMPLOYMENT_AGE_EDUCATION_URL),
            "ilostat_employment_rate_by_education": (
                ILO_EMPLOYMENT_RATE_BY_EDUCATION_URL
            ),
            "ilostat_occupation_by_education": (ILO_OCCUPATION_EDUCATION_URL),
            "ilostat_occupation_by_age_stage": (ILO_AGE_OCCUPATION_URL),
            "ilostat_employment_rate_by_age_marital_status": (
                ILO_AGE_MARITAL_EMPLOYMENT_RATE_URL
            ),
            "world_bank_global_welfare_profile_2022": (WORLD_BANK_WELFARE_PROFILE_URL),
            "pew_religious_composition_2020": PEW_RELIGION_URL,
            "ihme_gbd_2023_results_tool": (
                "https://vizhub.healthdata.org/gbd-results/"
            ),
            "statistics_canada_population_group_2021": (
                "https://www12.statcan.gc.ca/census-recensement/2021/dp-pd/"
                "prof/details/page.cfm?DGUIDlist=2021A000011124"
            ),
            "inegi_census_2020_indigenous": (
                "https://www.inegi.org.mx/contenidos/productos/prod_serv/"
                "contenidos/espanol/bvinegi/productos/nueva_estruc/702825198060.pdf"
            ),
        },
        "migration": migration_audit,
        "migration_status_by_sex": migration_status_audit,
        "education": education_audit,
        "ilo_joint_constraints": ilo_joint_audit,
        "ilo_age_stage_occupation": age_stage_occupation_audit,
        "ilo_relationship_employment": relationship_employment_audit,
        "education_income_joint": education_income_audit,
        "age_income_joint": age_income_audit,
        "religion": religion_audit,
        "income": income_audit,
        "relationship_source_years": marital_years,
        "ethnicity_conditional_distributions": ethnicity_distributions,
        "occupation": occupation_audit,
        "physical_condition": physical_audit,
        "mental_condition": mental_audit,
    }
    args.audit.parent.mkdir(parents=True, exist_ok=True)
    args.audit.write_text(
        json.dumps(audit, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
