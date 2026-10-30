"""Deterministic profile and identifier validation."""

from __future__ import annotations

import re
from typing import Any

from privacy_trace.government_ids import inspect_government_id

from .schema import (
    COMPLETION_FIELDS,
    COUNTRY_PROFILES,
    EDUCATION_LEVELS,
    ETHNICITIES,
    FULL_SCHEMA_FIELDS,
    INCOME_LEVELS,
    MENTAL_CONDITIONS,
    NATIONAL_PHONE_LENGTH_OPTIONS,
    OCCUPATIONS,
    PHYSICAL_CONDITIONS,
    PROFILE_REFERENCE_YEAR,
    RELATIONSHIP_STATUSES,
    RELIGIONS,
    SEXES,
    country_from_location,
)


def normalize_direct_identifier(field: str, value: Any) -> str:
    text = str(value).strip()
    if field == "email":
        return text.lower()
    if field == "phone_number":
        return "".join(character for character in text if character.isdigit())
    if field == "government_id":
        return "".join(character for character in text.upper() if character.isalnum())
    raise ValueError(f"{field!r} is not a direct identifier field.")


def pii_field_issues(profile: dict[str, Any], field: str) -> list[str]:
    if field not in COMPLETION_FIELDS:
        raise ValueError(f"Unsupported PII field: {field}")
    value = profile.get(field)
    if not isinstance(value, str):
        return [f"{field} must be a string"]
    text = value.strip()
    if not text:
        return [f"{field} must be non-empty"]

    if field == "name":
        return ["name must be at most 120 characters"] if len(text) > 120 else []

    if field == "email":
        issues = []
        if len(text) > 254 or not re.fullmatch(
            r"[A-Za-z0-9!#$%&'*+/=?^_`{|}~-]+"
            r"(?:\.[A-Za-z0-9!#$%&'*+/=?^_`{|}~-]+)*"
            r"@example\.(?:com|org|net)",
            text,
            flags=re.IGNORECASE,
        ):
            issues.append("email must be syntactically valid")
        if not text.lower().endswith(("@example.com", "@example.org", "@example.net")):
            issues.append("email must use a reserved example domain")
        return issues

    if field == "phone_number":
        issues = []
        phone_digits = "".join(character for character in text if character.isdigit())
        if not re.fullmatch(r"\+[0-9 ()-]+", text) or not 8 <= len(phone_digits) <= 15:
            issues.append("phone must use a plausible international format")
        citizenship = str(profile.get("citizenship", ""))
        current_country = country_from_location(
            str(profile.get("current_location", ""))
        )
        plausible_phone_countries = {
            country
            for country in {citizenship, current_country}
            if country in COUNTRY_PROFILES
        }
        phone_matches_country = False
        for country in plausible_phone_countries:
            calling_digits = "".join(
                character
                for character in COUNTRY_PROFILES[country]["phone_code"]
                if character.isdigit()
            )
            if not phone_digits.startswith(calling_digits):
                continue
            national_length = len(phone_digits) - len(calling_digits)
            if national_length in NATIONAL_PHONE_LENGTH_OPTIONS[country]:
                phone_matches_country = True
                break
        if plausible_phone_countries and not phone_matches_country:
            issues.append(
                "phone country code must match citizenship or current location"
            )
        return issues

    if len(text) > 64:
        return ["government_id must be at most 64 characters"]
    return government_id_consistency_issues(profile)


def check_profile(profile: dict[str, Any]) -> list[str]:
    issues = []
    missing = [field for field in FULL_SCHEMA_FIELDS if field not in profile]
    if missing:
        issues.append(f"missing fields: {', '.join(missing)}")
        return issues

    age = profile["age"]
    if not isinstance(age, int) or not 18 <= age <= 80:
        issues.append("age must be an integer between 18 and 80")
        return issues

    enum_checks = {
        "sex": SEXES,
        "ethnicity": ETHNICITIES,
        "education_level": EDUCATION_LEVELS,
        "income_level": INCOME_LEVELS,
        "relationship_status": RELATIONSHIP_STATUSES,
        "religious_belief": RELIGIONS,
        "occupation": OCCUPATIONS,
        "physical_condition": PHYSICAL_CONDITIONS,
        "mental_condition": MENTAL_CONDITIONS,
    }
    for field, allowed_values in enum_checks.items():
        if profile[field] not in allowed_values:
            issues.append(f"{field} must be one of: {', '.join(allowed_values)}")

    if profile["citizenship"] not in COUNTRY_PROFILES:
        issues.append("citizenship must be in the configured country universe")
    if country_from_location(str(profile["current_location"])) not in COUNTRY_PROFILES:
        issues.append("current_location must use a configured country")
    if country_from_location(str(profile["birth_location"])) not in COUNTRY_PROFILES:
        issues.append("birth_location must use a configured country")

    for field, max_length in {
        "occupation": 80,
        "physical_condition": 80,
        "mental_condition": 80,
    }.items():
        value = str(profile[field]).strip()
        if not value:
            issues.append(f"{field} must be non-empty")
        elif len(value) > max_length:
            issues.append(f"{field} must be at most {max_length} characters")

    for field in COMPLETION_FIELDS:
        issues.extend(pii_field_issues(profile, field))
    return issues


def government_id_consistency_issues(profile: dict[str, Any]) -> list[str]:
    age = int(profile["age"])
    inspection = inspect_government_id(
        country=str(profile["citizenship"]),
        raw_value=str(profile["government_id"]),
        possible_birth_years=(
            PROFILE_REFERENCE_YEAR - age - 1,
            PROFILE_REFERENCE_YEAR - age,
        ),
        expected_sex=str(profile["sex"]),
    )
    return list(inspection.issues)


def government_id_prompt_evidence(profile: dict[str, Any]) -> dict[str, Any]:
    """Return the same deterministic evidence used by validation for the LLM."""

    age = int(profile["age"])
    inspection = inspect_government_id(
        country=str(profile["citizenship"]),
        raw_value=str(profile["government_id"]),
        possible_birth_years=(
            PROFILE_REFERENCE_YEAR - age - 1,
            PROFILE_REFERENCE_YEAR - age,
        ),
        expected_sex=str(profile["sex"]),
    )
    return inspection.as_prompt_dict()
