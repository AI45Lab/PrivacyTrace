"""Command-line interface for synthetic profile generation."""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

from agent_env.recovery import (
    FailureLedger,
    FatalProviderError,
    RecoveryContract,
    atomic_write_json,
    ensure_recovery_manifest,
    file_hashes,
    require_model,
)

from .pipeline import (
    SyntheticProfileGenerator,
)
from .schema import (
    PROFILE_PROMPT_ID,
    GeneratorConfig,
)
from .storage import (
    prune_old_profile_generation_runs,
    write_pii_diagnostics,
    write_profiles,
)
from .targets import (
    build_default_targets,
    load_targets,
    targets_to_json,
)


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Generate synthetic profiles with candidate filtering, IPF calibration, and completion."
    )
    parser.add_argument(
        "--count", type=int, default=1000, help="Number of final profiles to generate."
    )
    parser.add_argument(
        "--candidate-count",
        type=int,
        default=None,
        help=(
            "Number of base unique seeds to generate before LLM filtering. "
            "The final sample size remains --count."
        ),
    )
    parser.add_argument(
        "--target-proposal-ratio",
        type=float,
        default=0.9,
        help=(
            "Fraction of random seeds drawn from target-table conditionals; "
            "the remainder uses uniform exploration."
        ),
    )
    parser.add_argument(
        "--seed", type=int, default=42, help="Random seed for reproducibility."
    )
    parser.add_argument(
        "--targets",
        type=Path,
        default=None,
        help="Path to IPF target constraints JSON.",
    )
    parser.add_argument(
        "--write-default-targets",
        type=Path,
        default=None,
        help="Write the built-in target constraint template and exit.",
    )
    parser.add_argument("--skip-ipf", action="store_true", help="Skip IPF calibration.")
    parser.add_argument(
        "--ipf-iterations", type=int, default=500, help="Maximum IPF iterations."
    )
    parser.add_argument(
        "--ipf-min-iterations",
        type=int,
        default=500,
        help="Minimum IPF iterations before tolerance may stop calibration.",
    )
    parser.add_argument(
        "--ipf-tolerance",
        type=float,
        default=0.05,
        help="IPF max L1 stopping tolerance.",
    )
    parser.add_argument(
        "--model",
        default=None,
        help="OpenAI-compatible model name. Defaults to MY_MODEL_NAME.",
    )
    parser.add_argument(
        "--base-url",
        default=None,
        help="OpenAI-compatible base URL. Defaults to MY_MODEL_BASE_URL.",
    )
    parser.add_argument(
        "--api-key",
        default=None,
        help=(
            "Primary OpenAI-compatible API key. Defaults to MY_MODEL_API_KEY; "
            "additional keys may be set in MY_MODEL_API_KEYS."
        ),
    )
    parser.add_argument(
        "--temperature",
        type=float,
        default=1.0,
        help="LLM completion temperature. Seed audit uses 0.",
    )
    parser.add_argument(
        "--batch-size", type=int, default=25, help="Fallback LLM batch size."
    )
    parser.add_argument(
        "--audit-batch-size", type=int, default=50, help="Seed-audit batch size."
    )
    parser.add_argument(
        "--completion-batch-size",
        type=int,
        default=25,
        help="Synthetic PII completion batch size.",
    )
    parser.add_argument(
        "--llm-workers",
        type=int,
        default=50,
        help="Concurrent LLM batch workers. Use 1 for serial execution.",
    )
    parser.add_argument(
        "--llm-timeout",
        type=float,
        default=120.0,
        help="Timeout in seconds for each LLM request.",
    )
    parser.add_argument(
        "--llm-rpm",
        type=int,
        default=0,
        help=(
            "Maximum LLM requests per rolling minute for each configured API "
            "key; 0 disables client-side rate limiting. Per-key values in "
            "MY_MODEL_API_KEY_RPMS override this default."
        ),
    )
    parser.add_argument(
        "--no-progress",
        action="store_true",
        help="Disable tqdm progress bars for LLM batch stages.",
    )
    parser.add_argument(
        "--llm-retries", type=int, default=2, help="JSON response retry count."
    )
    parser.add_argument(
        "--pii-field-retries",
        type=int,
        default=3,
        help="Maximum targeted regeneration attempts for each invalid PII field.",
    )
    parser.add_argument(
        "--max-backfill-rounds",
        type=int,
        default=3,
        help="Maximum target-support backfill rounds.",
    )
    parser.add_argument(
        "--sample-trials",
        type=int,
        default=50,
        help="Without-replacement samples to compare.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("artifacts/profile_runs/latest/profiles.jsonl"),
        help="Output path.",
    )
    parser.add_argument(
        "--candidate-pool-output",
        type=Path,
        default=Path("artifacts/profile_runs/latest/candidate_pool.jsonl"),
        help=(
            "JSON Lines path for every valid completed candidate "
            "before the final IPF sample."
        ),
    )
    parser.add_argument(
        "--seed-output",
        type=Path,
        default=Path("artifacts/profile_runs/latest/seeds.jsonl"),
        help="JSONL path for the base seed skeletons.",
    )
    parser.add_argument(
        "--seed-audit-output",
        type=Path,
        default=Path("artifacts/profile_runs/latest/seed_audit.jsonl"),
        help="JSONL path for seed audit decisions and reasons.",
    )
    parser.add_argument(
        "--json-array",
        action="store_true",
        help="Write a JSON array instead of JSON Lines.",
    )
    parser.add_argument(
        "--report-output",
        type=Path,
        default=None,
        help="Optional path for generation report JSON.",
    )
    parser.add_argument(
        "--diagnostics-dir",
        type=Path,
        default=None,
        help=(
            "Optional directory for initial PII, repaired PII, field error history, "
            "and call/token metrics. Diagnostics are also written if generation fails."
        ),
    )
    parser.add_argument(
        "--checkpoint-dir",
        type=Path,
        default=None,
        help=(
            "Persist each completed LLM batch here so an interrupted run can "
            "continue without repeating completed API calls."
        ),
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        help="Resume a compatible run from --checkpoint-dir.",
    )
    parser.add_argument("--run-id")
    parser.add_argument("--max-recovery-rounds", type=int, default=3)
    return parser


def main() -> int:
    from agent_env.settings import load_project_env

    load_project_env(Path(__file__).resolve().parents[1])
    parser = build_arg_parser()
    args = parser.parse_args()

    if args.write_default_targets:
        with open(args.write_default_targets, "w", encoding="utf-8") as handle:
            json.dump(
                targets_to_json(build_default_targets()),
                handle,
                ensure_ascii=False,
                indent=2,
            )
        print(f"Default target constraints written to: {args.write_default_targets}")
        return 0

    if args.count <= 0:
        print("Error: --count must be positive.", file=sys.stderr)
        return 1
    if args.candidate_count is not None and args.candidate_count <= 0:
        print("Error: --candidate-count must be positive.", file=sys.stderr)
        return 1
    if args.candidate_count is not None and args.candidate_count < args.count:
        print(
            "Error: --candidate-count must be at least --count.",
            file=sys.stderr,
        )
        return 1
    if not 0.0 <= args.target_proposal_ratio <= 1.0:
        print(
            "Error: --target-proposal-ratio must be between 0 and 1.", file=sys.stderr
        )
        return 1
    if args.llm_workers < 1:
        print("Error: --llm-workers must be at least 1.", file=sys.stderr)
        return 1
    if args.llm_timeout <= 0:
        print("Error: --llm-timeout must be positive.", file=sys.stderr)
        return 1
    if args.llm_rpm < 0:
        print("Error: --llm-rpm must be non-negative.", file=sys.stderr)
        return 1
    if args.pii_field_retries < 0:
        print("Error: --pii-field-retries must be non-negative.", file=sys.stderr)
        return 1
    if args.resume and args.checkpoint_dir is None:
        print("Error: --resume requires --checkpoint-dir.", file=sys.stderr)
        return 1
    if args.checkpoint_dir is not None and args.seed is None:
        print("Error: --checkpoint-dir requires a fixed --seed.", file=sys.stderr)
        return 1

    resolved_model = args.model or os.environ.get("MY_MODEL_NAME", "")
    try:
        require_model(resolved_model, stage="profile generation")
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    if args.max_recovery_rounds < 0:
        print("Error: --max-recovery-rounds cannot be negative.", file=sys.stderr)
        return 1

    targets = load_targets(args.targets) if args.targets else build_default_targets()
    recovery_root = args.output.parent / "recovery"
    run_id = args.run_id or args.output.parent.name
    recovery_inputs = [args.targets.resolve()] if args.targets else []
    try:
        recovery_config = {
            "count": args.count,
            "base_candidate_seed_count": args.candidate_count,
            "target_proposal_ratio": args.target_proposal_ratio,
            "audit_batch_size": args.audit_batch_size,
            "completion_batch_size": args.completion_batch_size,
            "pii_field_retries": args.pii_field_retries,
            "max_backfill_rounds": args.max_backfill_rounds,
            "sample_trials": args.sample_trials,
            "ipf_iterations": args.ipf_iterations,
            "ipf_min_iterations": args.ipf_min_iterations,
            "ipf_tolerance": args.ipf_tolerance,
        }
        recovery_contract = RecoveryContract(
            run_id=run_id,
            phase="profile",
            model=resolved_model,
            prompt_version=PROFILE_PROMPT_ID,
            seed=args.seed,
            input_hashes=file_hashes(recovery_inputs),
            config=recovery_config,
        )
        compatible_backfill_signatures = []
        for prior_rounds in range(args.max_backfill_rounds):
            prior_config = {
                **recovery_config,
                "max_backfill_rounds": prior_rounds,
            }
            compatible_backfill_signatures.append(
                RecoveryContract(
                    run_id=run_id,
                    phase="profile",
                    model=resolved_model,
                    prompt_version=PROFILE_PROMPT_ID,
                    seed=args.seed,
                    input_hashes=file_hashes(recovery_inputs),
                    config=prior_config,
                ).signature
            )
        recovery_manifest = ensure_recovery_manifest(
            recovery_root / "manifest.json",
            recovery_contract,
            workers=args.llm_workers,
            resume=args.resume,
            compatible_contract_signatures=compatible_backfill_signatures,
        )
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    ledger = FailureLedger(recovery_root, phase="profile", run_id=run_id)
    batch_summary_path = args.output.parent / "_batch_summary.json"
    if (
        ledger.recovery_round("profile_generation", resume=args.resume)
        > args.max_recovery_rounds
    ):
        print(
            "Error: profile generation exhausted maximum recovery rounds.",
            file=sys.stderr,
        )
        return 1
    config = GeneratorConfig(
        count=args.count,
        candidate_count=args.candidate_count,
        target_proposal_ratio=args.target_proposal_ratio,
        seed=args.seed,
        model=resolved_model,
        base_url=args.base_url,
        api_key=args.api_key,
        temperature=args.temperature,
        batch_size=args.batch_size,
        audit_batch_size=args.audit_batch_size,
        completion_batch_size=args.completion_batch_size,
        llm_workers=args.llm_workers,
        llm_timeout=args.llm_timeout,
        llm_requests_per_minute=args.llm_rpm,
        show_progress=not args.no_progress,
        llm_retries=args.llm_retries,
        pii_field_retries=args.pii_field_retries,
        max_backfill_rounds=args.max_backfill_rounds,
        sample_trials=args.sample_trials,
        ipf_iterations=args.ipf_iterations,
        ipf_min_iterations=args.ipf_min_iterations,
        ipf_tolerance=args.ipf_tolerance,
        skip_ipf=args.skip_ipf,
        checkpoint_dir=args.checkpoint_dir,
        resume=args.resume,
    )
    try:
        generator = SyntheticProfileGenerator(config=config, targets=targets)
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    try:
        profiles, report = generator.generate()
    except KeyboardInterrupt:
        if args.diagnostics_dir:
            write_pii_diagnostics(args.diagnostics_dir, generator)
        generator.close_checkpoint()
        ledger.record_failure(
            "profile_generation",
            error_type="interrupted",
            error="profile generation interrupted",
            attempts=1,
            recovery_round=ledger.recovery_round(
                "profile_generation", resume=args.resume
            ),
        )
        atomic_write_json(
            batch_summary_path,
            {
                "schema_version": "1.0",
                "run_id": run_id,
                "status": "interrupted",
                "expected_profile_count": args.count,
                "completed_profile_count": 0,
                "candidate_pool_size": len(generator.candidate_pool),
                "updated_at": time.time(),
            },
        )
        print(
            "Interrupted. Re-run the same command with --resume to continue "
            "from the completed LLM batches.",
            file=sys.stderr,
        )
        return 130
    except Exception as exc:
        if args.diagnostics_dir:
            write_pii_diagnostics(args.diagnostics_dir, generator)
        if args.candidate_pool_output and generator.candidate_pool:
            write_profiles(
                args.candidate_pool_output,
                generator.candidate_pool,
                jsonl=True,
            )
        if args.seed_output and generator.seed_pool:
            write_profiles(args.seed_output, generator.seed_pool, jsonl=True)
        if args.seed_audit_output and generator.seed_audit_records:
            write_profiles(
                args.seed_audit_output,
                generator.seed_audit_records,
                jsonl=True,
            )
        if args.report_output:
            args.report_output.parent.mkdir(parents=True, exist_ok=True)
            failure_report = {
                "status": "failed_before_final_sample",
                "error": str(exc),
                "seed": args.seed,
                "model": args.model,
                "candidate_pool_size": len(generator.candidate_pool),
                "base_seed_count": len(generator.seed_pool),
                "seed_audit_record_count": len(generator.seed_audit_records),
                "ipf": generator.last_ipf_report,
                "checkpoint": generator.checkpoint_report(),
            }
            atomic_write_json(args.report_output, failure_report)
        ledger.record_failure(
            "profile_generation",
            error_type="profile_generation",
            error=str(exc),
            attempts=1,
            recovery_round=ledger.recovery_round(
                "profile_generation", resume=args.resume
            ),
        )
        atomic_write_json(
            batch_summary_path,
            {
                "schema_version": "1.0",
                "run_id": run_id,
                "status": "failed",
                "expected_profile_count": args.count,
                "completed_profile_count": 0,
                "candidate_pool_size": len(generator.candidate_pool),
                "error": str(exc),
                "updated_at": time.time(),
            },
        )
        generator.close_checkpoint()
        print(f"Error: {exc}", file=sys.stderr)
        return 42 if isinstance(exc, FatalProviderError) else 1

    if args.diagnostics_dir:
        write_pii_diagnostics(args.diagnostics_dir, generator)
    if args.candidate_pool_output:
        write_profiles(
            args.candidate_pool_output,
            generator.candidate_pool,
            jsonl=True,
        )
    if args.seed_output:
        write_profiles(args.seed_output, generator.seed_pool, jsonl=True)
    if args.seed_audit_output:
        write_profiles(
            args.seed_audit_output,
            generator.seed_audit_records,
            jsonl=True,
        )
    write_profiles(args.output, profiles, jsonl=not args.json_array)
    if args.report_output:
        atomic_write_json(args.report_output, report)
    generator.mark_checkpoint_complete()
    generator.close_checkpoint()
    ledger.resolve("profile_generation", metadata={"profiles": len(profiles)})
    recovery_manifest.update(
        {
            "status": "completed",
            "updated_at": time.time(),
            "completed_at": time.time(),
            "base_seed_count": report.get("base_seed_count"),
            "seed_audit_record_count": report.get("seed_audit_record_count"),
            "candidate_pool_size": report.get("candidate_pool_size"),
            "unresolved_failure_count": len(ledger.unresolved()),
        }
    )
    atomic_write_json(recovery_root / "manifest.json", recovery_manifest)
    atomic_write_json(
        batch_summary_path,
        {
            "schema_version": "1.0",
            "run_id": run_id,
            "status": "completed",
            "expected_profile_count": args.count,
            "completed_profile_count": len(profiles),
            "base_seed_count": report.get("base_seed_count"),
            "total_audited_seed_count": report.get("total_audited_seed_count"),
            "candidate_pool_size": report.get("candidate_pool_size"),
            "unresolved_failure_count": len(ledger.unresolved()),
            "updated_at": time.time(),
            "completed_at": time.time(),
        },
    )
    current_paths = [args.output]
    if args.candidate_pool_output:
        current_paths.append(args.candidate_pool_output)
    if args.seed_output:
        current_paths.append(args.seed_output)
    if args.seed_audit_output:
        current_paths.append(args.seed_audit_output)
    if args.report_output:
        current_paths.append(args.report_output)
    if args.diagnostics_dir:
        current_paths.append(args.diagnostics_dir)
    if args.checkpoint_dir:
        current_paths.append(args.checkpoint_dir)
    removed_runs = prune_old_profile_generation_runs(current_paths)

    print(f"Generated {len(profiles)} synthetic profiles -> {args.output}")
    if removed_runs:
        print(f"Removed {len(removed_runs)} superseded profile-generation run(s).")
    if report.get("ipf"):
        print(f"IPF iterations: {report['ipf']['iterations']}")
    if report["completion_rejected"]:
        print(f"Rejected {report['completion_rejected']} invalid completion(s).")
    return 0
