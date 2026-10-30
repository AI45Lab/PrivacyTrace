"""Profile synthesis workflow coordinating the independent components."""

from __future__ import annotations

import copy
import hashlib
import json
import random
import threading
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from queue import Empty, Queue
from typing import Any, Callable

from agent_env.recovery import FatalProviderError, ProviderHealthExceeded
from privacy_trace.government_ids import repair_government_id

from .checkpoint import (
    ProfileCheckpoint,
)
from .llm import (
    ProfileLLMClient,
    parse_json_output,
)
from .population import (
    ProfilePopulation,
)
from .prompts import (
    build_completion_prompt,
    build_government_id_audit_prompt,
    build_pii_repair_prompt,
    build_seed_audit_prompt,
)
from .schema import (
    COMPLETION_FIELDS,
    DIRECT_IDENTIFIER_FIELDS,
    FULL_SCHEMA_FIELDS,
    GOVERNMENT_ID_LLM_AUDIT_ISSUE_PREFIX,
    GOVERNMENT_ID_LLM_AUDIT_REASON_CODES,
    GOVERNMENT_ID_REPAIR_POLICY_ID,
    LLM_COMPLETION_FIELDS,
    PROFILE_REFERENCE_YEAR,
    SKELETON_FIELDS,
    GeneratorConfig,
    IPFConstraint,
    strip_internal_fields,
)
from .targets import (
    build_default_targets,
    skeleton_ipf_coverage,
    validate_skeleton_ipf_coverage,
)
from .validation import (
    check_profile,
    normalize_direct_identifier,
    pii_field_issues,
)


class SyntheticProfileGenerator:
    """Coordinate profile proposals, LLM completion, and population sampling."""

    def __init__(
        self,
        config: GeneratorConfig | None = None,
        targets: list[IPFConstraint] | None = None,
    ) -> None:
        self.config = config or GeneratorConfig()
        if self.config.count <= 0:
            raise ValueError("count must be positive.")
        if self.config.candidate_count is not None and self.config.candidate_count <= 0:
            raise ValueError("candidate_count must be positive when provided.")
        if not 0.0 <= self.config.target_proposal_ratio <= 1.0:
            raise ValueError("target_proposal_ratio must be between 0 and 1.")
        if self.config.llm_workers < 1:
            raise ValueError("llm_workers must be at least 1.")
        if self.config.llm_timeout <= 0:
            raise ValueError("llm_timeout must be positive.")
        if self.config.llm_requests_per_minute < 0:
            raise ValueError("llm_requests_per_minute must be non-negative.")
        if self.config.pii_field_retries < 0:
            raise ValueError("pii_field_retries must be non-negative.")
        if self.config.ipf_iterations <= 0:
            raise ValueError("ipf_iterations must be positive.")
        if not 0 <= self.config.ipf_min_iterations <= self.config.ipf_iterations:
            raise ValueError("ipf_min_iterations must be between 0 and ipf_iterations.")
        self.targets = build_default_targets() if targets is None else targets
        if not self.config.skip_ipf and self.config.require_full_skeleton_ipf:
            validate_skeleton_ipf_coverage(self.targets)
        self.rng = random.Random(self.config.seed)
        self._pii_field_metrics: dict[str, dict[str, int]] = {
            field: {
                "initial_total": 0,
                "initial_passed": 0,
                "repair_rounds": 0,
                "repair_attempts": 0,
                "repair_attempt_passed": 0,
                "repaired_profiles": 0,
                "transport_failures": 0,
                "transport_exhausted": 0,
                "exhausted": 0,
            }
            for field in COMPLETION_FIELDS
        }
        self._pii_field_metrics["government_id"].update(
            {
                "registry_repair_attempts": 0,
                "registry_repair_changed": 0,
                "registry_repair_passed": 0,
            }
        )
        self._government_id_llm_metrics: dict[str, Any] = {
            "initial_audits": 0,
            "initial_accepted": 0,
            "initial_rejected": 0,
            "repair_audits": 0,
            "repair_accepted": 0,
            "repair_rejected": 0,
            "semantic_exhausted": 0,
            "rejection_reasons": {},
        }
        self._pii_diagnostics: list[dict[str, Any]] = []
        self._seen_direct_identifiers: dict[str, set[str]] = {
            "email": set(),
            "phone_number": set(),
            "government_id": set(),
        }
        self.candidate_pool: list[dict[str, Any]] = []
        self.seed_pool: list[dict[str, Any]] = []
        self.seed_audit_records: list[dict[str, Any]] = []
        self.last_ipf_report: dict[str, Any] | None = None
        self.llm = ProfileLLMClient(self.config)
        self.population = ProfilePopulation(self.config, self.targets, self.rng)
        self.checkpoint = ProfileCheckpoint(self.config, self.targets, self.llm)

    def checkpoint_report(self) -> dict[str, Any]:
        return self.checkpoint.checkpoint_report()

    def mark_checkpoint_complete(self) -> None:
        return self.checkpoint.mark_checkpoint_complete()

    def close_checkpoint(self) -> None:
        return self.checkpoint.close_checkpoint()

    def generate(self) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        base_seed_count = self.config.candidate_count or self.config.count
        if base_seed_count < self.config.count:
            raise ValueError(
                "candidate_count must be at least count so the final sample "
                "can be drawn from the base candidate pool"
            )
        seeds = self.generate_candidates(base_seed_count)
        self.seed_pool = [
            {field: seed[field] for field in SKELETON_FIELDS}
            | {"candidate_id": seed["_candidate_id"]}
            for seed in seeds
        ]
        candidates, stage_report = self.process_candidate_batch(
            seeds, seed_source="base"
        )

        replenish_rounds = 0
        replenish_seed_count = 0
        while (
            len(candidates) < self.config.count
            and replenish_rounds < self.config.max_backfill_rounds
        ):
            needed = self.config.count - len(candidates)
            extra_seeds = self.generate_candidates(max(needed * 2, 1))
            replenish_seed_count += len(extra_seeds)
            extra, extra_report = self.process_candidate_batch(
                extra_seeds, seed_source="replenish"
            )
            candidates.extend(extra)
            self._merge_stage_report(stage_report, extra_report)
            replenish_rounds += 1

        if len(candidates) < self.config.count:
            raise RuntimeError(
                f"Only {len(candidates)} valid profiles survived; {self.config.count} are required."
            )

        backfill_report = {"rounds": 0, "generated": 0, "remaining_missing_cells": []}
        capacity_report: dict[str, Any] | None = None
        if not self.config.skip_ipf:
            for round_number in range(1, self.config.max_backfill_rounds + 1):
                missing = self.find_missing_target_cells(candidates)
                if not missing:
                    break
                targeted_seeds = self.generate_targeted_candidates(missing)
                targeted, targeted_report = self.process_candidate_batch(
                    targeted_seeds, seed_source="target_support_backfill"
                )
                candidates.extend(targeted)
                self._merge_stage_report(stage_report, targeted_report)
                backfill_report["rounds"] = round_number
                backfill_report["generated"] += len(targeted_seeds)

            remaining = self.find_missing_target_cells(candidates)
            backfill_report["remaining_missing_cells"] = [
                {"constraint": cell["constraint"], "key": cell["key"]}
                for cell in remaining
            ]
            if remaining:
                preview = ", ".join(
                    f"{cell['constraint']}:{cell['key']}" for cell in remaining[:10]
                )
                raise RuntimeError(f"IPF target support is still incomplete: {preview}")

            capacity_backfill_generated = 0
            for _ in range(self.config.max_backfill_rounds):
                capacity_deficits = self.find_target_capacity_deficits(
                    candidates, self.config.count
                )
                if not capacity_deficits:
                    break
                targeted_seeds = self.generate_capacity_backfill_candidates(
                    capacity_deficits
                )
                targeted, targeted_report = self.process_candidate_batch(
                    targeted_seeds, seed_source="target_capacity_backfill"
                )
                candidates.extend(targeted)
                capacity_backfill_generated += len(targeted_seeds)
                self._merge_stage_report(stage_report, targeted_report)
            capacity_deficits = self.find_target_capacity_deficits(
                candidates, self.config.count
            )
            capacity_report = {
                "checked_positive_cells": sum(
                    target > 0
                    for constraint in self.targets
                    for target in constraint.targets.values()
                ),
                "backfill_generated": capacity_backfill_generated,
                "deficits": capacity_deficits,
            }
            if capacity_deficits:
                preview = ", ".join(
                    f"{cell['constraint']}:{cell['key']} "
                    f"({cell['available']}<{cell['required']})"
                    for cell in capacity_deficits[:10]
                )
                raise RuntimeError(
                    "Candidate pool lacks capacity for unique calibrated sampling: "
                    f"{preview}. Increase --target-proposal-ratio or "
                    "--max-backfill-rounds."
                )

        ipf_report: dict[str, Any] | None = None
        if not self.config.skip_ipf:
            # Preserve the fully validated pool before calibration so a failed
            # IPF pass can be recalibrated without repeating LLM generation.
            self.candidate_pool = [
                strip_internal_fields(candidate) for candidate in candidates
            ]
            ipf_report = self.apply_ipf(candidates)
            self.last_ipf_report = copy.deepcopy(ipf_report)
            if not ipf_report["converged"]:
                worst_name, worst_l1 = max(
                    ipf_report["final_l1"].items(), key=lambda item: item[1]
                )
                raise RuntimeError(
                    "IPF did not converge: "
                    f"worst constraint {worst_name!r} has L1={worst_l1}. "
                    "Increase --target-proposal-ratio or --max-backfill-rounds, "
                    "or inspect target compatibility."
                )

            selection = self.unique_selection_diagnostics(candidates, self.config.count)
            ipf_report["unique_selection"] = selection
            if selection["max_ideal_inclusion_probability"] > 1.0 + 1e-9:
                raise RuntimeError(
                    "The calibrated weights cannot be represented by a unique "
                    "without-replacement sample: max ideal inclusion probability is "
                    f"{selection['max_ideal_inclusion_probability']}. "
                    "Increase --target-proposal-ratio or --max-backfill-rounds."
                )
        else:
            for candidate in candidates:
                candidate["_weight"] = 1.0

        self.candidate_pool = [
            strip_internal_fields(candidate) for candidate in candidates
        ]
        sampled = self.sample_profiles(candidates, self.config.count)
        profiles = [strip_internal_fields(profile) for profile in sampled]
        residual_issues = [
            {"index": index, "issues": check_profile(profile)}
            for index, profile in enumerate(profiles)
            if check_profile(profile)
        ]
        if residual_issues:
            raise RuntimeError(
                f"Final sample contains invalid profiles: {residual_issues[:3]}"
            )

        final_audit = self.audit_final_sample(profiles)
        total_audited_seed_count = (
            stage_report["llm_seed_accepted"] + stage_report["llm_seed_rejected"]
        )
        total_completed_seed_count = (
            stage_report["completion_accepted"] + stage_report["completion_rejected"]
        )

        report = {
            "requested_count": self.config.count,
            "candidate_count": base_seed_count,
            "base_seed_count": len(self.seed_pool),
            "seed_audit_record_count": len(self.seed_audit_records),
            "total_audited_seed_count": total_audited_seed_count,
            "candidate_pool_size": len(candidates),
            "llm_seed_accepted": stage_report["llm_seed_accepted"],
            "llm_seed_rejected": stage_report["llm_seed_rejected"],
            "llm_seed_reasons": stage_report["llm_seed_reasons"],
            "completion_accepted": stage_report["completion_accepted"],
            "completion_rejected": stage_report["completion_rejected"],
            "logical_screen_survival_rate": (
                stage_report["llm_seed_accepted"] / total_audited_seed_count
                if total_audited_seed_count
                else None
            ),
            "completion_survival_rate": (
                stage_report["completion_accepted"] / total_completed_seed_count
                if total_completed_seed_count
                else None
            ),
            "replenish_rounds": replenish_rounds,
            "replenish_seed_count": replenish_seed_count,
            "backfill_seed_count": self.population._targeted_backfill_seed_count,
            "backfill": backfill_report,
            "target_capacity": capacity_report,
            "seed_proposal": {
                "target_ratio_requested": self.config.target_proposal_ratio,
                "target_proposal_available": self.population._target_proposal_available,
                "target_informed": self.population._target_proposal_seed_count,
                "uniform": self.population._uniform_seed_count,
                "targeted_backfill": self.population._targeted_backfill_seed_count,
            },
            "llm_workers": self.config.llm_workers,
            "llm_timeout": self.config.llm_timeout,
            "llm_requests_per_minute": self.config.llm_requests_per_minute,
            "llm_api_key_count": len(self.llm._api_keys),
            "llm_requests_per_minute_by_key": {
                f"key_{index + 1}": rpm
                for index, rpm in enumerate(self.llm._api_key_rpms)
            },
            "llm_model_aliases_by_key": {
                f"key_{index + 1}": model
                for index, model in enumerate(self.llm._api_key_models)
            },
            "llm_effective_requests_per_minute": (
                sum(self.llm._api_key_rpms)
                if self.llm._api_key_rpms
                and all(rpm > 0 for rpm in self.llm._api_key_rpms)
                else 0
            ),
            "llm_temperature": self.config.temperature,
            "pii_field_retries": self.config.pii_field_retries,
            "pii_validation": self.pii_metrics_report(),
            "llm_usage": copy.deepcopy(self.llm._llm_usage),
            "checkpoint": self.checkpoint_report(),
            "progress_enabled": self.config.show_progress,
            "ipf_skeleton_coverage": skeleton_ipf_coverage(self.targets),
            "ipf": ipf_report,
            "final_audit": final_audit,
            "final_validation": {"invalid_profiles": 0},
        }
        return profiles, report

    def pii_metrics_report(self) -> dict[str, Any]:
        fields: dict[str, dict[str, Any]] = {}
        for field, raw in self._pii_field_metrics.items():
            initial_total = raw["initial_total"]
            initial_failed = initial_total - raw["initial_passed"]
            fields[field] = {
                **raw,
                "initial_failed": initial_failed,
                "initial_pass_rate": (
                    raw["initial_passed"] / initial_total if initial_total else None
                ),
                "repair_profile_pass_rate": (
                    raw["repaired_profiles"] / initial_failed
                    if initial_failed
                    else None
                ),
                "repair_attempt_pass_rate": (
                    raw["repair_attempt_passed"] / raw["repair_attempts"]
                    if raw["repair_attempts"]
                    else None
                ),
            }
        government_id_llm = copy.deepcopy(self._government_id_llm_metrics)
        total_audits = (
            government_id_llm["initial_audits"] + government_id_llm["repair_audits"]
        )
        total_accepted = (
            government_id_llm["initial_accepted"] + government_id_llm["repair_accepted"]
        )
        government_id_llm["total_audits"] = total_audits
        government_id_llm["total_accepted"] = total_accepted
        government_id_llm["total_rejected"] = total_audits - total_accepted
        government_id_llm["accept_rate"] = (
            total_accepted / total_audits if total_audits else None
        )
        return {
            "fields": fields,
            "government_id_repair_policy": GOVERNMENT_ID_REPAIR_POLICY_ID,
            "government_id_llm_consistency": government_id_llm,
            "diagnostic_profile_count": len(self._pii_diagnostics),
        }

    def diagnostic_records(self) -> list[dict[str, Any]]:
        return copy.deepcopy(self._pii_diagnostics)

    @staticmethod
    def _empty_stage_report() -> dict[str, Any]:
        return {
            "llm_seed_accepted": 0,
            "llm_seed_rejected": 0,
            "llm_seed_reasons": {},
            "completion_accepted": 0,
            "completion_rejected": 0,
        }

    @staticmethod
    def _merge_stage_report(total: dict[str, Any], addition: dict[str, Any]) -> None:
        for key in [
            "llm_seed_accepted",
            "llm_seed_rejected",
            "completion_accepted",
            "completion_rejected",
        ]:
            total[key] += addition[key]
        for reason, count in addition["llm_seed_reasons"].items():
            total["llm_seed_reasons"][reason] = (
                total["llm_seed_reasons"].get(reason, 0) + count
            )

    def process_candidate_batch(
        self, seeds: list[dict[str, Any]], *, seed_source: str = "base"
    ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        report = self._empty_stage_report()
        audited, audit_report = self.audit_candidate_seeds(seeds)
        for seed in seeds:
            audit = seed.get("_llm_seed_audit", {})
            self.seed_audit_records.append(
                {
                    "candidate_id": seed.get("_candidate_id"),
                    "source": seed_source,
                    **{
                        field: seed[field] for field in SKELETON_FIELDS if field in seed
                    },
                    "decision": audit.get("decision"),
                    "reason_code": audit.get("reason_code"),
                    "reason": audit.get("reason", ""),
                }
            )
        report["llm_seed_accepted"] += audit_report["accepted"]
        report["llm_seed_rejected"] += audit_report["rejected"]
        report["llm_seed_reasons"].update(audit_report["reasons"])

        completed, completion_report = self.complete_profiles(audited)
        report["completion_accepted"] += completion_report["accepted"]
        report["completion_rejected"] += completion_report["rejected"]
        return completed, report

    def generate_candidates(self, count: int) -> list[dict[str, Any]]:
        return self.population.generate_candidates(count)

    def register_existing_candidate_state(
        self, candidates: list[dict[str, Any]]
    ) -> None:
        return self.population.register_existing_candidate_state(candidates)

    @staticmethod
    def _index_results_exact(
        results: list[Any], candidates: list[dict[str, Any]], stage: str
    ) -> dict[str, dict[str, Any]]:
        expected = {str(candidate["_candidate_id"]) for candidate in candidates}
        by_id: dict[str, dict[str, Any]] = {}
        duplicates = []
        for item in results:
            if not isinstance(item, dict) or item.get("candidate_id") is None:
                raise RuntimeError(f"{stage} returned an item without candidate_id.")
            candidate_id = str(item["candidate_id"])
            if candidate_id in by_id:
                duplicates.append(candidate_id)
            by_id[candidate_id] = item
        actual = set(by_id)
        missing = sorted(expected - actual)
        unknown = sorted(actual - expected)
        if duplicates or missing or unknown:
            raise RuntimeError(
                f"{stage} candidate_id mismatch: duplicates={duplicates}, "
                f"missing={missing}, unknown={unknown}"
            )
        return by_id

    def _call_llm_batch_results(
        self,
        *,
        prompt: str,
        temperature: float,
        candidates: list[dict[str, Any]],
        stage: str,
        required_fields: tuple[str, ...],
        nonempty_fields: tuple[str, ...] = (),
        string_fields: tuple[str, ...] = (),
        allowed_values: dict[str, set[str]] | None = None,
        requested_fields: tuple[str, ...] | None = None,
        result_validator: Callable[[str, dict[str, Any]], None] | None = None,
    ) -> dict[str, dict[str, Any]]:
        cache_key = self.checkpoint._llm_batch_cache_key(
            prompt=prompt,
            temperature=temperature,
            stage=stage,
            candidates=candidates,
            required_fields=required_fields,
            nonempty_fields=nonempty_fields,
            string_fields=string_fields,
            allowed_values=allowed_values,
            requested_fields=requested_fields,
            provider_model=self.llm._generation_model_for_stage(stage),
        )
        cached = self.checkpoint._load_validated_checkpoint_batch(
            cache_key, result_validator
        )
        if cached is not None:
            return cached

        last_error: Exception | None = None
        attempts = max(1, self.config.llm_retries + 1)
        for attempt in range(attempts):
            try:
                self.llm._acquire_llm_request_slot()
                self.llm._record_llm_request(
                    stage,
                    candidate_count=len(candidates),
                    requested_field_count=len(
                        required_fields
                        if requested_fields is None
                        else requested_fields
                    ),
                )
                parsed = self.call_llm_json(prompt, temperature=temperature)
                results = parsed.get("results")
                if not isinstance(results, list):
                    raise RuntimeError(f"{stage} output must contain a results array.")
                by_id = self._index_results_exact(results, candidates, stage)
                for candidate_id, item in by_id.items():
                    missing = [field for field in required_fields if field not in item]
                    if missing:
                        raise RuntimeError(
                            f"{stage} result {candidate_id} is missing fields: "
                            + ", ".join(missing)
                        )
                    wrong_types = [
                        field
                        for field in string_fields
                        if not isinstance(item.get(field), str)
                    ]
                    if wrong_types:
                        raise RuntimeError(
                            f"{stage} result {candidate_id} must use strings for: "
                            + ", ".join(wrong_types)
                        )
                    empty = [
                        field
                        for field in nonempty_fields
                        if item.get(field) is None or not str(item[field]).strip()
                    ]
                    if empty:
                        raise RuntimeError(
                            f"{stage} result {candidate_id} has empty fields: "
                            + ", ".join(empty)
                        )
                    for field, allowed in (allowed_values or {}).items():
                        value = str(item.get(field, "")).strip().lower()
                        if value not in allowed:
                            raise RuntimeError(
                                f"{stage} result {candidate_id} has invalid "
                                f"{field}={value!r}."
                            )
                self.checkpoint._validate_batch_result_items(by_id, result_validator)
                self.checkpoint._store_checkpoint_batch(
                    cache_key=cache_key,
                    stage=stage,
                    candidate_count=len(candidates),
                    result=by_id,
                )
                return by_id
            except Exception as exc:
                if isinstance(exc, (ProviderHealthExceeded, FatalProviderError)):
                    raise
                last_error = exc
                if attempt + 1 < attempts:
                    time.sleep(min(30.0, 2.0**attempt))
        raise RuntimeError(f"{stage} failed after {attempts} attempt(s): {last_error}")

    def _call_llm_batch_with_id_split(
        self,
        batch: list[dict[str, Any]],
        *,
        prompt_builder: Callable[[list[dict[str, Any]]], str],
        temperature: float,
        stage: str,
        required_fields: tuple[str, ...],
        nonempty_fields: tuple[str, ...] = (),
        string_fields: tuple[str, ...] = (),
        allowed_values: dict[str, set[str]] | None = None,
        requested_fields: tuple[str, ...] | None = None,
        result_validator: Callable[[str, dict[str, Any]], None] | None = None,
    ) -> dict[str, dict[str, Any]]:
        prompt = prompt_builder(batch)
        cache_key = self.checkpoint._llm_batch_cache_key(
            prompt=prompt,
            temperature=temperature,
            stage=stage,
            candidates=batch,
            required_fields=required_fields,
            nonempty_fields=nonempty_fields,
            string_fields=string_fields,
            allowed_values=allowed_values,
            requested_fields=requested_fields,
            provider_model=self.llm._generation_model_for_stage(stage),
        )
        cached = self.checkpoint._load_validated_checkpoint_batch(
            cache_key, result_validator
        )
        if cached is not None:
            return cached

        request_batch_size = int(
            getattr(self.llm._llm_request_context, "request_batch_size", 0) or 0
        )
        if request_batch_size > 0 and len(batch) > request_batch_size:
            combined: dict[str, dict[str, Any]] = {}
            for start in range(0, len(batch), request_batch_size):
                child = self._call_llm_batch_with_id_split(
                    batch[start : start + request_batch_size],
                    prompt_builder=prompt_builder,
                    temperature=temperature,
                    stage=stage,
                    required_fields=required_fields,
                    nonempty_fields=nonempty_fields,
                    string_fields=string_fields,
                    allowed_values=allowed_values,
                    requested_fields=requested_fields,
                    result_validator=result_validator,
                )
                combined.update(child)
            self.checkpoint._validate_batch_result_items(combined, result_validator)
            self.checkpoint._store_checkpoint_batch(
                cache_key=cache_key,
                stage=stage,
                candidate_count=len(batch),
                result=combined,
            )
            return combined

        # A failed parent batch may already have successful child checkpoints.
        # During resume, inspect those children before retrying the parent so an
        # interruption cannot recreate a storm of duplicate large requests.
        if self.config.resume and len(batch) > 1:
            midpoint = len(batch) // 2
            child_batches = (batch[:midpoint], batch[midpoint:])
            cached_children: dict[int, dict[str, dict[str, Any]]] = {}
            for child_index, child_batch in enumerate(child_batches):
                child_prompt = prompt_builder(child_batch)
                child_cache_key = self.checkpoint._llm_batch_cache_key(
                    prompt=child_prompt,
                    temperature=temperature,
                    stage=stage,
                    candidates=child_batch,
                    required_fields=required_fields,
                    nonempty_fields=nonempty_fields,
                    string_fields=string_fields,
                    allowed_values=allowed_values,
                    requested_fields=requested_fields,
                    provider_model=self.llm._generation_model_for_stage(stage),
                )
                child_cached = self.checkpoint._load_validated_checkpoint_batch(
                    child_cache_key,
                    result_validator,
                )
                if child_cached is not None:
                    cached_children[child_index] = child_cached

            if cached_children:
                combined: dict[str, dict[str, Any]] = {}
                for child_index, child_batch in enumerate(child_batches):
                    child_result = cached_children.get(child_index)
                    if child_result is None:
                        child_result = self._call_llm_batch_with_id_split(
                            child_batch,
                            prompt_builder=prompt_builder,
                            temperature=temperature,
                            stage=stage,
                            required_fields=required_fields,
                            nonempty_fields=nonempty_fields,
                            string_fields=string_fields,
                            allowed_values=allowed_values,
                            requested_fields=requested_fields,
                            result_validator=result_validator,
                        )
                    combined.update(child_result)
                self.checkpoint._validate_batch_result_items(combined, result_validator)
                self.checkpoint._store_checkpoint_batch(
                    cache_key=cache_key,
                    stage=stage,
                    candidate_count=len(batch),
                    result=combined,
                )
                return combined

        try:
            return self._call_llm_batch_results(
                prompt=prompt,
                temperature=temperature,
                candidates=batch,
                stage=stage,
                required_fields=required_fields,
                nonempty_fields=nonempty_fields,
                string_fields=string_fields,
                allowed_values=allowed_values,
                requested_fields=requested_fields,
                result_validator=result_validator,
            )
        except RuntimeError as exc:
            if isinstance(exc, (ProviderHealthExceeded, FatalProviderError)):
                raise
            message = str(exc).lower()
            nonrecoverable_markers = (
                "401",
                "403",
                "authentication",
                "invalid api key",
                "no llm api keys",
                "configuration is incomplete",
            )
            if len(batch) <= 1 or any(
                marker in message for marker in nonrecoverable_markers
            ):
                raise
            midpoint = len(batch) // 2
            left = self._call_llm_batch_with_id_split(
                batch[:midpoint],
                prompt_builder=prompt_builder,
                temperature=temperature,
                stage=stage,
                required_fields=required_fields,
                nonempty_fields=nonempty_fields,
                string_fields=string_fields,
                allowed_values=allowed_values,
                requested_fields=requested_fields,
                result_validator=result_validator,
            )
            right = self._call_llm_batch_with_id_split(
                batch[midpoint:],
                prompt_builder=prompt_builder,
                temperature=temperature,
                stage=stage,
                required_fields=required_fields,
                nonempty_fields=nonempty_fields,
                string_fields=string_fields,
                allowed_values=allowed_values,
                requested_fields=requested_fields,
                result_validator=result_validator,
            )
            combined = {**left, **right}
            self.checkpoint._validate_batch_result_items(combined, result_validator)
            self.checkpoint._store_checkpoint_batch(
                cache_key=cache_key,
                stage=stage,
                candidate_count=len(batch),
                result=combined,
            )
            return combined

    def _call_llm_batch_with_partial_results(
        self,
        batch: list[dict[str, Any]],
        *,
        prompt_builder: Callable[[list[dict[str, Any]]], str],
        temperature: float,
        stage: str,
        required_fields: tuple[str, ...],
        nonempty_fields: tuple[str, ...] = (),
        string_fields: tuple[str, ...] = (),
        allowed_values: dict[str, set[str]] | None = None,
        requested_fields: tuple[str, ...] | None = None,
        result_validator: Callable[[str, dict[str, Any]], None] | None = None,
        error_field: str = "_call_error",
    ) -> dict[str, dict[str, Any]]:
        """Return every successful item even when a sibling request fails.

        ``_call_llm_batch_with_id_split`` intentionally has all-or-nothing
        semantics for stages whose output is not useful unless the full batch
        is present. Field repair is different: every replacement is independent
        and a transport or parsing failure for one candidate must not discard a
        sibling's valid replacement. Successful child batches keep their normal
        checkpoints; only the irreducible failed candidates receive
        ``error_field`` and remain eligible for a transport retry.
        """

        if not batch:
            return {}

        request_batch_size = int(
            getattr(self.llm._llm_request_context, "request_batch_size", 0) or 0
        )
        if request_batch_size > 0 and len(batch) > request_batch_size:
            combined: dict[str, dict[str, Any]] = {}
            for start in range(0, len(batch), request_batch_size):
                combined.update(
                    self._call_llm_batch_with_partial_results(
                        batch[start : start + request_batch_size],
                        prompt_builder=prompt_builder,
                        temperature=temperature,
                        stage=stage,
                        required_fields=required_fields,
                        nonempty_fields=nonempty_fields,
                        string_fields=string_fields,
                        allowed_values=allowed_values,
                        requested_fields=requested_fields,
                        result_validator=result_validator,
                        error_field=error_field,
                    )
                )
            return combined

        try:
            return self._call_llm_batch_with_id_split(
                batch,
                prompt_builder=prompt_builder,
                temperature=temperature,
                stage=stage,
                required_fields=required_fields,
                nonempty_fields=nonempty_fields,
                string_fields=string_fields,
                allowed_values=allowed_values,
                requested_fields=requested_fields,
                result_validator=result_validator,
            )
        except RuntimeError as exc:
            if isinstance(exc, (ProviderHealthExceeded, FatalProviderError)):
                raise
            if len(batch) == 1:
                candidate_id = str(batch[0]["_candidate_id"])
                return {
                    candidate_id: {
                        "candidate_id": candidate_id,
                        error_field: str(exc),
                    }
                }
            midpoint = len(batch) // 2
            left = self._call_llm_batch_with_partial_results(
                batch[:midpoint],
                prompt_builder=prompt_builder,
                temperature=temperature,
                stage=stage,
                required_fields=required_fields,
                nonempty_fields=nonempty_fields,
                string_fields=string_fields,
                allowed_values=allowed_values,
                requested_fields=requested_fields,
                result_validator=result_validator,
                error_field=error_field,
            )
            right = self._call_llm_batch_with_partial_results(
                batch[midpoint:],
                prompt_builder=prompt_builder,
                temperature=temperature,
                stage=stage,
                required_fields=required_fields,
                nonempty_fields=nonempty_fields,
                string_fields=string_fields,
                allowed_values=allowed_values,
                requested_fields=requested_fields,
                result_validator=result_validator,
                error_field=error_field,
            )
            return {**left, **right}

    def _run_llm_batches(
        self,
        batches: list[list[dict[str, Any]]],
        worker: Callable[[list[dict[str, Any]]], Any],
        description: str,
        *,
        batch_family: str = "completion",
    ) -> list[Any]:
        """Run independent LLM batches concurrently and restore input order."""

        if not batches:
            return []
        if batch_family == "completion" and self.llm._generation_model:
            if self.llm._generation_key_source == "audit_pool":
                if self.llm._generation_scheduler_mode == "keyed":
                    return self._run_llm_batches_by_key(
                        batches,
                        worker,
                        description,
                        request_batch_sizes=self.llm._generation_key_batch_sizes,
                        key_indices=self.llm._generation_key_indexes,
                        key_concurrencies=self.llm._generation_key_concurrencies,
                        provider_role="generation",
                    )
                return self._run_generation_batches(
                    batches,
                    worker,
                    description,
                )
            return self._run_generation_batches(batches, worker, description)
        if self.llm._api_key_concurrencies:
            if batch_family == "audit":
                request_batch_sizes = self.llm._api_key_audit_batch_sizes
            elif batch_family == "completion":
                request_batch_sizes = self.llm._api_key_completion_batch_sizes
            else:
                raise ValueError(f"Unsupported LLM batch family: {batch_family}")
            return self._run_llm_batches_by_key(
                batches,
                worker,
                description,
                request_batch_sizes=request_batch_sizes,
            )
        worker_count = min(self.config.llm_workers, len(batches))
        progress = None
        if self.config.show_progress:
            try:
                from tqdm.auto import tqdm
            except ImportError as exc:
                raise RuntimeError(
                    "tqdm is required for progress display. Install it with: pip install tqdm"
                ) from exc
            progress = tqdm(
                total=len(batches),
                desc=f"{description} [{worker_count} workers]",
                unit="batch",
                dynamic_ncols=True,
            )

        def advance() -> None:
            if progress is not None:
                progress.update(1)

        if worker_count == 1:
            try:
                ordered_results = []
                for batch in batches:
                    ordered_results.append(worker(batch))
                    advance()
                return ordered_results
            finally:
                if progress is not None:
                    progress.close()

        ordered_results: list[Any] = [None] * len(batches)
        try:
            with ThreadPoolExecutor(
                max_workers=worker_count,
                thread_name_prefix="profile-llm",
            ) as executor:
                futures = {
                    executor.submit(worker, batch): index
                    for index, batch in enumerate(batches)
                }
                try:
                    for future in as_completed(futures):
                        ordered_results[futures[future]] = future.result()
                        advance()
                except Exception:
                    for future in futures:
                        future.cancel()
                    raise
        finally:
            if progress is not None:
                progress.close()
        return ordered_results

    def _run_generation_batches(
        self,
        batches: list[list[dict[str, Any]]],
        worker: Callable[[list[dict[str, Any]]], Any],
        description: str,
    ) -> list[Any]:
        """Run completion/repair work through the dedicated generation model."""

        worker_count = min(self.llm._generation_concurrency, len(batches))
        progress = None
        if self.config.show_progress:
            try:
                from tqdm.auto import tqdm
            except ImportError as exc:
                raise RuntimeError(
                    "tqdm is required for progress display. Install it with: pip install tqdm"
                ) from exc
            progress = tqdm(
                total=len(batches),
                desc=f"{description} [{worker_count} generation workers]",
                unit="batch",
                dynamic_ncols=True,
            )

        def run(batch: list[dict[str, Any]]) -> Any:
            self.llm._llm_request_context.provider_role = "generation"
            self.llm._llm_request_context.request_batch_size = (
                self.llm._generation_batch_size
            )
            try:
                return worker(batch)
            finally:
                for name in ("provider_role", "request_batch_size", "api_key_index"):
                    if hasattr(self.llm._llm_request_context, name):
                        delattr(self.llm._llm_request_context, name)

        def advance() -> None:
            if progress is not None:
                progress.update(1)

        if worker_count == 1:
            try:
                ordered_results = []
                for batch in batches:
                    ordered_results.append(run(batch))
                    advance()
                return ordered_results
            finally:
                if progress is not None:
                    progress.close()

        ordered_results: list[Any] = [None] * len(batches)
        try:
            with ThreadPoolExecutor(
                max_workers=worker_count,
                thread_name_prefix="profile-generation-llm",
            ) as executor:
                futures = {
                    executor.submit(run, batch): index
                    for index, batch in enumerate(batches)
                }
                try:
                    for future in as_completed(futures):
                        ordered_results[futures[future]] = future.result()
                        advance()
                except Exception:
                    for future in futures:
                        future.cancel()
                    raise
        finally:
            if progress is not None:
                progress.close()
        return ordered_results

    def _run_llm_batches_by_key(
        self,
        batches: list[list[dict[str, Any]]],
        worker: Callable[[list[dict[str, Any]]], Any],
        description: str,
        *,
        request_batch_sizes: tuple[int, ...],
        key_indices: tuple[int, ...] | None = None,
        key_concurrencies: tuple[int, ...] | None = None,
        provider_role: str = "audit",
    ) -> list[Any]:
        """Drain stable outer batches through independent per-key worker pools.

        Outer batch boundaries remain unchanged so a result assembled from
        single-item requests has the same checkpoint key as the legacy batch.
        This lets concurrency and request shaping change without invalidating
        already completed logical work.
        """

        selected_key_indices = (
            tuple(range(len(self.llm._api_key_concurrencies)))
            if key_indices is None
            else key_indices
        )
        selected_concurrencies = (
            self.llm._api_key_concurrencies
            if key_concurrencies is None
            else key_concurrencies
        )
        if not (
            len(request_batch_sizes)
            == len(selected_key_indices)
            == len(selected_concurrencies)
        ):
            raise RuntimeError("Per-key batch sizes do not match the key pool.")
        work: Queue[tuple[int, list[dict[str, Any]]]] = Queue()
        for index, batch in enumerate(batches):
            work.put((index, batch))
        ordered_results: list[Any] = [None] * len(batches)
        result_lock = threading.Lock()
        stop = threading.Event()
        errors: list[BaseException] = []
        worker_count = sum(selected_concurrencies)
        progress = None
        if self.config.show_progress:
            try:
                from tqdm.auto import tqdm
            except ImportError as exc:
                raise RuntimeError(
                    "tqdm is required for progress display. Install it with: pip install tqdm"
                ) from exc
            progress = tqdm(
                total=len(batches),
                desc=f"{description} [{worker_count} keyed workers]",
                unit="batch",
                dynamic_ncols=True,
            )

        def run_key_worker(pool_index: int, key_index: int) -> None:
            self.llm._llm_request_context.pinned_api_key_index = key_index
            self.llm._llm_request_context.request_batch_size = request_batch_sizes[
                pool_index
            ]
            self.llm._llm_request_context.provider_role = provider_role
            try:
                while not stop.is_set():
                    try:
                        index, batch = work.get_nowait()
                    except Empty:
                        return
                    try:
                        result = worker(batch)
                        with result_lock:
                            ordered_results[index] = result
                            if progress is not None:
                                progress.update(1)
                    except BaseException as exc:
                        with result_lock:
                            if not errors:
                                errors.append(exc)
                        stop.set()
                        return
                    finally:
                        work.task_done()
            finally:
                for name in (
                    "pinned_api_key_index",
                    "request_batch_size",
                    "provider_role",
                    "api_key_index",
                ):
                    if hasattr(self.llm._llm_request_context, name):
                        delattr(self.llm._llm_request_context, name)

        futures = []
        try:
            with ThreadPoolExecutor(
                max_workers=worker_count,
                thread_name_prefix="profile-keyed-llm",
            ) as executor:
                for pool_index, (key_index, concurrency) in enumerate(
                    zip(selected_key_indices, selected_concurrencies)
                ):
                    futures.extend(
                        executor.submit(run_key_worker, pool_index, key_index)
                        for _ in range(concurrency)
                    )
                for future in as_completed(futures):
                    future.result()
        finally:
            if progress is not None:
                progress.close()
        if errors:
            raise errors[0]
        if any(result is None for result in ordered_results):
            raise RuntimeError(
                f"{description} keyed scheduler stopped before all batches completed."
            )
        return ordered_results

    def audit_candidate_seeds(
        self, candidates: list[dict[str, Any]]
    ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        self.ensure_llm_config()
        accepted: list[dict[str, Any]] = []
        reasons: dict[str, int] = defaultdict(int)
        batch_size = self.config.audit_batch_size or self.config.batch_size
        batches = [
            candidates[start : start + batch_size]
            for start in range(0, len(candidates), batch_size)
        ]

        def audit_batch(batch: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
            return self._call_llm_batch_with_id_split(
                batch,
                prompt_builder=build_seed_audit_prompt,
                temperature=0.0,
                stage="LLM seed audit",
                required_fields=("decision", "reason_code", "reason"),
                allowed_values={"decision": {"accept", "reject"}},
            )

        batch_results = self._run_llm_batches(
            batches,
            audit_batch,
            "LLM seed audit",
            batch_family="audit",
        )
        for batch, by_id in zip(batches, batch_results):
            for candidate in batch:
                candidate_id = candidate["_candidate_id"]
                result = by_id.get(candidate_id)
                decision = str(result.get("decision", "reject")).lower()
                if decision not in {"accept", "reject"}:
                    raise RuntimeError(
                        f"LLM seed audit returned invalid decision {decision!r} "
                        f"for {candidate_id}."
                    )
                reason_code = result.get("reason_code")
                candidate["_llm_seed_audit"] = {
                    "decision": decision,
                    "reason_code": reason_code,
                    "reason": str(result.get("reason", "")),
                }
                if decision == "accept":
                    accepted.append(candidate)
                else:
                    reasons[str(reason_code or "unspecified")] += 1
        rejected = len(candidates) - len(accepted)
        return accepted, {
            "accepted": len(accepted),
            "rejected": rejected,
            "reasons": dict(reasons),
        }

    def audit_government_id_consistency_with_llm(
        self,
        profiles: list[dict[str, Any]],
        *,
        phase: str,
    ) -> dict[str, dict[str, str]]:
        if phase not in {"initial", "repair"}:
            raise ValueError("government ID audit phase must be 'initial' or 'repair'.")
        if not profiles:
            return {}

        self.ensure_llm_config()
        batch_size = self.config.audit_batch_size or self.config.batch_size
        batches = [
            profiles[start : start + batch_size]
            for start in range(0, len(profiles), batch_size)
        ]

        def audit_batch(batch: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
            return self._call_llm_batch_with_id_split(
                batch,
                prompt_builder=build_government_id_audit_prompt,
                temperature=0.0,
                stage="LLM government ID consistency audit",
                required_fields=("decision", "reason_code", "reason"),
                nonempty_fields=("decision", "reason_code"),
                string_fields=("decision", "reason_code", "reason"),
                allowed_values={
                    "decision": {"accept", "reject"},
                    "reason_code": GOVERNMENT_ID_LLM_AUDIT_REASON_CODES,
                },
                result_validator=self._validate_government_id_llm_audit_result,
            )

        batch_results = self._run_llm_batches(
            batches,
            audit_batch,
            "LLM government ID consistency audit",
            batch_family="audit",
        )
        audits: dict[str, dict[str, str]] = {}
        phase_audits = f"{phase}_audits"
        phase_accepted = f"{phase}_accepted"
        phase_rejected = f"{phase}_rejected"
        for batch, by_id in zip(batches, batch_results):
            for profile in batch:
                candidate_id = str(profile["_candidate_id"])
                result = by_id[candidate_id]
                decision = str(result["decision"]).strip().lower()
                reason_code = str(result["reason_code"]).strip().lower()
                reason = str(result["reason"]).strip()
                self._validate_government_id_llm_audit_result(candidate_id, result)
                audit = {
                    "decision": decision,
                    "reason_code": reason_code,
                    "reason": reason,
                }
                audits[candidate_id] = audit
                metrics = self._government_id_llm_metrics
                metrics[phase_audits] += 1
                metrics[phase_accepted if decision == "accept" else phase_rejected] += 1
                if decision == "reject":
                    reasons = metrics["rejection_reasons"]
                    reasons[reason_code] = reasons.get(reason_code, 0) + 1
        return audits

    @staticmethod
    def _validate_government_id_llm_audit_result(
        candidate_id: str,
        result: dict[str, Any],
    ) -> None:
        decision = str(result.get("decision", "")).strip().lower()
        reason_code = str(result.get("reason_code", "")).strip().lower()
        reason = str(result.get("reason", "")).strip()
        if decision == "accept" and (reason_code != "none" or reason):
            raise RuntimeError(
                "LLM government ID consistency audit must return "
                f"reason_code='none' and an empty reason when accepting {candidate_id}."
            )
        if decision == "reject" and (reason_code == "none" or not reason):
            raise RuntimeError(
                "LLM government ID consistency audit must return a specific "
                f"reason code and non-empty reason when rejecting {candidate_id}."
            )

    @staticmethod
    def _government_id_llm_audit_issues(
        audit: dict[str, str],
    ) -> list[str]:
        if audit["decision"] == "accept":
            return []
        return [
            f"{GOVERNMENT_ID_LLM_AUDIT_ISSUE_PREFIX} "
            f"({audit['reason_code']}): {audit['reason']}"
        ]

    def complete_profiles(
        self, skeletons: list[dict[str, Any]]
    ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        completed = self.complete_profiles_with_llm(skeletons, allow_field_errors=True)
        return self.revalidate_completed_profiles(completed)

    def revalidate_completed_profiles(
        self, completed: list[dict[str, Any]]
    ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        """Revalidate completed PII and repair only fields that now fail.

        This is the migration entry point when the shared government-ID
        registry is strengthened. It preserves valid skeleton and PII fields,
        while forcing every identifier through the current deterministic
        decoder and semantic audit prompt.
        """

        initial_profiles = [self._diagnostic_profile(profile) for profile in completed]
        final_field_issues, repair_history = self._validate_and_repair_pii(completed)
        valid: list[dict[str, Any]] = []
        for index, profile in enumerate(completed):
            issues = check_profile(profile)
            for field in COMPLETION_FIELDS:
                for issue in final_field_issues[index].get(field, []):
                    if issue not in issues:
                        issues.append(issue)
            if issues:
                profile["_completion_issues"] = issues
            else:
                for field in DIRECT_IDENTIFIER_FIELDS:
                    self._seen_direct_identifiers[field].add(
                        normalize_direct_identifier(field, profile[field])
                    )
                profile["_weight"] = 1.0
                valid.append(profile)
            self._pii_diagnostics.append(
                {
                    "candidate_id": str(
                        profile.get("_candidate_id", f"candidate_{index}")
                    ),
                    "initial": initial_profiles[index],
                    "repaired": self._diagnostic_profile(profile),
                    "repair_history": repair_history[index],
                    "government_id_llm_audits": copy.deepcopy(
                        profile.get("_government_id_llm_audits", [])
                    ),
                    "accepted": not issues,
                    "final_issues": issues,
                }
            )
        rejected = len(completed) - len(valid)
        return valid, {"accepted": len(valid), "rejected": rejected}

    @staticmethod
    def _diagnostic_profile(profile: dict[str, Any]) -> dict[str, Any]:
        return {
            "candidate_id": str(profile.get("_candidate_id", "")),
            **{
                field: copy.deepcopy(profile.get(field)) for field in FULL_SCHEMA_FIELDS
            },
        }

    @staticmethod
    def _registry_repair_government_id(
        profile: dict[str, Any],
        validation_issues: list[str],
        semantic_attempt: int,
    ) -> str:
        """Apply shared country rules deterministically to one LLM proposal.

        The LLM remains the proposal generator. This postprocessor consumes the
        current deterministic failures and any prior semantic-audit feedback,
        edits only the encoded components named by that feedback, and produces
        a stable result for checkpoint resume.
        """

        candidate_id = str(profile.get("_candidate_id", ""))
        previous_value = str(profile.get("government_id", ""))
        seed_payload = json.dumps(
            {
                "policy": GOVERNMENT_ID_REPAIR_POLICY_ID,
                "candidate_id": candidate_id,
                "semantic_attempt": semantic_attempt,
                "previous_value": previous_value,
                "validation_issues": validation_issues,
            },
            ensure_ascii=False,
            sort_keys=True,
        )
        deterministic_seed = int.from_bytes(
            hashlib.sha256(seed_payload.encode("utf-8")).digest()[:8],
            "big",
        )
        age = int(profile["age"])
        return repair_government_id(
            country=str(profile["citizenship"]),
            previous_value=previous_value,
            validation_issues=validation_issues,
            possible_birth_years=(
                PROFILE_REFERENCE_YEAR - age - 1,
                PROFILE_REFERENCE_YEAR - age,
            ),
            expected_sex=str(profile["sex"]),
            name=str(profile["name"]),
            birth_location=str(profile["birth_location"]),
            rng=random.Random(deterministic_seed),
        )

    def _validate_and_repair_pii(
        self, profiles: list[dict[str, Any]]
    ) -> tuple[
        list[dict[str, list[str]]],
        list[dict[str, list[dict[str, Any]]]],
    ]:
        final_issues: list[dict[str, list[str]]] = [
            {field: [] for field in COMPLETION_FIELDS} for _ in profiles
        ]
        histories: list[dict[str, list[dict[str, Any]]]] = [
            {field: [] for field in COMPLETION_FIELDS} for _ in profiles
        ]
        max_retries = self.config.pii_field_retries

        for field in COMPLETION_FIELDS:
            claimed = (
                set(self._seen_direct_identifiers[field])
                if field in DIRECT_IDENTIFIER_FIELDS
                else set()
            )
            pending: dict[int, list[str]] = {}
            metrics = self._pii_field_metrics[field]
            initial_issues: dict[int, list[str]] = {}
            initial_audits: dict[int, dict[str, str]] = {}
            initial_audit_indexes: list[int] = []

            for index, profile in enumerate(profiles):
                issues = pii_field_issues(profile, field)
                if not issues and field in DIRECT_IDENTIFIER_FIELDS:
                    normalized = normalize_direct_identifier(field, profile[field])
                    if normalized in claimed:
                        issues = [
                            f"{field} duplicates an identifier already used by another profile"
                        ]
                    else:
                        claimed.add(normalized)
                initial_issues[index] = issues
                if field == "government_id" and not issues:
                    initial_audit_indexes.append(index)

            if initial_audit_indexes:
                audits = self.audit_government_id_consistency_with_llm(
                    [profiles[index] for index in initial_audit_indexes],
                    phase="initial",
                )
                for index in initial_audit_indexes:
                    profile = profiles[index]
                    audit = audits[str(profile["_candidate_id"])]
                    initial_audits[index] = audit
                    profile.setdefault("_government_id_llm_audits", []).append(
                        {"attempt": 0, "phase": "initial", **copy.deepcopy(audit)}
                    )
                    audit_issues = self._government_id_llm_audit_issues(audit)
                    if audit_issues:
                        claimed.discard(
                            normalize_direct_identifier(field, profile[field])
                        )
                        initial_issues[index] = audit_issues

            for index, profile in enumerate(profiles):
                issues = initial_issues[index]
                metrics["initial_total"] += 1
                if issues:
                    pending[index] = issues
                    history_entry = {
                        "attempt": 0,
                        "value": copy.deepcopy(profile.get(field)),
                        "issues": issues,
                    }
                    if index in initial_audits:
                        history_entry["llm_audit"] = copy.deepcopy(
                            initial_audits[index]
                        )
                    histories[index][field].append(history_entry)
                else:
                    metrics["initial_passed"] += 1

            semantic_attempts = {index: 0 for index in pending}
            transport_failures = {index: 0 for index in pending}
            last_transport_errors: dict[int, str] = {}
            max_transport_failures = max(1, self.config.llm_retries + 1)
            repair_round = 0

            while pending:
                repairable_indexes = [
                    index
                    for index in pending
                    if semantic_attempts[index] < max_retries
                    and transport_failures[index] < max_transport_failures
                ]
                if not repairable_indexes:
                    break
                repair_round += 1
                metrics["repair_rounds"] += 1
                batch_size = self.config.completion_batch_size or self.config.batch_size
                indexes_by_semantic_attempt: dict[int, list[int]] = defaultdict(list)
                for index in repairable_indexes:
                    indexes_by_semantic_attempt[semantic_attempts[index]].append(index)

                by_id: dict[str, dict[str, Any]] = {}
                for semantic_attempt, group_indexes in sorted(
                    indexes_by_semantic_attempt.items()
                ):
                    repair_items = []
                    for index in group_indexes:
                        item = copy.deepcopy(profiles[index])
                        item["_repair_field"] = field
                        item["_repair_issues"] = list(pending[index])
                        repair_items.append(item)
                    batches = [
                        repair_items[start : start + batch_size]
                        for start in range(0, len(repair_items), batch_size)
                    ]
                    # Preserve legacy cache keys for name/email/phone. The new
                    # government-ID stage is intentionally rerun at a stable
                    # temperature because transport retries are not semantic
                    # attempts and must reuse the same successful children.
                    group_temperature = (
                        min(1.5, max(0.7, self.config.temperature))
                        if field == "government_id"
                        else min(
                            1.5,
                            max(
                                0.7,
                                self.config.temperature + 0.15 * semantic_attempt,
                            ),
                        )
                    )

                    def repair_batch(
                        batch: list[dict[str, Any]],
                    ) -> dict[str, dict[str, Any]]:
                        stage = f"LLM PII repair: {field}"
                        if field == "government_id":
                            stage += " feedback"
                        return self._call_llm_batch_with_partial_results(
                            batch,
                            prompt_builder=lambda items: build_pii_repair_prompt(
                                items,
                                field,
                            ),
                            temperature=group_temperature,
                            stage=stage,
                            required_fields=(),
                            requested_fields=(field,),
                            error_field="_repair_call_error",
                        )

                    batch_results = self._run_llm_batches(
                        batches,
                        repair_batch,
                        (
                            f"LLM PII repair: {field} semantic attempt "
                            f"{semantic_attempt + 1}, round {repair_round}"
                        ),
                        batch_family="completion",
                    )
                    by_id.update(
                        {
                            candidate_id: result
                            for batch_result in batch_results
                            for candidate_id, result in batch_result.items()
                        }
                    )
                attempt_issues: dict[int, list[str]] = {}
                attempt_audits: dict[int, dict[str, str]] = {}
                attempt_registry_repairs: dict[int, dict[str, Any]] = {}
                attempt_audit_indexes: list[int] = []
                round_transport_errors: dict[int, str] = {}
                for index in repairable_indexes:
                    profile = profiles[index]
                    result = by_id.get(str(profile["_candidate_id"]), {})
                    call_error = result.get("_repair_call_error")
                    if not call_error and field not in result:
                        call_error = (
                            f"repair result for {profile['_candidate_id']} "
                            f"did not include {field}"
                        )
                    if call_error:
                        round_transport_errors[index] = str(call_error)
                        continue

                    semantic_attempts[index] += 1
                    transport_failures[index] = 0
                    value = result[field]
                    profile[field] = value.strip() if isinstance(value, str) else value
                    issues = pii_field_issues(profile, field)
                    if field == "government_id":
                        normalized = normalize_direct_identifier(field, profile[field])
                        if not issues and normalized in claimed:
                            issues = [
                                f"{field} duplicates an identifier already used by another profile"
                            ]
                        semantic_feedback = [
                            issue
                            for issue in pending[index]
                            if issue.startswith(GOVERNMENT_ID_LLM_AUDIT_ISSUE_PREFIX)
                        ]
                        registry_feedback = list(
                            dict.fromkeys([*issues, *semantic_feedback])
                        )
                        if registry_feedback:
                            llm_value = copy.deepcopy(profile[field])
                            metrics["registry_repair_attempts"] += 1
                            profile[field] = self._registry_repair_government_id(
                                profile,
                                registry_feedback,
                                semantic_attempts[index],
                            )
                            if profile[field] != llm_value:
                                metrics["registry_repair_changed"] += 1
                            issues = pii_field_issues(profile, field)
                            normalized = normalize_direct_identifier(
                                field, profile[field]
                            )
                            if not issues and normalized in claimed:
                                issues = [
                                    f"{field} duplicates an identifier already used by another profile"
                                ]
                            if not issues:
                                metrics["registry_repair_passed"] += 1
                            attempt_registry_repairs[index] = {
                                "policy": GOVERNMENT_ID_REPAIR_POLICY_ID,
                                "llm_value": llm_value,
                                "feedback": registry_feedback,
                                "value": copy.deepcopy(profile[field]),
                                "issues": list(issues),
                            }
                        if not issues:
                            claimed.add(normalized)
                    elif not issues and field in DIRECT_IDENTIFIER_FIELDS:
                        normalized = normalize_direct_identifier(field, profile[field])
                        if normalized in claimed:
                            issues = [
                                f"{field} duplicates an identifier already used by another profile"
                            ]
                        else:
                            claimed.add(normalized)
                    attempt_issues[index] = issues
                    if field == "government_id" and not issues:
                        attempt_audit_indexes.append(index)

                if attempt_audit_indexes:
                    audits = self.audit_government_id_consistency_with_llm(
                        [profiles[index] for index in attempt_audit_indexes],
                        phase="repair",
                    )
                    for index in attempt_audit_indexes:
                        profile = profiles[index]
                        audit = audits[str(profile["_candidate_id"])]
                        attempt_audits[index] = audit
                        profile.setdefault("_government_id_llm_audits", []).append(
                            {
                                "attempt": semantic_attempts[index],
                                "phase": "repair",
                                **copy.deepcopy(audit),
                            }
                        )
                        audit_issues = self._government_id_llm_audit_issues(audit)
                        if audit_issues:
                            claimed.discard(
                                normalize_direct_identifier(field, profile[field])
                            )
                            attempt_issues[index] = audit_issues

                repairable_set = set(repairable_indexes)
                next_pending: dict[int, list[str]] = {
                    index: issues
                    for index, issues in pending.items()
                    if index not in repairable_set
                }
                for index in repairable_indexes:
                    profile = profiles[index]
                    if index in round_transport_errors:
                        error = round_transport_errors[index]
                        transport_failures[index] += 1
                        last_transport_errors[index] = error
                        metrics["transport_failures"] += 1
                        # Preserve the last substantive deterministic/Judge
                        # feedback. Transport failures are execution metadata,
                        # not a new semantic diagnosis for the next prompt.
                        next_pending[index] = list(pending[index])
                        histories[index][field].append(
                            {
                                "attempt": semantic_attempts[index],
                                "event": "transport_failure",
                                "transport_round": transport_failures[index],
                                "value": copy.deepcopy(profile.get(field)),
                                "issues": list(pending[index]),
                                "transport_error": error,
                            }
                        )
                        continue

                    issues = attempt_issues[index]
                    metrics["repair_attempts"] += 1
                    if issues:
                        next_pending[index] = issues
                    else:
                        metrics["repair_attempt_passed"] += 1
                        metrics["repaired_profiles"] += 1
                    history_entry = {
                        "attempt": semantic_attempts[index],
                        "event": "semantic_attempt",
                        "value": copy.deepcopy(profile.get(field)),
                        "issues": issues,
                    }
                    if index in attempt_audits:
                        history_entry["llm_audit"] = copy.deepcopy(
                            attempt_audits[index]
                        )
                    if index in attempt_registry_repairs:
                        history_entry["registry_repair"] = copy.deepcopy(
                            attempt_registry_repairs[index]
                        )
                    histories[index][field].append(history_entry)
                pending = next_pending

            for index, issues in pending.items():
                unresolved = list(issues)
                transport_exhausted = (
                    transport_failures.get(index, 0) >= max_transport_failures
                    and semantic_attempts.get(index, 0) < max_retries
                )
                if transport_exhausted:
                    unresolved.append(
                        f"{field} repair transport exhausted after "
                        f"{transport_failures[index]} round(s): "
                        f"{last_transport_errors.get(index, 'unknown request failure')}"
                    )
                    metrics["transport_exhausted"] += 1
                final_issues[index][field] = unresolved
                metrics["exhausted"] += 1
                if (
                    field == "government_id"
                    and not transport_exhausted
                    and semantic_attempts.get(index, 0) >= max_retries
                    and any(
                        issue.startswith(GOVERNMENT_ID_LLM_AUDIT_ISSUE_PREFIX)
                        for issue in issues
                    )
                ):
                    self._government_id_llm_metrics["semantic_exhausted"] += 1

        return final_issues, histories

    def complete_profiles_with_llm(
        self,
        skeletons: list[dict[str, Any]],
        *,
        allow_field_errors: bool = False,
    ) -> list[dict[str, Any]]:
        self.ensure_llm_config()
        completed: list[dict[str, Any]] = []
        batch_size = self.config.completion_batch_size or self.config.batch_size
        batches = [
            skeletons[start : start + batch_size]
            for start in range(0, len(skeletons), batch_size)
        ]

        def complete_batch(batch: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
            return self._call_llm_batch_with_id_split(
                batch,
                prompt_builder=build_completion_prompt,
                temperature=self.config.temperature,
                stage="LLM completion",
                required_fields=(
                    () if allow_field_errors else tuple(LLM_COMPLETION_FIELDS)
                ),
                nonempty_fields=(
                    () if allow_field_errors else tuple(LLM_COMPLETION_FIELDS)
                ),
                string_fields=(
                    () if allow_field_errors else tuple(LLM_COMPLETION_FIELDS)
                ),
                requested_fields=tuple(LLM_COMPLETION_FIELDS),
            )

        batch_results = self._run_llm_batches(
            batches,
            complete_batch,
            "LLM completion",
            batch_family="completion",
        )
        for batch, by_id in zip(batches, batch_results):
            for skeleton in batch:
                result = by_id.get(skeleton["_candidate_id"])
                completion = {
                    field: result.get(field) for field in LLM_COMPLETION_FIELDS
                }
                profile = copy.deepcopy(skeleton)
                profile.update(
                    {
                        field: (value.strip() if isinstance(value, str) else value)
                        for field, value in completion.items()
                    }
                )
                completed.append(profile)
        return completed

    def find_missing_target_cells(
        self, candidates: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        return self.population.find_missing_target_cells(candidates)

    def find_target_capacity_deficits(
        self, candidates: list[dict[str, Any]], output_count: int
    ) -> list[dict[str, Any]]:
        return self.population.find_target_capacity_deficits(candidates, output_count)

    def generate_capacity_backfill_candidates(
        self, deficits: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        return self.population.generate_capacity_backfill_candidates(deficits)

    def generate_targeted_candidates(
        self, missing_cells: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        return self.population.generate_targeted_candidates(missing_cells)

    def apply_ipf(self, candidates: list[dict[str, Any]]) -> dict[str, Any]:
        return self.population.apply_ipf(candidates)

    @staticmethod
    def unique_selection_diagnostics(
        candidates: list[dict[str, Any]], count: int
    ) -> dict[str, float]:
        return ProfilePopulation.unique_selection_diagnostics(candidates, count)

    def sample_profiles(
        self, candidates: list[dict[str, Any]], count: int
    ) -> list[dict[str, Any]]:
        return self.population.sample_profiles(candidates, count)

    def audit_final_sample(self, profiles: list[dict[str, Any]]) -> dict[str, Any]:
        return self.population.audit_final_sample(profiles)

    def ensure_llm_config(self) -> None:
        return self.llm.ensure_llm_config()

    def call_llm_json(self, prompt: str, temperature: float) -> dict[str, Any]:
        return parse_json_output(self.call_llm(prompt, temperature=temperature))

    def call_llm(self, prompt: str, temperature: float | None = None) -> str:
        return self.llm.call_llm(prompt, temperature)
