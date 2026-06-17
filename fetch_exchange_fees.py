import argparse
import csv
import json
import os
from typing import Iterable, List, Mapping

from exchange_fee.clients import TARGET_ACCOUNTS, fetch_all_fee_records, fee_records_to_rows
from exchange_fee.live_table import build_normalized_live_table
from exchange_fee.reference_table import normalize_reference_table


BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_REFERENCE_PATH = os.path.join(BASE_DIR, "tablefee.tsv")
DEFAULT_OUTPUT_TSV = os.path.join(BASE_DIR, "exchange_fee_snapshot.tsv")
DEFAULT_OUTPUT_JSON = os.path.join(BASE_DIR, "exchange_fee_snapshot.json")
DEFAULT_REFERENCE_NORMALIZED = os.path.join(BASE_DIR, "tablefee.normalized.tsv")
DEFAULT_LIVE_NORMALIZED_TSV = os.path.join(BASE_DIR, "exchange_fee.normalized.tsv")
DEFAULT_LIVE_NORMALIZED_JSON = os.path.join(BASE_DIR, "exchange_fee.normalized.json")


def write_tsv(path: str, rows: List[Mapping[str, str]]) -> None:
    if not rows:
        return
    with open(path, "w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()), delimiter="\t")
        writer.writeheader()
        writer.writerows(rows)


def write_json(path: str, rows: Iterable[Mapping[str, str]]) -> None:
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(list(rows), handle, ensure_ascii=False, indent=2)


def parse_account_overrides(items: list[str]) -> dict[str, str]:
    overrides: dict[str, str] = {}
    for item in items:
        if "=" not in item:
            raise ValueError(f"Invalid --account value: {item}")
        exchange, account = item.split("=", 1)
        overrides[exchange.strip()] = account.strip()
    return overrides


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Fetch actual fee rates from exchange private APIs and normalize the local reference table."
    )
    parser.add_argument(
        "--account",
        action="append",
        default=[],
        help="Override account mapping, for example: --account binance=mpusstockbn65",
    )
    parser.add_argument(
        "--reference",
        default=DEFAULT_REFERENCE_PATH,
        help=f"Reference fee table path. Default: {DEFAULT_REFERENCE_PATH}",
    )
    parser.add_argument(
        "--output-tsv",
        default=DEFAULT_OUTPUT_TSV,
        help=f"Output path for the live fee snapshot TSV. Default: {DEFAULT_OUTPUT_TSV}",
    )
    parser.add_argument(
        "--output-json",
        default=DEFAULT_OUTPUT_JSON,
        help=f"Output path for the live fee snapshot JSON. Default: {DEFAULT_OUTPUT_JSON}",
    )
    parser.add_argument(
        "--reference-output",
        default=DEFAULT_REFERENCE_NORMALIZED,
        help=f"Output path for the normalized reference table TSV. Default: {DEFAULT_REFERENCE_NORMALIZED}",
    )
    parser.add_argument(
        "--normalized-output-tsv",
        default=DEFAULT_LIVE_NORMALIZED_TSV,
        help=f"Output path for the normalized live fee TSV. Default: {DEFAULT_LIVE_NORMALIZED_TSV}",
    )
    parser.add_argument(
        "--normalized-output-json",
        default=DEFAULT_LIVE_NORMALIZED_JSON,
        help=f"Output path for the normalized live fee JSON. Default: {DEFAULT_LIVE_NORMALIZED_JSON}",
    )
    args = parser.parse_args()

    accounts = dict(TARGET_ACCOUNTS)
    accounts.update(parse_account_overrides(args.account))

    reference_rows = normalize_reference_table(args.reference)
    fee_records = fetch_all_fee_records(accounts)
    fee_rows = fee_records_to_rows(fee_records)
    normalized_live_rows = build_normalized_live_table(fee_records, reference_rows)

    write_tsv(args.output_tsv, fee_rows)
    write_json(args.output_json, fee_rows)
    write_tsv(args.reference_output, reference_rows)
    write_tsv(args.normalized_output_tsv, normalized_live_rows)
    write_json(args.normalized_output_json, normalized_live_rows)

    ok_count = sum(1 for row in fee_rows if row["status"] == "ok")
    error_count = len(fee_rows) - ok_count
    print(f"Live fee snapshot written to: {args.output_tsv}")
    print(f"Live fee JSON written to    : {args.output_json}")
    print(f"Reference table written to  : {args.reference_output}")
    print(f"Normalized live TSV written : {args.normalized_output_tsv}")
    print(f"Normalized live JSON written: {args.normalized_output_json}")
    print(f"Success rows: {ok_count}")
    print(f"Error rows  : {error_count}")


if __name__ == "__main__":
    main()
