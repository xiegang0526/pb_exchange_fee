from __future__ import annotations

from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from typing import Any, Dict


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def decimal_rate_to_percent(rate: str) -> str:
    if rate == "":
        return ""
    return f"{float(rate) * 100:.5f}%"


def percent_to_decimal(rate: str) -> str:
    cleaned = rate.strip().rstrip("%")
    if not cleaned:
        return ""
    return f"{float(cleaned) / 100:.8f}".rstrip("0").rstrip(".")


@dataclass
class FeeRecord:
    exchange: str
    account: str
    product: str
    symbol: str
    vip_level: str
    maker_rate: str
    taker_rate: str
    maker_rate_percent: str
    taker_rate_percent: str
    source: str
    endpoint: str
    status: str
    fetched_at: str
    note: str = ""
    raw: Dict[str, Any] | None = None

    def to_row(self) -> Dict[str, str]:
        row = asdict(self)
        row["raw"] = "" if self.raw is None else str(self.raw)
        return row

    @classmethod
    def success(
        cls,
        *,
        exchange: str,
        account: str,
        product: str,
        symbol: str,
        vip_level: str,
        maker_rate: str,
        taker_rate: str,
        source: str,
        endpoint: str,
        note: str = "",
        raw: Dict[str, Any] | None = None,
    ) -> "FeeRecord":
        return cls(
            exchange=exchange,
            account=account,
            product=product,
            symbol=symbol,
            vip_level=vip_level,
            maker_rate=maker_rate,
            taker_rate=taker_rate,
            maker_rate_percent=decimal_rate_to_percent(maker_rate),
            taker_rate_percent=decimal_rate_to_percent(taker_rate),
            source=source,
            endpoint=endpoint,
            status="ok",
            fetched_at=utc_now_iso(),
            note=note,
            raw=raw,
        )

    @classmethod
    def error(
        cls,
        *,
        exchange: str,
        account: str,
        product: str,
        symbol: str,
        endpoint: str,
        note: str,
    ) -> "FeeRecord":
        return cls(
            exchange=exchange,
            account=account,
            product=product,
            symbol=symbol,
            vip_level="",
            maker_rate="",
            taker_rate="",
            maker_rate_percent="",
            taker_rate_percent="",
            source="api",
            endpoint=endpoint,
            status="error",
            fetched_at=utc_now_iso(),
            note=note,
            raw=None,
        )
