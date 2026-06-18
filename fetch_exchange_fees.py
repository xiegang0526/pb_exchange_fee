import argparse
import os

from exchange_fee.clients import TARGET_ACCOUNTS
from exchange_fee.pipeline import collect_fee_artifacts, write_json, write_tsv


BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_REFERENCE_PATH = os.path.join(BASE_DIR, "tablefee.tsv")
DEFAULT_OUTPUT_TSV = os.path.join(BASE_DIR, "exchange_fee_snapshot.tsv")
DEFAULT_OUTPUT_JSON = os.path.join(BASE_DIR, "exchange_fee_snapshot.json")
DEFAULT_REFERENCE_NORMALIZED = os.path.join(BASE_DIR, "tablefee.normalized.tsv")
DEFAULT_LIVE_NORMALIZED_TSV = os.path.join(BASE_DIR, "exchange_fee.normalized.tsv")
DEFAULT_LIVE_NORMALIZED_JSON = os.path.join(BASE_DIR, "exchange_fee.normalized.json")
DEFAULT_ACCOUNT_LEVELS_TSV = os.path.join(BASE_DIR, "exchange_account_levels.tsv")
DEFAULT_ACCOUNT_LEVELS_JSON = os.path.join(BASE_DIR, "exchange_account_levels.json")

FEE_ROW_FIELDS = [
    "exchange",
    "account",
    "product",
    "symbol",
    "vip_level",
    "maker_rate",
    "taker_rate",
    "maker_rate_percent",
    "taker_rate_percent",
    "source",
    "endpoint",
    "status",
    "fetched_at",
    "note",
    "raw",
]
NORMALIZED_ROW_FIELDS = [
    "exchange",
    "vip_tier",
    "product",
    "maker_rate_percent",
    "taker_rate_percent",
    "maker_rate",
    "taker_rate",
]
ACCOUNT_LEVEL_FIELDS = [
    "exchange_key",
    "exchange",
    "account",
    "account_level",
    "level_source",
    "matched_products",
    "note",
]


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
    parser.add_argument(
        "--account-levels-tsv",
        default=DEFAULT_ACCOUNT_LEVELS_TSV,
        help=f"Output path for the account levels TSV. Default: {DEFAULT_ACCOUNT_LEVELS_TSV}",
    )
    parser.add_argument(
        "--account-levels-json",
        default=DEFAULT_ACCOUNT_LEVELS_JSON,
        help=f"Output path for the account levels JSON. Default: {DEFAULT_ACCOUNT_LEVELS_JSON}",
    )
    args = parser.parse_args()

    accounts = dict(TARGET_ACCOUNTS)
    accounts.update(parse_account_overrides(args.account))

    artifacts = collect_fee_artifacts(args.reference, accounts)
    fee_rows = artifacts["fee_rows"]
    reference_rows = artifacts["reference_rows"]
    normalized_live_rows = artifacts["normalized_live_rows"]
    account_level_rows = artifacts["account_level_rows"]

    write_tsv(args.output_tsv, fee_rows, FEE_ROW_FIELDS)
    write_json(args.output_json, fee_rows)
    write_tsv(args.reference_output, reference_rows, NORMALIZED_ROW_FIELDS)
    write_tsv(args.normalized_output_tsv, normalized_live_rows, NORMALIZED_ROW_FIELDS)
    write_json(args.normalized_output_json, normalized_live_rows)
    write_tsv(args.account_levels_tsv, account_level_rows, ACCOUNT_LEVEL_FIELDS)
    write_json(args.account_levels_json, account_level_rows)

    ok_count = sum(1 for row in fee_rows if row["status"] == "ok")
    error_count = len(fee_rows) - ok_count
    print(f"Live fee snapshot written to: {args.output_tsv}")
    print(f"Live fee JSON written to    : {args.output_json}")
    print(f"Reference table written to  : {args.reference_output}")
    print(f"Normalized live TSV written : {args.normalized_output_tsv}")
    print(f"Normalized live JSON written: {args.normalized_output_json}")
    print(f"Account levels TSV written  : {args.account_levels_tsv}")
    print(f"Account levels JSON written : {args.account_levels_json}")
    print(f"Success rows: {ok_count}")
    print(f"Error rows  : {error_count}")


if __name__ == "__main__":
    main()
