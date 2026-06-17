from __future__ import annotations

from collections import defaultdict
from typing import Dict, Iterable, List, Tuple

from .models import FeeRecord


DISPLAY_EXCHANGE = {
    "binance": "Binance",
    "okex": "OKX",
    "bybit": "Bybit",
    "bitget": "Bitget",
    "gate": "Gate",
    "kucoin": "KuCoin",
    "deribit": "Deribit",
    "coinbase": "Coinbase",
}


PREFERRED_SYMBOLS = {
    ("binance", "Spot"): ["BTCUSDT"],
    ("binance", "USDT-M Futures"): ["BTCUSDT"],
    ("binance", "COIN-M Futrues"): ["BTCUSD_PERP", "BTCUSD"],
    ("binance", "Options"): ["BTCUSDT", "BTC"],
    ("bybit", "Spot"): ["BTCUSDT"],
    ("bybit", "Futures"): ["BTCUSDT"],
    ("bybit", "Inverse Futures"): ["BTCUSD"],
    ("bybit", "Options"): ["BTC"],
    ("bitget", "Spot"): ["BTCUSDT"],
    ("bitget", "USDT-M Futures"): ["BTCUSDT"],
    ("bitget", "COIN-M Futures"): ["BTCUSD"],
    ("bitget", "USDC-M Futures"): ["BTCUSDC"],
    ("gate", "Spot"): ["BTC_USDT"],
    ("kucoin", "Spot"): ["BTC-USDT"],
    ("kucoin", "Futures"): ["XBTUSDTM"],
    ("okex", "Spot"): ["BTC-USDT"],
    ("okex", "Futures"): ["BTC-USD"],
    ("okex", "Options"): ["BTC-USD"],
    ("coinbase", "Spot"): ["ALL"],
}


def _display_exchange_name(exchange: str) -> str:
    return DISPLAY_EXCHANGE.get(exchange, exchange)


def _infer_vip_tier(
    exchange: str,
    product: str,
    maker_rate: str,
    taker_rate: str,
    reference_rows: Iterable[Dict[str, str]],
) -> str:
    matches = {
        row["vip_tier"]
        for row in reference_rows
        if row["exchange"].lower() == exchange.lower()
        and row["product"] == product
        and row["maker_rate"] == maker_rate
        and row["taker_rate"] == taker_rate
    }
    if len(matches) == 1:
        return next(iter(matches))
    return ""


def _record_score(record: FeeRecord, preferred_symbols: List[str]) -> Tuple[int, int]:
    success_score = 0 if record.status == "ok" else 1
    try:
        symbol_score = preferred_symbols.index(record.symbol)
    except ValueError:
        symbol_score = len(preferred_symbols) + 1
    return success_score, symbol_score


def build_normalized_live_table(
    records: Iterable[FeeRecord],
    reference_rows: List[Dict[str, str]],
) -> List[Dict[str, str]]:
    grouped: Dict[Tuple[str, str], List[FeeRecord]] = defaultdict(list)
    for record in records:
        grouped[(record.exchange, record.product)].append(record)

    reference_order = {
        (row["exchange"].lower(), row["product"]): index
        for index, row in enumerate(reference_rows)
    }

    normalized_rows: List[Dict[str, str]] = []
    for (exchange, product), group in grouped.items():
        preferred_symbols = PREFERRED_SYMBOLS.get((exchange, product), [])
        chosen = sorted(group, key=lambda item: _record_score(item, preferred_symbols))[0]
        display_exchange = _display_exchange_name(exchange)
        inferred_vip = ""
        if chosen.status == "ok":
            inferred_vip = _infer_vip_tier(
                display_exchange,
                product,
                chosen.maker_rate,
                chosen.taker_rate,
                reference_rows,
            )
        normalized_rows.append(
            {
                "exchange": display_exchange,
                "vip_tier": inferred_vip or chosen.vip_level,
                "product": product,
                "maker_rate_percent": chosen.maker_rate_percent,
                "taker_rate_percent": chosen.taker_rate_percent,
                "maker_rate": chosen.maker_rate,
                "taker_rate": chosen.taker_rate,
            }
        )

    normalized_rows.sort(
        key=lambda row: (
            reference_order.get((row["exchange"].lower(), row["product"]), 10**9),
            row["exchange"],
            row["product"],
        )
    )
    return normalized_rows
