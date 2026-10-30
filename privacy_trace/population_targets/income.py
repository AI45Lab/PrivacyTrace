"""Income targets and conditional welfare-profile transfers."""

from __future__ import annotations

import io
import json
import urllib.parse
import urllib.request
import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

from .common import (
    grouped_education_margins,
    normalize,
)
from .constants import (
    COUNTRY_CODES,
    INCOME_LEVELS,
    INCOME_MEDIAN_MULTIPLIERS,
    MAX_DIRECT_WELFARE_GROUP_SHARE_RATIO,
    MIN_DIRECT_WELFARE_GROUP_SHARE_RATIO,
    PIP_URL,
    WELFARE_AGE_TYPES,
    WELFARE_EDUCATION_LEVEL_TO_GROUP,
    WELFARE_EDUCATION_TYPES,
)


def latest_national_pip_row(
    rows: list[dict[str, Any]], *, require_median: bool = False
) -> dict[str, Any]:
    eligible = [
        row
        for row in rows
        if row.get("reporting_level") == "national"
        and row.get("headcount") is not None
        and (not require_median or row.get("median") is not None)
    ]
    if not eligible:
        raise RuntimeError("PIP returned no eligible national observations.")
    observed = [row for row in eligible if not bool(row.get("is_interpolated"))]
    return max(
        observed or eligible,
        key=lambda row: (
            int(row["reporting_year"]),
            int(row.get("survey_year") or 0),
        ),
    )


def matching_pip_row(
    rows: list[dict[str, Any]], reference: dict[str, Any]
) -> dict[str, Any]:
    identity_fields = (
        "reporting_year",
        "survey_year",
        "reporting_level",
        "welfare_type",
        "is_interpolated",
    )
    matches = [
        row
        for row in rows
        if row.get("headcount") is not None
        and all(row.get(field) == reference.get(field) for field in identity_fields)
    ]
    if not matches:
        raise RuntimeError(
            "PIP did not return the selected distribution at the requested threshold."
        )
    return matches[0]


def fetch_pip_rows(cache: Path) -> dict[str, Any]:
    cache_file = cache / "pip_2021_ppp_relative_median_headcounts.json"
    if cache_file.exists():
        output: dict[str, dict[str, Any]] = json.loads(
            cache_file.read_text(encoding="utf-8")
        )
    else:
        output = {}

    def request_rows(iso3: str, year: str | int, line: float) -> list[dict[str, Any]]:
        url = PIP_URL.format(country=iso3, year=year, line=f"{line:.8f}")
        last_error: Exception | None = None
        for _ in range(4):
            try:
                request = urllib.request.Request(
                    url, headers={"User-Agent": "Mozilla/5.0"}
                )
                with urllib.request.urlopen(request, timeout=240) as response:
                    return json.load(response)
            except Exception as exc:
                last_error = exc
        raise RuntimeError(f"PIP request failed for {iso3}: {last_error}")

    def fetch_country(country: str, iso3: str) -> tuple[str, dict[str, Any]]:
        reference = latest_national_pip_row(
            request_rows(iso3, "all", 1.0), require_median=True
        )
        median = float(reference["median"])
        thresholds = {
            str(multiplier): median * multiplier
            for multiplier in INCOME_MEDIAN_MULTIPLIERS
        }
        headcounts = {}
        for multiplier, threshold in thresholds.items():
            rows = request_rows(iso3, int(reference["reporting_year"]), threshold)
            headcounts[multiplier] = float(
                matching_pip_row(rows, reference)["headcount"]
            )
        return country, {
            "reporting_year": int(reference["reporting_year"]),
            "survey_year": reference.get("survey_year"),
            "is_interpolated": bool(reference.get("is_interpolated")),
            "welfare_type": reference["welfare_type"],
            "median_2021_ppp_usd_per_day": median,
            "thresholds_2021_ppp_usd_per_day": thresholds,
            "headcounts": headcounts,
        }

    with ThreadPoolExecutor(max_workers=10) as executor:
        futures = {}
        for country, info in COUNTRY_CODES.items():
            if country in output:
                continue
            future = executor.submit(fetch_country, country, info["iso3"])
            futures[future] = country
        for future in as_completed(futures):
            country, row = future.result()
            output[country] = row
    cache_file.parent.mkdir(parents=True, exist_ok=True)
    cache_file.write_text(
        json.dumps(output, indent=2, sort_keys=True), encoding="utf-8"
    )
    return output


def build_income_targets(
    country_mass: dict[str, float], pip_rows: dict[str, Any]
) -> tuple[dict[str, float], dict[str, Any]]:
    targets: dict[str, float] = {}
    audit: dict[str, Any] = {}
    for country, mass in country_mass.items():
        row = pip_rows[country]
        headcounts = [
            float(row["headcounts"][str(multiplier)])
            for multiplier in INCOME_MEDIAN_MULTIPLIERS
        ]
        shares = [
            headcounts[0],
            headcounts[1] - headcounts[0],
            headcounts[2] - headcounts[1],
            headcounts[3] - headcounts[2],
            1.0 - headcounts[3],
        ]
        shares = list(
            normalize({str(i): value for i, value in enumerate(shares)}).values()
        )
        for label, share in zip(INCOME_LEVELS, shares):
            targets[f"{country} | {label}"] = mass * share
        audit[country] = {
            "reporting_year": row["reporting_year"],
            "survey_year": row.get("survey_year"),
            "is_interpolated": row.get("is_interpolated", False),
            "welfare_type": row["welfare_type"],
            "median_2021_ppp_usd_per_day": row["median_2021_ppp_usd_per_day"],
            "thresholds_2021_ppp_usd_per_day": row["thresholds_2021_ppp_usd_per_day"],
            "headcounts_by_median_multiplier": row["headcounts"],
            "income_level_shares": {
                label: share for label, share in zip(INCOME_LEVELS, shares)
            },
        }
    return targets, audit


def load_world_bank_welfare_profile(path: Path) -> Any:
    try:
        import pandas
    except ImportError as exc:
        raise RuntimeError(
            "The World Bank education-welfare Stata file requires pandas. "
            "Install project requirements and rerun."
        ) from exc
    with zipfile.ZipFile(path) as archive:
        member = next(
            (
                name
                for name in archive.namelist()
                if name.endswith("global_profile_lineup_2022_country_level.dta")
            ),
            None,
        )
        if member is None:
            raise RuntimeError(
                "World Bank reproducibility package is missing the welfare "
                "profile Stata file."
            )
        return pandas.read_stata(
            io.BytesIO(archive.read(member)),
            convert_categoricals=False,
        )


def build_conditioned_income_targets(
    *,
    country_mass: dict[str, float],
    conditioned_margins: dict[str, float],
    income_targets: dict[str, float],
    welfare_rows: Any,
    group_source_types: dict[str, str],
    dimension_name: str,
) -> tuple[dict[str, float], dict[str, Any]]:
    """Transfer a World Bank conditioned welfare profile to relative bands.

    The source identifies group-specific shares below $2.15 and $6.85. PIP
    identifies the mass in this project's five median-relative bands. Within
    each observed welfare-rank interval, maximum entropy is the
    least-informative allocation that preserves both sets of margins.
    """

    source_types = set(group_source_types.values())
    frame = welfare_rows[welfare_rows["type"].isin(source_types)].copy()
    direct: dict[tuple[str, str], dict[str, Any]] = {}
    for row in frame.itertuples(index=False):
        direct[(str(row.country_code), str(row.type))] = {
            "region": str(row.region),
            "hc215": min(1.0, max(0.0, float(row.hc215))),
            "hc685": min(1.0, max(0.0, float(row.hc685))),
            "pop": max(0.0, float(row.pop)),
        }

    region_rates: dict[tuple[str, str], dict[str, float]] = {}
    for region in sorted(str(value) for value in frame["region"].unique()):
        for source_type in source_types:
            rows = [
                row
                for (iso3, row_type), row in direct.items()
                if row_type == source_type and row["region"] == region
            ]
            population = sum(row["pop"] for row in rows)
            if population <= 0:
                continue
            region_rates[(region, source_type)] = {
                "hc215": sum(row["pop"] * row["hc215"] for row in rows) / population,
                "hc685": sum(row["pop"] * row["hc685"] for row in rows) / population,
            }

    targets: dict[str, float] = {}
    audit: dict[str, Any] = {}
    for country, info in COUNTRY_CODES.items():
        iso3 = info["iso3"]
        country_rows = [row for (code, _), row in direct.items() if code == iso3]
        source_country_population = sum(row["pop"] for row in country_rows)
        region = country_rows[0]["region"] if country_rows else "OHI"
        group_margins = {
            group: conditioned_margins[f"{country} | {group}"]
            for group in group_source_types
        }
        group_shares = {
            group: value / country_mass[country]
            for group, value in group_margins.items()
        }
        direct_share_ratios = {}
        for group, source_type in group_source_types.items():
            source_row = direct.get((iso3, source_type))
            source_share = (
                source_row["pop"] / source_country_population
                if source_row is not None and source_country_population > 0
                else None
            )
            margin_share = group_shares[group]
            direct_share_ratios[group] = (
                source_share / margin_share
                if source_share is not None and margin_share > 1e-12
                else None
            )
        country_dimension_reliable = all(
            direct.get((iso3, source_type)) is not None
            and (
                direct_share_ratios[group] is None
                or (
                    MIN_DIRECT_WELFARE_GROUP_SHARE_RATIO
                    <= direct_share_ratios[group]
                    <= MAX_DIRECT_WELFARE_GROUP_SHARE_RATIO
                )
            )
            for group, source_type in group_source_types.items()
        )
        conditional: dict[str, dict[str, float]] = {}
        provenance: dict[str, str] = {}
        source_population_shares: dict[str, float | None] = {}
        source_to_margin_share_ratios: dict[str, float | None] = {}
        for group, source_type in group_source_types.items():
            row = direct.get((iso3, source_type))
            source_share = (
                row["pop"] / source_country_population
                if row is not None and source_country_population > 0
                else None
            )
            margin_share = group_shares[group]
            share_ratio = direct_share_ratios[group]
            source_population_shares[group] = source_share
            source_to_margin_share_ratios[group] = share_ratio
            direct_row_reliable = (
                row is not None
                and country_dimension_reliable
                and (
                    share_ratio is None
                    or (
                        MIN_DIRECT_WELFARE_GROUP_SHARE_RATIO
                        <= share_ratio
                        <= MAX_DIRECT_WELFARE_GROUP_SHARE_RATIO
                    )
                )
            )
            if direct_row_reliable:
                conditional[group] = {
                    "hc215": row["hc215"],
                    "hc685": max(row["hc215"], row["hc685"]),
                }
                provenance[group] = "country_direct"
            else:
                proxy = region_rates.get((region, source_type))
                if proxy is None:
                    proxy = region_rates[("OHI", source_type)]
                conditional[group] = {
                    "hc215": proxy["hc215"],
                    "hc685": max(proxy["hc215"], proxy["hc685"]),
                }
                reason = (
                    "country_dimension_population_share_mismatch"
                    if row is not None and not country_dimension_reliable
                    else "direct_group_population_share_mismatch"
                    if row is not None
                    else "country_group_missing"
                )
                provenance[group] = f"world_bank_region_proxy:{region}:{reason}"

        q215 = sum(
            group_shares[group] * conditional[group]["hc215"]
            for group in group_source_types
        )
        q685 = sum(
            group_shares[group] * conditional[group]["hc685"]
            for group in group_source_types
        )
        q685 = max(q215, q685)
        welfare_zones = [
            (0.0, q215, "below_2.15"),
            (q215, q685, "2.15_to_6.85"),
            (q685, 1.0, "above_6.85"),
        ]

        income_shares = {
            level: income_targets[f"{country} | {level}"] / country_mass[country]
            for level in INCOME_LEVELS
        }
        income_intervals = []
        lower = 0.0
        for level in INCOME_LEVELS:
            upper = lower + income_shares[level]
            income_intervals.append((lower, upper, level))
            lower = upper
        income_intervals[-1] = (
            income_intervals[-1][0],
            1.0,
            income_intervals[-1][2],
        )

        country_joint = {
            (group, level): 0.0
            for group in group_source_types
            for level in INCOME_LEVELS
        }
        for group in group_source_types:
            zone_conditional = {
                "below_2.15": conditional[group]["hc215"],
                "2.15_to_6.85": (
                    conditional[group]["hc685"] - conditional[group]["hc215"]
                ),
                "above_6.85": 1.0 - conditional[group]["hc685"],
            }
            for zone_low, zone_high, zone_name in welfare_zones:
                zone_width = zone_high - zone_low
                group_zone_mass = group_shares[group] * zone_conditional[zone_name]
                if zone_width <= 1e-15:
                    continue
                for income_low, income_high, level in income_intervals:
                    overlap = max(
                        0.0,
                        min(zone_high, income_high) - max(zone_low, income_low),
                    )
                    if overlap > 0:
                        country_joint[(group, level)] += (
                            group_zone_mass * overlap / zone_width
                        )

        for (group, level), value in country_joint.items():
            targets[f"{country} | {group} | {level}"] = country_mass[country] * value
        row_error = max(
            abs(
                sum(country_joint[(group, level)] for level in INCOME_LEVELS)
                - group_shares[group]
            )
            for group in group_source_types
        )
        column_error = max(
            abs(
                sum(country_joint[(group, level)] for group in group_source_types)
                - income_shares[level]
            )
            for level in INCOME_LEVELS
        )
        if max(row_error, column_error) > 1e-8:
            raise RuntimeError(
                f"{dimension_name}-income transfer failed margins for {country}: "
                f"row={row_error}, column={column_error}"
            )
        audit[country] = {
            "conditioned_dimension": dimension_name,
            "world_bank_region": region,
            "source_provenance": provenance,
            "source_group_population_shares": source_population_shares,
            "conditioned_margin_shares": group_shares,
            "source_to_conditioned_share_ratios": (source_to_margin_share_ratios),
            "direct_group_share_ratio_acceptance": {
                "minimum": MIN_DIRECT_WELFARE_GROUP_SHARE_RATIO,
                "maximum": MAX_DIRECT_WELFARE_GROUP_SHARE_RATIO,
            },
            "country_dimension_direct_accepted": (country_dimension_reliable),
            "conditioned_headcounts": conditional,
            "implied_welfare_rank_cuts": {
                "2.15": q215,
                "6.85": q685,
            },
            "maximum_entropy_scope": (
                "within each of the three observed welfare-rank intervals"
            ),
            "maximum_margin_error": max(row_error, column_error),
        }
    return targets, audit


def build_education_income_targets(
    *,
    country_mass: dict[str, float],
    education_targets: dict[str, float],
    income_targets: dict[str, float],
    welfare_rows: Any,
) -> tuple[dict[str, float], dict[str, Any]]:
    conditioned_margins = {
        f"{country} | {group}": value
        for country in COUNTRY_CODES
        for group, value in grouped_education_margins(
            education_targets,
            country,
            WELFARE_EDUCATION_LEVEL_TO_GROUP,
        ).items()
    }
    return build_conditioned_income_targets(
        country_mass=country_mass,
        conditioned_margins=conditioned_margins,
        income_targets=income_targets,
        welfare_rows=welfare_rows,
        group_source_types=WELFARE_EDUCATION_TYPES,
        dimension_name="education",
    )


def build_age_income_targets(
    *,
    country_mass: dict[str, float],
    country_age_sex_targets: dict[str, float],
    income_targets: dict[str, float],
    welfare_rows: Any,
) -> tuple[dict[str, float], dict[str, Any]]:
    conditioned_margins: dict[str, float] = {}
    for country in COUNTRY_CODES:
        youth = sum(
            country_age_sex_targets[f"{country} | 18-24 | {sex}"]
            for sex in ("female", "male")
        )
        conditioned_margins[f"{country} | youth"] = youth
        conditioned_margins[f"{country} | adult"] = country_mass[country] - youth
    return build_conditioned_income_targets(
        country_mass=country_mass,
        conditioned_margins=conditioned_margins,
        income_targets=income_targets,
        welfare_rows=welfare_rows,
        group_source_types=WELFARE_AGE_TYPES,
        dimension_name="age_stage",
    )
