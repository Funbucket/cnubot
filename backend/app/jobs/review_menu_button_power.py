"""Fisher power by independent-binomial enumeration, not a normal approximation."""
import argparse

from scipy.stats import binom, fisher_exact


def power(n, baseline, delta):
    a_range = range(int(binom.ppf(1e-9, n, baseline)), int(binom.ppf(1-1e-9, n, baseline))+1)
    b_range = range(int(binom.ppf(1e-9, n, baseline+delta)), int(binom.ppf(1-1e-9, n, baseline+delta))+1)
    return float(sum(binom.pmf(a, n, baseline)*binom.pmf(b, n, baseline+delta)
                     for a in a_range for b in b_range
                     if fisher_exact([[a, n-a], [b, n-b]]).pvalue < .05))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--baseline', type=float, default=55/1649)
    parser.add_argument('--total', type=int, nargs='+', default=[1200, 1600])
    parser.add_argument('--delta', type=float, nargs='+', default=[.01, .02, .025, .03])
    args = parser.parse_args()
    if any(n <= 0 or n % 2 for n in args.total) or any(not 0 < args.baseline < args.baseline+d < 1 for d in args.delta):
        parser.error('Use positive even totals and 0 < baseline < baseline+delta < 1')
    for total in args.total:
        for delta in args.delta:
            print({'total': total, 'baseline': args.baseline, 'delta': delta,
                   'power': round(power(total//2, args.baseline, delta), 4)}, flush=True)


if __name__ == '__main__':
    main()
