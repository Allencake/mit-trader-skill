"""Planted-edge test market: synthetic prices, one with a real momentum edge built in.
Used to check that the pipeline can find a true edge and reject pure noise. Not market data."""
from .data import synthetic_prices

PLANTED = {
    "NOISE_A": dict(seed=1),
    "NOISE_B": dict(seed=2),
    "NOISE_C": dict(seed=3, drift=0.0006),
    "EDGE_MOM": dict(seed=5, planted_momentum=0.08),
}


def planted_config(cfg):
    cfg = dict(cfg)
    cfg["_home"] = cfg["_home"] / "planted"
    for sub in ("cache", "runs", "tickets"):
        (cfg["_home"] / sub).mkdir(parents=True, exist_ok=True)
    cfg["universe"] = {"stocks_etfs": list(PLANTED), "crypto": [], "pairs": []}
    return cfg


def planted_loader(symbol):
    return synthetic_prices(**PLANTED[symbol])
