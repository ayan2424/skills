#!/usr/bin/env python3
"""Deterministic helpers for experiment sample size, binary significance, and 2-arm SRM."""

from __future__ import annotations

import argparse
import json
import math
from statistics import NormalDist


NORMAL = NormalDist()


def _probability(value: float, name: str, open_interval: bool = False) -> None:
    lower_ok = value > 0 if open_interval else value >= 0
    upper_ok = value < 1 if open_interval else value <= 1
    if not (lower_ok and upper_ok):
        boundary = "(0, 1)" if open_interval else "[0, 1]"
        raise ValueError(f"{name} must be in {boundary}")


def binary_sample_size(
    baseline: float,
    mde: float,
    effect_scale: str,
    alpha: float,
    power: float,
    allocation_ratio: float,
    alternative: str,
    design_effect: float,
    attrition: float,
) -> dict[str, float | int | str]:
    _probability(baseline, "baseline", open_interval=True)
    _probability(alpha, "alpha", open_interval=True)
    _probability(power, "power", open_interval=True)
    _probability(attrition, "attrition")
    if mde <= 0 or allocation_ratio <= 0 or design_effect < 1 or attrition >= 1:
        raise ValueError("mde and allocation_ratio must be positive; design_effect >= 1; attrition < 1")
    if effect_scale == "absolute":
        delta = mde
    elif effect_scale == "relative":
        delta = baseline * mde
    else:
        raise ValueError("binary metrics support absolute or relative MDE")
    treatment = baseline + delta
    if not 0 < treatment < 1:
        raise ValueError("baseline + MDE must remain in (0, 1)")
    ratio = allocation_ratio
    alpha_tail = alpha / 2 if alternative == "two_sided" else alpha
    z_alpha = NORMAL.inv_cdf(1 - alpha_tail)
    z_power = NORMAL.inv_cdf(power)
    pooled = (baseline + ratio * treatment) / (1 + ratio)
    null_term = math.sqrt(pooled * (1 - pooled) * (1 + 1 / ratio))
    alt_term = math.sqrt(baseline * (1 - baseline) + treatment * (1 - treatment) / ratio)
    control_raw = math.ceil(((z_alpha * null_term + z_power * alt_term) / delta) ** 2)
    treatment_raw = math.ceil(control_raw * ratio)
    inflation = design_effect / (1 - attrition)
    control = math.ceil(control_raw * inflation)
    treatment_n = math.ceil(treatment_raw * inflation)
    return {
        "metric_type": "binary",
        "baseline": baseline,
        "target": treatment,
        "absolute_mde": delta,
        "control_sample_size_raw": control_raw,
        "treatment_sample_size_raw": treatment_raw,
        "control_sample_size": control,
        "treatment_sample_size": treatment_n,
        "total_sample_size": control + treatment_n,
        "method": "normal approximation for two independent proportions",
    }


def continuous_sample_size(
    standard_deviation: float,
    mde: float,
    effect_scale: str,
    baseline_mean: float | None,
    alpha: float,
    power: float,
    allocation_ratio: float,
    alternative: str,
    design_effect: float,
    attrition: float,
) -> dict[str, float | int | str]:
    _probability(alpha, "alpha", open_interval=True)
    _probability(power, "power", open_interval=True)
    _probability(attrition, "attrition")
    if standard_deviation <= 0 or mde <= 0 or allocation_ratio <= 0 or design_effect < 1 or attrition >= 1:
        raise ValueError("standard_deviation, mde and allocation_ratio must be positive; design_effect >= 1; attrition < 1")
    if effect_scale == "absolute":
        delta = mde
    elif effect_scale == "standardized":
        delta = mde * standard_deviation
    elif effect_scale == "relative":
        if baseline_mean is None or baseline_mean == 0:
            raise ValueError("continuous relative MDE requires a non-zero baseline_mean")
        delta = abs(baseline_mean) * mde
    else:
        raise ValueError("unsupported effect scale")
    alpha_tail = alpha / 2 if alternative == "two_sided" else alpha
    z_alpha = NORMAL.inv_cdf(1 - alpha_tail)
    z_power = NORMAL.inv_cdf(power)
    control_raw = math.ceil(((z_alpha + z_power) * standard_deviation / delta) ** 2 * (1 + 1 / allocation_ratio))
    treatment_raw = math.ceil(control_raw * allocation_ratio)
    inflation = design_effect / (1 - attrition)
    control = math.ceil(control_raw * inflation)
    treatment_n = math.ceil(treatment_raw * inflation)
    return {
        "metric_type": "continuous",
        "standard_deviation": standard_deviation,
        "absolute_mde": delta,
        "control_sample_size_raw": control_raw,
        "treatment_sample_size_raw": treatment_raw,
        "control_sample_size": control,
        "treatment_sample_size": treatment_n,
        "total_sample_size": control + treatment_n,
        "method": "normal approximation for two independent means",
    }


def binary_significance(control_success: int, control_n: int, treatment_success: int, treatment_n: int, alpha: float, alternative: str) -> dict[str, float | int | bool | None | list[float | None] | str]:
    _probability(alpha, "alpha", open_interval=True)
    if min(control_success, treatment_success) < 0 or control_n <= 0 or treatment_n <= 0:
        raise ValueError("counts must be non-negative and sample sizes positive")
    if control_success > control_n or treatment_success > treatment_n:
        raise ValueError("successes cannot exceed sample size")
    p0 = control_success / control_n
    p1 = treatment_success / treatment_n
    effect = p1 - p0
    pooled = (control_success + treatment_success) / (control_n + treatment_n)
    pooled_se = math.sqrt(pooled * (1 - pooled) * (1 / control_n + 1 / treatment_n))
    z = effect / pooled_se if pooled_se else 0.0
    if alternative == "two_sided":
        p_value = 2 * (1 - NORMAL.cdf(abs(z)))
        critical = NORMAL.inv_cdf(1 - alpha / 2)
        bounds: list[float | None] = [effect - critical * math.sqrt(p0 * (1 - p0) / control_n + p1 * (1 - p1) / treatment_n), effect + critical * math.sqrt(p0 * (1 - p0) / control_n + p1 * (1 - p1) / treatment_n)]
    elif alternative == "greater":
        p_value = 1 - NORMAL.cdf(z)
        critical = NORMAL.inv_cdf(1 - alpha)
        bounds = [effect - critical * math.sqrt(p0 * (1 - p0) / control_n + p1 * (1 - p1) / treatment_n), None]
    elif alternative == "less":
        p_value = NORMAL.cdf(z)
        critical = NORMAL.inv_cdf(1 - alpha)
        bounds = [None, effect + critical * math.sqrt(p0 * (1 - p0) / control_n + p1 * (1 - p1) / treatment_n)]
    else:
        raise ValueError("alternative must be two_sided, greater, or less")
    return {
        "control_success": control_success,
        "control_n": control_n,
        "control_rate": p0,
        "treatment_success": treatment_success,
        "treatment_n": treatment_n,
        "treatment_rate": p1,
        "absolute_effect": effect,
        "relative_uplift": effect / p0 if p0 else None,
        "confidence_interval": bounds,
        "z_statistic": z,
        "p_value": max(0.0, min(1.0, p_value)),
        "alpha": alpha,
        "statistically_significant": p_value < alpha,
        "method": "pooled two-proportion z-test; unpooled Wald effect interval",
    }


def srm_two_arm(control_n: int, treatment_n: int, treatment_to_control_ratio: float, alpha: float) -> dict[str, float | int | bool | str]:
    _probability(alpha, "alpha", open_interval=True)
    if control_n < 0 or treatment_n < 0 or control_n + treatment_n == 0 or treatment_to_control_ratio <= 0:
        raise ValueError("observed counts must be non-negative with positive total and expected ratio")
    total = control_n + treatment_n
    expected_control = total / (1 + treatment_to_control_ratio)
    expected_treatment = total - expected_control
    chi_square = (control_n - expected_control) ** 2 / expected_control + (treatment_n - expected_treatment) ** 2 / expected_treatment
    p_value = math.erfc(math.sqrt(chi_square / 2))
    return {
        "control_n": control_n,
        "treatment_n": treatment_n,
        "expected_treatment_to_control_ratio": treatment_to_control_ratio,
        "chi_square": chi_square,
        "p_value": p_value,
        "alpha": alpha,
        "srm_detected": p_value < alpha,
        "method": "chi-square goodness-of-fit, 1 degree of freedom",
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    sample = sub.add_parser("sample-size")
    sample.add_argument("--metric-type", choices=["binary", "continuous"], required=True)
    sample.add_argument("--baseline", type=float)
    sample.add_argument("--baseline-mean", type=float)
    sample.add_argument("--standard-deviation", type=float)
    sample.add_argument("--mde", type=float, required=True)
    sample.add_argument("--effect-scale", choices=["absolute", "relative", "standardized"], required=True)
    sample.add_argument("--alpha", type=float, default=0.05)
    sample.add_argument("--power", type=float, default=0.8)
    sample.add_argument("--allocation-ratio", type=float, default=1.0)
    sample.add_argument("--alternative", choices=["two_sided", "one_sided"], default="two_sided")
    sample.add_argument("--design-effect", type=float, default=1.0)
    sample.add_argument("--attrition", type=float, default=0.0)
    test = sub.add_parser("binary-test")
    test.add_argument("--control-success", type=int, required=True)
    test.add_argument("--control-n", type=int, required=True)
    test.add_argument("--treatment-success", type=int, required=True)
    test.add_argument("--treatment-n", type=int, required=True)
    test.add_argument("--alpha", type=float, default=0.05)
    test.add_argument("--alternative", choices=["two_sided", "greater", "less"], default="two_sided")
    srm = sub.add_parser("srm")
    srm.add_argument("--control-n", type=int, required=True)
    srm.add_argument("--treatment-n", type=int, required=True)
    srm.add_argument("--expected-ratio", type=float, default=1.0)
    srm.add_argument("--alpha", type=float, default=0.01)
    sub.add_parser("self-test")
    return parser


def self_test() -> dict[str, str]:
    binary = binary_sample_size(0.10, 0.01, "absolute", 0.05, 0.8, 1, "two_sided", 1, 0)
    assert binary["control_sample_size"] > 1000
    continuous = continuous_sample_size(10, 2, "absolute", None, 0.05, 0.8, 1, "two_sided", 1, 0)
    assert continuous["total_sample_size"] > 0
    neutral = binary_significance(100, 1000, 100, 1000, 0.05, "two_sided")
    assert neutral["p_value"] == 1.0 and neutral["absolute_effect"] == 0
    balanced = srm_two_arm(500, 500, 1, 0.01)
    assert balanced["p_value"] == 1.0 and not balanced["srm_detected"]
    return {"status": "passed"}


def main() -> int:
    args = build_parser().parse_args()
    try:
        if args.command == "sample-size":
            if args.metric_type == "binary":
                if args.baseline is None:
                    raise ValueError("binary sample size requires --baseline")
                result = binary_sample_size(args.baseline, args.mde, args.effect_scale, args.alpha, args.power, args.allocation_ratio, args.alternative, args.design_effect, args.attrition)
            else:
                if args.standard_deviation is None:
                    raise ValueError("continuous sample size requires --standard-deviation")
                result = continuous_sample_size(args.standard_deviation, args.mde, args.effect_scale, args.baseline_mean, args.alpha, args.power, args.allocation_ratio, args.alternative, args.design_effect, args.attrition)
        elif args.command == "binary-test":
            result = binary_significance(args.control_success, args.control_n, args.treatment_success, args.treatment_n, args.alpha, args.alternative)
        elif args.command == "srm":
            result = srm_two_arm(args.control_n, args.treatment_n, args.expected_ratio, args.alpha)
        else:
            result = self_test()
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except ValueError as exc:
        print(json.dumps({"status": "error", "message": str(exc)}, ensure_ascii=False))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
