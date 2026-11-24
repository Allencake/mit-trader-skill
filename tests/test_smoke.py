"""Smoke test on the synthetic planted-edge market (no network).
Run: python tests/test_smoke.py   (or: pytest tests)"""
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from mit_trader.common import load_config, read_json  # noqa: E402
from mit_trader.planted import planted_config, planted_loader  # noqa: E402
from mit_trader.research import run_research  # noqa: E402
from mit_trader.stats import deflated_sharpe, sharpe  # noqa: E402
from mit_trader.today import approve, monte_carlo, run_today  # noqa: E402


def quiet(*_):
    pass


def test_pipeline():
    with tempfile.TemporaryDirectory() as tmp:
        os.environ["MIT_TRADER_HOME"] = tmp
        cfg = planted_config(load_config())
        run = run_research(cfg, planted_loader, log=quiet)
        status = {r["id"]: r["status"] for r in run["results"]}
        # 埋了优势的序列上，动量类至少一个要被找出来；纯噪声上的不应该通过
        assert any(v == "APPROVED" for k, v in status.items() if k.endswith("EDGE_MOM") and not k.startswith("mean_reversion"))
        assert not any(v == "APPROVED" for k, v in status.items() if "NOISE" in k)

        tickets = run_today(cfg, planted_loader, log=quiet)
        assert tickets, "planted 市场最后一天应该有信号"
        t = tickets[0]
        assert t["status"] == "pending_approval" and t["mode"] == "paper"
        assert 0 < t["account_fraction"] <= cfg["limits"]["max_position_pct"] + 1e-9
        assert t["var_1d"]["historical"] <= t["var_1d"]["limit"]

        assert approve(cfg, t["id"], "好的", log=quiet) is False  # 只有 yes 才执行
        assert approve(cfg, t["id"], "yes", log=quiet) is True
        assert approve(cfg, t["id"], "yes", log=quiet) is False  # 不重复执行
        led = read_json(cfg["_home"] / "paper_ledger.json", {})
        assert t["legs"][0]["symbol"] in led["positions"]


def test_kelly_zero_when_no_edge():
    import numpy as np
    pool = np.random.default_rng(0).normal(-0.002, 0.01, 2000)
    mc = monte_carlo(pool, 5, 0.03, 0.0005, 5000)
    assert mc["kelly_full"] <= 0


def test_dsr_penalises_many_trials():
    import numpy as np
    r = np.random.default_rng(1).normal(0.0005, 0.01, 1500)
    assert deflated_sharpe(r, 2, 1e-4) > deflated_sharpe(r, 200, 1e-4)
    assert abs(sharpe(r, 252)) < 5


if __name__ == "__main__":
    test_pipeline(); test_kelly_zero_when_no_edge(); test_dsr_penalises_many_trials()
    print("smoke tests passed")
