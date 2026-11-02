"""Population categories, source URLs, and target output paths."""

from __future__ import annotations

from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]

DEFAULT_TARGET = PROJECT_ROOT / "data/targets/demographic_targets_2025.json"

DEFAULT_AUDIT = PROJECT_ROOT / "data/sources/official_ipf/derived_inputs_2025.json"

DEFAULT_VALUES_DOC = PROJECT_ROOT / "docs/current_ipf_constraint_values.md"

DEFAULT_CACHE = PROJECT_ROOT / ".cache/official_ipf"

DEFAULT_CITY_CATALOG = PROJECT_ROOT / "data/catalogs/wup2025_cities_2025.json"

DEFAULT_IHME_GBD_2023 = DEFAULT_CACHE / "ihme_gbd_2023.csv"

WPP_URL = (
    "https://population.un.org/wpp/assets/Excel%20Files/"
    "1_Indicator%20(Standard)/CSV_FILES/"
    "WPP2024_PopulationByAge5GroupSex_Medium.csv.gz"
)

IMS_URL = (
    "https://www.un.org/development/desa/pd/sites/"
    "www.un.org.development.desa.pd/files/"
    "undesa_pd_2020_ims_stock_by_sex_destination_and_origin.xlsx"
)

UNDATA_URL = (
    "https://data.un.org/Handlers/DownloadHandler.ashx?"
    "DataFilter=tableCode:{table}%3BcountryCode:{country_code}"
    "&DataMartId=POP&Format=csv"
)

PIP_URL = (
    "https://api.worldbank.org/pip/v1/pip?"
    "country={country}&year={year}&povline={line}"
    "&ppp_version=2021&format=json"
)

OECD_MIDDLE_INCOME_URL = (
    "https://www.oecd.org/en/publications/under-pressure-the-squeezed-middle-class_"
    "689afed1-en/full-report/component-6.html"
)

ILO_OCCUPATION_URL = (
    "https://rplumber.ilo.org/files/indicator/EMP_2EMP_SEX_OCU_NB_A.rds"
)

ILO_EMPLOYMENT_RATE_URL = (
    "https://rplumber.ilo.org/files/indicator/EMP_2WAP_SEX_AGE_RT_A.rds"
)

ILO_EMPLOYMENT_RATE_BY_AGE_URL = (
    "https://rplumber.ilo.org/files/indicator/EMP_DWAP_SEX_AGE_RT_A.rds"
)

ILO_WORKING_AGE_AGE_EDUCATION_URL = (
    "https://rplumber.ilo.org/files/indicator/POP_XWAP_SEX_AGE_EDU_NB_A.rds"
)

ILO_EMPLOYMENT_AGE_EDUCATION_URL = (
    "https://rplumber.ilo.org/files/indicator/EMP_TEMP_SEX_AGE_EDU_NB_A.rds"
)

ILO_EMPLOYMENT_RATE_BY_EDUCATION_URL = (
    "https://rplumber.ilo.org/files/indicator/EMP_DWAP_SEX_EDU_RT_A.rds"
)

ILO_OCCUPATION_EDUCATION_URL = (
    "https://rplumber.ilo.org/files/indicator/EMP_TEMP_SEX_OCU_EDU_NB_A.rds"
)

ILO_AGE_OCCUPATION_URL = (
    "https://rplumber.ilo.org/files/indicator/EMP_TEMP_SEX_AGE_OCU_NB_A.rds"
)

ILO_AGE_MARITAL_EMPLOYMENT_RATE_URL = (
    "https://rplumber.ilo.org/files/indicator/EMP_DWAP_SEX_AGE_MTS_RT_A.rds"
)

WORLD_BANK_WELFARE_PROFILE_URL = (
    "https://reproducibility.worldbank.org/catalog/250/download/732"
)

WORLD_BANK_WELFARE_PROFILE_MEMBER = (
    "FR_WLD_2024_198/Reproducibility package/Chapter 1/1-data/raw/other/"
    "global_profile_lineup_2022_country_level.dta"
)

WUP_CITY_URL = (
    "https://population.un.org/wup/assets/Download/Cities/"
    "WUP2025-F21-DEGURBA-Cities_Pop.xlsx"
)

PEW_RELIGION_URL = (
    "https://www.pewresearch.org/wp-content/uploads/sites/20/2025/06/"
    "Religious-Composition-2010-2020-dataset.zip"
)

WORLD_BANK_API = (
    "https://api.worldbank.org/v2/country/{countries}/indicator/{indicator}"
    "?format=json&per_page=20000"
)

COUNTRY_CODES = {
    "United States": {"m49": 840, "iso3": "USA", "un_name": "United States of America"},
    "China": {"m49": 156, "iso3": "CHN", "un_name": "China"},
    "India": {"m49": 356, "iso3": "IND", "un_name": "India"},
    "Brazil": {"m49": 76, "iso3": "BRA", "un_name": "Brazil"},
    "Mexico": {"m49": 484, "iso3": "MEX", "un_name": "Mexico"},
    "Nigeria": {"m49": 566, "iso3": "NGA", "un_name": "Nigeria"},
    "Germany": {"m49": 276, "iso3": "DEU", "un_name": "Germany"},
    "Japan": {"m49": 392, "iso3": "JPN", "un_name": "Japan"},
    "United Kingdom": {"m49": 826, "iso3": "GBR", "un_name": "United Kingdom"},
    "Canada": {"m49": 124, "iso3": "CAN", "un_name": "Canada"},
    "Colombia": {"m49": 170, "iso3": "COL", "un_name": "Colombia"},
    "France": {"m49": 250, "iso3": "FRA", "un_name": "France"},
    "Poland": {"m49": 616, "iso3": "POL", "un_name": "Poland"},
    "South Korea": {"m49": 410, "iso3": "KOR", "un_name": "Republic of Korea"},
    "Indonesia": {"m49": 360, "iso3": "IDN", "un_name": "Indonesia"},
    "Philippines": {"m49": 608, "iso3": "PHL", "un_name": "Philippines"},
    "Vietnam": {"m49": 704, "iso3": "VNM", "un_name": "Viet Nam"},
    "Pakistan": {"m49": 586, "iso3": "PAK", "un_name": "Pakistan"},
    "Bangladesh": {"m49": 50, "iso3": "BGD", "un_name": "Bangladesh"},
    "Egypt": {"m49": 818, "iso3": "EGY", "un_name": "Egypt"},
    "Turkey": {"m49": 792, "iso3": "TUR", "un_name": "Türkiye"},
    "Iran": {
        "m49": 364,
        "iso3": "IRN",
        "un_name": "Iran (Islamic Republic of)",
    },
    "Ethiopia": {"m49": 231, "iso3": "ETH", "un_name": "Ethiopia"},
    "South Africa": {"m49": 710, "iso3": "ZAF", "un_name": "South Africa"},
    "Kenya": {"m49": 404, "iso3": "KEN", "un_name": "Kenya"},
    "Australia": {"m49": 36, "iso3": "AUS", "un_name": "Australia"},
}

AGE_GROUPS = {
    "18-24": (18, 24),
    "25-34": (25, 34),
    "35-44": (35, 44),
    "45-54": (45, 54),
    "55-64": (55, 64),
    "65-80": (65, 80),
}

SEX_MAP = {"Male": "male", "Female": "female"}

RELATIONSHIP_MAP = {
    "Single (never married)": "single",
    "In consensual union": "in relationship",
    "Married": "married",
    "Divorced and not remarried": "divorced",
    "Married but separated": "divorced",
    "Widowed and not remarried": "widowed",
}

RELATIONSHIPS = [
    "single",
    "in relationship",
    "married",
    "divorced",
    "widowed",
]

ETHNICITIES = [
    "East Asian",
    "SE Asian",
    "South Asian",
    "MENA",
    "Black",
    "White",
    "Latino",
    "Indigenous",
    "Pacific Islander",
    "Mixed",
]

INCOME_MEDIAN_MULTIPLIERS = [0.75, 1.0, 1.5, 2.0]

INCOME_LEVELS = ["low", "lower-middle", "middle", "upper-middle", "high"]

EDUCATION_LEVELS = [
    "none",
    "primary",
    "lower secondary",
    "upper secondary",
    "vocational",
    "bachelor",
    "master",
    "doctorate",
]

EDUCATION_INDICATORS = {
    "primary": "SE.PRM.CUAT.ZS",
    "lower_secondary": "SE.SEC.CUAT.LO.ZS",
    "upper_secondary": "SE.SEC.CUAT.UP.ZS",
    "post_secondary": "SE.SEC.CUAT.PO.ZS",
    "bachelor": "SE.TER.CUAT.BA.ZS",
    "master": "SE.TER.CUAT.MS.ZS",
    "doctorate": "SE.TER.CUAT.DO.ZS",
}

ILO_EDUCATION_GROUPS = {
    "less than basic": {"EDU_AGGREGATE_LTB"},
    "basic": {"EDU_AGGREGATE_BAS"},
    "intermediate": {"EDU_AGGREGATE_INT"},
    "advanced": {"EDU_AGGREGATE_ADV"},
}

ILO_EDUCATION_LEVEL_TO_GROUP = {
    "none": "less than basic",
    "primary": "basic",
    "lower secondary": "basic",
    "upper secondary": "intermediate",
    "vocational": "intermediate",
    "bachelor": "advanced",
    "master": "advanced",
    "doctorate": "advanced",
}

ILO_EDUCATION_DETAILED_TO_GROUP = {
    "EDU_ISCED11_0": "less than basic",
    "EDU_ISCED11_1": "basic",
    "EDU_ISCED11_2": "basic",
    "EDU_ISCED11_3": "intermediate",
    "EDU_ISCED11_4": "intermediate",
    "EDU_ISCED11_5": "advanced",
    "EDU_ISCED11_6": "advanced",
    "EDU_ISCED11_7": "advanced",
    "EDU_ISCED11_8": "advanced",
    "EDU_ISCED97_0": "less than basic",
    "EDU_ISCED97_1": "basic",
    "EDU_ISCED97_2": "basic",
    "EDU_ISCED97_3": "intermediate",
    "EDU_ISCED97_4": "intermediate",
    "EDU_ISCED97_5": "advanced",
    "EDU_ISCED97_5A": "advanced",
    "EDU_ISCED97_5B": "advanced",
    "EDU_ISCED97_6": "advanced",
}

ILO_AGE_CODES = {
    "AGE_10YRBANDS_Y15-24": "18-24",
    "AGE_10YRBANDS_Y25-34": "25-34",
    "AGE_10YRBANDS_Y35-44": "35-44",
    "AGE_10YRBANDS_Y45-54": "45-54",
    "AGE_10YRBANDS_Y55-64": "55-64",
    "AGE_10YRBANDS_YGE65": "65-80",
}

ILO_SEX_CODES = {"SEX_M": "male", "SEX_F": "female"}

WELFARE_EDUCATION_TYPES = {
    "no education": "No education",
    "primary": "Primary (complete or incomplete)",
    "secondary": "Secondary (complete or incomplete)",
    "tertiary": "Tertiary (complete or incomplete)",
}

MIN_DIRECT_WELFARE_GROUP_SHARE_RATIO = 0.1

MAX_DIRECT_WELFARE_GROUP_SHARE_RATIO = 10.0

WELFARE_EDUCATION_LEVEL_TO_GROUP = {
    "none": "no education",
    "primary": "primary",
    "lower secondary": "secondary",
    "upper secondary": "secondary",
    "vocational": "secondary",
    "bachelor": "tertiary",
    "master": "tertiary",
    "doctorate": "tertiary",
}

WELFARE_AGE_TYPES = {
    "youth": "youth [15-24]",
    "adult": "adult [25+]",
}

ILO_AGE_STAGE_CODES = {
    "AGE_YTHADULT_Y15-24": "youth",
    "AGE_YTHADULT_YGE25": "adult",
}

ILO_MARITAL_STATUS_TO_RELATIONSHIP = {
    "MTS_DETAILS_SGLE": "single",
    "MTS_DETAILS_UNION": "in relationship",
    "MTS_DETAILS_MRD": "married",
    "MTS_DETAILS_SEP": "divorced",
    "MTS_DETAILS_WID": "widowed",
}

OCCUPATION_CODES = {
    "OCU_ISCO08_1": "managers",
    "OCU_ISCO08_2": "professionals",
    "OCU_ISCO08_3": "technicians and associate professionals",
    "OCU_ISCO08_4": "clerical support workers",
    "OCU_ISCO08_5": "service and sales workers",
    "OCU_ISCO08_7": "craft and related trades workers",
    "OCU_ISCO08_8": "plant and machine operators and assemblers",
    "OCU_ISCO08_96": "elementary and skilled agricultural workers",
}

OCCUPATIONS = ["None", *OCCUPATION_CODES.values()]

ILO_OBSERVED_OCCUPATION_TO_GROUP = {
    "OCU_ISCO08_1": "managers",
    "OCU_ISCO08_2": "professionals",
    "OCU_ISCO08_3": "technicians and associate professionals",
    "OCU_ISCO08_4": "clerical support workers",
    "OCU_ISCO08_5": "service and sales workers",
    "OCU_ISCO08_6": "elementary and skilled agricultural workers",
    "OCU_ISCO08_7": "craft and related trades workers",
    "OCU_ISCO08_8": "plant and machine operators and assemblers",
    "OCU_ISCO08_9": "elementary and skilled agricultural workers",
}

GBD_LOCATION_ID_TO_COUNTRY = {
    102: "United States",
    6: "China",
    163: "India",
    135: "Brazil",
    130: "Mexico",
    214: "Nigeria",
    81: "Germany",
    67: "Japan",
    4749: "United Kingdom",
    101: "Canada",
    125: "Colombia",
    80: "France",
    51: "Poland",
    68: "South Korea",
    11: "Indonesia",
    16: "Philippines",
    20: "Vietnam",
    165: "Pakistan",
    161: "Bangladesh",
    141: "Egypt",
    155: "Turkey",
    142: "Iran",
    179: "Ethiopia",
    196: "South Africa",
    180: "Kenya",
    71: "Australia",
}

GBD_SEX_ID_TO_SEX = {1: "male", 2: "female"}

GBD_AGE_ID_TO_RANGE = {
    8: (15, 19),
    9: (20, 24),
    10: (25, 29),
    11: (30, 34),
    12: (35, 39),
    13: (40, 44),
    14: (45, 49),
    15: (50, 54),
    16: (55, 59),
    17: (60, 64),
    18: (65, 69),
    19: (70, 74),
    20: (75, 79),
    30: (80, 84),
}

PHYSICAL_CAUSE_IDS = {
    "migraine": (547,),
    "tension-type headache": (548,),
    "idiopathic epilepsy": (545,),
    "Parkinson's disease": (544,),
    "Alzheimer's disease and other dementias": (543,),
    "stroke": (494,),
    "age-related and other hearing loss": (674,),
    "osteoarthritis": (628,),
    "rheumatoid arthritis": (627,),
    "low back pain": (630,),
    "asthma": (515,),
    "chronic obstructive pulmonary disease": (509,),
    "type 2 diabetes": (976,),
    "chronic kidney disease": (589,),
    "atrial fibrillation and flutter": (500,),
    "gastritis and duodenitis": (528,),
    "peptic ulcer disease": (527,),
    "dermatitis": (654,),
    "urticaria": (664,),
    "psoriasis": (655,),
    "alopecia areata": (662,),
    "HIV/AIDS": (298,),
}

MENTAL_CAUSE_IDS = {
    "schizophrenia": (559,),
    # The query exports major depressive disorder and dysthymia separately.
    "depressive disorders": (568, 569),
    "bipolar disorder": (570,),
    "anxiety disorders": (571,),
    # The query exports anorexia nervosa and bulimia nervosa separately.
    "eating disorders": (573, 574),
    "autism spectrum disorders": (575,),
    "ADHD": (578,),
    "conduct disorder": (579,),
    "idiopathic developmental intellectual disability": (582,),
    "other mental disorders": (585,),
    "alcohol use disorders": (560,),
    "opioid use disorders": (562,),
    "amphetamine use disorders": (564,),
    "cocaine use disorders": (563,),
    "cannabis use disorders": (565,),
    "other drug use disorders": (566,),
}

PHYSICAL_CONDITIONS = ["None", *PHYSICAL_CAUSE_IDS]

MENTAL_CONDITIONS = ["None", *MENTAL_CAUSE_IDS]

PHYSICAL_SYSTEMS = {
    "migraine": "neurological",
    "tension-type headache": "neurological",
    "idiopathic epilepsy": "neurological",
    "Parkinson's disease": "neurological",
    "Alzheimer's disease and other dementias": "neurological",
    "stroke": "cardiovascular_and_neurological",
    "age-related and other hearing loss": "sensory",
    "osteoarthritis": "musculoskeletal",
    "rheumatoid arthritis": "musculoskeletal",
    "low back pain": "musculoskeletal",
    "asthma": "respiratory",
    "chronic obstructive pulmonary disease": "respiratory",
    "type 2 diabetes": "metabolic",
    "chronic kidney disease": "renal",
    "atrial fibrillation and flutter": "cardiovascular",
    "gastritis and duodenitis": "digestive",
    "peptic ulcer disease": "digestive",
    "dermatitis": "skin",
    "urticaria": "skin",
    "psoriasis": "skin",
    "alopecia areata": "skin",
    "HIV/AIDS": "infectious",
}

PHYSICAL_CONDITION_STATISTICS = {
    condition: {
        "gbd_cause_ids": list(cause_ids),
        "system": PHYSICAL_SYSTEMS[condition],
        "estimate_year": 2023,
        "scope": "country_age_sex_specific",
        "span_type": "GBD_cause_or_documented_child_cause_sum",
        "source_key": "ihme_gbd_2023_prevalence_query",
    }
    for condition, cause_ids in PHYSICAL_CAUSE_IDS.items()
}

MENTAL_CONDITION_STATISTICS = {
    condition: {
        "gbd_cause_ids": list(cause_ids),
        "family": (
            "alcohol_use_disorders"
            if condition == "alcohol use disorders"
            else (
                "drug_use_disorders"
                if condition.endswith("drug use disorders")
                or condition
                in {
                    "opioid use disorders",
                    "amphetamine use disorders",
                    "cocaine use disorders",
                    "cannabis use disorders",
                }
                else "mental_disorders"
            )
        ),
        "estimate_year": 2023,
        "scope": "country_age_sex_specific",
        "span_type": "GBD_cause_or_documented_child_cause_sum",
        "source_key": "ihme_gbd_2023_prevalence_query",
    }
    for condition, cause_ids in MENTAL_CAUSE_IDS.items()
}

IMS_ORIGIN_TO_ETHNICITY = {
    910: "Black",  # Eastern Africa
    911: "Black",  # Middle Africa
    913: "Black",  # Southern Africa
    914: "Black",  # Western Africa
    912: "MENA",  # Northern Africa
    5500: "MENA",  # Central Asia
    922: "MENA",  # Western Asia
    5501: "South Asian",  # Southern Asia
    906: "East Asian",  # Eastern Asia
    920: "SE Asian",  # South-Eastern Asia
    915: "Latino",  # Caribbean
    916: "Latino",  # Central America
    931: "Latino",  # South America
    923: "White",  # Eastern Europe
    924: "White",  # Northern Europe
    925: "White",  # Southern Europe
    926: "White",  # Western Europe
    905: "White",  # Northern America
    927: "White",  # Australia and New Zealand
    928: "Pacific Islander",  # Melanesia
    954: "Pacific Islander",  # Micronesia
    957: "Pacific Islander",  # Polynesia
    2003: "Mixed",  # Other/unknown origin
}

BASE_ETHNICITY = {
    "Colombia": "Latino",
    "France": "White",
    "Germany": "White",
    "Poland": "White",
    "South Korea": "East Asian",
    "Indonesia": "SE Asian",
    "Philippines": "SE Asian",
    "Vietnam": "SE Asian",
    "India": "South Asian",
    "Pakistan": "South Asian",
    "Bangladesh": "South Asian",
    "Egypt": "MENA",
    "Turkey": "MENA",
    "Iran": "MENA",
    "Japan": "East Asian",
    "Nigeria": "Black",
    "Ethiopia": "Black",
    "South Africa": "Black",
    "Kenya": "Black",
    "Australia": "White",
}
