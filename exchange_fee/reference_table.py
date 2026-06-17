import csv
from typing import Dict, List

from .models import percent_to_decimal


def normalize_reference_table(table_path: str) -> List[Dict[str, str]]:
    records: Dict[tuple[str, str, str], Dict[str, str]] = {}
    current_exchange = ""
    current_vip = ""
    current_trading = ""

    with open(table_path, "r", encoding="utf-8") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        for row in reader:
            current_exchange = (row.get("Exchange") or "").strip() or current_exchange
            current_vip = (row.get("VIP Tier") or "").strip() or current_vip
            current_trading = (row.get("Trading") or "").strip() or current_trading
            fee_type = (row.get("Fee Type") or "").strip()
            fee_rate = (row.get("Fee rate") or "").strip()
            if not fee_type or not fee_rate:
                continue
            key = (current_exchange, current_vip, current_trading)
            bucket = records.setdefault(key, {})
            bucket[fee_type.lower()] = fee_rate

    normalized: List[Dict[str, str]] = []
    for (exchange, vip_tier, trading), bucket in records.items():
        maker = bucket.get("maker", "")
        taker = bucket.get("taker", "")
        normalized.append(
            {
                "exchange": exchange,
                "vip_tier": vip_tier,
                "product": trading,
                "maker_rate_percent": maker,
                "taker_rate_percent": taker,
                "maker_rate": percent_to_decimal(maker),
                "taker_rate": percent_to_decimal(taker),
            }
        )

    return normalized
