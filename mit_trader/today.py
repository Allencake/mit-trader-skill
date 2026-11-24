"""/mit-trader today: which approved strategies fire today, GARCH stop, Monte Carlo + Kelly size,
portfolio VaR and user limits. Output = trade tickets waiting for the user's "yes"."""
from datetime import date

import numpy as np
import pandas as pd

from .common import ann_factor, cost_rate, read_json, write_json
from .data import get_prices
from .ledger import fill, load_ledger, mark_to_market, save_ledger
from .strategies import FAMILY_BY_KEY


def garch_sigma(returns, window):
    """One-day-ahead volatility from GARCH(1,1) (lecture 9: Volatility Modeling)."""
    from arch import arch_model
    r = returns.dropna().iloc[-window:] * 100
    res = arch_model(r, vol="GARCH", p=1, q=1, mean="Constant", dist="normal").fit(disp="off")
    f = res.forecast(horizon=1, reindex=False)
    sigma = float(np.sqrt(f.variance.values[-1, 0])) / 100
    return sigma, {k: round(float(v), 6) for k, v in res.params.items()}


def monte_carlo(pool, horizon, stop_pct, cost, n_paths, seed=0):
    """Bootstrap the strategy's out-of-sample daily returns into n_paths trades of `horizon` days.
    A path that touches -stop_pct is closed at the stop."""
    pool = np.asarray(pool, float)
    if len(pool) < 30:
        return None
    rng = np.random.default_rng(seed)
    draws = rng.choice(pool, size=(n_paths, horizon), replace=True)
    paths = np.cumprod(1 + draws, axis=1) - 1
    hit = (paths <= -stop_pct).any(axis=1)
    outcome = np.where(hit, -stop_pct, paths[:, -1]) - 2 * cost
    wins, losses = outcome[outcome > 0], outcome[outcome <= 0]
    p = len(wins) / n_paths
    b = float(wins.mean()) if len(wins) else 0.0
    a = float(-losses.mean()) if len(losses) else 1e-9
    kelly = p / a - (1 - p) / b if (b > 0 and a > 0) else (-1.0 if b == 0 else 1.0)
    return {"p_win": round(p, 4), "avg_win": round(b, 5), "avg_loss": round(a, 5),
            "stop_hit_rate": round(float(hit.mean()), 4), "kelly_full": round(float(kelly), 4),
            "p5": round(float(np.percentile(outcome, 5)), 5), "median": round(float(np.median(outcome)), 5)}


def portfolio_var(book, returns, conf):
    """Historical-simulation and parametric one-day VaR (lecture 7: Value At Risk Models).
    book: {symbol: signed notional}; returns: DataFrame of daily returns."""
    syms = [s for s in book if s in returns.columns and book[s] != 0]
    if not syms:
        return 0.0, 0.0
    R = returns[syms].dropna().iloc[-500:]
    w = np.array([book[s] for s in syms])
    pnl = R.values @ w
    hist = float(-np.quantile(pnl, 1 - conf))
    from scipy.stats import norm
    sd = float(np.sqrt(w @ R.cov().values @ w))
    param = float(norm.ppf(conf) * sd - pnl.mean())
    return max(hist, 0.0), max(param, 0.0)


def _legs(strat, side, notional, prices, beta=None):
    syms = strat["symbols"]
    if len(syms) == 1:
        s = syms[0]
        return [{"symbol": s, "side": "BUY" if side > 0 else "SELL", "notional": round(notional, 2),
                 "qty": round(side * notional / prices[s], 6), "ref_price": prices[s]}]
    a, b = syms
    wa, wb = 1 / (1 + abs(beta)), abs(beta) / (1 + abs(beta))
    sb = -np.sign(beta) * side
    return [{"symbol": a, "side": "BUY" if side > 0 else "SELL", "notional": round(notional * wa, 2),
             "qty": round(side * notional * wa / prices[a], 6), "ref_price": prices[a]},
            {"symbol": b, "side": "BUY" if sb > 0 else "SELL", "notional": round(notional * wb, 2),
             "qty": round(sb * notional * wb / prices[b], 6), "ref_price": prices[b]}]


def check_stops(cfg, led, prices, log):
    for sym, p in list(led["positions"].items()):
        stop = p.get("stop")
        px = prices.get(sym)
        if stop is None or px is None:
            continue
        if (p["qty"] > 0 and px <= stop) or (p["qty"] < 0 and px >= stop):
            fill(cfg, led, sym, -p["qty"], px, "止损（模拟）", p.get("ticket"))
            log(f"止损触发（模拟账本）：{sym} 收盘 {px:.4f} 越过止损 {stop:.4f}，已平仓")


def run_today(cfg, loader=None, log=print):
    loader = loader or (lambda s: get_prices(cfg, s))
    tc, lim = cfg["today"], cfg["limits"]
    approved = read_json(cfg["_home"] / "approved.json", {"strategies": []})["strategies"]
    led = load_ledger(cfg)

    data, rets = {}, {}
    for s in set(list(led["positions"]) + [x for st in approved for x in st["symbols"]]):
        data[s] = loader(s)
        rets[s] = data[s]["close"].pct_change()
    prices = {s: float(df["close"].iloc[-1]) for s, df in data.items()}
    returns = pd.DataFrame(rets)

    check_stops(cfg, led, prices, log)
    equity = mark_to_market(led, prices)
    today_key = date.today().isoformat()
    marks = led.setdefault("equity_marks", {})
    prev = [v for k, v in sorted(marks.items()) if k < today_key]
    marks[today_key] = round(equity, 2)
    save_ledger(cfg, led)
    log(f"模拟账本权益 {equity:,.2f}（paper，非真实账户）")

    if prev and (equity / prev[-1] - 1) <= -lim["daily_loss_limit_pct"]:
        log(f"今日模拟亏损已超过上限 {lim['daily_loss_limit_pct']:.0%}，今天不出新单。")
        return []
    if not approved:
        log("候选池是空的：上一轮 research 没有策略三关全过。今天不出交易单。")
        return []

    book = {s: p["qty"] * prices[s] for s, p in led["positions"].items()}
    open_n = len(led["positions"])
    tickets, taken = [], set()
    tpath = cfg["_home"] / "tickets" / f"{today_key}.json"
    n_done = len([t for t in read_json(tpath, {"tickets": []})["tickets"] if t["status"] != "pending_approval"])
    for st in approved:
        fam = FAMILY_BY_KEY[st["family"]]
        syms = st["symbols"]
        d = data[syms[0]] if fam.kind == "single" else {"a": data[syms[0]], "b": data[syms[1]]}
        pos, ret = fam.fn(d, st["params"], cfg["research"]["allow_short"], beta=st.get("beta"))
        side = float(pos.iloc[-1])
        asof = str(pos.index[-1].date())
        if side == 0:
            log(f"· {st['id']}：今天没触发"); continue
        if any(s in led["positions"] or s in taken for s in syms):
            log(f"· {st['id']}：{'/'.join(syms)} 已有持仓或今天已出单，不重复开"); continue
        if open_n >= lim["max_open_positions"]:
            log(f"· {st['id']}：持仓数已到上限 {lim['max_open_positions']}"); continue

        sigma, gparams = garch_sigma(ret, tc["garch_window_days"])
        stop_pct = tc["stop_sigma_mult"] * sigma * np.sqrt(tc["holding_days"])
        cost = cost_rate(cfg, syms[0]) * len(syms)
        mc = monte_carlo(st["oos_inpos_returns"], tc["holding_days"], stop_pct, cost, tc["mc_paths"])
        if mc is None:
            log(f"· {st['id']}：样本外持仓天数太少，没法做蒙特卡洛，跳过"); continue
        f = tc["kelly_fraction"] * mc["kelly_full"]
        if f <= 0:
            log(f"· {st['id']}：Kelly = {mc['kelly_full']:.3f} ≤ 0，仓位为零，不下"); continue
        f = min(f, lim["max_position_pct"], lim["max_risk_per_trade_pct"] / stop_pct)
        gross_now = sum(abs(v) for v in book.values())
        f = min(f, max(lim["max_gross_exposure_pct"] - gross_now / equity, 0))
        if f <= 0:
            log(f"· {st['id']}：总敞口已到上限"); continue
        notional = f * equity
        legs = _legs(st, 1 if side > 0 else -1, notional, prices, st.get("beta"))
        for lg in legs:
            px = lg["ref_price"]
            if fam.kind == "single":
                lg["stop"] = round(px * (1 - stop_pct) if lg["side"] == "BUY" else px * (1 + stop_pct), 6)
            else:  # 配对的止损看价差，不看单腿
                lg["stop"] = None

        trial = dict(book)
        for lg in legs:
            trial[lg["symbol"]] = trial.get(lg["symbol"], 0) + (lg["notional"] if lg["side"] == "BUY" else -lg["notional"])
        var_h, var_p = portfolio_var(trial, returns, lim["var_confidence"])
        scale = 1.0
        cap = lim["max_portfolio_var_pct"] * equity
        while max(var_h, var_p) > cap and scale > 0.05:
            scale *= 0.8
            trial = dict(book)
            for lg in legs:
                trial[lg["symbol"]] = trial.get(lg["symbol"], 0) + scale * (lg["notional"] if lg["side"] == "BUY" else -lg["notional"])
            var_h, var_p = portfolio_var(trial, returns, lim["var_confidence"])
        if max(var_h, var_p) > cap:
            log(f"· {st['id']}：加上这笔组合 VaR 超上限，不下"); continue
        if scale < 1:
            for lg in legs:
                lg["notional"] = round(lg["notional"] * scale, 2); lg["qty"] = round(lg["qty"] * scale, 6)
        book = trial
        taken.update(syms)
        open_n += 1
        tid = f"T{today_key.replace('-', '')}-{n_done + len(tickets) + 1:02d}"
        tickets.append({
            "id": tid, "status": "pending_approval", "mode": "paper", "strategy": st["id"],
            "family_zh": st["family_zh"], "source": st["source"], "params": st["params"], "signal_asof": asof,
            "legs": legs, "account_fraction": round(f * scale, 4),
            "garch": {"sigma_1d": round(sigma, 5), "params": gparams, "stop_pct": round(stop_pct, 5)},
            "monte_carlo": mc, "kelly_fraction_used": tc["kelly_fraction"],
            "var_1d": {"historical": round(var_h, 2), "parametric": round(var_p, 2), "limit": round(cap, 2)},
        })

    path = cfg["_home"] / "tickets" / f"{today_key}.json"
    old = read_json(path, {"tickets": []})["tickets"]
    keep = [t for t in old if t["status"] != "pending_approval"]
    write_json(path, {"date": today_key, "tickets": keep + tickets})
    for t in tickets:
        log("")
        log(f"交易单 {t['id']}  [{t['strategy']}]  {t['family_zh']}  信号日 {t['signal_asof']}")
        for lg in t["legs"]:
            stop_txt = f"{lg['stop']:.4f}" if lg["stop"] is not None else "按价差"
            log(f"   {lg['side']:<4} {lg['symbol']:<10} 数量 {lg['qty']}  参考价 {lg['ref_price']:.4f}  止损 {stop_txt}  金额 {lg['notional']:,.2f}")
        g, m, v = t["garch"], t["monte_carlo"], t["var_1d"]
        log(f"   GARCH(1,1) 一日波动 {g['sigma_1d']:.2%} → 止损距离 {g['stop_pct']:.2%}" + ("（价差）" if len(t["legs"]) > 1 else ""))
        log(f"   蒙特卡洛 {cfg['today']['mc_paths']} 条路径：盈利概率 {m['p_win']:.1%}，平均盈 {m['avg_win']:.2%} / 平均亏 {m['avg_loss']:.2%}，"
            f"全 Kelly {m['kelly_full']:.2f} 倍账户 × {t['kelly_fraction_used']} → 再按你的上限截断，实用 {t['account_fraction']:.2%} 账户")
        log(f"   组合一日 VaR（{lim['var_confidence']:.0%}）历史法 {v['historical']:,.2f} / 参数法 {v['parametric']:,.2f}，上限 {v['limit']:,.2f}")
        log(f"   回复 yes 才会写入模拟账本：python -m mit_trader approve {t['id']} --answer yes")
    if not tickets:
        log("今天没有新交易单。")
    return tickets


def approve(cfg, ticket_id, answer, log=print):
    if cfg.get("mode") != "paper":
        raise SystemExit("本版本只支持 paper 模式，不接真实券商。")
    if answer.strip() != "yes":
        log(f"没收到 yes（收到的是 {answer!r}），交易单 {ticket_id} 不执行。")
        return False
    day = ticket_id[1:9]
    path = cfg["_home"] / "tickets" / f"{day[:4]}-{day[4:6]}-{day[6:]}.json"
    doc = read_json(path, None)
    t = next((x for x in (doc or {}).get("tickets", []) if x["id"] == ticket_id), None)
    if t is None:
        raise SystemExit(f"找不到交易单 {ticket_id}")
    if t["status"] != "pending_approval":
        log(f"交易单 {ticket_id} 状态是 {t['status']}，不重复执行。")
        return False
    led = load_ledger(cfg)
    for lg in t["legs"]:
        px = fill(cfg, led, lg["symbol"], lg["qty"], lg["ref_price"], f"批准执行（模拟）{t['strategy']}", ticket_id, lg["stop"])
        log(f"模拟成交：{lg['side']} {lg['symbol']} {lg['qty']} @ {px:.4f}")
    save_ledger(cfg, led)
    t["status"] = "filled_paper"
    write_json(path, doc)
    return True


def reject(cfg, ticket_id, log=print):
    day = ticket_id[1:9]
    path = cfg["_home"] / "tickets" / f"{day[:4]}-{day[4:6]}-{day[6:]}.json"
    doc = read_json(path, None)
    for t in (doc or {}).get("tickets", []):
        if t["id"] == ticket_id and t["status"] == "pending_approval":
            t["status"] = "rejected_by_user"; write_json(path, doc); log(f"{ticket_id} 已放弃"); return
    log(f"没有待批的 {ticket_id}")
