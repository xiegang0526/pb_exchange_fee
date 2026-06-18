import argparse
import os

from exchange_fee.clients import TARGET_ACCOUNTS
from exchange_fee.pipeline import collect_fee_artifacts, write_json, write_tsv
from exchange_fee.slack_report import generate_report_artifacts, send_webhook_payloads


BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_REFERENCE_PATH = os.path.join(BASE_DIR, "tablefee.tsv")
DEFAULT_TIMEZONE = "Asia/Shanghai"
DEFAULT_WEBHOOK_ENV = "FEE_REPORT_WEBHOOK_URL"

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
        description="Fetch exchange fee data, compare with yesterday, and send a Slack fee report."
    )
    parser.add_argument(
        "--account",
        action="append",
        default=[],
        help="Override account mapping, for example: --account binance=mpbncrossarb85",
    )
    parser.add_argument(
        "--reference",
        default=DEFAULT_REFERENCE_PATH,
        help=f"Reference fee table path. Default: {DEFAULT_REFERENCE_PATH}",
    )
    parser.add_argument(
        "--timezone",
        default=DEFAULT_TIMEZONE,
        help=f"Timezone for report date and yesterday comparison. Default: {DEFAULT_TIMEZONE}",
    )
    parser.add_argument(
        "--webhook-url",
        default=os.environ.get(DEFAULT_WEBHOOK_ENV, ""),
        help=f"Slack webhook URL. Defaults to env {DEFAULT_WEBHOOK_ENV}",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Generate outputs and payloads but do not send the webhook request.",
    )
    args = parser.parse_args()

    accounts = dict(TARGET_ACCOUNTS)
    accounts.update(parse_account_overrides(args.account))

    artifacts = collect_fee_artifacts(args.reference, accounts)
    write_tsv(DEFAULT_OUTPUT_TSV, artifacts["fee_rows"], FEE_ROW_FIELDS)
    write_json(DEFAULT_OUTPUT_JSON, artifacts["fee_rows"])
    write_tsv(DEFAULT_REFERENCE_NORMALIZED, artifacts["reference_rows"], NORMALIZED_ROW_FIELDS)
    write_tsv(DEFAULT_LIVE_NORMALIZED_TSV, artifacts["normalized_live_rows"], NORMALIZED_ROW_FIELDS)
    write_json(DEFAULT_LIVE_NORMALIZED_JSON, artifacts["normalized_live_rows"])
    write_tsv(DEFAULT_ACCOUNT_LEVELS_TSV, artifacts["account_level_rows"], ACCOUNT_LEVEL_FIELDS)
    write_json(DEFAULT_ACCOUNT_LEVELS_JSON, artifacts["account_level_rows"])

    report_artifacts = generate_report_artifacts(
        BASE_DIR,
        artifacts["normalized_live_rows"],
        args.timezone,
    )
    webhook_payloads = report_artifacts["payloads"]

    webhook_sent = False
    webhook_response = []
    if args.webhook_url and not args.dry_run:
        webhook_response = send_webhook_payloads(args.webhook_url, webhook_payloads)
        webhook_sent = True

    print(f"Normalized snapshot : {DEFAULT_LIVE_NORMALIZED_JSON}")
    print(f"History snapshot    : {report_artifacts['today_history_path']}")
    print(f"HTML report         : {report_artifacts['html_report_path']}")
    print(f"Webhook payload count: {len(webhook_payloads)}")
    print(f"Change count        : {len(report_artifacts['changes'])}")
    print(f"Webhook sent        : {webhook_sent}")
    if webhook_response:
        print(f"Webhook responses   : {webhook_response}")


if __name__ == "__main__":
    main()
