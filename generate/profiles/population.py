"""Candidate generation, IPF calibration, and sampling."""

from __future__ import annotations

import copy
import math
import random
import re
from collections import defaultdict
from typing import Any

from .schema import (
    AGE_GROUPS,
    COUNTRY_PROFILES,
    EDUCATION_LEVELS,
    ETHNICITIES,
    ILO_EDUCATION_GROUP_TO_OPTIONS,
    INCOME_LEVELS,
    MENTAL_CONDITIONS,
    OCCUPATION_GROUP_TO_OPTIONS,
    OCCUPATION_TO_GROUP,
    OCCUPATIONS,
    PHYSICAL_CONDITIONS,
    RELATIONSHIP_STATUSES,
    RELIGIONS,
    SEXES,
    SKELETON_FIELDS,
    WELFARE_EDUCATION_GROUP_TO_OPTIONS,
    WELFARE_EDUCATION_TO_GROUP,
    GeneratorConfig,
    IPFConstraint,
    bounded,
    candidate_key,
    city_size_from_location,
    country_from_location,
)
from .targets import (
    distribution_l1,
    weighted_distribution,
)


class ProfilePopulation:
    """Candidate proposals, population calibration, and weighted sampling."""

    def __init__(
        self, config: GeneratorConfig, targets: list[IPFConstraint], rng: random.Random
    ) -> None:
        self.config = config
        self.targets = targets
        self.rng = rng
        self._candidate_serial = 0
        self._seen_seed_keys: set[tuple[Any, ...]] = set()
        self._uniform_seed_count = 0
        self._target_proposal_seed_count = 0
        self._targeted_backfill_seed_count = 0
        self._proposal_constraints = {
            constraint.fields: constraint for constraint in self.targets
        }
        self._proposal_options_cache: dict[
            tuple[tuple[str, ...], tuple[str, ...]],
            tuple[list[tuple[str, ...]], list[float]],
        ] = {}
        self._proposal_fused_options_cache: dict[
            tuple[
                tuple[tuple[tuple[str, ...], tuple[str, ...]], ...],
                tuple[str, ...],
            ],
            tuple[list[str], list[float]],
        ] = {}
        self._target_proposal_available = self._has_target_proposal_constraints()

    def generate_candidates(self, count: int) -> list[dict[str, Any]]:
        candidates: list[dict[str, Any]] = []
        attempts = 0
        max_attempts = max(100, count * 100)
        while len(candidates) < count and attempts < max_attempts:
            attempts += 1
            use_target_proposal = (
                self._target_proposal_available
                and self.config.target_proposal_ratio > 0
                and self.rng.random() < self.config.target_proposal_ratio
            )
            candidate = (
                self._generate_target_proposal_seed()
                if use_target_proposal
                else self._generate_uniform_seed()
            )
            key = self._skeleton_key(candidate)
            if key in self._seen_seed_keys:
                continue
            self._seen_seed_keys.add(key)
            candidate["_candidate_id"] = self._next_candidate_id()
            candidates.append(candidate)
            if use_target_proposal:
                self._target_proposal_seed_count += 1
            else:
                self._uniform_seed_count += 1

        if len(candidates) != count:
            raise RuntimeError(
                f"Could generate only {len(candidates)}/{count} unique seeds."
            )
        return candidates

    def register_existing_candidate_state(
        self, candidates: list[dict[str, Any]]
    ) -> None:
        """Reserve skeletons and IDs before extending a persisted pool.

        Migration and recovery jobs may need to generate targeted backfill for
        an already completed candidate pool.  Registering the persisted state
        prevents a new backfill seed from reusing either an existing skeleton
        or a stable ``cand_XXXXXXXX`` identifier.
        """

        max_serial = self._candidate_serial
        seen_ids: set[str] = set()
        for candidate in candidates:
            self._seen_seed_keys.add(self._skeleton_key(candidate))
            candidate_id = candidate.get("_candidate_id")
            if not isinstance(candidate_id, str) or not candidate_id:
                raise ValueError(
                    "Every registered candidate must have a non-empty _candidate_id"
                )
            if candidate_id in seen_ids:
                raise ValueError(f"Duplicate registered candidate ID: {candidate_id}")
            seen_ids.add(candidate_id)
            match = re.fullmatch(r"cand_(\d{8})", candidate_id)
            if match is None:
                raise ValueError(
                    "Registered candidate IDs must use the cand_XXXXXXXX format: "
                    f"{candidate_id}"
                )
            max_serial = max(max_serial, int(match.group(1)) + 1)
        self._candidate_serial = max_serial

    def _has_target_proposal_constraints(self) -> bool:
        required = {
            ("current_country",),
            ("current_country", "current_city_size"),
            (
                "current_country",
                "age_group",
                "sex",
                "relationship_status",
            ),
            (
                "current_country",
                "relationship_status",
                "employment_status",
            ),
            ("current_country", "education_level"),
            ("current_country", "religious_belief"),
            ("current_country", "citizenship_country"),
            ("current_country", "birth_country"),
            ("current_country", "ethnicity"),
            (
                "current_country",
                "age_group",
                "sex",
                "ilo_education_group",
            ),
            (
                "current_country",
                "welfare_education_group",
                "income_level",
            ),
            (
                "current_country",
                "age_stage",
                "income_level",
            ),
            (
                "current_country",
                "age_group",
                "sex",
                "employment_status",
            ),
            (
                "current_country",
                "age_stage",
                "sex",
                "occupation_group",
            ),
            (
                "current_country",
                "sex",
                "birth_migration_status",
            ),
            (
                "current_country",
                "sex",
                "citizenship_migration_status",
            ),
            ("current_country", "sex", "occupation_group"),
            (
                "current_country",
                "age_group",
                "sex",
                "physical_condition",
            ),
            (
                "current_country",
                "age_group",
                "sex",
                "mental_condition",
            ),
        }
        return required <= set(self._proposal_constraints)

    def _draw_target_values(
        self, fields: tuple[str, ...], prefix: tuple[str, ...] = ()
    ) -> tuple[str, ...]:
        cache_key = (fields, prefix)
        cached = self._proposal_options_cache.get(cache_key)
        if cached is not None:
            options, weights = cached
            return self.rng.choices(options, weights=weights, k=1)[0]
        constraint = self._proposal_constraints[fields]
        options: list[tuple[str, ...]] = []
        weights: list[float] = []
        for key, target in constraint.targets.items():
            values = tuple(key.split(" | "))
            if target > 0 and values[: len(prefix)] == prefix:
                options.append(values[len(prefix) :])
                weights.append(target)
        if not options:
            raise RuntimeError(
                f"No positive target proposal values for fields={fields}, prefix={prefix}."
            )
        self._proposal_options_cache[cache_key] = (options, weights)
        return self.rng.choices(options, weights=weights, k=1)[0]

    def _draw_target_row(
        self,
        fields: tuple[str, ...],
        fixed_values: dict[str, str],
    ) -> tuple[str, ...]:
        """Draw a complete target row subject to named fixed dimensions."""

        options: list[tuple[str, ...]] = []
        weights: list[float] = []
        for key, target in self._proposal_constraints[fields].targets.items():
            values = tuple(key.split(" | "))
            if target <= 0:
                continue
            if any(
                field in fixed_values and fixed_values[field] != value
                for field, value in zip(fields, values)
            ):
                continue
            options.append(values)
            weights.append(target)
        if not options:
            raise RuntimeError(
                f"No positive target rows for fields={fields}, "
                f"fixed_values={fixed_values}."
            )
        return self.rng.choices(options, weights=weights, k=1)[0]

    def _draw_filtered_target_value(
        self,
        fields: tuple[str, ...],
        prefix: tuple[str, ...],
        *,
        allowed: set[str],
    ) -> str:
        constraint = self._proposal_constraints[fields]
        options: list[str] = []
        weights: list[float] = []
        for key, target in constraint.targets.items():
            values = tuple(key.split(" | "))
            if target > 0 and values[: len(prefix)] == prefix and values[-1] in allowed:
                options.append(values[-1])
                weights.append(target)
        if not options:
            raise RuntimeError(
                f"No filtered target proposal values for fields={fields}, "
                f"prefix={prefix}, allowed={sorted(allowed)}."
            )
        return self.rng.choices(options, weights=weights, k=1)[0]

    def _draw_fused_target_value(
        self,
        conditionals: list[tuple[tuple[str, ...], tuple[str, ...]]],
        *,
        allowed: set[str],
    ) -> str:
        """Fuse overlapping target conditionals with a geometric mean."""

        cache_key = (tuple(conditionals), tuple(sorted(allowed)))
        cached = self._proposal_fused_options_cache.get(cache_key)
        if cached is not None:
            options, weights = cached
            return self.rng.choices(options, weights=weights, k=1)[0]
        # Never let Python's process-randomized set order affect a fixed-seed
        # run. Checkpoint resume depends on regenerating byte-identical prompts.
        combined = {option: 1.0 for option in sorted(allowed)}
        for fields, prefix in conditionals:
            local: dict[str, float] = defaultdict(float)
            for key, target in self._proposal_constraints[fields].targets.items():
                values = tuple(key.split(" | "))
                if target > 0 and values[: len(prefix)] == prefix:
                    local[values[-1]] += target
            for option in combined:
                combined[option] *= max(0.0, local.get(option, 0.0))
        options = [option for option, weight in combined.items() if weight > 0]
        if not options:
            raise RuntimeError(
                "Overlapping target proposal conditionals have no common "
                f"positive support: {conditionals}."
            )
        exponent = 1.0 / len(conditionals)
        weights = [combined[option] ** exponent for option in options]
        self._proposal_fused_options_cache[cache_key] = (options, weights)
        return self.rng.choices(options, weights=weights, k=1)[0]

    def _choose_location(
        self,
        country: str,
        *,
        size_class: str | None = None,
        population_weighted: bool = False,
    ) -> str:
        profile = COUNTRY_PROFILES[country]
        locations = list(profile["locations"])
        cities = profile.get("cities", {})
        if size_class is not None:
            locations = [
                location
                for location in locations
                if cities.get(location, {}).get("size_class") == size_class
            ]
        if not locations:
            raise RuntimeError(
                f"No city candidates for {country} and size_class={size_class!r}."
            )
        if population_weighted and cities:
            weights = [
                float(cities[location]["population_2025"]) for location in locations
            ]
            return self.rng.choices(locations, weights=weights, k=1)[0]
        return self.rng.choice(locations)

    def _generate_target_proposal_seed(
        self,
        fixed_values: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        """Draw a coherent random seed from target-table conditionals.

        This is a proposal distribution, not an additional plausibility rule.
        IPF still performs the final calibration after LLM rejection/completion.
        """

        fixed_values = fixed_values or {}
        demographic_fields = (
            "current_country",
            "age_group",
            "sex",
            "relationship_status",
        )
        demographic_values = (
            self._draw_target_row(demographic_fields, fixed_values)
            if any(field in fixed_values for field in demographic_fields)
            else self._draw_target_values(demographic_fields)
        )
        current_country, age_band, sex, relationship = demographic_values
        current_city_size = self._draw_target_values(
            ("current_country", "current_city_size"), (current_country,)
        )[0]
        birth_status = self._draw_target_values(
            (
                "current_country",
                "sex",
                "birth_migration_status",
            ),
            (current_country, sex),
        )[0]
        birth_country = (
            current_country
            if birth_status == "local"
            else self._draw_filtered_target_value(
                ("current_country", "birth_country"),
                (current_country,),
                allowed=set(COUNTRY_PROFILES) - {current_country},
            )
        )
        citizenship_status = self._draw_target_values(
            (
                "current_country",
                "sex",
                "citizenship_migration_status",
            ),
            (current_country, sex),
        )[0]
        citizenship_country = (
            current_country
            if citizenship_status == "local"
            else self._draw_filtered_target_value(
                ("current_country", "citizenship_country"),
                (current_country,),
                allowed=set(COUNTRY_PROFILES) - {current_country},
            )
        )
        ilo_education_group = self._draw_target_values(
            (
                "current_country",
                "age_group",
                "sex",
                "ilo_education_group",
            ),
            (current_country, age_band, sex),
        )[0]
        education = self._draw_filtered_target_value(
            ("current_country", "education_level"),
            (current_country,),
            allowed=set(ILO_EDUCATION_GROUP_TO_OPTIONS[ilo_education_group]),
        )
        religion = self._draw_target_values(
            ("current_country", "religious_belief"), (current_country,)
        )[0]
        stage = "youth" if age_band == "18-24" else "adult"
        income = self._draw_fused_target_value(
            [
                (
                    (
                        "current_country",
                        "welfare_education_group",
                        "income_level",
                    ),
                    (
                        current_country,
                        WELFARE_EDUCATION_TO_GROUP[education],
                    ),
                ),
                (
                    (
                        "current_country",
                        "age_stage",
                        "income_level",
                    ),
                    (current_country, stage),
                ),
            ],
            allowed=set(INCOME_LEVELS),
        )
        ethnicity = self._draw_target_values(
            ("current_country", "ethnicity"), (current_country,)
        )[0]
        employment_status = self._draw_fused_target_value(
            [
                (
                    (
                        "current_country",
                        "age_group",
                        "sex",
                        "employment_status",
                    ),
                    (current_country, age_band, sex),
                ),
                (
                    (
                        "current_country",
                        "relationship_status",
                        "employment_status",
                    ),
                    (current_country, relationship),
                ),
            ],
            allowed={"employed", "not employed"},
        )
        occupation_group = (
            "None"
            if employment_status == "not employed"
            else self._draw_filtered_target_value(
                (
                    "current_country",
                    "age_stage",
                    "sex",
                    "occupation_group",
                ),
                (current_country, stage, sex),
                allowed=set(OCCUPATION_GROUP_TO_OPTIONS) - {"None"},
            )
        )
        occupation = self.rng.choice(OCCUPATION_GROUP_TO_OPTIONS[occupation_group])
        physical_condition = self._draw_target_values(
            (
                "current_country",
                "age_group",
                "sex",
                "physical_condition",
            ),
            (current_country, age_band, sex),
        )[0]
        mental_condition = self._draw_target_values(
            (
                "current_country",
                "age_group",
                "sex",
                "mental_condition",
            ),
            (current_country, age_band, sex),
        )[0]
        physical_condition = fixed_values.get("physical_condition", physical_condition)
        mental_condition = fixed_values.get("mental_condition", mental_condition)
        bounds = {label: (low, high) for label, low, high in AGE_GROUPS}
        age_low, age_high = bounds[age_band]

        for country in (current_country, birth_country, citizenship_country):
            if country not in COUNTRY_PROFILES:
                raise RuntimeError(
                    f"Target proposal country {country!r} has no location/identifier catalog entry."
                )

        return {
            "age": self.rng.randint(age_low, age_high),
            "sex": sex,
            "ethnicity": ethnicity,
            "citizenship": citizenship_country,
            "current_location": self._choose_location(
                current_country,
                size_class=current_city_size,
                population_weighted=True,
            ),
            "birth_location": self._choose_location(
                birth_country,
                population_weighted=True,
            ),
            "education_level": education,
            "income_level": income,
            "relationship_status": relationship,
            "religious_belief": religion,
            "occupation": occupation,
            "physical_condition": physical_condition,
            "mental_condition": mental_condition,
            "_citizenship_country": citizenship_country,
            "_current_country": current_country,
            "_current_city_size": current_city_size,
            "_birth_country": birth_country,
            "_occupation_group": occupation_group,
        }

    def _generate_uniform_seed(self) -> dict[str, Any]:
        countries = list(COUNTRY_PROFILES)
        current_country = self.rng.choice(countries)
        birth_country = self.rng.choice(countries)
        citizenship_country = self.rng.choice(countries)
        occupation = self.rng.choice(OCCUPATIONS)
        physical_condition = self.rng.choice(PHYSICAL_CONDITIONS)
        mental_condition = self.rng.choice(MENTAL_CONDITIONS)
        current_location = self._choose_location(current_country)
        return {
            "age": self.rng.randint(18, 80),
            "sex": self.rng.choice(SEXES),
            "ethnicity": self.rng.choice(ETHNICITIES),
            "citizenship": citizenship_country,
            "current_location": current_location,
            "birth_location": self._choose_location(birth_country),
            "education_level": self.rng.choice(EDUCATION_LEVELS),
            "income_level": self.rng.choice(INCOME_LEVELS),
            "relationship_status": self.rng.choice(RELATIONSHIP_STATUSES),
            "religious_belief": self.rng.choice(RELIGIONS),
            "occupation": occupation,
            "physical_condition": physical_condition,
            "mental_condition": mental_condition,
            "_citizenship_country": citizenship_country,
            "_current_country": current_country,
            "_current_city_size": city_size_from_location(current_location),
            "_birth_country": birth_country,
            "_occupation_group": OCCUPATION_TO_GROUP[occupation],
        }

    def _next_candidate_id(self) -> str:
        value = f"cand_{self._candidate_serial:08d}"
        self._candidate_serial += 1
        return value

    @staticmethod
    def _skeleton_key(candidate: dict[str, Any]) -> tuple[Any, ...]:
        return tuple(candidate[field] for field in SKELETON_FIELDS)

    def find_missing_target_cells(
        self, candidates: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        missing = []
        for constraint in self.targets:
            present = {
                candidate_key(candidate, constraint.fields) for candidate in candidates
            }
            for key, target in constraint.targets.items():
                if target > 0 and key not in present:
                    values = key.split(" | ")
                    missing.append(
                        {
                            "constraint": constraint.name,
                            "fields": constraint.fields,
                            "key": key,
                            "values": values,
                        }
                    )
        return missing

    def find_target_capacity_deficits(
        self, candidates: list[dict[str, Any]], output_count: int
    ) -> list[dict[str, Any]]:
        """Find marginal cells that cannot supply a unique calibrated sample.

        This inexpensive check is necessary but not sufficient: overlapping
        constraints can still make the joint support infeasible, which is why
        IPF convergence and ideal-inclusion diagnostics are checked later.
        """

        deficits = []
        for constraint in self.targets:
            counts: dict[str, int] = defaultdict(int)
            for candidate in candidates:
                counts[candidate_key(candidate, constraint.fields)] += 1
            for key, target in constraint.targets.items():
                if target <= 0:
                    continue
                required = max(
                    1,
                    math.ceil(output_count * target - 1e-12),
                )
                available = counts.get(key, 0)
                if available < required:
                    deficits.append(
                        {
                            "constraint": constraint.name,
                            "fields": constraint.fields,
                            "key": key,
                            "available": available,
                            "required": required,
                        }
                    )
        return deficits

    def generate_capacity_backfill_candidates(
        self, deficits: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        candidates = []
        for cell in deficits:
            values = str(cell["key"]).split(" | ")
            for _ in range(int(cell["required"]) - int(cell["available"])):
                candidates.append(
                    self._generate_targeted_candidate(tuple(cell["fields"]), values)
                )
                self._targeted_backfill_seed_count += 1
        return candidates

    def generate_targeted_candidates(
        self, missing_cells: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        candidates = []
        for cell in missing_cells:
            candidate = self._generate_targeted_candidate(
                cell["fields"], cell["values"]
            )
            candidates.append(candidate)
            self._targeted_backfill_seed_count += 1
        return candidates

    def _generate_targeted_candidate(
        self, fields: tuple[str, ...], values: list[str]
    ) -> dict[str, Any]:
        if len(fields) != len(values):
            raise ValueError(f"Invalid target cell: {fields} -> {values}")
        fixed_values = dict(zip(fields, values))
        for _ in range(500):
            candidate = (
                self._generate_target_proposal_seed(fixed_values)
                if self._target_proposal_available
                else self._generate_uniform_seed()
            )
            try:
                for field, value in zip(fields, values):
                    self._force_bucket_value(candidate, field, value)
            except ValueError:
                raise
            key = self._skeleton_key(candidate)
            if key in self._seen_seed_keys:
                continue
            self._seen_seed_keys.add(key)
            candidate["_candidate_id"] = self._next_candidate_id()
            return candidate
        raise RuntimeError(f"Could not generate a unique seed for {fields}={values}")

    def _force_bucket_value(
        self, candidate: dict[str, Any], field: str, value: str
    ) -> None:
        if field == "age_group":
            bounds = {label: (low, high) for label, low, high in AGE_GROUPS}
            if value not in bounds:
                raise ValueError(f"Unsupported age group: {value}")
            low, high = bounds[value]
            candidate["age"] = self.rng.randint(low, high)
            return
        if field == "current_country":
            if value not in COUNTRY_PROFILES:
                raise ValueError(f"Unsupported current country: {value}")
            candidate["_current_country"] = value
            candidate["current_location"] = self._choose_location(value)
            candidate["_current_city_size"] = city_size_from_location(
                candidate["current_location"]
            )
            return
        if field == "birth_country":
            if value not in COUNTRY_PROFILES:
                raise ValueError(f"Unsupported birth country: {value}")
            candidate["_birth_country"] = value
            candidate["birth_location"] = self._choose_location(value)
            return
        if field == "citizenship_country":
            if value not in COUNTRY_PROFILES:
                raise ValueError(f"Unsupported citizenship country: {value}")
            candidate["_citizenship_country"] = value
            candidate["citizenship"] = value
            return
        if field == "citizenship":
            if value not in COUNTRY_PROFILES:
                raise ValueError(f"Unsupported citizenship: {value}")
            candidate["_citizenship_country"] = value
            candidate["citizenship"] = value
            return
        if field == "current_location":
            country = country_from_location(value)
            if country not in COUNTRY_PROFILES:
                raise ValueError(f"Unsupported current location: {value}")
            candidate["_current_country"] = country
            candidate["current_location"] = value
            candidate["_current_city_size"] = city_size_from_location(value)
            return
        if field == "birth_location":
            country = country_from_location(value)
            if country not in COUNTRY_PROFILES:
                raise ValueError(f"Unsupported birth location: {value}")
            candidate["_birth_country"] = country
            candidate["birth_location"] = value
            return
        if field == "age":
            candidate["age"] = int(value)
            return
        if field == "age_stage":
            if value == "youth":
                candidate["age"] = self.rng.randint(18, 24)
                return
            if value == "adult":
                candidate["age"] = self.rng.randint(25, 80)
                return
            raise ValueError(f"Unsupported age stage: {value}")
        if field == "current_city_size":
            country = str(candidate["_current_country"])
            candidate["_current_city_size"] = value
            candidate["current_location"] = self._choose_location(
                country,
                size_class=value,
                population_weighted=True,
            )
            return
        if field == "ilo_education_group":
            if value not in ILO_EDUCATION_GROUP_TO_OPTIONS:
                raise ValueError(f"Unsupported ILO education group: {value}")
            candidate["education_level"] = self.rng.choice(
                ILO_EDUCATION_GROUP_TO_OPTIONS[value]
            )
            return
        if field == "welfare_education_group":
            if value not in WELFARE_EDUCATION_GROUP_TO_OPTIONS:
                raise ValueError(f"Unsupported welfare education group: {value}")
            candidate["education_level"] = self.rng.choice(
                WELFARE_EDUCATION_GROUP_TO_OPTIONS[value]
            )
            return
        if field == "employment_status":
            if value == "not employed":
                candidate["occupation"] = "None"
                candidate["_occupation_group"] = "None"
                return
            if value == "employed":
                group = self.rng.choice(
                    [group for group in OCCUPATION_GROUP_TO_OPTIONS if group != "None"]
                )
                candidate["_occupation_group"] = group
                candidate["occupation"] = self.rng.choice(
                    OCCUPATION_GROUP_TO_OPTIONS[group]
                )
                return
            raise ValueError(f"Unsupported employment status: {value}")
        if field in {
            "birth_migration_status",
            "citizenship_migration_status",
        }:
            if value not in {"local", "foreign"}:
                raise ValueError(f"Unsupported migration status: {value}")
            current_country = str(candidate["_current_country"])
            country = (
                current_country
                if value == "local"
                else self.rng.choice(
                    [option for option in COUNTRY_PROFILES if option != current_country]
                )
            )
            if field == "birth_migration_status":
                candidate["_birth_country"] = country
                candidate["birth_location"] = self._choose_location(country)
            else:
                candidate["_citizenship_country"] = country
                candidate["citizenship"] = country
            return
        if field == "occupation_group":
            if value not in OCCUPATION_GROUP_TO_OPTIONS:
                raise ValueError(f"Unsupported occupation group: {value}")
            candidate["_occupation_group"] = value
            candidate["occupation"] = self.rng.choice(
                OCCUPATION_GROUP_TO_OPTIONS[value]
            )
            return
        if field in SKELETON_FIELDS:
            candidate[field] = value
            if field == "occupation":
                candidate["_occupation_group"] = OCCUPATION_TO_GROUP[value]
            return
        raise ValueError(f"Unsupported IPF field for targeted generation: {field}")

    def apply_ipf(self, candidates: list[dict[str, Any]]) -> dict[str, Any]:
        missing = self.find_missing_target_cells(candidates)
        if missing:
            preview = ", ".join(
                f"{cell['constraint']}:{cell['key']}" for cell in missing[:10]
            )
            raise RuntimeError(
                f"Cannot run IPF with unsupported positive target cells: {preview}"
            )
        weights = [1.0 for _ in candidates]
        constraint_keys = [
            [candidate_key(candidate, constraint.fields) for candidate in candidates]
            for constraint in self.targets
        ]

        def distribution_from_keys(
            keys: list[str], current_weights: list[float]
        ) -> dict[str, float]:
            totals: dict[str, float] = defaultdict(float)
            for key, weight in zip(keys, current_weights):
                totals[key] += weight
            total = sum(totals.values())
            if total <= 0:
                return dict(totals)
            return {key: value / total for key, value in totals.items()}

        diagnostics = []

        for iteration in range(self.config.ipf_iterations):
            for constraint, keys in zip(self.targets, constraint_keys):
                current = distribution_from_keys(keys, weights)
                factors = {
                    key: (
                        0.0
                        if constraint.targets.get(key, 0.0) <= 0
                        else bounded(
                            constraint.targets[key] / current_value,
                            0.05,
                            20.0,
                        )
                    )
                    for key, current_value in current.items()
                    if current_value > 0
                }
                weights = [
                    weight * factors.get(key, 0.0) for key, weight in zip(keys, weights)
                ]

                total = sum(weights)
                if total > 0:
                    scale = len(weights) / total
                    weights = [weight * scale for weight in weights]

            max_l1 = 0.0
            for constraint, keys in zip(self.targets, constraint_keys):
                distance = distribution_l1(
                    distribution_from_keys(keys, weights),
                    constraint.targets,
                )
                max_l1 = max(max_l1, distance)
            diagnostics.append({"iteration": iteration + 1, "max_l1": round(max_l1, 6)})
            if (
                iteration + 1 >= self.config.ipf_min_iterations
                and max_l1 <= self.config.ipf_tolerance
            ):
                break

        for candidate, weight in zip(candidates, weights):
            candidate["_weight"] = max(weight, 0.0)

        final_distances = {
            constraint.name: round(
                distribution_l1(
                    distribution_from_keys(keys, weights),
                    constraint.targets,
                ),
                6,
            )
            for constraint, keys in zip(self.targets, constraint_keys)
        }
        total = sum(weights)
        squared = sum(weight * weight for weight in weights)
        effective_sample_size = (total * total / squared) if squared > 0 else 0.0
        return {
            "iterations": len(diagnostics),
            "converged": bool(
                diagnostics and diagnostics[-1]["max_l1"] <= self.config.ipf_tolerance
            ),
            "diagnostics": diagnostics,
            "final_l1": final_distances,
            "weight_summary": {
                "min": round(min(weights), 8) if weights else 0.0,
                "max": round(max(weights), 8) if weights else 0.0,
                "effective_sample_size": round(effective_sample_size, 4),
            },
        }

    @staticmethod
    def unique_selection_diagnostics(
        candidates: list[dict[str, Any]], count: int
    ) -> dict[str, float]:
        """Check whether calibrated mass can fit into a unique sample.

        If profile i represented an ideal inclusion probability, it would be
        count * weight_i / sum(weights). Values above one prove that a unique
        without-replacement sample cannot preserve the calibrated measure.
        """

        weights = [
            max(0.0, float(candidate.get("_weight", 0.0))) for candidate in candidates
        ]
        total = sum(weights)
        maximum = max(weights, default=0.0)
        ideal = (count * maximum / total) if total > 0 else math.inf
        return {
            "max_ideal_inclusion_probability": round(ideal, 6),
            "sampling_fraction": round(count / len(candidates), 6)
            if candidates
            else 0.0,
            "positive_weight_candidates": sum(weight > 0 for weight in weights),
        }

    def sample_profiles(
        self, candidates: list[dict[str, Any]], count: int
    ) -> list[dict[str, Any]]:
        if count > len(candidates):
            raise ValueError(
                f"Cannot sample {count} profiles from {len(candidates)} candidates."
            )
        trials = max(1, self.config.sample_trials)
        best_sample: list[dict[str, Any]] | None = None
        best_error = math.inf
        for _ in range(trials):
            sample = self._weighted_sample_without_replacement(candidates, count)
            error = self._sample_total_l1(sample) if not self.config.skip_ipf else 0.0
            if error < best_error:
                best_error = error
                best_sample = sample
        if best_sample is None:
            raise RuntimeError("Weighted sampling produced no sample.")
        return [copy.deepcopy(candidate) for candidate in best_sample]

    def _weighted_sample_without_replacement(
        self, candidates: list[dict[str, Any]], count: int
    ) -> list[dict[str, Any]]:
        scored = []
        for candidate in candidates:
            weight = max(float(candidate.get("_weight", 0.0)), 0.0)
            if weight == 0:
                continue
            uniform = max(self.rng.random(), 1e-300)
            score = math.log(uniform) / weight
            scored.append((score, candidate))
        if len(scored) < count:
            raise RuntimeError(
                f"Only {len(scored)} candidates have positive calibrated weight; "
                f"{count} unique profiles are required."
            )
        scored.sort(key=lambda item: item[0], reverse=True)
        return [candidate for _, candidate in scored[:count]]

    def _sample_total_l1(self, sample: list[dict[str, Any]]) -> float:
        weights = [1.0] * len(sample)
        return sum(
            distribution_l1(
                weighted_distribution(sample, weights, constraint.fields),
                constraint.targets,
            )
            for constraint in self.targets
        )

    def audit_final_sample(self, profiles: list[dict[str, Any]]) -> dict[str, Any]:
        weights = [1.0] * len(profiles)
        final_l1 = {
            constraint.name: round(
                distribution_l1(
                    weighted_distribution(profiles, weights, constraint.fields),
                    constraint.targets,
                ),
                6,
            )
            for constraint in self.targets
        }
        skeleton_keys = {self._skeleton_key(profile) for profile in profiles}
        return {
            "final_l1": final_l1,
            "max_l1": round(max(final_l1.values()), 6) if final_l1 else 0.0,
            "total_l1": round(sum(final_l1.values()), 6),
            "unique_skeleton_count": len(skeleton_keys),
            "duplicate_skeleton_count": len(profiles) - len(skeleton_keys),
        }
