#!/usr/bin/env python3
"""Rebuild official population targets. Implementation is in privacy_trace.population_targets."""

from pathlib import Path
import sys

PROJECT_DIR = Path(__file__).resolve().parents[1]
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

from privacy_trace.population_targets.cli import (
    main,
)
from privacy_trace.population_targets.common import (
    calibrate_probabilities_to_mean,
    download,
    grouped_education_margins,
    normalize,
    overlap_fraction,
    parse_age_range,
    rake_matrix,
    read_zipped_csv,
)
from privacy_trace.population_targets.constants import (
    AGE_GROUPS,
    BASE_ETHNICITY,
    COUNTRY_CODES,
    DEFAULT_AUDIT,
    DEFAULT_CACHE,
    DEFAULT_CITY_CATALOG,
    DEFAULT_IHME_GBD_2023,
    DEFAULT_TARGET,
    DEFAULT_VALUES_DOC,
    EDUCATION_INDICATORS,
    EDUCATION_LEVELS,
    ETHNICITIES,
    GBD_AGE_ID_TO_RANGE,
    GBD_LOCATION_ID_TO_COUNTRY,
    GBD_SEX_ID_TO_SEX,
    ILO_AGE_CODES,
    ILO_AGE_MARITAL_EMPLOYMENT_RATE_URL,
    ILO_AGE_OCCUPATION_URL,
    ILO_AGE_STAGE_CODES,
    ILO_EDUCATION_DETAILED_TO_GROUP,
    ILO_EDUCATION_GROUPS,
    ILO_EDUCATION_LEVEL_TO_GROUP,
    ILO_EMPLOYMENT_AGE_EDUCATION_URL,
    ILO_EMPLOYMENT_RATE_BY_AGE_URL,
    ILO_EMPLOYMENT_RATE_BY_EDUCATION_URL,
    ILO_EMPLOYMENT_RATE_URL,
    ILO_MARITAL_STATUS_TO_RELATIONSHIP,
    ILO_OBSERVED_OCCUPATION_TO_GROUP,
    ILO_OCCUPATION_EDUCATION_URL,
    ILO_OCCUPATION_URL,
    ILO_SEX_CODES,
    ILO_WORKING_AGE_AGE_EDUCATION_URL,
    IMS_ORIGIN_TO_ETHNICITY,
    IMS_URL,
    INCOME_LEVELS,
    INCOME_MEDIAN_MULTIPLIERS,
    MAX_DIRECT_WELFARE_GROUP_SHARE_RATIO,
    MENTAL_CAUSE_IDS,
    MENTAL_CONDITIONS,
    MENTAL_CONDITION_STATISTICS,
    MIN_DIRECT_WELFARE_GROUP_SHARE_RATIO,
    OCCUPATIONS,
    OCCUPATION_CODES,
    OECD_MIDDLE_INCOME_URL,
    PEW_RELIGION_URL,
    PHYSICAL_CAUSE_IDS,
    PHYSICAL_CONDITIONS,
    PHYSICAL_CONDITION_STATISTICS,
    PHYSICAL_SYSTEMS,
    PIP_URL,
    PROJECT_ROOT,
    RELATIONSHIPS,
    RELATIONSHIP_MAP,
    SEX_MAP,
    UNDATA_URL,
    WELFARE_AGE_TYPES,
    WELFARE_EDUCATION_LEVEL_TO_GROUP,
    WELFARE_EDUCATION_TYPES,
    WORLD_BANK_API,
    WORLD_BANK_WELFARE_PROFILE_MEMBER,
    WORLD_BANK_WELFARE_PROFILE_URL,
    WPP_URL,
    WUP_CITY_URL,
)
from privacy_trace.population_targets.constraints import (
    constraint,
    rounded,
    update_income_constraint_and_metadata,
    upsert_constraint,
)
from privacy_trace.population_targets.demographics import (
    build_country_age_sex_targets,
    build_country_relationship_targets,
    build_education_targets,
    build_ethnicity_targets,
    build_migration_status_by_sex_targets,
    build_migration_targets,
    build_population_targets,
    build_relationship_targets,
    city_size_class,
    direct_ethnicity_distributions,
    fetch_wdi_education,
    load_ims,
    load_marital_rows,
    load_pew_religion,
    load_wpp,
    load_wup_city_catalog,
)
from privacy_trace.population_targets.employment import (
    _education_code_mapping,
    _ilo_candidate_groups,
    build_age_stage_occupation_targets,
    build_ilo_joint_targets,
    build_occupation_targets,
    build_relationship_employment_targets,
    load_ilo_rds,
    select_ilo_age_education_panel,
    select_ilo_age_marital_rate_panel,
    select_ilo_age_rate_panel,
    select_ilo_age_stage_occupation_panel,
    select_ilo_education_rate_panel,
    select_ilo_occupation_education_panel,
)
from privacy_trace.population_targets.health import (
    build_health_targets,
    build_one_label_health_targets,
    load_ihme_gbd_2023,
)
from privacy_trace.population_targets.income import (
    build_age_income_targets,
    build_conditioned_income_targets,
    build_education_income_targets,
    build_income_targets,
    fetch_pip_rows,
    latest_national_pip_row,
    load_world_bank_welfare_profile,
    matching_pip_row,
)
from privacy_trace.population_targets.reports import (
    render_values_doc,
    write_income_audit,
)

if __name__ == "__main__":
    main()
