from __future__ import annotations

from collections import defaultdict
from typing import Dict, Iterable, List, Tuple

from .live_table import DISPLAY_EXCHANGE
from .models import FeeRecord


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


def _normalize_direct_level(exchange: str, level: str) -> str:
    cleaned = (level or "").strip()
    if not cleaned:
        return ""

    exchange = exchange.lower()
    upper = cleaned.upper()

    if exchange == "binance":
        return cleaned if cleaned.startswith("V") else (f"V{cleaned}" if cleaned.isdigit() else cleaned)
    if exchange in {"gate", "kucoin", "bitget"}:
        return cleaned if upper.startswith("VIP") else (f"VIP {cleaned}" if cleaned.isdigit() else cleaned)
    if exchange == "deribit":
        if upper.startswith("VIP") and cleaned[3:].isdigit():
            return f"VIP {cleaned[3:]}"
        return cleaned
    if exchange == "coinbase":
        return cleaned.replace("_", " ").title()
    if exchange == "bybit":
        if any(token in upper for token in ["VIP", "PRO", "MM"]):
            return cleaned.replace("-", " ")
        return ""
    return cleaned


def build_account_level_rows(
    records: Iterable[FeeRecord],
    reference_rows: List[Dict[str, str]],
) -> List[Dict[str, str]]:
    grouped: Dict[Tuple[str, str], List[FeeRecord]] = defaultdict(list)
    for record in records:
        grouped[(record.exchange, record.account)].append(record)

    level_rows: List[Dict[str, str]] = []
    for (exchange, account), group in grouped.items():
        display_exchange = _display_exchange_name(exchange)

        direct_candidates = {
            _normalize_direct_level(exchange, record.vip_level)
            for record in group
            if record.status == "ok"
        }
        direct_candidates.discard("")

        inferred_candidates = {
            _infer_vip_tier(
                display_exchange,
                record.product,
                record.maker_rate,
                record.taker_rate,
                reference_rows,
            )
            for record in group
            if record.status == "ok"
        }
        inferred_candidates.discard("")

        chosen_level = ""
        level_source = ""
        note = ""
        if len(direct_candidates) == 1:
            chosen_level = next(iter(direct_candidates))
            level_source = "api"
        elif len(inferred_candidates) == 1:
            chosen_level = next(iter(inferred_candidates))
            level_source = "reference_match"
        elif len(direct_candidates) > 1:
            level_source = "ambiguous_api"
            note = f"Multiple direct levels found: {sorted(direct_candidates)}"
        elif len(inferred_candidates) > 1:
            level_source = "ambiguous_reference"
            note = f"Multiple inferred levels found: {sorted(inferred_candidates)}"
        else:
            level_source = "unresolved"
            note = "No direct or uniquely inferred account level was found."

        matched_products = [
            record.product
            for record in group
            if record.status == "ok"
            and (
                _normalize_direct_level(exchange, record.vip_level) == chosen_level
                or _infer_vip_tier(
                    display_exchange,
                    record.product,
                    record.maker_rate,
                    record.taker_rate,
                    reference_rows,
                )
                == chosen_level
            )
        ]

        level_rows.append(
            {
                "exchange_key": exchange,
                "exchange": display_exchange,
                "account": account,
                "account_level": chosen_level,
                "level_source": level_source,
                "matched_products": ",".join(matched_products),
                "note": note,
            }
        )

    level_rows.sort(key=lambda row: (row["exchange"], row["account"]))
    return level_rows


def apply_account_levels(
    records: Iterable[FeeRecord],
    level_rows: Iterable[Dict[str, str]],
) -> List[FeeRecord]:
    level_map = {
        (row["exchange"].lower(), row["account"]): row["account_level"]
        for row in level_rows
        if row["account_level"]
    }

    updated: List[FeeRecord] = []
    for record in records:
        account_level = level_map.get((_display_exchange_name(record.exchange).lower(), record.account))
        if account_level:
            record.vip_level = account_level
        updated.append(record)
    return updated
