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
    "krakenspot": "Kraken",
    "krakenswap": "Kraken",
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
    ("krakenspot", "Spot"): ["XXBTZUSD"],
    ("krakenswap", "Futures"): ["ALL"],
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


def _has_rate_values(record: FeeRecord) -> bool:
    return bool(
        (record.maker_rate or "").strip()
        or (record.taker_rate or "").strip()
        or (record.maker_rate_percent or "").strip()
        or (record.taker_rate_percent or "").strip()
    )


def _is_usable_record(record: FeeRecord) -> bool:
    return bool((record.product or "").strip()) and _has_rate_values(record)


def build_normalized_live_table(
    records: Iterable[FeeRecord],
    reference_rows: List[Dict[str, str]],
) -> List[Dict[str, str]]:
    grouped: Dict[Tuple[str, str], List[FeeRecord]] = defaultdict(list)
    for record in records:
        if not (record.product or "").strip():
            continue
        grouped[(record.exchange, record.product)].append(record)

    reference_order = {
        (row["exchange"].lower(), row["product"]): index
        for index, row in enumerate(reference_rows)
    }

    best_actual_rows: Dict[Tuple[str, str], FeeRecord] = {}
    inferred_exchange_vip: Dict[str, str] = {}

    for (exchange, product), group in grouped.items():
        preferred_symbols = PREFERRED_SYMBOLS.get((exchange, product), [])
        chosen = sorted(group, key=lambda item: _record_score(item, preferred_symbols))[0]
        best_actual_rows[(exchange, product)] = chosen
        display_exchange = _display_exchange_name(exchange)
        if chosen.status == "ok":
            inferred_vip = _infer_vip_tier(
                display_exchange,
                product,
                chosen.maker_rate,
                chosen.taker_rate,
                reference_rows,
            )
            if inferred_vip:
                inferred_exchange_vip.setdefault(display_exchange, inferred_vip)
            elif chosen.vip_level:
                inferred_exchange_vip.setdefault(display_exchange, chosen.vip_level)

    normalized_rows: List[Dict[str, str]] = []
    emitted_keys: set[Tuple[str, str]] = set()

    for reference_row in reference_rows:
        display_exchange = reference_row["exchange"]
        product = reference_row["product"]
        exchange_key = next(
            (key for key, value in DISPLAY_EXCHANGE.items() if value == display_exchange),
            display_exchange.lower(),
        )
        inferred_vip = inferred_exchange_vip.get(display_exchange, "")
        if inferred_vip and inferred_vip != reference_row["vip_tier"]:
            continue

        actual = best_actual_rows.get((exchange_key, product))
        if actual is not None and actual.status == "ok" and _is_usable_record(actual):
            normalized_rows.append(
                {
                    "exchange": display_exchange,
                    "vip_tier": inferred_vip or actual.vip_level or reference_row["vip_tier"],
                    "product": product,
                    "maker_rate_percent": actual.maker_rate_percent,
                    "taker_rate_percent": actual.taker_rate_percent,
                    "maker_rate": actual.maker_rate,
                    "taker_rate": actual.taker_rate,
                }
            )
        elif inferred_vip:
            normalized_rows.append(
                {
                    "exchange": display_exchange,
                    "vip_tier": reference_row["vip_tier"],
                    "product": product,
                    "maker_rate_percent": reference_row["maker_rate_percent"],
                    "taker_rate_percent": reference_row["taker_rate_percent"],
                    "maker_rate": reference_row["maker_rate"],
                    "taker_rate": reference_row["taker_rate"],
                }
            )
        else:
            continue
        emitted_keys.add((display_exchange, product))

    for (exchange, product), chosen in best_actual_rows.items():
        display_exchange = _display_exchange_name(exchange)
        if (display_exchange, product) in emitted_keys:
            continue
        if chosen.status != "ok" or not _is_usable_record(chosen):
            continue
        inferred_vip = ""
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
