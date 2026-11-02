"""Command-line arguments for the population-target rebuild."""

from __future__ import annotations

import argparse
from pathlib import Path

from .constants import (
    DEFAULT_AUDIT,
    DEFAULT_CACHE,
    DEFAULT_CITY_CATALOG,
    DEFAULT_IHME_GBD_2023,
    DEFAULT_TARGET,
    DEFAULT_VALUES_DOC,
)
from .pipeline import (
    rebuild_targets,
)


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--target", type=Path, default=DEFAULT_TARGET)
    parser.add_argument("--audit", type=Path, default=DEFAULT_AUDIT)
    parser.add_argument("--values-doc", type=Path, default=DEFAULT_VALUES_DOC)
    parser.add_argument("--cache-dir", type=Path, default=DEFAULT_CACHE)
    parser.add_argument(
        "--city-catalog",
        type=Path,
        default=DEFAULT_CITY_CATALOG,
    )
    parser.add_argument(
        "--ihme-gbd",
        type=Path,
        default=DEFAULT_IHME_GBD_2023,
        help=(
            "Verified IHME GBD 2023 CSV containing prevalence rates for the "
            "configured countries, sexes, ages, and causes."
        ),
    )
    parser.add_argument(
        "--income-only",
        action="store_true",
        help=(
            "Rebuild country_x_income_level plus its dependent "
            "education-by-income and age-stage-by-income joint constraints "
            "and audit metadata."
        ),
    )
    return parser


def main() -> None:
    rebuild_targets(build_arg_parser().parse_args())
