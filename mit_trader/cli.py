"""Command line: python -m mit_trader <research|today|approve|reject|ledger|explain> ..."""
import argparse
import sys
from pathlib import Path

from .common import ROOT, load_config


def _explain(concept):
    import yaml
    idx = yaml.safe_load(open(ROOT / "concepts" / "index.yaml", encoding="utf-8"))
    key = concept.strip().lower().replace(" ", "_")
    for k, v in idx.items():
        if key == k or key in [a.lower() for a in v.get("aliases", [])]:
            print(open(ROOT / "concepts" / v["file"], encoding="utf-8").read())
            return
    print(f"还没有「{concept}」的讲解。可用：" + "、".join(idx))


def main(argv=None):
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(prog="mit_trader")
    ap.add_argument("--config", default=None, help="配置文件路径，默认用仓库里的 config.yaml")
    sub = ap.add_subparsers(dest="cmd", required=True)
    rs = sub.add_parser("research", help="三关检验：样本外 / 运气 / 成本")
    td = sub.add_parser("today", help="今天哪些策略触发，出待批交易单")
    a = sub.add_parser("approve", help="批准一张交易单（只写模拟账本）")
    a.add_argument("ticket_id"); a.add_argument("--answer", required=True)
    r = sub.add_parser("reject", help="放弃一张交易单"); r.add_argument("ticket_id")
    lg = sub.add_parser("ledger", help="看模拟账本")
    for x in (rs, td, a, r, lg):
        x.add_argument("--planted", action="store_true", help="用合成的「埋了优势」的测试市场，检查流程，不是行情数据")
    e = sub.add_parser("explain", help="大白话讲一个概念"); e.add_argument("concept", nargs="+")
    args = ap.parse_args(argv)

    if args.cmd == "explain":
        return _explain(" ".join(args.concept))
    cfg = load_config(args.config)
    loader = None
    if getattr(args, "planted", False):
        from .planted import planted_config, planted_loader
        cfg, loader = planted_config(cfg), planted_loader
        print("【测试市场】合成数据，只用来检查流程，不是行情。")
    if args.cmd == "research":
        from .research import print_report, run_research
        print_report(run_research(cfg, loader))
    elif args.cmd == "today":
        from .today import run_today
        run_today(cfg, loader)
    elif args.cmd == "approve":
        from .today import approve
        approve(cfg, args.ticket_id, args.answer)
    elif args.cmd == "reject":
        from .today import reject
        reject(cfg, args.ticket_id)
    elif args.cmd == "ledger":
        from .ledger import load_ledger
        import json
        print(json.dumps(load_ledger(cfg), ensure_ascii=False, indent=2))
