"""/mit-trader research: walk-forward + luck test + costs. All three gates must pass."""
from datetime import datetime

import numpy as np
import pandas as pd

from .common import ann_factor, cost_rate, write_json
from .data import get_prices
from .stats import block_permutation_pvalue, deflated_sharpe, sharpe
from .strategies import FAMILIES, adf_pvalue, hedge_ratio


def strategy_returns(pos, ret, cost):
    """Trade yesterday's signal today. Costs charged on every change in position."""
    held = pos.shift(1).fillna(0)
    gross = held * ret
    turnover = held.diff().abs().fillna(held.abs())
    return gross, gross - turnover * cost, held


def build_candidates(cfg, loader):
    """Yield (candidate_id, family, data, symbols, ann, cost)."""
    uni = cfg["universe"]
    singles = list(uni.get("stocks_etfs", [])) + list(uni.get("crypto", []))
    for fam in FAMILIES:
        if fam.kind == "single":
            for s in singles:
                yield f"{fam.key}:{s}", fam, loader(s), [s]
        else:
            for a, b in uni.get("pairs", []):
                yield f"{fam.key}:{a}~{b}", fam, {"a": loader(a), "b": loader(b)}, [a, b]


def _index_of(data):
    if "close" in data:
        return data["close"].dropna().index
    return data["a"]["close"].index.intersection(data["b"]["close"].index)


def walk_forward(fam, data, symbols, cfg):
    rc = cfg["research"]
    ann = max(ann_factor(s) for s in symbols)
    cost = cost_rate(cfg, symbols[0]) * len(symbols)
    idx = _index_of(data)
    min_train = int(rc["min_train_years"] * ann)
    if len(idx) < min_train + 2 * ann:
        return None, "数据不够长"
    tests = np.array_split(np.arange(min_train, len(idx)), rc["walk_forward_folds"])
    oos_gross, oos_net, oos_pos, folds, train_sharpes = [], [], [], [], []
    chosen = None
    for seg in tests:
        train_end, t0, t1 = idx[seg[0] - 1], idx[seg[0]], idx[seg[-1]]
        best, best_sr, best_series = None, -np.inf, None
        for p in fam.params():
            pos, ret = fam.fn(data, p, rc["allow_short"], train_end=train_end)
            pos, ret = pos.loc[:t1], ret.loc[:t1]
            g, n, held = strategy_returns(pos, ret, cost)
            sr = sharpe(n.loc[:train_end], ann)  # 只用训练段挑参数
            train_sharpes.append(sr / np.sqrt(ann))
            if sr > best_sr:
                best, best_sr, best_series = p, sr, (g, n, held, ret)
        g, n, held, ret = best_series
        oos_gross.append(g.loc[t0:t1]); oos_net.append(n.loc[t0:t1]); oos_pos.append((held.loc[t0:t1], ret.loc[t0:t1]))
        folds.append({"test_from": str(t0.date()), "test_to": str(t1.date()), "params": best,
                      "oos_gross_sharpe": round(sharpe(g.loc[t0:t1], ann), 3)})
        chosen = best
    G, N = pd.concat(oos_gross), pd.concat(oos_net)
    P = pd.concat([x[0] for x in oos_pos]); R = pd.concat([x[1] for x in oos_pos])
    return {"ann": ann, "cost": cost, "gross": G, "net": N, "pos": P, "ret": R, "folds": folds,
            "params": chosen, "train_sharpes": train_sharpes}, None


def run_research(cfg, loader=None, log=print):
    loader = loader or (lambda s: get_prices(cfg, s))
    rc = cfg["research"]
    stress = cfg["costs"]["stress_multiplier"]
    cache, results, errors = {}, [], []

    def cached(s):
        if s not in cache:
            cache[s] = loader(s)
        return cache[s]

    wf = {}
    def safe(s):
        try:
            return cached(s)
        except Exception as e:
            return e

    for cid, fam, data, symbols in build_candidates(cfg, safe):
        bad = [d for d in (data.values() if isinstance(data, dict) and "a" in data else [data]) if isinstance(d, Exception)]
        if bad:
            errors.append({"id": cid, "reason": f"取数失败：{bad[0]}"}); continue
        try:
            out, why = walk_forward(fam, data, symbols, cfg)
        except Exception as e:  # 单个标的出错不拖垮整轮
            out, why = None, f"出错：{e}"
        if out is None:
            errors.append({"id": cid, "reason": why}); continue
        wf[cid] = (fam, symbols, out)

    # 参数是在 walk-forward 的训练段里挑的，样本外不受参数搜索污染；
    # 剩下的多重测试来自「同时测了多少个候选」，所以 DSR 的试验数 = 候选数，方差取候选之间样本外 Sharpe 的方差。
    n_trials = sum(len(fam.params()) for fam, _, _ in wf.values())
    n_cand = len(wf)
    oos_sr = [float(o["gross"].mean() / o["gross"].std(ddof=1)) if o["gross"].std(ddof=1) > 0 else 0.0
              for _, _, o in wf.values()]
    sr_var = float(np.var(oos_sr)) if len(oos_sr) > 1 else 1e-4
    perm = {cid: block_permutation_pvalue(o["pos"].values, o["ret"].values, o["ann"], rc["permutations"])[1]
            for cid, (_, _, o) in wf.items()}
    # Benjamini-Hochberg：控制「通过的里面有多少是运气」的比例
    ranked = sorted(perm.items(), key=lambda kv: kv[1])
    bh_pass, m = set(), len(ranked)
    for i, (cid, pv) in enumerate(ranked, 1):
        if pv <= rc["gate_fdr_q"] * i / m:
            bh_pass = {c for c, _ in ranked[:i]}

    for cid, (fam, symbols, o) in wf.items():
        ann = o["ann"]
        gross_sr = sharpe(o["gross"], ann)
        hit = float(np.mean([f["oos_gross_sharpe"] > 0 for f in o["folds"]]))
        g1 = gross_sr >= rc["gate_oos_sharpe"] and hit >= rc["gate_fold_hit_ratio"]
        p_perm = perm[cid]
        dsr = deflated_sharpe(o["gross"].values, n_cand, sr_var)
        g2 = cid in bh_pass and dsr >= rc["gate_dsr"]
        net_sr = sharpe(o["net"], ann)
        stressed = o["gross"] - (o["gross"] - o["net"]) * stress
        stress_sr = sharpe(stressed, ann)
        g3 = net_sr >= rc["gate_net_sharpe"] and stress_sr > 0
        status = "APPROVED" if (g1 and g2 and g3) else "REJECTED"
        failed = [n for n, ok in (("样本外", g1), ("运气检验", g2), ("成本", g3)) if not ok]
        extra = {}
        if fam.kind == "pair":
            a, b = symbols
            la, lb = np.log(cache[a]["close"]), np.log(cache[b]["close"])
            j = la.index.intersection(lb.index)
            beta, alpha = hedge_ratio(la.loc[j], lb.loc[j])
            extra = {"beta": beta, "adf_p": adf_pvalue(la.loc[j] - beta * lb.loc[j])}
        in_pos = o["net"][o["pos"] != 0] * np.sign(o["pos"][o["pos"] != 0])
        results.append({
            "id": cid, "family": fam.key, "family_zh": fam.name_zh, "source": fam.source, "symbols": symbols,
            "status": status, "failed_gates": failed, "params": o["params"], **extra,
            "oos_from": o["folds"][0]["test_from"], "oos_to": o["folds"][-1]["test_to"],
            "oos_gross_sharpe": round(gross_sr, 3), "fold_hit_ratio": round(hit, 2),
            "perm_p": round(p_perm, 4), "deflated_sharpe_prob": round(dsr, 3),
            "oos_net_sharpe": round(net_sr, 3), "stress_cost_sharpe": round(stress_sr, 3),
            "folds": o["folds"],
            # today 用：样本外、持仓日、按方向折算后的每日净收益（蒙特卡洛的抽样池）
            "oos_inpos_returns": [round(float(x), 6) for x in in_pos.values],
        })

    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    run = {"run_at": datetime.now().isoformat(timespec="seconds"), "n_candidates": len(results),
           "n_param_trials": n_trials, "skipped": errors, "results": results}
    write_json(cfg["_home"] / "runs" / f"research-{stamp}.json", run)
    write_json(cfg["_home"] / "approved.json",
               {"run_at": run["run_at"], "strategies": [r for r in results if r["status"] == "APPROVED"]})
    return run


def print_report(run, log=print):
    res = run["results"]
    ok = [r for r in res if r["status"] == "APPROVED"]
    log(f"候选 {len(res)} 个（walk-forward 内共试 {run['n_param_trials']} 组参数；运气检验按 {len(res)} 个候选做多重测试校正）")
    log(f"APPROVED {len(ok)} · REJECTED {len(res) - len(ok)} · 跳过 {len(run['skipped'])}")
    log("")
    log(f"{'候选':<28}{'状态':<10}{'样本外SR':>9}{'分段胜':>7}{'置换p':>8}{'DSR':>7}{'净SR':>8}{'成本x2':>8}  未过")
    for r in sorted(res, key=lambda r: (r["status"] != "APPROVED", -r["oos_net_sharpe"])):
        log(f"{r['id']:<28}{r['status']:<10}{r['oos_gross_sharpe']:>9.2f}{r['fold_hit_ratio']:>7.2f}"
            f"{r['perm_p']:>8.3f}{r['deflated_sharpe_prob']:>7.2f}{r['oos_net_sharpe']:>8.2f}{r['stress_cost_sharpe']:>8.2f}  "
            f"{'、'.join(r['failed_gates']) or '-'}")
    for s in run["skipped"]:
        log(f"跳过 {s['id']}：{s['reason']}")
    log("")
    log("说明：以上是历史数据上的检验统计，不是收益承诺。三关全过才进入 today 的候选池。")
