import math


def minimum_sample_size(
    baseline_rate: float, mde: float, alpha: float = 0.05, power: float = 0.8
) -> int:
    """Approximate per-variant sample size for a two-sided two-proportion test."""
    if not 0 < baseline_rate < 1 or mde <= 0 or mde >= 1:
        raise ValueError("baseline_rate must be between 0 and 1 and mde must be positive")
    if not 0 < alpha < 1 or not 0 < power < 1:
        raise ValueError("alpha and power must be between 0 and 1")
    target = baseline_rate + mde
    z_alpha = normal_quantile(1 - alpha / 2)
    z_power = normal_quantile(power)
    pooled = 2 * baseline_rate * (1 - baseline_rate)
    separate = baseline_rate * (1 - baseline_rate) + target * (1 - target)
    n = ((z_alpha * math.sqrt(pooled) + z_power * math.sqrt(separate)) / mde) ** 2
    return math.ceil(n)


def compare_proportions(control_successes, control_users, treatment_successes, treatment_users):
    control_rate = control_successes / control_users if control_users else 0
    treatment_rate = treatment_successes / treatment_users if treatment_users else 0
    uplift = (treatment_rate - control_rate) / control_rate if control_rate else None
    se = math.sqrt(
        (control_rate * (1 - control_rate) / control_users if control_users else 0)
        + (treatment_rate * (1 - treatment_rate) / treatment_users if treatment_users else 0)
    )
    z = (treatment_rate - control_rate) / se if se else 0
    p_value = math.erfc(abs(z) / math.sqrt(2))
    return {
        "control_rate": control_rate,
        "treatment_rate": treatment_rate,
        "uplift": uplift,
        "z_score": z,
        "p_value": p_value,
        "ci_low": (treatment_rate - control_rate) - 1.96 * se,
        "ci_high": (treatment_rate - control_rate) + 1.96 * se,
    }


def normal_quantile(p: float) -> float:
    # Peter John Acklam's rational approximation, sufficient for planning UI values.
    if p <= 0 or p >= 1:
        raise ValueError("p must be between 0 and 1")
    a = [-39.6968302866538, 220.946098424521, -275.928510446969, 138.357751867269, -30.6647980661472, 2.50662827745924]
    b = [-54.4760987982241, 161.585836858041, -155.698979859887, 66.8013118877197, -13.2806815528857]
    c = [-0.00778489400243029, -0.322396458041136, -2.40075827716184, -2.54973253934373, 4.37466414146497, 2.93816398269878]
    d = [0.00778469570904146, 0.32246712907004, 2.445134137143, 3.75440866190742]
    if p < 0.02425:
        q = math.sqrt(-2 * math.log(p))
        numerator = c[0]
        for coefficient in c[1:]:
            numerator = numerator * q + coefficient
        denominator = d[0]
        for coefficient in d[1:]:
            denominator = denominator * q + coefficient
        return numerator / (denominator * q + 1)
    if p > 1 - 0.02425:
        return -normal_quantile(1 - p)
    q = p - 0.5
    r = q * q
    numerator = a[0]
    for coefficient in a[1:]:
        numerator = numerator * r + coefficient
    denominator = b[0]
    for coefficient in b[1:]:
        denominator = denominator * r + coefficient
    numerator *= q
    denominator = denominator * r + 1
    return numerator / denominator
