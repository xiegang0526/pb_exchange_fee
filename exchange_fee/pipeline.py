from __future__ import annotations

import csv
import json
import os
from typing import Iterable, List, Mapping, Sequence

from .account_levels import apply_account_levels, build_account_level_rows
from .clients import TARGET_ACCOUNTS, fetch_all_fee_records, fee_records_to_rows
from .live_table import build_normalized_live_table
from .reference_table import normalize_reference_table


def write_tsv(path: str, rows: List[Mapping[str, str]], fieldnames: Sequence[str] | None = None) -> None:
    if not rows and not fieldnames:
        fieldnames = []
    if rows and not fieldnames:
        fieldnames = list(rows[0].keys())
    if fieldnames is None:
        fieldnames = []
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="") as handle:
        if not fieldnames:
            return
        writer = csv.DictWriter(handle, fieldnames=list(fieldnames), delimiter="\t")
        writer.writeheader()
        writer.writerows(rows)


def write_json(path: str, rows: Iterable[Mapping[str, str]]) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(list(rows), handle, ensure_ascii=False, indent=2)


def collect_fee_artifacts(
    reference_path: str,
    accounts: dict[str, str] | None = None,
) -> dict[str, object]:
    accounts = accounts or dict(TARGET_ACCOUNTS)
    reference_rows = normalize_reference_table(reference_path)
    fee_records = fetch_all_fee_records(accounts)
    account_level_rows = build_account_level_rows(fee_records, reference_rows)
    fee_records = apply_account_levels(fee_records, account_level_rows)
    fee_rows = fee_records_to_rows(fee_records)
    normalized_live_rows = build_normalized_live_table(fee_records, reference_rows)
    return {
        "accounts": accounts,
        "reference_rows": reference_rows,
        "fee_records": fee_records,
        "fee_rows": fee_rows,
        "normalized_live_rows": normalized_live_rows,
        "account_level_rows": account_level_rows,
    }
