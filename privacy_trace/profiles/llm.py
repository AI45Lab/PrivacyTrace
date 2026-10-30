"""LLM transport and per-key scheduling for profile generation."""

from __future__ import annotations

import json
import os
import re
import threading
import time
from collections import deque
from typing import Any

from agent_env.recovery import (
    FatalProviderError,
    ProviderHealthExceeded,
    RollingFailureWindow,
    RollingRateLimiter,
    is_fatal_provider_error,
    is_transient_provider_error,
)

from .schema import (
    GeneratorConfig,
)


class ProfileLLMClient:
    """OpenAI-compatible requests, per-key rate limits, and usage accounting."""

    def __init__(self, config: GeneratorConfig) -> None:
        self.config = config
        self._provider_health = RollingFailureWindow()
        self._provider_halted = threading.Event()
        self._llm_request_context = threading.local()
        self._metrics_lock = threading.Lock()
        self._llm_rate_condition = threading.Condition()
        self._api_keys: tuple[str, ...] = ()
        self._api_key_rpms: tuple[int, ...] = ()
        self._api_key_models: tuple[str, ...] = ()
        self._api_key_concurrencies: tuple[int, ...] = ()
        self._api_key_audit_batch_sizes: tuple[int, ...] = ()
        self._api_key_completion_batch_sizes: tuple[int, ...] = ()
        self._api_key_rate_limiters: list[RollingRateLimiter | None] = []
        self._llm_request_times_by_key: list[deque[float]] = []
        self._llm_requests_assigned_by_key: list[int] = []
        self._llm_key_cursor = 0
        self._generation_api_key: str | None = None
        self._generation_base_url: str | None = None
        self._generation_model: str | None = None
        self._generation_concurrency = 1
        self._generation_batch_size = 1
        self._generation_rpm = 0
        self._generation_rate_limiter: RollingRateLimiter | None = None
        self._generation_key_source = "dedicated"
        self._generation_scheduler_mode = "dedicated"
        self._generation_key_indexes: tuple[int, ...] = ()
        self._generation_key_concurrencies: tuple[int, ...] = ()
        self._generation_key_batch_sizes: tuple[int, ...] = ()
        self._llm_usage: dict[str, Any] = {
            "requests": 0,
            "candidate_items": 0,
            "requested_field_values": 0,
            "requests_by_key": {},
            "by_stage": {},
            "provider_tokens": {
                "prompt": 0,
                "completion": 0,
                "total": 0,
            },
        }

    def _generation_model_for_stage(self, stage: str) -> str | None:
        if not self._generation_model:
            return None
        if stage == "LLM completion" or stage.startswith("LLM PII repair:"):
            return self._generation_model
        return None

    def _acquire_llm_request_slot(self) -> None:
        provider_role = getattr(
            self._llm_request_context,
            "provider_role",
            "audit",
        )
        if (
            provider_role == "generation"
            and self._generation_key_source != "audit_pool"
        ):
            if self._generation_rate_limiter is not None:
                self._generation_rate_limiter.acquire()
            self._llm_request_context.api_key_index = -1
            return

        pinned_key_index = getattr(
            self._llm_request_context,
            "pinned_api_key_index",
            None,
        )
        if pinned_key_index is not None:
            key_index = int(pinned_key_index)
            if not 0 <= key_index < len(self._api_keys):
                raise RuntimeError("Pinned LLM API key selection is out of range.")
            limiter = self._api_key_rate_limiters[key_index]
            if limiter is not None:
                limiter.acquire()
            self._llm_request_context.api_key_index = key_index
            return

        # In RPM-led mode there are no per-key worker pools. Assign work in
        # exact proportion to the configured RPMs, then let each key's
        # evenly-spaced limiter reserve the request time. The global executor
        # is only a transport pool; it does not decide key allocation.
        if self._api_key_rate_limiters and any(self._api_key_rate_limiters):
            with self._llm_rate_condition:
                eligible_key_indexes = (
                    self._generation_key_indexes
                    if provider_role == "generation"
                    and self._generation_key_source == "audit_pool"
                    else tuple(range(len(self._api_keys)))
                )
                available_keys = [
                    index
                    for index in eligible_key_indexes
                    if self._api_key_rpms[index] > 0
                ]
                if not available_keys:
                    raise RuntimeError("No positive per-key RPM is configured.")
                key_index = min(
                    available_keys,
                    key=lambda index: (
                        self._llm_requests_assigned_by_key[index]
                        / self._api_key_rpms[index],
                        (index - self._llm_key_cursor) % len(self._api_keys),
                    ),
                )
                self._llm_requests_assigned_by_key[key_index] += 1
                self._llm_key_cursor = (key_index + 1) % len(self._api_keys)
                self._llm_request_context.api_key_index = key_index
                limiter = self._api_key_rate_limiters[key_index]
            if limiter is not None:
                limiter.acquire()
            return

        window_seconds = 60.0
        with self._llm_rate_condition:
            while True:
                now = time.monotonic()
                cutoff = now - window_seconds
                for request_times in self._llm_request_times_by_key:
                    while request_times and request_times[0] <= cutoff:
                        request_times.popleft()

                key_count = len(self._api_keys)
                if not key_count:
                    raise RuntimeError("No LLM API keys are configured.")
                available: list[tuple[float, int]] = []
                for offset in range(key_count):
                    key_index = (self._llm_key_cursor + offset) % key_count
                    request_times = self._llm_request_times_by_key[key_index]
                    key_limit = self._api_key_rpms[key_index]
                    if key_limit <= 0 or len(request_times) < key_limit:
                        utilization = (
                            -1.0 if key_limit <= 0 else len(request_times) / key_limit
                        )
                        available.append((utilization, key_index))

                if available:
                    # Prefer the key with the lowest fraction of its RPM window
                    # consumed.  Stable ordering preserves round-robin ties while
                    # allowing high-capacity keys to receive proportionally more
                    # work than low-capacity slots.
                    _, key_index = min(available, key=lambda item: item[0])
                    request_times = self._llm_request_times_by_key[key_index]
                    if self._api_key_rpms[key_index] > 0:
                        request_times.append(now)
                    self._llm_key_cursor = (key_index + 1) % key_count
                    self._llm_request_context.api_key_index = key_index
                    return

                wait_seconds = min(
                    max(0.01, window_seconds - (now - request_times[0]))
                    for request_times, key_limit in zip(
                        self._llm_request_times_by_key,
                        self._api_key_rpms,
                    )
                    if key_limit > 0
                )
                self._llm_rate_condition.wait(timeout=wait_seconds)

    def _record_llm_request(
        self, stage: str, *, candidate_count: int, requested_field_count: int
    ) -> None:
        if getattr(self._llm_request_context, "provider_role", "audit") == "generation":
            if self._generation_key_source == "audit_pool":
                key_index = int(getattr(self._llm_request_context, "api_key_index", 0))
                key_alias = f"generation_key_{key_index + 1}"
            else:
                key_alias = "generation"
        else:
            key_index = int(getattr(self._llm_request_context, "api_key_index", 0))
            key_alias = f"key_{key_index + 1}"
        with self._metrics_lock:
            self._llm_usage["requests"] += 1
            self._llm_usage["candidate_items"] += candidate_count
            self._llm_usage["requested_field_values"] += (
                candidate_count * requested_field_count
            )
            requests_by_key = self._llm_usage.setdefault("requests_by_key", {})
            requests_by_key[key_alias] = requests_by_key.get(key_alias, 0) + 1
            by_stage = self._llm_usage["by_stage"]
            stage_metrics = by_stage.setdefault(
                stage,
                {
                    "requests": 0,
                    "candidate_items": 0,
                    "requested_field_values": 0,
                },
            )
            stage_metrics["requests"] += 1
            stage_metrics["candidate_items"] += candidate_count
            stage_metrics["requested_field_values"] += (
                candidate_count * requested_field_count
            )

    def ensure_llm_config(self) -> None:
        self.config.api_key = self.config.api_key or os.environ.get("MY_MODEL_API_KEY")
        self.config.base_url = self.config.base_url or os.environ.get(
            "MY_MODEL_BASE_URL"
        )
        self.config.model = self.config.model or os.environ.get("MY_MODEL_NAME")
        extra_keys = [
            value
            for value in re.split(
                r"[\s,;]+",
                os.environ.get("MY_MODEL_API_KEYS", "").strip(),
            )
            if value
        ]
        api_keys = tuple(
            dict.fromkeys(key for key in [self.config.api_key, *extra_keys] if key)
        )
        missing = [
            name
            for name, value in [
                ("MY_MODEL_API_KEY or MY_MODEL_API_KEYS", api_keys),
                ("MY_MODEL_BASE_URL", self.config.base_url),
                ("MY_MODEL_NAME", self.config.model),
            ]
            if not value
        ]
        if missing:
            raise RuntimeError(f"Missing LLM configuration: {', '.join(missing)}")
        raw_key_rpms = os.environ.get("MY_MODEL_API_KEY_RPMS", "").strip()
        if raw_key_rpms:
            try:
                api_key_rpms = tuple(
                    int(value) for value in re.split(r"[\s,;]+", raw_key_rpms) if value
                )
            except ValueError as exc:
                raise RuntimeError(
                    "MY_MODEL_API_KEY_RPMS must contain only integers."
                ) from exc
            if len(api_key_rpms) != len(api_keys):
                raise RuntimeError(
                    "MY_MODEL_API_KEY_RPMS must provide exactly one value for "
                    "each configured API key."
                )
            if any(value < 0 for value in api_key_rpms):
                raise RuntimeError("MY_MODEL_API_KEY_RPMS values must be non-negative.")
        else:
            api_key_rpms = (self.config.llm_requests_per_minute,) * len(api_keys)
        raw_key_models = os.environ.get("MY_MODEL_API_KEY_MODELS", "").strip()
        api_key_models = (
            tuple(value for value in re.split(r"[\s,;]+", raw_key_models) if value)
            if raw_key_models
            else (str(self.config.model),) * len(api_keys)
        )
        if len(api_key_models) != len(api_keys):
            raise RuntimeError(
                "MY_MODEL_API_KEY_MODELS must provide exactly one model alias "
                "for each configured API key."
            )

        def integer_slots(
            variable: str, *, allow_zero: bool = False
        ) -> tuple[int, ...] | None:
            raw = os.environ.get(variable, "").strip()
            if not raw:
                return None
            try:
                values = tuple(
                    int(value) for value in re.split(r"[\s,;]+", raw) if value
                )
            except ValueError as exc:
                raise RuntimeError(f"{variable} must contain only integers.") from exc
            if len(values) != len(api_keys):
                raise RuntimeError(
                    f"{variable} must provide exactly one value for each "
                    "configured API key."
                )
            if any(value < (0 if allow_zero else 1) for value in values):
                requirement = "non-negative" if allow_zero else "positive"
                raise RuntimeError(f"{variable} values must be {requirement}.")
            return values

        configured_concurrencies = integer_slots(
            "MY_MODEL_API_KEY_CONCURRENCIES", allow_zero=True
        )
        audit_batch_sizes = integer_slots("MY_MODEL_API_KEY_AUDIT_BATCH_SIZES")
        completion_batch_sizes = integer_slots(
            "MY_MODEL_API_KEY_COMPLETION_BATCH_SIZES"
        )
        if configured_concurrencies is None:
            api_key_concurrencies: tuple[int, ...] = ()
            audit_batch_sizes = ()
            completion_batch_sizes = ()
        else:
            if not any(configured_concurrencies):
                raise RuntimeError(
                    "MY_MODEL_API_KEY_CONCURRENCIES must enable at least one key."
                )
            if audit_batch_sizes is None:
                audit_batch_sizes = (self.config.audit_batch_size,) * len(api_keys)
            if completion_batch_sizes is None:
                completion_batch_sizes = (self.config.completion_batch_size,) * len(
                    api_keys
                )
            total_workers = sum(configured_concurrencies)
            if self.config.llm_workers >= total_workers:
                api_key_concurrencies = configured_concurrencies
            else:
                active_key_count = sum(value > 0 for value in configured_concurrencies)
                if self.config.llm_workers < active_key_count:
                    raise RuntimeError(
                        "llm_workers must be at least the active API key count "
                        "when keyed concurrency is enabled."
                    )
                scale = self.config.llm_workers / total_workers
                raw_scaled = [value * scale for value in configured_concurrencies]
                scaled = [
                    0 if configured == 0 else max(1, int(value))
                    for value, configured in zip(raw_scaled, configured_concurrencies)
                ]
                while sum(scaled) > self.config.llm_workers:
                    reducible = [
                        index for index, value in enumerate(scaled) if value > 1
                    ]
                    if not reducible:
                        break
                    index = max(reducible, key=lambda item: scaled[item])
                    scaled[index] -= 1
                while sum(scaled) < self.config.llm_workers:
                    index = max(
                        (
                            item
                            for item, configured in enumerate(configured_concurrencies)
                            if configured > 0
                        ),
                        key=lambda item: raw_scaled[item] - scaled[item],
                    )
                    scaled[index] += 1
                api_key_concurrencies = tuple(scaled)

        generation_key_source = (
            os.environ.get(
                "PROFILE_GENERATION_KEY_SOURCE",
                "dedicated",
            )
            .strip()
            .casefold()
        )
        if generation_key_source not in {"dedicated", "audit_pool"}:
            raise RuntimeError(
                "PROFILE_GENERATION_KEY_SOURCE must be 'dedicated' or 'audit_pool'."
            )
        generation_api_key = (
            (
                os.environ.get("PROFILE_GENERATION_API_KEY", "").strip()
                or os.environ.get("DS_KEY", "").strip()
                or None
            )
            if generation_key_source == "dedicated"
            else None
        )
        generation_base_url = (
            os.environ.get("PROFILE_GENERATION_BASE_URL", "").strip() or None
        )
        generation_model = (
            os.environ.get("PROFILE_GENERATION_MODEL", "").strip() or None
        )
        if generation_key_source == "audit_pool":
            if not generation_model:
                raise RuntimeError(
                    "Audit-pool generation requires PROFILE_GENERATION_MODEL."
                )
            generation_base_url = str(self.config.base_url)
        else:
            generation_values = (
                generation_api_key,
                generation_base_url,
                generation_model,
            )
            if any(generation_values) and not all(generation_values):
                raise RuntimeError(
                    "Dedicated generation configuration requires DS_KEY (or "
                    "PROFILE_GENERATION_API_KEY), PROFILE_GENERATION_BASE_URL, "
                    "and PROFILE_GENERATION_MODEL."
                )

        def positive_generation_integer(variable: str, default: int) -> int:
            raw = os.environ.get(variable, "").strip()
            if not raw:
                return default
            try:
                value = int(raw)
            except ValueError as exc:
                raise RuntimeError(f"{variable} must be an integer.") from exc
            if value <= 0:
                raise RuntimeError(f"{variable} must be positive.")
            return value

        generation_scheduler_mode = (
            os.environ.get("PROFILE_GENERATION_SCHEDULER", "keyed").strip().casefold()
        )
        if generation_key_source == "audit_pool":
            if generation_scheduler_mode not in {"keyed", "rpm"}:
                raise RuntimeError(
                    "PROFILE_GENERATION_SCHEDULER must be 'keyed' or 'rpm' "
                    "for audit-pool generation."
                )
        else:
            generation_scheduler_mode = "dedicated"

        generation_key_indexes: tuple[int, ...] = ()
        generation_key_concurrencies: tuple[int, ...] = ()
        generation_key_batch_sizes: tuple[int, ...] = ()
        if generation_key_source == "audit_pool" and generation_model:
            raw_generation_indexes = os.environ.get(
                "PROFILE_GENERATION_KEY_INDEXES",
                "",
            ).strip()
            try:
                configured_generation_indexes = tuple(
                    int(value)
                    for value in re.split(r"[\s,;]+", raw_generation_indexes)
                    if value
                )
            except ValueError as exc:
                raise RuntimeError(
                    "PROFILE_GENERATION_KEY_INDEXES must contain integers."
                ) from exc
            if not configured_generation_indexes:
                configured_generation_indexes = tuple(range(1, len(api_keys) + 1))
            if len(set(configured_generation_indexes)) != len(
                configured_generation_indexes
            ) or any(
                value < 1 or value > len(api_keys)
                for value in configured_generation_indexes
            ):
                raise RuntimeError(
                    "PROFILE_GENERATION_KEY_INDEXES must contain unique, valid "
                    "one-based audit-pool key indexes."
                )
            generation_key_indexes = tuple(
                value - 1 for value in configured_generation_indexes
            )

            def generation_slots(
                variable: str, defaults: tuple[int, ...]
            ) -> tuple[int, ...]:
                raw = os.environ.get(variable, "").strip()
                if not raw:
                    return defaults
                try:
                    values = tuple(
                        int(value) for value in re.split(r"[\s,;]+", raw) if value
                    )
                except ValueError as exc:
                    raise RuntimeError(f"{variable} must contain integers.") from exc
                if len(values) != len(generation_key_indexes) or any(
                    value <= 0 for value in values
                ):
                    raise RuntimeError(
                        f"{variable} must provide one positive value per "
                        "generation key index."
                    )
                return values

            generation_key_batch_sizes = generation_slots(
                "PROFILE_GENERATION_KEY_BATCH_SIZES",
                tuple(
                    completion_batch_sizes[index]
                    if completion_batch_sizes
                    else self.config.completion_batch_size
                    for index in generation_key_indexes
                ),
            )
            if generation_scheduler_mode == "rpm":
                if any(
                    self_rpm <= 0
                    for self_rpm in (
                        api_key_rpms[index] for index in generation_key_indexes
                    )
                ):
                    raise RuntimeError(
                        "RPM-led generation requires a positive "
                        "MY_MODEL_API_KEY_RPMS value for every selected key."
                    )
                if len(set(generation_key_batch_sizes)) != 1:
                    raise RuntimeError(
                        "RPM-led generation requires the same request batch "
                        "size for every selected key."
                    )
                generation_key_concurrencies = ()
                generation_concurrency = positive_generation_integer(
                    "PROFILE_GENERATION_CONCURRENCY",
                    self.config.llm_workers,
                )
                generation_batch_size = generation_key_batch_sizes[0]
                generation_rpm = sum(
                    api_key_rpms[index] for index in generation_key_indexes
                )
            else:
                generation_key_concurrencies = generation_slots(
                    "PROFILE_GENERATION_KEY_CONCURRENCIES",
                    tuple(
                        api_key_concurrencies[index]
                        if api_key_concurrencies
                        else max(
                            1,
                            self.config.llm_workers // len(generation_key_indexes),
                        )
                        for index in generation_key_indexes
                    ),
                )
                generation_concurrency = sum(generation_key_concurrencies)
                generation_batch_size = max(generation_key_batch_sizes)
                generation_rpm = 0
        elif generation_api_key:
            generation_concurrency = positive_generation_integer(
                "PROFILE_GENERATION_CONCURRENCY",
                20,
            )
            generation_batch_size = positive_generation_integer(
                "PROFILE_GENERATION_BATCH_SIZE",
                5,
            )
            raw_generation_rpm = os.environ.get("PROFILE_GENERATION_RPM", "").strip()
            try:
                generation_rpm = int(raw_generation_rpm or "0")
            except ValueError as exc:
                raise RuntimeError(
                    "PROFILE_GENERATION_RPM must be an integer."
                ) from exc
            if generation_rpm < 0:
                raise RuntimeError("PROFILE_GENERATION_RPM must be non-negative.")
        else:
            generation_concurrency = 1
            generation_batch_size = 1
            generation_rpm = 0

        with self._llm_rate_condition:
            if (
                api_keys != self._api_keys
                or api_key_rpms != self._api_key_rpms
                or api_key_models != self._api_key_models
                or api_key_concurrencies != self._api_key_concurrencies
                or audit_batch_sizes != self._api_key_audit_batch_sizes
                or completion_batch_sizes != self._api_key_completion_batch_sizes
                or generation_api_key != self._generation_api_key
                or generation_base_url != self._generation_base_url
                or generation_model != self._generation_model
                or generation_concurrency != self._generation_concurrency
                or generation_batch_size != self._generation_batch_size
                or generation_rpm != self._generation_rpm
                or generation_key_source != self._generation_key_source
                or generation_scheduler_mode != self._generation_scheduler_mode
                or generation_key_indexes != self._generation_key_indexes
                or generation_key_concurrencies != self._generation_key_concurrencies
                or generation_key_batch_sizes != self._generation_key_batch_sizes
            ):
                self._api_keys = api_keys
                self._api_key_rpms = api_key_rpms
                self._api_key_models = api_key_models
                self._api_key_concurrencies = api_key_concurrencies
                self._api_key_audit_batch_sizes = tuple(audit_batch_sizes)
                self._api_key_completion_batch_sizes = tuple(completion_batch_sizes)
                self._api_key_rate_limiters = [
                    RollingRateLimiter(value) if value > 0 else None
                    for value in self._api_key_rpms
                ]
                self._llm_request_times_by_key = [deque() for _ in self._api_keys]
                self._llm_requests_assigned_by_key = [0 for _ in self._api_keys]
                self._llm_key_cursor = 0
                self._generation_api_key = generation_api_key
                self._generation_base_url = generation_base_url
                self._generation_model = generation_model
                self._generation_concurrency = generation_concurrency
                self._generation_batch_size = generation_batch_size
                self._generation_rpm = generation_rpm
                self._generation_key_source = generation_key_source
                self._generation_scheduler_mode = generation_scheduler_mode
                self._generation_key_indexes = generation_key_indexes
                self._generation_key_concurrencies = generation_key_concurrencies
                self._generation_key_batch_sizes = generation_key_batch_sizes
                self._generation_rate_limiter = (
                    RollingRateLimiter(generation_rpm) if generation_rpm > 0 else None
                )
                self._record_key_scheduler_metrics()

    def _record_key_scheduler_metrics(self) -> None:
        self._llm_usage["provider_health_mode"] = (
            os.environ.get("MY_MODEL_PROVIDER_HEALTH_MODE", "gate").strip().casefold()
        )
        self._llm_usage["key_scheduler"] = {
            f"key_{index + 1}": {
                "rpm": self._api_key_rpms[index],
                "model_alias": self._api_key_models[index],
                "concurrency": (
                    self._api_key_concurrencies[index]
                    if self._api_key_concurrencies
                    else None
                ),
                "audit_batch_size": (
                    self._api_key_audit_batch_sizes[index]
                    if self._api_key_concurrencies
                    else self.config.audit_batch_size
                ),
                "completion_batch_size": (
                    self._api_key_completion_batch_sizes[index]
                    if self._api_key_concurrencies
                    else self.config.completion_batch_size
                ),
            }
            for index in range(len(self._api_keys))
        }
        self._llm_usage["generation_scheduler"] = (
            {
                "provider": self._generation_key_source,
                "model_alias": self._generation_model,
                "scheduler_mode": self._generation_scheduler_mode,
                "rpm": self._generation_rpm,
                "max_in_flight": self._generation_concurrency,
                "batch_size": self._generation_batch_size,
                "key_aliases": [
                    f"generation_key_{index + 1}"
                    for index in self._generation_key_indexes
                ],
                "key_rpms": {
                    f"generation_key_{index + 1}": self._api_key_rpms[index]
                    for index in self._generation_key_indexes
                },
                "key_concurrencies": list(self._generation_key_concurrencies),
                "key_batch_sizes": list(self._generation_key_batch_sizes),
            }
            if self._generation_model
            else {
                "provider": "audit_pool_fallback",
                "model_alias": None,
            }
        )

    def _record_provider_error_alias(
        self,
        key_alias: str,
        error: BaseException,
    ) -> None:
        with self._metrics_lock:
            errors_by_key = self._llm_usage.setdefault("provider_errors_by_key", {})
            metrics = errors_by_key.setdefault(
                key_alias,
                {"total": 0, "transient": 0, "fatal": 0, "last_error": ""},
            )
            metrics["total"] += 1
            metrics["transient"] += int(is_transient_provider_error(error))
            metrics["fatal"] += int(is_fatal_provider_error(error))
            metrics["last_error"] = str(error)[:500]

    def _record_provider_error(self, key_index: int, error: BaseException) -> None:
        self._record_provider_error_alias(f"key_{key_index + 1}", error)

    def call_llm(self, prompt: str, temperature: float | None = None) -> str:
        if self._provider_halted.is_set():
            raise ProviderHealthExceeded(
                "provider health window exceeded 5%; resume with lower concurrency"
            )
        try:
            from openai import OpenAI
        except ImportError as exc:
            raise RuntimeError(
                "OpenAI client not installed. Run: pip install openai"
            ) from exc

        provider_role = getattr(
            self._llm_request_context,
            "provider_role",
            "audit",
        )
        if provider_role == "generation":
            if self._generation_key_source == "audit_pool":
                key_index = int(getattr(self._llm_request_context, "api_key_index", -1))
                if not self._generation_model or not 0 <= key_index < len(
                    self._api_keys
                ):
                    raise RuntimeError("Audit-pool generation provider is incomplete.")
                request_api_key = self._api_keys[key_index]
                request_base_url = self.config.base_url
                request_model = self._generation_model
                key_alias = f"generation_key_{key_index + 1}"
            else:
                if not (
                    self._generation_api_key
                    and self._generation_base_url
                    and self._generation_model
                ):
                    raise RuntimeError("Dedicated generation provider is incomplete.")
                request_api_key = self._generation_api_key
                request_base_url = self._generation_base_url
                request_model = self._generation_model
                key_alias = "generation"
                key_index = -1
        else:
            key_index = int(getattr(self._llm_request_context, "api_key_index", 0))
            if not 0 <= key_index < len(self._api_keys):
                raise RuntimeError("LLM API key selection is out of range.")
            request_api_key = self._api_keys[key_index]
            request_base_url = self.config.base_url
            request_model = self._api_key_models[key_index]
            key_alias = f"key_{key_index + 1}"
        # Do not reuse provider keep-alive connections across requests.  The
        # GLM endpoint can leave an otherwise established connection waiting
        # indefinitely after one or two successful responses.  A fresh client
        # keeps retries independent and makes the configured request timeout
        # effective without changing prompts or checkpoint cache keys.
        client = OpenAI(
            base_url=request_base_url,
            api_key=request_api_key,
            timeout=self.config.llm_timeout,
            max_retries=0,
        )
        request_kwargs: dict[str, Any] = {
            "model": request_model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": (
                self.config.temperature if temperature is None else temperature
            ),
            "response_format": {"type": "json_object"},
        }
        if request_model.casefold() in {"glm-5.2", "glm5-2"}:
            request_kwargs["reasoning_effort"] = "none"
        close = getattr(client, "close", None)
        watchdog: threading.Timer | None = None
        if callable(close):
            # The provider has been observed keeping an established socket
            # open far beyond the SDK timeout. Closing the request-scoped
            # transport from a watchdog thread forces the blocked call to
            # return so normal retries and the rolling health gate can run.
            watchdog = threading.Timer(self.config.llm_timeout, close)
            watchdog.daemon = True
            watchdog.start()
        try:
            response = client.chat.completions.create(**request_kwargs)
        except Exception as exc:
            self._record_provider_error_alias(key_alias, exc)
            if is_fatal_provider_error(exc):
                self._provider_halted.set()
                raise FatalProviderError(f"{key_alias}: {exc}") from exc
            health_tripped = self._provider_health.record(
                is_transient_provider_error(exc)
            )
            health_mode = (
                os.environ.get("MY_MODEL_PROVIDER_HEALTH_MODE", "gate")
                .strip()
                .casefold()
            )
            if health_mode not in {"gate", "retry"}:
                raise RuntimeError(
                    "MY_MODEL_PROVIDER_HEALTH_MODE must be 'gate' or 'retry'."
                ) from exc
            if health_tripped and health_mode == "gate":
                self._provider_halted.set()
                raise ProviderHealthExceeded(
                    "provider health window exceeded 5%; resume with lower "
                    f"concurrency; {key_alias}: {exc}"
                ) from exc
            raise RuntimeError(f"{key_alias} provider request failed: {exc}") from exc
        finally:
            if watchdog is not None:
                watchdog.cancel()
            if callable(close):
                try:
                    close()
                except Exception:
                    # Closing a completed/failed transport must never mask the
                    # provider result that drives retry and health semantics.
                    pass
        self._provider_health.record(False)
        usage = getattr(response, "usage", None)
        if usage is not None:
            prompt_tokens = int(getattr(usage, "prompt_tokens", 0) or 0)
            completion_tokens = int(getattr(usage, "completion_tokens", 0) or 0)
            total_tokens = int(
                getattr(usage, "total_tokens", prompt_tokens + completion_tokens) or 0
            )
            with self._metrics_lock:
                provider_tokens = self._llm_usage["provider_tokens"]
                provider_tokens["prompt"] += prompt_tokens
                provider_tokens["completion"] += completion_tokens
                provider_tokens["total"] += total_tokens
        content = response.choices[0].message.content
        if not content:
            raise RuntimeError("LLM returned an empty response.")
        return content


def parse_json_output(raw: str) -> dict[str, Any]:
    text = raw.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else text
    if text.endswith("```"):
        text = text[:-3].strip()
    return json.loads(text)
