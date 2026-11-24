"""Statistics for the research gates."""
import math

import numpy as np
from scipy import stats


def sharpe(r, ann):
    r = np.asarray(r, dtype=float)
    if len(r) < 2 or r.std(ddof=1) == 0:
        return 0.0
    return float(r.mean() / r.std(ddof=1) * math.sqrt(ann))


def block_permutation_pvalue(pos, ret, ann, n_perm=500, block=20, seed=0):
    """Luck test: shuffle blocks of the position series against the real returns.
    If the real Sharpe is not clearly above the shuffled ones, the edge could be luck."""
    pos, ret = np.asarray(pos, float), np.asarray(ret, float)
    obs = sharpe(pos * ret, ann)
    rng = np.random.default_rng(seed)
    n = len(pos)
    nb = int(math.ceil(n / block))
    blocks = [pos[i * block:(i + 1) * block] for i in range(nb)]
    hits = 0
    for _ in range(n_perm):
        order = rng.permutation(nb)
        shuffled = np.concatenate([blocks[i] for i in order])[:n]
        if sharpe(shuffled * ret, ann) >= obs:
            hits += 1
    return obs, (hits + 1) / (n_perm + 1)


def deflated_sharpe(r, n_trials, sr_var):
    """Deflated Sharpe ratio (Bailey & López de Prado, 2014), per-period units.
    Returns the probability that the true Sharpe is above what the best of n_trials would show by luck."""
    r = np.asarray(r, float)
    T = len(r)
    if T < 30 or r.std(ddof=1) == 0:
        return 0.0
    sr = r.mean() / r.std(ddof=1)
    g3 = stats.skew(r)
    g4 = stats.kurtosis(r, fisher=False)
    n = max(int(n_trials), 2)
    emc = 0.5772156649
    sr0 = math.sqrt(max(sr_var, 1e-12)) * ((1 - emc) * stats.norm.ppf(1 - 1 / n) + emc * stats.norm.ppf(1 - 1 / (n * math.e)))
    denom = math.sqrt(max(1 - g3 * sr + (g4 - 1) / 4 * sr ** 2, 1e-12))
    return float(stats.norm.cdf((sr - sr0) * math.sqrt(T - 1) / denom))
