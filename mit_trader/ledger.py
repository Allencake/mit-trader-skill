"""Paper ledger (JSON). Nothing here talks to a real broker."""
from datetime import datetime

from .common import cost_rate, read_json, write_json


def ledger_path(cfg):
    return cfg["_home"] / "paper_ledger.json"


def load_ledger(cfg):
    led = read_json(ledger_path(cfg), None)
    if led is None:
        eq = float(cfg["account"]["starting_equity"])
        led = {"cash": eq, "positions": {}, "history": [], "equity_marks": {}}
    return led


def save_ledger(cfg, led):
    write_json(ledger_path(cfg), led)


def mark_to_market(led, prices):
    """prices: {symbol: last close}. Returns equity and per-position value."""
    eq = led["cash"]
    for sym, p in led["positions"].items():
        px = prices.get(sym, p["avg_price"])
        eq += p["qty"] * px
    return eq


def fill(cfg, led, symbol, qty, ref_price, note, ticket_id=None, stop=None):
    """Paper fill at ref_price with fee + slippage. qty>0 buy, qty<0 sell/short."""
    rate = cost_rate(cfg, symbol)
    side = 1 if qty > 0 else -1
    px = ref_price * (1 + side * rate)
    led["cash"] -= qty * px
    pos = led["positions"].get(symbol, {"qty": 0.0, "avg_price": px})
    new_qty = pos["qty"] + qty
    if abs(new_qty) < 1e-12:
        led["positions"].pop(symbol, None)
    else:
        if pos["qty"] == 0 or (pos["qty"] > 0) == (qty > 0):
            pos["avg_price"] = (pos["qty"] * pos["avg_price"] + qty * px) / new_qty
        pos["qty"] = new_qty
        if stop is not None:
            pos["stop"] = stop
        if ticket_id:
            pos["ticket"] = ticket_id
        led["positions"][symbol] = pos
    led["history"].append({"time": datetime.now().isoformat(timespec="seconds"), "symbol": symbol, "qty": qty,
                           "price": round(px, 6), "ticket": ticket_id, "note": note})
    return px
