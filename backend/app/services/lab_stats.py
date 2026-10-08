"""Fixed inference: Fisher exact, Newcombe-Wilson, fixed-theta Welch."""
import math
from statistics import mean, variance
from scipy.stats import fisher_exact, norm, t, binomtest

ANALYSIS_VERSION = 'itt-fisher-newcombe-welch-v1'


def wilson(successes, users):
    z = float(norm.ppf(0.975))
    p = successes / users
    denominator = 1 + z*z/users
    center = (p + z*z/(2*users))/denominator
    half = z*math.sqrt(p*(1-p)/users + z*z/(4*users*users))/denominator
    return center-half, center+half


def click_effect(a, na, b, nb):
    if not na or not nb:
        return None
    if not 0 <= a <= na or not 0 <= b <= nb:
        raise ValueError('Invalid successes or denominators')
    pa, pb = a/na, b/nb
    la, ua = wilson(a, na)
    lb, ub = wilson(b, nb)
    delta = pb-pa
    return dict(control_rate=pa, treatment_rate=pb, delta=delta,
                ci_low=delta-math.sqrt((pb-lb)**2+(ua-pa)**2),
                ci_high=delta+math.sqrt((ub-pb)**2+(pa-la)**2),
                p_value=float(fisher_exact([[a,na-a],[b,nb-b]]).pvalue),
                additional_per_1000=1000*delta,
                relative_change=delta/pa if pa else None,
                test='two-sided Fisher exact', ci_method='Newcombe-Wilson 95%')


def welch(a, b):
    if len(a) < 2 or len(b) < 2:
        return None
    va, vb = variance(a)/len(a), variance(b)/len(b)
    se2 = va+vb
    delta = mean(b)-mean(a)
    if se2 == 0:
        # A degenerate sample cannot validate safety from an estimated t distribution.
        return None
    df = se2*se2/(va*va/(len(a)-1)+vb*vb/(len(b)-1))
    half = float(t.ppf(0.975,df))*math.sqrt(se2)
    return dict(delta=delta,ci_low=delta-half,ci_high=delta+half,
                standard_error=math.sqrt(se2),degrees_of_freedom=df)


def safety_effect(rows, theta, margin):
    if not rows:
        return None
    xmean = mean(r['pre_activity_days'] for r in rows)
    raw = {v:[r['activity_days'] for r in rows if r['variant']==v] for v in ('A','B')}
    adjusted = {v:[r['activity_days']-theta*(r['pre_activity_days']-xmean)
                  for r in rows if r['variant']==v] for v in ('A','B')}
    official = welch(adjusted['A'], adjusted['B'])
    reference = welch(raw['A'], raw['B'])
    return dict(official=official, raw=reference,
                raw_mean_a=mean(raw['A']) if raw['A'] else None,
                raw_mean_b=mean(raw['B']) if raw['B'] else None,
                theta=theta,margin=margin,
                passed=bool(official and official['ci_low'] > margin),
                variance_ratio=(official['standard_error']/reference['standard_error'])**2
                    if official and reference else None)


def assignment_quality(na, nb):
    total = na+nb
    if total < 100:
        return dict(status='pending',p_value=None, a=na,b=nb)
    p = float(binomtest(na,total,0.5).pvalue)
    return dict(status='pass' if p >= 0.001 else 'fail',p_value=p,a=na,b=nb)
