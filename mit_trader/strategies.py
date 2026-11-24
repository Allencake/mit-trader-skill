"""Strategy library. Every rule only uses data up to day t; the backtest trades it on day t+1.

Each family returns (position, asset_return) for a given parameter set:
  position: series in [-1, 1] (fraction of the slot, sign = direction)
  asset_return: daily return of the traded instrument (for pairs, the hedged spread)
"""
from dataclasses import dataclass, field
from itertools import product

import numpy as np
import pandas as pd


def _hold_state(entry_long, entry_short, exit_long, exit_short):
    """Turn entry/exit boolean series into a held position (stateful, causal)."""
    pos = np.zeros(len(entry_long))
    cur = 0.0
    el, es, xl, xs = (np.asarray(a, dtype=bool) for a in (entry_long, entry_short, exit_long, exit_short))
    for t in range(len(pos)):
        if cur > 0 and xl[t]:
            cur = 0.0
        elif cur < 0 and xs[t]:
            cur = 0.0
        if cur == 0:
            if el[t]:
                cur = 1.0
            elif es[t]:
                cur = -1.0
        pos[t] = cur
    return pos


def tsmom(data, p, allow_short, **_):
    close = data["close"]
    sig = np.sign(close / close.shift(p["lookback"]) - 1).fillna(0)
    if not allow_short:
        sig = sig.clip(lower=0)
    return sig, close.pct_change().fillna(0)


def mean_reversion(data, p, allow_short, **_):
    close = data["close"]
    w, k = p["window"], p["z_entry"]
    z = (close - close.rolling(w).mean()) / close.rolling(w).std()
    z = z.fillna(0)
    pos = _hold_state(z < -k, (z > k) & allow_short, z >= 0, z <= 0)
    return pd.Series(pos, index=close.index), close.pct_change().fillna(0)


def breakout(data, p, allow_short, **_):
    close = data["close"]
    hi = data["high"].rolling(p["entry"]).max().shift(1)
    lo = data["low"].rolling(p["entry"]).min().shift(1)
    ex_lo = data["low"].rolling(p["exit"]).min().shift(1)
    ex_hi = data["high"].rolling(p["exit"]).max().shift(1)
    pos = _hold_state(close > hi, (close < lo) & allow_short, close < ex_lo, close > ex_hi)
    return pd.Series(pos, index=close.index), close.pct_change().fillna(0)


def hedge_ratio(log_a, log_b):
    """OLS of log A on log B (Engle-Granger first step). Returns (beta, alpha)."""
    beta, alpha = np.polyfit(log_b.values, log_a.values, 1)
    return float(beta), float(alpha)


def adf_pvalue(series):
    from arch.unitroot import ADF
    return float(ADF(series.dropna().values, trend="c").pvalue)


def pairs(data, p, allow_short, train_end=None, beta=None, **_):
    a, b = data["a"]["close"], data["b"]["close"]
    df = pd.concat([a, b], axis=1, keys=["a", "b"]).dropna()
    la, lb = np.log(df["a"]), np.log(df["b"])
    if beta is None:
        fit = slice(None, train_end)
        beta, _ = hedge_ratio(la.loc[fit], lb.loc[fit])
    spread = la - beta * lb
    w, k = p["window"], p["z_entry"]
    z = ((spread - spread.rolling(w).mean()) / spread.rolling(w).std()).fillna(0)
    # 配对天然一多一空：z 低 = 买 A 卖 B
    pos = _hold_state(z < -k, z > k, z >= 0, z <= 0)
    ret = (df["a"].pct_change() - beta * df["b"].pct_change()) / (1 + abs(beta))
    return pd.Series(pos, index=df.index), ret.fillna(0)


@dataclass
class Family:
    key: str
    name_zh: str
    source: str
    fn: callable
    grid: dict = field(default_factory=dict)
    kind: str = "single"  # single | pair

    def params(self):
        keys = list(self.grid)
        return [dict(zip(keys, vals)) for vals in product(*(self.grid[k] for k in keys))]


FAMILIES = [
    Family("tsmom", "时间序列动量", "第 1 讲把 momentum 列为系统化策略的一类；规则为经典时序动量（过去 N 天涨就持有）", tsmom,
           {"lookback": [20, 60, 120, 250]}),
    Family("mean_reversion", "均值回归", "第 8 讲 时间序列（平稳性、自回归）；价格偏离均线 k 个标准差进场，回到均线离场", mean_reversion,
           {"window": [10, 20, 50], "z_entry": [1.5, 2.0]}),
    Family("breakout", "通道突破", "非课程内容：经典唐奇安通道突破，作为对照组", breakout,
           {"entry": [20, 55], "exit": [10, 20]}),
    Family("pairs", "协整配对", "第 12 讲 时间序列 III（协整）；对冲比用 Engle-Granger 两步法（课程讲协整，两步法是常用做法），价差 z 分数进出", pairs,
           {"window": [20, 60], "z_entry": [1.5, 2.0]}, kind="pair"),
]
FAMILY_BY_KEY = {f.key: f for f in FAMILIES}
