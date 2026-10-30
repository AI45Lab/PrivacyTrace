"""Profile attributes, catalog values, and generation configuration."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from privacy_trace.government_ids import GOVERNMENT_ID_RULES, government_id_format_hints

SKELETON_FIELDS = [
    "age",
    "sex",
    "ethnicity",
    "citizenship",
    "current_location",
    "birth_location",
    "education_level",
    "income_level",
    "relationship_status",
    "religious_belief",
    "occupation",
    "physical_condition",
    "mental_condition",
]

COMPLETION_FIELDS = [
    "name",
    "email",
    "phone_number",
    "government_id",
]

LLM_COMPLETION_FIELDS = [
    "name",
    "email",
    "phone_number",
    "government_id",
]

DIRECT_IDENTIFIER_FIELDS = ("email", "phone_number", "government_id")

FULL_SCHEMA_FIELDS = SKELETON_FIELDS + COMPLETION_FIELDS

PROJECT_ROOT = Path(__file__).resolve().parents[2]

REAL_TARGETS_PATH = PROJECT_ROOT / "data/targets/demographic_targets_2025.json"

CHECKPOINT_FORMAT_VERSION = 3

PROFILE_REFERENCE_YEAR = 2025

PROFILE_PROMPT_ID = "profile_seed_audit_pii_completion_government_id"

GOVERNMENT_ID_LLM_AUDIT_REASON_CODES = {
    "none",
    "wrong_document_type",
    "citizenship_mismatch",
    "birth_information_mismatch",
    "sex_mismatch",
    "name_component_mismatch",
    "region_component_implausible",
    "internally_inconsistent",
    "other_clear_government_id_contradiction",
}

GOVERNMENT_ID_LLM_AUDIT_ISSUE_PREFIX = (
    "government_id failed LLM logical-consistency audit"
)

GOVERNMENT_ID_REPAIR_POLICY_ID = "llm_feedback_registry_postprocess"

SKELETON_IPF_BUCKET_FIELDS = {
    "age": {"age", "age_group", "age_stage"},
    "sex": {"sex"},
    "ethnicity": {"ethnicity"},
    "citizenship": {
        "citizenship",
        "citizenship_country",
        "citizenship_migration_status",
    },
    "current_location": {
        "current_location",
        "current_country",
        "current_city_size",
        "birth_migration_status",
        "citizenship_migration_status",
    },
    "birth_location": {
        "birth_location",
        "birth_country",
        "birth_migration_status",
    },
    "education_level": {
        "education_level",
        "ilo_education_group",
        "welfare_education_group",
    },
    "income_level": {"income_level"},
    "relationship_status": {"relationship_status"},
    "religious_belief": {"religious_belief"},
    "occupation": {"occupation", "occupation_group", "employment_status"},
    "physical_condition": {"physical_condition"},
    "mental_condition": {"mental_condition"},
}

SEXES = ["male", "female"]

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

ILO_EDUCATION_GROUP_TO_OPTIONS = {
    "less than basic": ["none"],
    "basic": ["primary", "lower secondary"],
    "intermediate": ["upper secondary", "vocational"],
    "advanced": ["bachelor", "master", "doctorate"],
}

ILO_EDUCATION_TO_GROUP = {
    option: group
    for group, options in ILO_EDUCATION_GROUP_TO_OPTIONS.items()
    for option in options
}

WELFARE_EDUCATION_GROUP_TO_OPTIONS = {
    "no education": ["none"],
    "primary": ["primary"],
    "secondary": ["lower secondary", "upper secondary", "vocational"],
    "tertiary": ["bachelor", "master", "doctorate"],
}

WELFARE_EDUCATION_TO_GROUP = {
    option: group
    for group, options in WELFARE_EDUCATION_GROUP_TO_OPTIONS.items()
    for option in options
}

INCOME_LEVELS = ["low", "lower-middle", "middle", "upper-middle", "high"]

RELATIONSHIP_STATUSES = [
    "single",
    "in relationship",
    "married",
    "divorced",
    "widowed",
]

RELIGIONS = [
    "Unaffiliated",
    "Christian",
    "Muslim",
    "Hindu",
    "Buddhist",
    "Jewish",
    "Folk",
]

OCCUPATION_GROUP_TO_OPTIONS = {
    "None": ["None"],
    "managers": [
        "chief executive",
        "government administrator",
        "nonprofit director",
        "finance manager",
        "human resources manager",
        "sales manager",
        "factory manager",
        "construction manager",
        "logistics manager",
        "hotel manager",
        "restaurant manager",
        "retail manager",
    ],
    "professionals": [
        "civil engineer",
        "mechanical engineer",
        "electrical engineer",
        "architect",
        "chemist",
        "biologist",
        "physician",
        "registered nurse",
        "pharmacist",
        "dentist",
        "primary school teacher",
        "secondary school teacher",
        "university lecturer",
        "accountant",
        "financial analyst",
        "marketing specialist",
        "software developer",
        "data scientist",
        "cybersecurity analyst",
        "lawyer",
        "psychologist",
        "journalist",
    ],
    "technicians and associate professionals": [
        "civil engineering technician",
        "electrical technician",
        "land surveyor",
        "medical laboratory technician",
        "paramedic",
        "pharmacy technician",
        "bookkeeper",
        "insurance agent",
        "real estate agent",
        "paralegal",
        "social work assistant",
        "photographer",
        "network technician",
        "web technician",
        "IT support technician",
    ],
    "clerical support workers": [
        "office clerk",
        "secretary",
        "data entry clerk",
        "bank teller",
        "travel clerk",
        "call center agent",
        "inventory clerk",
        "payroll clerk",
        "shipping clerk",
        "receptionist",
        "library clerk",
        "mail clerk",
    ],
    "service and sales workers": [
        "chef",
        "waiter",
        "hairdresser",
        "retail salesperson",
        "cashier",
        "market vendor",
        "childcare worker",
        "nursing aide",
        "home care aide",
        "police officer",
        "firefighter",
        "security guard",
    ],
    "craft and related trades workers": [
        "bricklayer",
        "carpenter",
        "plumber",
        "welder",
        "machinist",
        "auto mechanic",
        "jeweler",
        "potter",
        "printer",
        "electrician",
        "electronics repairer",
        "appliance repairer",
        "baker",
        "butcher",
        "tailor",
    ],
    "plant and machine operators and assemblers": [
        "CNC machine operator",
        "chemical plant operator",
        "power plant operator",
        "electronics assembler",
        "vehicle assembler",
        "product assembler",
        "truck driver",
        "bus driver",
        "excavator operator",
    ],
    "elementary and skilled agricultural workers": [
        "crop farmer",
        "orchard farmer",
        "forestry worker",
        "commercial fisher",
        "subsistence farmer",
        "subsistence fisher",
        "office cleaner",
        "domestic cleaner",
        "farm laborer",
        "forestry laborer",
        "construction laborer",
        "factory laborer",
        "kitchen helper",
        "fast-food preparer",
        "street vendor",
        "car washer",
        "garbage collector",
        "delivery courier",
    ],
}

OCCUPATION_GROUPS = list(OCCUPATION_GROUP_TO_OPTIONS)

OCCUPATIONS = [
    option for options in OCCUPATION_GROUP_TO_OPTIONS.values() for option in options
]

OCCUPATION_TO_GROUP = {
    option: group
    for group, options in OCCUPATION_GROUP_TO_OPTIONS.items()
    for option in options
}

PHYSICAL_CONDITIONS = [
    "None",
    "migraine",
    "tension-type headache",
    "idiopathic epilepsy",
    "Parkinson's disease",
    "Alzheimer's disease and other dementias",
    "stroke",
    "age-related and other hearing loss",
    "osteoarthritis",
    "rheumatoid arthritis",
    "low back pain",
    "asthma",
    "chronic obstructive pulmonary disease",
    "type 2 diabetes",
    "chronic kidney disease",
    "atrial fibrillation and flutter",
    "gastritis and duodenitis",
    "peptic ulcer disease",
    "dermatitis",
    "urticaria",
    "psoriasis",
    "alopecia areata",
    "HIV/AIDS",
]

MENTAL_CONDITIONS = [
    "None",
    "schizophrenia",
    "depressive disorders",
    "bipolar disorder",
    "anxiety disorders",
    "eating disorders",
    "autism spectrum disorders",
    "ADHD",
    "conduct disorder",
    "idiopathic developmental intellectual disability",
    "other mental disorders",
    "alcohol use disorders",
    "opioid use disorders",
    "amphetamine use disorders",
    "cocaine use disorders",
    "cannabis use disorders",
    "other drug use disorders",
]

AGE_GROUPS = [
    ("18-24", 18, 24),
    ("25-34", 25, 34),
    ("35-44", 35, 44),
    ("45-54", 45, 54),
    ("55-64", 55, 64),
    ("65-80", 65, 80),
]

COUNTRY_PROFILES: dict[str, dict[str, Any]] = {
    "United States": {
        "weight": 0.18,
        "locations": [
            "New York, United States",
            "Los Angeles, United States",
            "Chicago, United States",
            "Houston, United States",
            "Boston, United States",
            "Seattle, United States",
        ],
        "phone_code": "+1",
        "ethnicity": {
            "White": 0.55,
            "Latino": 0.19,
            "Black": 0.13,
            "East Asian": 0.05,
            "South Asian": 0.03,
            "Mixed": 0.035,
            "Indigenous": 0.01,
            "Pacific Islander": 0.005,
        },
        "religion": {
            "Christian": 0.58,
            "Unaffiliated": 0.30,
            "Jewish": 0.02,
            "Muslim": 0.02,
            "Hindu": 0.01,
            "Buddhist": 0.01,
            "Folk": 0.06,
        },
    },
    "China": {
        "weight": 0.17,
        "locations": [
            "Beijing, China",
            "Shanghai, China",
            "Guangzhou, China",
            "Shenzhen, China",
            "Chengdu, China",
            "Hangzhou, China",
        ],
        "phone_code": "+86",
        "ethnicity": {
            "East Asian": 0.91,
            "Mixed": 0.05,
            "SE Asian": 0.02,
            "South Asian": 0.01,
            "White": 0.005,
            "MENA": 0.005,
        },
        "religion": {
            "Unaffiliated": 0.55,
            "Folk": 0.23,
            "Buddhist": 0.18,
            "Christian": 0.03,
            "Muslim": 0.01,
        },
    },
    "India": {
        "weight": 0.16,
        "locations": [
            "Delhi, India",
            "Mumbai, India",
            "Bengaluru, India",
            "Hyderabad, India",
            "Chennai, India",
            "Kolkata, India",
        ],
        "phone_code": "+91",
        "ethnicity": {
            "South Asian": 0.92,
            "Mixed": 0.04,
            "East Asian": 0.02,
            "SE Asian": 0.01,
            "MENA": 0.01,
        },
        "religion": {
            "Hindu": 0.78,
            "Muslim": 0.14,
            "Christian": 0.03,
            "Folk": 0.03,
            "Buddhist": 0.01,
            "Unaffiliated": 0.01,
        },
    },
    "Brazil": {
        "weight": 0.08,
        "locations": [
            "Sao Paulo, Brazil",
            "Rio de Janeiro, Brazil",
            "Brasilia, Brazil",
            "Salvador, Brazil",
            "Fortaleza, Brazil",
        ],
        "phone_code": "+55",
        "ethnicity": {
            "Latino": 0.52,
            "White": 0.33,
            "Black": 0.08,
            "Mixed": 0.06,
            "Indigenous": 0.01,
        },
        "religion": {
            "Christian": 0.78,
            "Unaffiliated": 0.12,
            "Folk": 0.10,
        },
    },
    "Mexico": {
        "weight": 0.07,
        "locations": [
            "Mexico City, Mexico",
            "Guadalajara, Mexico",
            "Monterrey, Mexico",
            "Puebla, Mexico",
        ],
        "phone_code": "+52",
        "ethnicity": {
            "Latino": 0.78,
            "Indigenous": 0.12,
            "White": 0.05,
            "Mixed": 0.05,
        },
        "religion": {
            "Christian": 0.82,
            "Unaffiliated": 0.10,
            "Folk": 0.08,
        },
    },
    "Nigeria": {
        "weight": 0.07,
        "locations": [
            "Lagos, Nigeria",
            "Abuja, Nigeria",
            "Kano, Nigeria",
            "Ibadan, Nigeria",
            "Port Harcourt, Nigeria",
        ],
        "phone_code": "+234",
        "ethnicity": {
            "Black": 0.94,
            "MENA": 0.02,
            "Mixed": 0.04,
        },
        "religion": {
            "Christian": 0.47,
            "Muslim": 0.47,
            "Folk": 0.05,
            "Unaffiliated": 0.01,
        },
    },
    "Germany": {
        "weight": 0.07,
        "locations": [
            "Berlin, Germany",
            "Munich, Germany",
            "Hamburg, Germany",
            "Frankfurt, Germany",
            "Cologne, Germany",
        ],
        "phone_code": "+49",
        "ethnicity": {
            "White": 0.75,
            "MENA": 0.08,
            "East Asian": 0.03,
            "Black": 0.03,
            "South Asian": 0.03,
            "Mixed": 0.08,
        },
        "religion": {
            "Christian": 0.50,
            "Unaffiliated": 0.38,
            "Muslim": 0.06,
            "Jewish": 0.01,
            "Buddhist": 0.01,
            "Folk": 0.04,
        },
    },
    "Japan": {
        "weight": 0.06,
        "locations": [
            "Tokyo, Japan",
            "Osaka, Japan",
            "Nagoya, Japan",
            "Sapporo, Japan",
            "Fukuoka, Japan",
        ],
        "phone_code": "+81",
        "ethnicity": {
            "East Asian": 0.93,
            "Mixed": 0.045,
            "White": 0.02,
            "Pacific Islander": 0.005,
        },
        "religion": {
            "Folk": 0.48,
            "Buddhist": 0.33,
            "Unaffiliated": 0.18,
            "Christian": 0.01,
        },
    },
    "United Kingdom": {
        "weight": 0.07,
        "locations": [
            "London, United Kingdom",
            "Manchester, United Kingdom",
            "Birmingham, United Kingdom",
            "Glasgow, United Kingdom",
            "Leeds, United Kingdom",
        ],
        "phone_code": "+44",
        "ethnicity": {
            "White": 0.74,
            "South Asian": 0.08,
            "Black": 0.04,
            "East Asian": 0.02,
            "MENA": 0.03,
            "Mixed": 0.09,
        },
        "religion": {
            "Christian": 0.46,
            "Unaffiliated": 0.38,
            "Muslim": 0.06,
            "Hindu": 0.02,
            "Folk": 0.06,
            "Jewish": 0.01,
            "Buddhist": 0.01,
        },
    },
    "Canada": {
        "weight": 0.07,
        "locations": [
            "Toronto, Canada",
            "Vancouver, Canada",
            "Montreal, Canada",
            "Calgary, Canada",
            "Ottawa, Canada",
        ],
        "phone_code": "+1",
        "ethnicity": {
            "White": 0.62,
            "South Asian": 0.08,
            "East Asian": 0.08,
            "Black": 0.04,
            "Indigenous": 0.05,
            "MENA": 0.03,
            "Pacific Islander": 0.005,
            "Mixed": 0.095,
        },
        "religion": {
            "Christian": 0.53,
            "Unaffiliated": 0.34,
            "Muslim": 0.04,
            "Hindu": 0.02,
            "Folk": 0.05,
            "Jewish": 0.01,
            "Buddhist": 0.01,
        },
    },
}

COUNTRY_PHONE_CODES = {
    "United States": "+1",
    "Canada": "+1",
    "Mexico": "+52",
    "Brazil": "+55",
    "Colombia": "+57",
    "United Kingdom": "+44",
    "Germany": "+49",
    "France": "+33",
    "Poland": "+48",
    "China": "+86",
    "Japan": "+81",
    "South Korea": "+82",
    "Indonesia": "+62",
    "Philippines": "+63",
    "Vietnam": "+84",
    "India": "+91",
    "Pakistan": "+92",
    "Bangladesh": "+880",
    "Egypt": "+20",
    "Turkey": "+90",
    "Iran": "+98",
    "Nigeria": "+234",
    "Ethiopia": "+251",
    "South Africa": "+27",
    "Kenya": "+254",
    "Australia": "+61",
}

CITY_CATALOG_PATH = PROJECT_ROOT / "data/catalogs/wup2025_cities_2025.json"

if CITY_CATALOG_PATH.exists():
    with open(CITY_CATALOG_PATH, "r", encoding="utf-8") as city_catalog_handle:
        _city_catalog = json.load(city_catalog_handle)["countries"]
    COUNTRY_PROFILES = {
        country: {
            "locations": [
                f"{city['name']}, {country}" for city in _city_catalog[country]
            ],
            "cities": {
                f"{city['name']}, {country}": city for city in _city_catalog[country]
            },
            "phone_code": phone_code,
        }
        for country, phone_code in COUNTRY_PHONE_CODES.items()
    }

NATIONAL_PHONE_LENGTH_OPTIONS = {
    "United States": {10},
    "China": {10, 11},
    "India": {10},
    "Brazil": {10, 11},
    "Mexico": {10},
    "Nigeria": {10},
    "Germany": {10, 11},
    "Japan": {9, 10},
    "United Kingdom": {10},
    "Canada": {10},
    "Colombia": {10},
    "France": {9},
    "Poland": {9},
    "South Korea": {9, 10},
    "Indonesia": {9, 10, 11, 12},
    "Philippines": {10},
    "Vietnam": {9, 10},
    "Pakistan": {10},
    "Bangladesh": {10},
    "Egypt": {10},
    "Turkey": {10},
    "Iran": {10},
    "Ethiopia": {9},
    "South Africa": {9},
    "Kenya": {9},
    "Australia": {9},
}

GOVERNMENT_ID_FORMAT_HINTS = government_id_format_hints()

if set(GOVERNMENT_ID_RULES) != set(COUNTRY_PROFILES):
    missing = sorted(set(COUNTRY_PROFILES) - set(GOVERNMENT_ID_RULES))
    extra = sorted(set(GOVERNMENT_ID_RULES) - set(COUNTRY_PROFILES))
    raise RuntimeError(
        "government-ID registry must exactly cover COUNTRY_PROFILES; "
        f"missing={missing}, extra={extra}"
    )


@dataclass(frozen=True)
class IPFConstraint:
    name: str
    fields: tuple[str, ...]
    targets: dict[str, float]


@dataclass
class GeneratorConfig:
    count: int = 1000
    candidate_count: int | None = None
    target_proposal_ratio: float = 0.9
    seed: int = 42
    model: str | None = None
    base_url: str | None = None
    api_key: str | None = None
    temperature: float = 1.0
    batch_size: int = 25
    audit_batch_size: int = 50
    completion_batch_size: int = 25
    llm_workers: int = 50
    llm_timeout: float = 120.0
    llm_requests_per_minute: int = 0
    show_progress: bool = False
    llm_retries: int = 2
    pii_field_retries: int = 3
    max_backfill_rounds: int = 3
    sample_trials: int = 50
    ipf_iterations: int = 500
    ipf_min_iterations: int = 0
    ipf_tolerance: float = 0.05
    skip_ipf: bool = False
    require_full_skeleton_ipf: bool = False
    checkpoint_dir: Path | None = None
    resume: bool = False


def normalize(weights: dict[str, float]) -> dict[str, float]:
    total = sum(max(0.0, weight) for weight in weights.values())
    if total <= 0:
        equal = 1.0 / max(1, len(weights))
        return {key: equal for key in weights}
    return {key: max(0.0, value) / total for key, value in weights.items()}


def bounded(value: float, lower: float, upper: float) -> float:
    return max(lower, min(upper, value))


def age_group(age: int) -> str:
    for label, low, high in AGE_GROUPS:
        if low <= age <= high:
            return label
    return "65-80" if age > 80 else "18-24"


def age_stage(age: int) -> str:
    return "youth" if age <= 24 else "adult"


def make_key(values: Iterable[Any]) -> str:
    return " | ".join(str(value) for value in values)


def country_from_location(location: str) -> str:
    if "," in location:
        return location.rsplit(",", 1)[1].strip()
    return location.strip()


def city_size_from_location(location: str) -> str:
    country = country_from_location(location)
    profile = COUNTRY_PROFILES.get(country, {})
    city = profile.get("cities", {}).get(location)
    return "" if city is None else str(city["size_class"])


def bucket_value(candidate: dict[str, Any], field: str) -> str:
    if field == "age_group":
        return age_group(int(candidate["age"]))
    if field == "age_stage":
        return age_stage(int(candidate["age"]))
    if field == "current_country":
        return candidate.get("_current_country") or country_from_location(
            candidate["current_location"]
        )
    if field == "birth_country":
        return candidate.get("_birth_country") or country_from_location(
            candidate["birth_location"]
        )
    if field == "citizenship_country":
        return candidate.get("_citizenship_country") or str(candidate["citizenship"])
    if field == "occupation_group":
        return (
            candidate.get("_occupation_group")
            or OCCUPATION_TO_GROUP[str(candidate["occupation"])]
        )
    if field == "employment_status":
        return "not employed" if str(candidate["occupation"]) == "None" else "employed"
    if field == "ilo_education_group":
        return ILO_EDUCATION_TO_GROUP[str(candidate["education_level"])]
    if field == "welfare_education_group":
        return WELFARE_EDUCATION_TO_GROUP[str(candidate["education_level"])]
    if field == "birth_migration_status":
        return (
            "local"
            if bucket_value(candidate, "birth_country")
            == bucket_value(candidate, "current_country")
            else "foreign"
        )
    if field == "citizenship_migration_status":
        return (
            "local"
            if bucket_value(candidate, "citizenship_country")
            == bucket_value(candidate, "current_country")
            else "foreign"
        )
    if field == "current_city_size":
        return str(
            candidate.get("_current_city_size")
            or city_size_from_location(str(candidate["current_location"]))
        )
    return str(candidate[field])


def candidate_key(candidate: dict[str, Any], fields: tuple[str, ...]) -> str:
    return make_key(bucket_value(candidate, field) for field in fields)


def strip_internal_fields(candidate: dict[str, Any]) -> dict[str, Any]:
    return {
        field: candidate[field] for field in FULL_SCHEMA_FIELDS if field in candidate
    }
