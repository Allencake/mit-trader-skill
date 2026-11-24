import json, os
from pathlib import Path
import yaml

ROOT = Path(__file__).resolve().parent.parent
TRADING_DAYS = 252
CRYPTO_DAYS = 365


def load_config(path=None):
    path = Path(path) if path else ROOT / "config.yaml"
    with open(path, encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    home = Path(os.environ.get("MIT_TRADER_HOME") or os.path.expanduser(cfg["data"].get("home", "~/.mit-trader")))
    cfg["_home"] = home
    for sub in ("cache", "runs", "tickets"):
        (home / sub).mkdir(parents=True, exist_ok=True)
    return cfg


def is_crypto(symbol):
    return "/" in symbol


def ann_factor(symbol):
    return CRYPTO_DAYS if is_crypto(symbol) else TRADING_DAYS


def cost_rate(cfg, symbol):
    c = cfg["costs"]
    if is_crypto(symbol):
        return (c["crypto_fee_bps"] + c["crypto_slippage_bps"]) / 1e4
    return (c["stock_fee_bps"] + c["stock_slippage_bps"]) / 1e4


def read_json(path, default):
    path = Path(path)
    if not path.exists():
        return default
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def write_json(path, obj):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2, default=str)
    tmp.replace(path)
