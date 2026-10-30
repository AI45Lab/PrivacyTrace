"""Resumable cache of completed profile-generation batches."""

from __future__ import annotations

import copy
import hashlib
import json
import sqlite3
import threading
from pathlib import Path
from typing import Any, Callable

from agent_env.recovery import atomic_write_json

from .llm import (
    ProfileLLMClient,
)
from .schema import (
    CHECKPOINT_FORMAT_VERSION,
    GeneratorConfig,
    IPFConstraint,
)


class ProfileCheckpoint:
    """Persistent LLM batch cache and resume metadata."""

    def __init__(
        self,
        config: GeneratorConfig,
        targets: list[IPFConstraint],
        llm: ProfileLLMClient,
    ) -> None:
        self.config = config
        self.targets = targets
        self.llm = llm
        self._checkpoint_lock = threading.Lock()
        self._checkpoint_connection: sqlite3.Connection | None = None
        self._checkpoint_manifest_path: Path | None = None
        self._checkpoint_metrics_path: Path | None = None
        self._checkpoint_stats: dict[str, Any] = {
            "enabled": False,
            "resumed": False,
            "cached_batches_available": 0,
            "cache_hits": 0,
            "cache_writes": 0,
            "quarantined_batches": 0,
        }
        if self.config.checkpoint_dir is not None:
            self._initialize_checkpoint()

    def _checkpoint_signature(
        self,
        *,
        max_backfill_rounds: int | None = None,
    ) -> str:
        payload = {
            "format_version": CHECKPOINT_FORMAT_VERSION,
            "count": self.config.count,
            "candidate_count": self.config.candidate_count,
            "target_proposal_ratio": self.config.target_proposal_ratio,
            "seed": self.config.seed,
            "model": self.config.model,
            "base_url": self.config.base_url,
            "temperature": self.config.temperature,
            "batch_size": self.config.batch_size,
            "audit_batch_size": self.config.audit_batch_size,
            "completion_batch_size": self.config.completion_batch_size,
            "pii_field_retries": self.config.pii_field_retries,
            "max_backfill_rounds": (
                self.config.max_backfill_rounds
                if max_backfill_rounds is None
                else max_backfill_rounds
            ),
            "sample_trials": self.config.sample_trials,
            "ipf_iterations": self.config.ipf_iterations,
            "ipf_min_iterations": self.config.ipf_min_iterations,
            "ipf_tolerance": self.config.ipf_tolerance,
            "skip_ipf": self.config.skip_ipf,
            "targets": [
                {
                    "name": constraint.name,
                    "fields": list(constraint.fields),
                    "targets": constraint.targets,
                }
                for constraint in self.targets
            ],
        }
        encoded = json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    @staticmethod
    def _write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
        atomic_write_json(path, payload)

    def _initialize_checkpoint(self) -> None:
        if self.config.seed is None:
            raise ValueError(
                "A fixed --seed is required when checkpointing is enabled."
            )
        self.llm.ensure_llm_config()
        checkpoint_dir = Path(self.config.checkpoint_dir).resolve()
        manifest_path = checkpoint_dir / "manifest.json"
        database_path = checkpoint_dir / "llm_batches.sqlite3"
        metrics_path = checkpoint_dir / "llm_usage.json"
        signature = self._checkpoint_signature()

        if self.config.resume:
            if not manifest_path.is_file():
                raise RuntimeError(
                    f"Cannot resume: checkpoint manifest does not exist: {manifest_path}"
                )
            with open(manifest_path, "r", encoding="utf-8") as handle:
                manifest = json.load(handle)
            if manifest.get("format_version") != CHECKPOINT_FORMAT_VERSION:
                raise RuntimeError(
                    "Cannot resume: checkpoint format version does not match."
                )
            if manifest.get("signature") != signature:
                # Raising the backfill ceiling only appends deterministic rounds
                # after every previously configured round has been exhausted. It
                # does not alter candidate IDs, prompts, or cache keys from those
                # completed rounds. Decreasing the ceiling remains incompatible.
                prior_ceiling_matches = any(
                    manifest.get("signature")
                    == self._checkpoint_signature(max_backfill_rounds=prior_rounds)
                    for prior_rounds in range(self.config.max_backfill_rounds)
                )
                if not prior_ceiling_matches:
                    raise RuntimeError(
                        "Cannot resume: generation settings or IPF targets do not "
                        "match the checkpoint."
                    )
                self._checkpoint_stats["extended_backfill_ceiling"] = True
        else:
            if manifest_path.exists() or database_path.exists():
                raise RuntimeError(
                    f"Checkpoint already exists at {checkpoint_dir}; pass --resume "
                    "to continue it or choose a new directory."
                )
            checkpoint_dir.mkdir(parents=True, exist_ok=True)
            self._write_json_atomic(
                manifest_path,
                {
                    "format_version": CHECKPOINT_FORMAT_VERSION,
                    "signature": signature,
                    "status": "in_progress",
                    "count": self.config.count,
                    "seed": self.config.seed,
                    "model": self.config.model,
                    "api_key_count": len(self.llm._api_keys),
                    "audit_batch_size": self.config.audit_batch_size,
                    "completion_batch_size": self.config.completion_batch_size,
                },
            )

        checkpoint_dir.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(
            database_path,
            check_same_thread=False,
            timeout=60,
        )
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA synchronous=FULL")
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS batch_cache (
                cache_key TEXT PRIMARY KEY,
                stage TEXT NOT NULL,
                candidate_count INTEGER NOT NULL,
                result_json TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS quarantined_batch_cache (
                quarantine_id INTEGER PRIMARY KEY AUTOINCREMENT,
                cache_key TEXT NOT NULL,
                stage TEXT NOT NULL,
                candidate_count INTEGER NOT NULL,
                result_json TEXT NOT NULL,
                original_created_at TEXT NOT NULL,
                quarantine_reason TEXT NOT NULL,
                quarantined_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        connection.commit()
        cached_batches = int(
            connection.execute("SELECT COUNT(*) FROM batch_cache").fetchone()[0]
        )
        self._checkpoint_connection = connection
        self._checkpoint_manifest_path = manifest_path
        self._checkpoint_metrics_path = metrics_path
        self._checkpoint_stats.update(
            {
                "enabled": True,
                "resumed": self.config.resume,
                "cached_batches_available": cached_batches,
            }
        )
        if self.config.resume and metrics_path.is_file():
            with open(metrics_path, "r", encoding="utf-8") as handle:
                saved_usage = json.load(handle)
            if isinstance(saved_usage, dict):
                self.llm._llm_usage = saved_usage
                self.llm._llm_usage.setdefault("requests_by_key", {})
                self.llm._llm_usage.setdefault("provider_errors_by_key", {})
                self.llm._record_key_scheduler_metrics()

    @staticmethod
    def _llm_batch_cache_key(
        *,
        prompt: str,
        temperature: float,
        stage: str,
        candidates: list[dict[str, Any]],
        required_fields: tuple[str, ...],
        nonempty_fields: tuple[str, ...],
        string_fields: tuple[str, ...],
        allowed_values: dict[str, set[str]] | None,
        requested_fields: tuple[str, ...] | None,
        provider_model: str | None = None,
    ) -> str:
        payload = {
            "format_version": CHECKPOINT_FORMAT_VERSION,
            "stage": stage,
            "temperature": temperature,
            "candidate_ids": [
                str(candidate["_candidate_id"]) for candidate in candidates
            ],
            "prompt": prompt,
            "required_fields": required_fields,
            "nonempty_fields": nonempty_fields,
            "string_fields": string_fields,
            "allowed_values": {
                field: sorted(values)
                for field, values in sorted((allowed_values or {}).items())
            },
            "requested_fields": requested_fields,
        }
        # Audit cache keys predate split audit/generation providers. Preserve
        # them exactly, while ensuring generation results can never be reused
        # after changing the generation model.
        if provider_model:
            payload["provider_model"] = provider_model
        encoded = json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    def _load_checkpoint_batch(
        self, cache_key: str
    ) -> dict[str, dict[str, Any]] | None:
        if self._checkpoint_connection is None:
            return None
        with self._checkpoint_lock:
            row = self._checkpoint_connection.execute(
                "SELECT result_json FROM batch_cache WHERE cache_key = ?",
                (cache_key,),
            ).fetchone()
            if row is None:
                return None
            parsed = json.loads(str(row[0]))
            self._checkpoint_stats["cache_hits"] += 1
        if not isinstance(parsed, dict):
            raise RuntimeError(f"Checkpoint batch {cache_key} is not a JSON object.")
        return parsed

    def _quarantine_checkpoint_batch(self, cache_key: str, reason: str) -> None:
        if self._checkpoint_connection is None:
            return
        with self._checkpoint_lock:
            row = self._checkpoint_connection.execute(
                """
                SELECT stage, candidate_count, result_json, created_at
                FROM batch_cache
                WHERE cache_key = ?
                """,
                (cache_key,),
            ).fetchone()
            if row is None:
                return
            self._checkpoint_connection.execute(
                """
                INSERT INTO quarantined_batch_cache
                    (cache_key, stage, candidate_count, result_json,
                     original_created_at, quarantine_reason)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (cache_key, row[0], row[1], row[2], row[3], reason),
            )
            self._checkpoint_connection.execute(
                "DELETE FROM batch_cache WHERE cache_key = ?",
                (cache_key,),
            )
            self._checkpoint_connection.commit()
            self._checkpoint_stats["quarantined_batches"] += 1
            self._checkpoint_stats["cached_batches_available"] = max(
                0,
                self._checkpoint_stats["cached_batches_available"] - 1,
            )

    @staticmethod
    def _validate_batch_result_items(
        result: dict[str, dict[str, Any]],
        result_validator: Callable[[str, dict[str, Any]], None] | None,
    ) -> None:
        if result_validator is None:
            return
        for candidate_id, item in result.items():
            result_validator(candidate_id, item)

    def _load_validated_checkpoint_batch(
        self,
        cache_key: str,
        result_validator: Callable[[str, dict[str, Any]], None] | None,
    ) -> dict[str, dict[str, Any]] | None:
        """Load one cache entry, quarantining malformed or invalid results."""

        try:
            cached = self._load_checkpoint_batch(cache_key)
        except (RuntimeError, TypeError, ValueError) as exc:
            self._quarantine_checkpoint_batch(cache_key, str(exc))
            return None
        if cached is None:
            return None
        try:
            self._validate_batch_result_items(cached, result_validator)
        except RuntimeError as exc:
            self._quarantine_checkpoint_batch(cache_key, str(exc))
            return None
        return cached

    def _persist_checkpoint_metrics(self) -> None:
        if self._checkpoint_metrics_path is None:
            return
        with self.llm._metrics_lock:
            usage = copy.deepcopy(self.llm._llm_usage)
        with self._checkpoint_lock:
            self._write_json_atomic(self._checkpoint_metrics_path, usage)

    def _store_checkpoint_batch(
        self,
        *,
        cache_key: str,
        stage: str,
        candidate_count: int,
        result: dict[str, dict[str, Any]],
    ) -> None:
        if self._checkpoint_connection is None:
            return
        serialized = json.dumps(
            result,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        with self._checkpoint_lock:
            cursor = self._checkpoint_connection.execute(
                """
                INSERT OR IGNORE INTO batch_cache
                    (cache_key, stage, candidate_count, result_json)
                VALUES (?, ?, ?, ?)
                """,
                (cache_key, stage, candidate_count, serialized),
            )
            self._checkpoint_connection.commit()
            if cursor.rowcount:
                self._checkpoint_stats["cache_writes"] += 1
                self._checkpoint_stats["cached_batches_available"] += 1
        self._persist_checkpoint_metrics()

    def checkpoint_report(self) -> dict[str, Any]:
        report = copy.deepcopy(self._checkpoint_stats)
        if self.config.checkpoint_dir is not None:
            report["directory"] = str(Path(self.config.checkpoint_dir).resolve())
        return report

    def mark_checkpoint_complete(self) -> None:
        if self._checkpoint_manifest_path is None:
            return
        with self._checkpoint_lock:
            with open(
                self._checkpoint_manifest_path,
                "r",
                encoding="utf-8",
            ) as handle:
                manifest = json.load(handle)
            manifest["status"] = "completed"
            self._write_json_atomic(self._checkpoint_manifest_path, manifest)
        self._persist_checkpoint_metrics()

    def close_checkpoint(self) -> None:
        connection = self._checkpoint_connection
        if connection is None:
            return
        with self._checkpoint_lock:
            connection.close()
            self._checkpoint_connection = None
