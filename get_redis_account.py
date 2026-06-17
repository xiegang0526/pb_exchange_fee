import argparse
from pprint import pprint

from exchange_fee.account_store import load_account_credentials, mask_credentials


def query_account(exchange, account, reveal=False):
    credentials = load_account_credentials(exchange, account)
    if reveal:
        pprint(credentials)
        return credentials

    masked = mask_credentials(credentials)
    print(f"Exchange   : {exchange}")
    print(f"Account    : {account}")
    print(f"Access Key : {masked.get('ACCESS_KEY', masked.get('apiKey', ''))}")
    print(f"Secret Key : {masked.get('SECRET_KEY', masked.get('secret', ''))}")
    print(f"Passphrase : {masked.get('PASSPHRASE', masked.get('passphrase', ''))}")
    return credentials


def main():
    parser = argparse.ArgumentParser(description="Query account credentials from Redis.")
    parser.add_argument("exchange", help="Exchange name, for example: binance")
    parser.add_argument("account", help="Account name, for example: mpusstockbn65")
    parser.add_argument(
        "--reveal",
        action="store_true",
        help="Print the full raw credential payload. Use with care on shared machines.",
    )
    args = parser.parse_args()
    query_account(args.exchange, args.account, reveal=args.reveal)


if __name__ == "__main__":
    main()
