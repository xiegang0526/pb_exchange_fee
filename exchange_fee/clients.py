from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Dict, Iterable, List
from urllib.parse import urlencode

import requests

from .account_store import load_account_credentials
from .models import FeeRecord


TARGET_ACCOUNTS = {
    "bitget": "mpusstockbg28",
    "bybit": "mpusstockbybit45",
    "binance": "mpbnellenmm85",
    "gate": "mpusstockgate52",
    "kucoin": "mpusstockkucoin23",
    "okex": "mpusstockokx45",
    "deribit": "mpusstockderibit15",
    "coinbase": "mpusstockcb11",
    "krakenspot": "mpusstockkraken14",
    "krakenswap": "mpusstockkraken14",
}


DEFAULT_TIMEOUT = 15


@dataclass(frozen=True)
class QueryTarget:
    product: str
    symbol: str
    category: str = ""
    inst_type: str = ""
    inst_family: str = ""
    settle: str = ""


def _compact_error(response: requests.Response) -> str:
    text = response.text.strip().replace("\n", " ")
    return f"HTTP {response.status_code}: {text[:300]}"


def _get_required(credentials: Dict[str, str], *names: str) -> str:
    for name in names:
        value = credentials.get(name)
        if value:
            return value
    raise KeyError(f"Missing credential field: {', '.join(names)}")


def _percent_string_to_decimal(rate_percent: str) -> str:
    cleaned = str(rate_percent).strip()
    if cleaned == "":
        return ""
    return f"{float(cleaned) / 100:.8f}".rstrip("0").rstrip(".")


class ExchangeClient:
    exchange = ""

    def __init__(self, account: str, credentials: Dict[str, str]):
        self.account = account
        self.credentials = credentials
        self.session = requests.Session()

    def fetch(self) -> List[FeeRecord]:
        raise NotImplementedError

    def error_record(self, product: str, symbol: str, endpoint: str, exc: Exception) -> FeeRecord:
        return FeeRecord.error(
            exchange=self.exchange,
            account=self.account,
            product=product,
            symbol=symbol,
            endpoint=endpoint,
            note=str(exc),
        )


class BinanceClient(ExchangeClient):
    exchange = "binance"
    spot_base = "https://api.binance.com"
    usdt_futures_base = "https://fapi.binance.com"
    coin_futures_base = "https://dapi.binance.com"
    options_base = "https://eapi.binance.com"

    def _query_account_level(self) -> str:
        endpoints = [
            (self.usdt_futures_base, "/fapi/v1/accountConfig", "feeTier"),
            (self.usdt_futures_base, "/fapi/v2/account", "feeTier"),
        ]
        for base_url, path, field_name in endpoints:
            try:
                payload = self._signed_get(
                    base_url,
                    path,
                    {"timestamp": str(int(time.time() * 1000))},
                )
                fee_tier = payload.get(field_name)
                if fee_tier not in (None, ""):
                    return f"V{fee_tier}"
            except Exception:
                continue
        return ""

    def _signed_get(self, base_url: str, path: str, params: Dict[str, str]) -> Dict[str, object]:
        query = urlencode(params)
        secret = _get_required(self.credentials, "SECRET_KEY")
        signature = hmac.new(secret.encode(), query.encode(), hashlib.sha256).hexdigest()
        headers = {"X-MBX-APIKEY": _get_required(self.credentials, "ACCESS_KEY")}
        response = self.session.get(
            f"{base_url}{path}",
            params={**params, "signature": signature},
            headers=headers,
            timeout=DEFAULT_TIMEOUT,
        )
        if response.status_code >= 400:
            raise RuntimeError(_compact_error(response))
        return response.json()

    def fetch(self) -> List[FeeRecord]:
        records: List[FeeRecord] = []
        account_level = self._query_account_level()
        targets = [
            QueryTarget("Spot", "BTCUSDT"),
            QueryTarget("USDT-M Futures", "BTCUSDT"),
            QueryTarget("COIN-M Futrues", "BTCUSD_PERP"),
        ]
        now_ms = str(int(time.time() * 1000))
        endpoint_map = {
            "Spot": (self.spot_base, "/api/v3/account/commission"),
            "USDT-M Futures": (self.usdt_futures_base, "/fapi/v1/commissionRate"),
            "COIN-M Futrues": (self.coin_futures_base, "/dapi/v1/commissionRate"),
        }
        for target in targets:
            base_url, path = endpoint_map[target.product]
            params = {"symbol": target.symbol, "timestamp": now_ms}
            try:
                payload = self._signed_get(base_url, path, params)
                if target.product == "Spot":
                    standard = payload.get("standardCommission", {})
                    maker_rate = str(standard.get("maker", ""))
                    taker_rate = str(standard.get("taker", ""))
                    note = "Uses standardCommission from Binance spot account commission."
                else:
                    maker_rate = str(payload.get("makerCommissionRate", ""))
                    taker_rate = str(payload.get("takerCommissionRate", ""))
                    note = ""
                records.append(
                    FeeRecord.success(
                        exchange=self.exchange,
                        account=self.account,
                        product=target.product,
                        symbol=target.symbol,
                        vip_level=account_level,
                        maker_rate=maker_rate,
                        taker_rate=taker_rate,
                        source="api",
                        endpoint=path,
                        note=note,
                        raw=payload,
                    )
                )
            except Exception as exc:
                records.append(self.error_record(target.product, target.symbol, path, exc))

        try:
            payload = self._signed_get(
                self.options_base,
                "/eapi/v1/commission",
                {"timestamp": str(int(time.time() * 1000))},
            )
            if isinstance(payload, dict):
                items = payload.get("commissions", [])
            elif isinstance(payload, list):
                items = payload
            else:
                items = []
            if not items:
                raise RuntimeError(f"Unexpected options payload: {payload}")
            target = next(
                (
                    item
                    for item in items
                    if isinstance(item, dict) and str(item.get("underlying", "")).upper() == "BTCUSDT"
                ),
                items[0],
            )
            if not isinstance(target, dict):
                raise RuntimeError(f"Unexpected options payload: {payload}")
            records.append(
                FeeRecord.success(
                    exchange=self.exchange,
                    account=self.account,
                    product="Options",
                    symbol=str(target.get("underlying", "BTCUSDT")),
                    vip_level=account_level,
                    maker_rate=str(
                        target.get("makerCommissionRate", target.get("makerFee", ""))
                    ),
                    taker_rate=str(
                        target.get("takerCommissionRate", target.get("takerFee", ""))
                    ),
                    source="api",
                    endpoint="/eapi/v1/commission",
                    raw=target,
                )
            )
        except Exception as exc:
            records.append(self.error_record("Options", "", "/eapi/v1/commission", exc))
        return records


class BybitClient(ExchangeClient):
    exchange = "bybit"
    base_url = "https://api.bybit.com"

    def _signed_get(self, path: str, params: Dict[str, str]) -> Dict[str, object]:
        timestamp = str(int(time.time() * 1000))
        recv_window = "5000"
        api_key = _get_required(self.credentials, "ACCESS_KEY")
        secret = _get_required(self.credentials, "SECRET_KEY")
        query = urlencode(params)
        payload = f"{timestamp}{api_key}{recv_window}{query}"
        signature = hmac.new(secret.encode(), payload.encode(), hashlib.sha256).hexdigest()
        headers = {
            "X-BAPI-API-KEY": api_key,
            "X-BAPI-TIMESTAMP": timestamp,
            "X-BAPI-RECV-WINDOW": recv_window,
            "X-BAPI-SIGN": signature,
        }
        response = self.session.get(
            f"{self.base_url}{path}",
            params=params,
            headers=headers,
            timeout=DEFAULT_TIMEOUT,
        )
        if response.status_code >= 400:
            raise RuntimeError(_compact_error(response))
        data = response.json()
        if data.get("retCode") != 0:
            raise RuntimeError(str(data))
        return data

    def fetch(self) -> List[FeeRecord]:
        records: List[FeeRecord] = []
        targets = [
            QueryTarget("Spot", "BTCUSDT", category="spot"),
            QueryTarget("Futures", "BTCUSDT", category="linear"),
            QueryTarget("Inverse Futures", "BTCUSD", category="inverse"),
            QueryTarget("Options", "BTC", category="option"),
        ]
        for target in targets:
            path = "/v5/account/fee-rate"
            params = {"category": target.category}
            if target.symbol:
                if target.category == "option":
                    params["baseCoin"] = target.symbol
                else:
                    params["symbol"] = target.symbol
            try:
                payload = self._signed_get(path, params)
                rows = payload.get("result", {}).get("list", [])
                if not rows:
                    raise RuntimeError(f"Unexpected Bybit payload: {payload}")
                row = rows[0]
                records.append(
                    FeeRecord.success(
                        exchange=self.exchange,
                        account=self.account,
                        product=target.product,
                        symbol=str(row.get("symbol", target.symbol)),
                        vip_level=str(row.get("feeGroupId", "")),
                        maker_rate=str(row.get("makerFeeRate", "")),
                        taker_rate=str(row.get("takerFeeRate", "")),
                        source="api",
                        endpoint=path,
                        raw=row,
                    )
                )
            except Exception as exc:
                records.append(self.error_record(target.product, target.symbol, path, exc))
        return records


class BitgetClient(ExchangeClient):
    exchange = "bitget"
    base_url = "https://api.bitget.com"
    classic_trade_rate_path = "/api/v2/common/trade-rate"
    uta_fee_rate_path = "/api/v3/account/fee-rate"

    def _signed_get(self, path: str, params: Dict[str, str]) -> Dict[str, object]:
        timestamp = str(int(time.time() * 1000))
        query = urlencode(params)
        prehash = f"{timestamp}GET{path}"
        if query:
            prehash += f"?{query}"
        secret = _get_required(self.credentials, "SECRET_KEY")
        signature = base64.b64encode(
            hmac.new(secret.encode(), prehash.encode(), hashlib.sha256).digest()
        ).decode()
        headers = {
            "ACCESS-KEY": _get_required(self.credentials, "ACCESS_KEY"),
            "ACCESS-SIGN": signature,
            "ACCESS-TIMESTAMP": timestamp,
            "ACCESS-PASSPHRASE": _get_required(self.credentials, "PASSPHRASE"),
            "Content-Type": "application/json",
        }
        response = self.session.get(
            f"{self.base_url}{path}",
            params=params,
            headers=headers,
            timeout=DEFAULT_TIMEOUT,
        )
        if response.status_code >= 400:
            raise RuntimeError(_compact_error(response))
        data = response.json()
        if str(data.get("code")) != "00000":
            raise RuntimeError(str(data))
        return data

    @staticmethod
    def _is_classic_mode_error(exc: Exception) -> bool:
        message = str(exc)
        return "40084" in message and "Classic Account mode" in message

    def _success_record(
        self,
        *,
        product: str,
        symbol: str,
        payload_row: Dict[str, object],
        endpoint: str,
        vip_level: str = "",
        note: str = "",
    ) -> FeeRecord:
        return FeeRecord.success(
            exchange=self.exchange,
            account=self.account,
            product=product,
            symbol=symbol,
            vip_level=vip_level,
            maker_rate=str(payload_row.get("makerFeeRate", "")),
            taker_rate=str(payload_row.get("takerFeeRate", "")),
            source="api",
            endpoint=endpoint,
            note=note,
            raw=payload_row,
        )

    def _fetch_classic_trade_rate(self, symbol: str, business_type: str) -> Dict[str, object]:
        attempts = [
            {"symbol": symbol, "businessType": business_type},
            {"symbol": symbol, "business": business_type},
        ]
        last_error: Exception | None = None
        for params in attempts:
            try:
                return self._signed_get(self.classic_trade_rate_path, params)
            except Exception as exc:
                last_error = exc
        if last_error is None:
            raise RuntimeError("Unknown Bitget classic trade-rate error.")
        raise last_error

    def _fetch_classic(self) -> List[FeeRecord]:
        records: List[FeeRecord] = []
        note = (
            "Classic account fallback via /api/v2/common/trade-rate. "
            "Bitget UTA fee endpoint is unavailable for Classic Account mode."
        )

        targets = [
            ("Spot", "BTCUSDT", "spot"),
            ("USDT-M Futures", "BTCUSDT", "mix"),
            ("COIN-M Futures", "BTCUSD", "mix"),
            ("USDC-M Futures", "BTCUSDC", "mix"),
        ]
        for product, symbol, business_type in targets:
            try:
                payload = self._fetch_classic_trade_rate(symbol, business_type)
                row = payload.get("data", {})
                records.append(
                    self._success_record(
                        product=product,
                        symbol=symbol,
                        payload_row=row if isinstance(row, dict) else {},
                        endpoint=self.classic_trade_rate_path,
                        note=note,
                    )
                )
            except Exception as exc:
                records.append(self.error_record(product, symbol, self.classic_trade_rate_path, exc))
        return records

    def _fetch_uta(self, first_payload: Dict[str, object]) -> List[FeeRecord]:
        records: List[FeeRecord] = []
        targets = [
            QueryTarget("Spot", "BTCUSDT", category="SPOT"),
            QueryTarget("USDT-M Futures", "BTCUSDT", category="USDT-FUTURES"),
            QueryTarget("COIN-M Futures", "BTCUSD", category="COIN-FUTURES"),
            QueryTarget("USDC-M Futures", "BTCUSDC", category="USDC-FUTURES"),
        ]

        first_row = first_payload.get("data", {})
        records.append(
            self._success_record(
                product="Spot",
                symbol="BTCUSDT",
                payload_row=first_row if isinstance(first_row, dict) else {},
                endpoint=self.uta_fee_rate_path,
                vip_level=str(first_row.get("level", first_row.get("vipLevel", "")))
                if isinstance(first_row, dict)
                else "",
            )
        )

        for target in targets[1:]:
            params = {"category": target.category, "symbol": target.symbol}
            try:
                payload = self._signed_get(self.uta_fee_rate_path, params)
                row = payload.get("data", {})
                records.append(
                    self._success_record(
                        product=target.product,
                        symbol=target.symbol,
                        payload_row=row if isinstance(row, dict) else {},
                        endpoint=self.uta_fee_rate_path,
                        vip_level=str(row.get("level", row.get("vipLevel", "")))
                        if isinstance(row, dict)
                        else "",
                    )
                )
            except Exception as exc:
                records.append(self.error_record(target.product, target.symbol, self.uta_fee_rate_path, exc))
        return records

    def fetch(self) -> List[FeeRecord]:
        try:
            first_payload = self._signed_get(
                self.uta_fee_rate_path,
                {"category": "SPOT", "symbol": "BTCUSDT"},
            )
        except Exception as exc:
            if self._is_classic_mode_error(exc):
                return self._fetch_classic()
            return [self.error_record("Spot", "BTCUSDT", self.uta_fee_rate_path, exc)]
        return self._fetch_uta(first_payload)


class GateClient(ExchangeClient):
    exchange = "gate"
    base_url = "https://api.gateio.ws"
    prefix = "/api/v4"

    def _signed_get(self, path: str, params: Dict[str, str] | None = None) -> object:
        params = params or {}
        query = urlencode(params)
        timestamp = str(int(time.time()))
        body_hash = hashlib.sha512(b"").hexdigest()
        sign_payload = "\n".join(["GET", f"{self.prefix}{path}", query, body_hash, timestamp])
        secret = _get_required(self.credentials, "SECRET_KEY")
        signature = hmac.new(secret.encode(), sign_payload.encode(), hashlib.sha512).hexdigest()
        headers = {
            "KEY": _get_required(self.credentials, "ACCESS_KEY"),
            "SIGN": signature,
            "Timestamp": timestamp,
            "Accept": "application/json",
            "Content-Type": "application/json",
        }
        response = self.session.get(
            f"{self.base_url}{self.prefix}{path}",
            params=params,
            headers=headers,
            timeout=DEFAULT_TIMEOUT,
        )
        if response.status_code >= 400:
            raise RuntimeError(_compact_error(response))
        return response.json()

    @staticmethod
    def _pick_rate(row: Dict[str, object], *names: str) -> str:
        for name in names:
            if name in row and row[name] not in (None, ""):
                return str(row[name])
        return ""

    @staticmethod
    def _extract_symbol_row(payload: object, symbol: str) -> Dict[str, object] | None:
        if isinstance(payload, dict):
            direct = payload.get(symbol)
            if isinstance(direct, dict):
                return {
                    **direct,
                    "currency_pair": str(direct.get("currency_pair", symbol)),
                    "_symbol_key": symbol,
                }
            if "currency_pair" in payload:
                return payload
            dict_values = [(key, value) for key, value in payload.items() if isinstance(value, dict)]
            if len(dict_values) == 1:
                key, value = dict_values[0]
                return {
                    **value,
                    "currency_pair": str(value.get("currency_pair", key)),
                    "_symbol_key": key,
                }
        if isinstance(payload, list):
            for item in payload:
                if isinstance(item, dict) and item.get("currency_pair") == symbol:
                    return item
            if payload and isinstance(payload[0], dict):
                return payload[0]
        return None

    def fetch(self) -> List[FeeRecord]:
        records: List[FeeRecord] = []
        try:
            payload = self._signed_get("/spot/batch_fee")
            match = self._extract_symbol_row(payload, "BTC_USDT")
            if not isinstance(match, dict):
                raise RuntimeError(f"Unexpected Gate spot payload: {payload}")
            records.append(
                FeeRecord.success(
                    exchange=self.exchange,
                    account=self.account,
                    product="Spot",
                    symbol=str(match.get("currency_pair", match.get("_symbol_key", "BTC_USDT"))),
                    vip_level=str(match.get("user_tier", "")),
                    maker_rate=self._pick_rate(match, "maker_fee", "maker_fee_rate"),
                    taker_rate=self._pick_rate(match, "taker_fee", "taker_fee_rate"),
                    source="api",
                    endpoint="/spot/batch_fee",
                    raw=match,
                )
            )
        except Exception:
            try:
                payload = self._signed_get("/spot/batch_fee", {"currency_pairs": "BTC_USDT"})
                match = self._extract_symbol_row(payload, "BTC_USDT")
                if not isinstance(match, dict):
                    raise RuntimeError(f"Unexpected Gate spot payload: {payload}")
                records.append(
                    FeeRecord.success(
                        exchange=self.exchange,
                        account=self.account,
                        product="Spot",
                        symbol=str(match.get("currency_pair", match.get("_symbol_key", "BTC_USDT"))),
                        vip_level=str(match.get("user_tier", "")),
                        maker_rate=self._pick_rate(match, "maker_fee", "maker_fee_rate"),
                        taker_rate=self._pick_rate(match, "taker_fee", "taker_fee_rate"),
                        source="api",
                        endpoint="/spot/batch_fee",
                        note="Used currency_pairs=BTC_USDT because Gate spot batch_fee requires this parameter.",
                        raw=match,
                    )
                )
            except Exception as exc:
                records.append(self.error_record("Spot", "BTC_USDT", "/spot/batch_fee", exc))

        for settle, product, symbol in [
            ("usdt", "Futures -USDT Prep", "BTC_USDT"),
            ("btc", "Futures -BTC Prep", "BTC_USD"),
        ]:
            path = f"/futures/{settle}/fee"
            try:
                payload = self._signed_get(path)
                row = self._extract_symbol_row(payload, symbol)
                if not isinstance(row, dict):
                    raise RuntimeError(f"Unexpected Gate futures payload: {payload}")
                records.append(
                    FeeRecord.success(
                        exchange=self.exchange,
                        account=self.account,
                        product=product,
                        symbol=str(row.get("currency_pair", row.get("_symbol_key", symbol))),
                        vip_level=str(row.get("user_tier", "")),
                        maker_rate=self._pick_rate(row, "maker_fee", "maker_fee_rate"),
                        taker_rate=self._pick_rate(row, "taker_fee", "taker_fee_rate"),
                        source="api",
                        endpoint=path,
                        raw=row,
                    )
                )
            except Exception as exc:
                records.append(self.error_record(product, symbol, path, exc))
        return records


class KuCoinClient(ExchangeClient):
    exchange = "kucoin"
    base_url = "https://api.kucoin.com"

    def _signed_get(self, path: str, params: Dict[str, str]) -> Dict[str, object]:
        timestamp = str(int(time.time() * 1000))
        endpoint = path
        query = urlencode(params)
        if query:
            endpoint = f"{path}?{query}"
        prehash = f"{timestamp}GET{endpoint}"
        secret = _get_required(self.credentials, "SECRET_KEY")
        signature = base64.b64encode(
            hmac.new(secret.encode(), prehash.encode(), hashlib.sha256).digest()
        ).decode()
        passphrase = _get_required(self.credentials, "PASSPHRASE")
        passphrase_signature = base64.b64encode(
            hmac.new(secret.encode(), passphrase.encode(), hashlib.sha256).digest()
        ).decode()
        headers = {
            "KC-API-KEY": _get_required(self.credentials, "ACCESS_KEY"),
            "KC-API-SIGN": signature,
            "KC-API-TIMESTAMP": timestamp,
            "KC-API-PASSPHRASE": passphrase_signature,
            "KC-API-KEY-VERSION": "2",
        }
        response = self.session.get(
            f"{self.base_url}{path}",
            params=params,
            headers=headers,
            timeout=DEFAULT_TIMEOUT,
        )
        if response.status_code >= 400:
            raise RuntimeError(_compact_error(response))
        data = response.json()
        if str(data.get("code")) != "200000":
            raise RuntimeError(str(data))
        return data

    def fetch(self) -> List[FeeRecord]:
        records: List[FeeRecord] = []
        try:
            payload = self._signed_get("/api/v1/trade-fees", {"symbols": "BTC-USDT"})
            rows = payload.get("data", [])
            if not rows:
                raise RuntimeError(f"Unexpected KuCoin spot payload: {payload}")
            row = rows[0]
            records.append(
                FeeRecord.success(
                    exchange=self.exchange,
                    account=self.account,
                    product="Spot",
                    symbol=str(row.get("symbol", "BTC-USDT")),
                    vip_level=str(row.get("level", "")),
                    maker_rate=str(row.get("makerFeeRate", "")),
                    taker_rate=str(row.get("takerFeeRate", "")),
                    source="api",
                    endpoint="/api/v1/trade-fees",
                    raw=row,
                )
            )
        except Exception as exc:
            records.append(self.error_record("Spot", "BTC-USDT", "/api/v1/trade-fees", exc))

        try:
            payload = self._signed_get("/api/v1/base-fee", {"symbol": "XBTUSDTM"})
            row = payload.get("data", {})
            records.append(
                FeeRecord.success(
                    exchange=self.exchange,
                    account=self.account,
                    product="Futures",
                    symbol=str(row.get("symbol", "XBTUSDTM")),
                    vip_level=str(row.get("level", "")),
                    maker_rate=str(row.get("makerFeeRate", "")),
                    taker_rate=str(row.get("takerFeeRate", "")),
                    source="api",
                    endpoint="/api/v1/base-fee",
                    raw=row,
                )
            )
        except Exception as exc:
            records.append(self.error_record("Futures", "XBTUSDTM", "/api/v1/base-fee", exc))
        return records


class OKXClient(ExchangeClient):
    exchange = "okex"
    base_url = "https://www.okx.com"

    @staticmethod
    def _iso_timestamp() -> str:
        return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")

    def _signed_get(self, path: str, params: Dict[str, str]) -> Dict[str, object]:
        timestamp = self._iso_timestamp()
        query = urlencode(params)
        request_path = path if not query else f"{path}?{query}"
        prehash = f"{timestamp}GET{request_path}"
        secret = _get_required(self.credentials, "SECRET_KEY")
        signature = base64.b64encode(
            hmac.new(secret.encode(), prehash.encode(), hashlib.sha256).digest()
        ).decode()
        headers = {
            "OK-ACCESS-KEY": _get_required(self.credentials, "ACCESS_KEY"),
            "OK-ACCESS-SIGN": signature,
            "OK-ACCESS-TIMESTAMP": timestamp,
            "OK-ACCESS-PASSPHRASE": _get_required(self.credentials, "PASSPHRASE"),
        }
        response = self.session.get(
            f"{self.base_url}{path}",
            params=params,
            headers=headers,
            timeout=DEFAULT_TIMEOUT,
        )
        if response.status_code >= 400:
            raise RuntimeError(_compact_error(response))
        data = response.json()
        if str(data.get("code")) != "0":
            raise RuntimeError(str(data))
        return data

    def fetch(self) -> List[FeeRecord]:
        records: List[FeeRecord] = []
        targets = [
            QueryTarget("Spot", "BTC-USDT", inst_type="SPOT"),
            QueryTarget("Futures", "BTC-USD", inst_type="FUTURES", inst_family="BTC-USD"),
            QueryTarget("Options", "BTC-USD", inst_type="OPTION", inst_family="BTC-USD"),
        ]
        path = "/api/v5/account/trade-fee"
        for target in targets:
            params = {"instType": target.inst_type}
            if target.inst_family:
                params["instFamily"] = target.inst_family
            else:
                params["instId"] = target.symbol
            try:
                payload = self._signed_get(path, params)
                rows = payload.get("data", [])
                if not rows:
                    raise RuntimeError(f"Unexpected OKX payload: {payload}")
                row = rows[0]
                records.append(
                    FeeRecord.success(
                        exchange=self.exchange,
                        account=self.account,
                        product=target.product,
                        symbol=target.symbol,
                        vip_level=str(row.get("level", "")),
                        maker_rate=str(row.get("maker", "")),
                        taker_rate=str(row.get("taker", "")),
                        source="api",
                        endpoint=path,
                        raw=row,
                    )
                )
            except Exception as exc:
                records.append(self.error_record(target.product, target.symbol, path, exc))
        return records


class DeribitClient(ExchangeClient):
    exchange = "deribit"
    base_url = "https://www.deribit.com/api/v2"
    preferred_products = {
        "BTC / ETH Futrue",
        "BTC / ETH Perpetual",
        "BTC / ETH Option",
        "USDC Future",
        "USDC Perpetual",
    }

    def _access_token(self) -> str:
        params = {
            "grant_type": "client_credentials",
            "client_id": _get_required(self.credentials, "ACCESS_KEY"),
            "client_secret": _get_required(self.credentials, "SECRET_KEY"),
        }
        response = self.session.get(
            f"{self.base_url}/public/auth",
            params=params,
            timeout=DEFAULT_TIMEOUT,
        )
        if response.status_code >= 400:
            raise RuntimeError(_compact_error(response))
        data = response.json()
        if data.get("error"):
            raise RuntimeError(str(data))
        return str(data["result"]["access_token"])

    def _private_get(self, path: str, params: Dict[str, str], access_token: str) -> Dict[str, object]:
        headers = {"Authorization": f"Bearer {access_token}"}
        response = self.session.get(
            f"{self.base_url}{path}",
            params=params,
            headers=headers,
            timeout=DEFAULT_TIMEOUT,
        )
        if response.status_code >= 400:
            raise RuntimeError(_compact_error(response))
        data = response.json()
        if data.get("error"):
            raise RuntimeError(str(data))
        return data

    @staticmethod
    def _build_fee_records_from_summary(
        account: str,
        summary: Dict[str, object],
        endpoint: str,
    ) -> List[FeeRecord]:
        records: List[FeeRecord] = []
        fee_group = str(summary.get("fee_group", ""))
        fees = summary.get("fees", {})
        if not isinstance(fees, dict):
            return records

        product_name_map = {
            ("usd", "future"): "BTC / ETH Futrue",
            ("usd", "perpetual"): "BTC / ETH Perpetual",
            ("usd", "option"): "BTC / ETH Option",
            ("usdc", "future"): "USDC Future",
            ("usdc", "perpetual"): "USDC Perpetual",
        }

        for symbol_key, symbol_fees in fees.items():
            if not isinstance(symbol_fees, dict):
                continue
            quote = "usdc" if str(symbol_key).lower().endswith("usdc") else "usd"
            for instrument_type, product_name in [
                ("future", product_name_map.get((quote, "future"), "")),
                ("perpetual", product_name_map.get((quote, "perpetual"), "")),
                ("option", product_name_map.get((quote, "option"), "")),
            ]:
                if not product_name:
                    continue
                instrument_fees = symbol_fees.get(instrument_type)
                if not isinstance(instrument_fees, dict):
                    continue
                default_fee = instrument_fees.get("default")
                if not isinstance(default_fee, dict):
                    continue
                maker = str(default_fee.get("maker", ""))
                taker = str(default_fee.get("taker", ""))
                if maker == "" and taker == "":
                    continue
                records.append(
                    FeeRecord.success(
                        exchange="deribit",
                        account=account,
                        product=product_name,
                        symbol=str(symbol_key).upper(),
                        vip_level=fee_group,
                        maker_rate=maker,
                        taker_rate=taker,
                        source="api",
                        endpoint=endpoint,
                        note="Parsed Deribit fees from account summary fees map.",
                        raw={
                            "symbol_key": symbol_key,
                            "instrument_type": instrument_type,
                            "default_fee": default_fee,
                            "fee_group": fee_group,
                        },
                    )
                )
        return records

    def fetch(self) -> List[FeeRecord]:
        records: List[FeeRecord] = []
        seen_products: set[str] = set()
        try:
            access_token = self._access_token()
        except Exception as exc:
            return [self.error_record("Account Summary", "", "/public/auth", exc)]

        for currency in ["BTC", "ETH", "USDC"]:
            path = "/private/get_account_summary"
            params = {"currency": currency, "extended": "true"}
            try:
                payload = self._private_get(path, params, access_token)
                row = payload.get("result", {})
                parsed_rows = self._build_fee_records_from_summary(self.account, row, path)
                if parsed_rows:
                    for parsed_row in parsed_rows:
                        if parsed_row.product not in self.preferred_products:
                            continue
                        if parsed_row.product in seen_products:
                            continue
                        seen_products.add(parsed_row.product)
                        records.append(parsed_row)
                    continue
                records.append(
                    FeeRecord.success(
                        exchange=self.exchange,
                        account=self.account,
                        product="Account Summary",
                        symbol=currency,
                        vip_level=str(row.get("fee_group", "")),
                        maker_rate=str(row.get("maker_commission", "")),
                        taker_rate=str(row.get("taker_commission", "")),
                        source="api",
                        endpoint=path,
                        note="Deribit fallback to top-level maker_commission and taker_commission.",
                        raw=row,
                    )
                )
            except Exception as exc:
                records.append(self.error_record("Account Summary", currency, path, exc))
        return records


class CoinbaseClient(ExchangeClient):
    exchange = "coinbase"
    base_url = "https://api.exchange.coinbase.com"

    def _signed_get(self, path: str) -> Dict[str, object]:
        timestamp = str(int(time.time()))
        secret = _get_required(self.credentials, "SECRET_KEY")
        decoded_secret = base64.b64decode(secret)
        message = f"{timestamp}GET{path}".encode()
        signature = base64.b64encode(hmac.new(decoded_secret, message, hashlib.sha256).digest()).decode()
        headers = {
            "CB-ACCESS-KEY": _get_required(self.credentials, "ACCESS_KEY"),
            "CB-ACCESS-SIGN": signature,
            "CB-ACCESS-TIMESTAMP": timestamp,
            "CB-ACCESS-PASSPHRASE": _get_required(self.credentials, "PASSPHRASE"),
        }
        response = self.session.get(
            f"{self.base_url}{path}",
            headers=headers,
            timeout=DEFAULT_TIMEOUT,
        )
        if response.status_code >= 400:
            raise RuntimeError(_compact_error(response))
        return response.json()

    def fetch(self) -> List[FeeRecord]:
        path = "/fees"
        try:
            payload = self._signed_get(path)
            return [
                FeeRecord.success(
                    exchange=self.exchange,
                    account=self.account,
                    product="Spot",
                    symbol="ALL",
                    vip_level=str(payload.get("fee_tier", "")),
                    maker_rate=str(payload.get("maker_fee_rate", "")),
                    taker_rate=str(payload.get("taker_fee_rate", "")),
                    source="api",
                    endpoint=path,
                    raw=payload,
                )
            ]
        except Exception as exc:
            return [self.error_record("Spot", "ALL", path, exc)]


class KrakenSpotClient(ExchangeClient):
    exchange = "krakenspot"
    base_url = "https://api.kraken.com"

    def _signed_post(self, path: str, data: Dict[str, str]) -> Dict[str, object]:
        nonce = str(int(time.time() * 1000))
        payload = {"nonce": nonce, **data}
        post_data = urlencode(payload)
        secret = base64.b64decode(_get_required(self.credentials, "SECRET_KEY"))
        sha256 = hashlib.sha256((nonce + post_data).encode()).digest()
        message = path.encode() + sha256
        signature = base64.b64encode(hmac.new(secret, message, hashlib.sha512).digest()).decode()
        headers = {
            "API-Key": _get_required(self.credentials, "ACCESS_KEY"),
            "API-Sign": signature,
            "Content-Type": "application/x-www-form-urlencoded; charset=utf-8",
        }
        response = self.session.post(
            f"{self.base_url}{path}",
            data=payload,
            headers=headers,
            timeout=DEFAULT_TIMEOUT,
        )
        if response.status_code >= 400:
            raise RuntimeError(_compact_error(response))
        data = response.json()
        if data.get("error"):
            raise RuntimeError(str(data))
        return data

    def fetch(self) -> List[FeeRecord]:
        path = "/0/private/TradeVolume"
        try:
            payload = self._signed_post(path, {"pair": "XXBTZUSD"})
            result = payload.get("result", {})
            fees = result.get("fees", {})
            fees_maker = result.get("fees_maker", {})
            row = fees.get("XXBTZUSD", {})
            maker_row = fees_maker.get("XXBTZUSD", {})
            if not isinstance(row, dict) or not isinstance(maker_row, dict):
                raise RuntimeError(f"Unexpected Kraken spot TradeVolume payload: {payload}")

            maker_rate = _percent_string_to_decimal(str(maker_row.get("fee", "")))
            taker_rate = _percent_string_to_decimal(str(row.get("fee", "")))
            tier_volume = str(row.get("tier_volume", ""))
            note = (
                "Kraken Spot uses TradeVolume; fee fields are percentages and were converted to decimal rates."
            )
            vip_level = f"30D Volume {tier_volume} USD" if tier_volume else ""
            return [
                FeeRecord.success(
                    exchange=self.exchange,
                    account=self.account,
                    product="Spot",
                    symbol="XXBTZUSD",
                    vip_level=vip_level,
                    maker_rate=maker_rate,
                    taker_rate=taker_rate,
                    source="api",
                    endpoint=path,
                    note=note,
                    raw=result,
                )
            ]
        except Exception as exc:
            return [self.error_record("Spot", "XXBTZUSD", path, exc)]


class KrakenSwapClient(ExchangeClient):
    exchange = "krakenswap"
    base_url = "https://futures.kraken.com"

    def _signed_get(self, path: str, params: Dict[str, str] | None = None) -> Dict[str, object]:
        params = params or {}
        nonce = str(int(time.time() * 1000))
        post_data = urlencode(params)
        endpoint_path = f"/api/v3{path}"
        request_path = f"/derivatives{endpoint_path}"
        secret = base64.b64decode(_get_required(self.credentials, "SECRET_KEY"))
        payload_to_hash = f"{post_data}{nonce}{endpoint_path}".encode()
        digest = hashlib.sha256(payload_to_hash).digest()
        authent = base64.b64encode(hmac.new(secret, digest, hashlib.sha512).digest()).decode()
        headers = {
            "APIKey": _get_required(self.credentials, "ACCESS_KEY"),
            "Authent": authent,
            "Nonce": nonce,
        }
        response = self.session.get(
            f"{self.base_url}{request_path}",
            params=params,
            headers=headers,
            timeout=DEFAULT_TIMEOUT,
        )
        if response.status_code >= 400:
            raise RuntimeError(_compact_error(response))
        data = response.json()
        if data.get("result") != "success":
            raise RuntimeError(str(data))
        return data

    @staticmethod
    def _pick_active_tier(tiers: List[Dict[str, object]], usd_volume: float) -> Dict[str, object] | None:
        active: Dict[str, object] | None = None
        active_threshold = float("-inf")
        for tier in tiers:
            threshold = float(tier.get("usdVolume", 0))
            if threshold <= usd_volume and threshold >= active_threshold:
                active = tier
                active_threshold = threshold
        return active

    def fetch(self) -> List[FeeRecord]:
        schedule_path = "/feeschedules"
        volumes_path = "/feeschedules/volumes"
        try:
            schedules_payload = self._signed_get(schedule_path)
            volumes_payload = self._signed_get(volumes_path)
            schedules = schedules_payload.get("feeSchedules", [])
            volumes_by_uid = volumes_payload.get("volumesByFeeSchedule", {})
            if not isinstance(schedules, list) or not isinstance(volumes_by_uid, dict):
                raise RuntimeError(
                    f"Unexpected Kraken futures fee payloads: schedules={schedules_payload}, volumes={volumes_payload}"
                )

            candidates = [
                (uid, float(volume))
                for uid, volume in volumes_by_uid.items()
            ]
            if not candidates:
                raise RuntimeError("No Kraken futures fee schedule volume found for this account.")

            schedule_uid, usd_volume = max(candidates, key=lambda item: item[1])
            schedule = next(
                (item for item in schedules if isinstance(item, dict) and item.get("uid") == schedule_uid),
                None,
            )
            if not isinstance(schedule, dict):
                raise RuntimeError(f"Kraken futures fee schedule UID {schedule_uid} not found in /feeschedules.")

            tiers = schedule.get("tiers", [])
            if not isinstance(tiers, list):
                raise RuntimeError(f"Unexpected Kraken futures tiers payload: {schedule}")
            active_tier = self._pick_active_tier(tiers, usd_volume)
            if active_tier is None:
                raise RuntimeError(
                    f"Unable to map Kraken futures volume {usd_volume} to a fee tier in schedule {schedule_uid}."
                )

            maker_rate = _percent_string_to_decimal(str(active_tier.get("makerFee", "")))
            taker_rate = _percent_string_to_decimal(str(active_tier.get("takerFee", "")))
            vip_level = str(schedule.get("name", ""))
            note = (
                "Kraken Futures uses deprecated fee schedule endpoints before 2026-06-22; "
                "makerFee/takerFee are percentages and were converted to decimal rates."
            )
            raw = {
                "schedule": schedule,
                "activeTier": active_tier,
                "volume": usd_volume,
            }
            return [
                FeeRecord.success(
                    exchange=self.exchange,
                    account=self.account,
                    product="Futures",
                    symbol="ALL",
                    vip_level=vip_level,
                    maker_rate=maker_rate,
                    taker_rate=taker_rate,
                    source="api",
                    endpoint=volumes_path,
                    note=note,
                    raw=raw,
                )
            ]
        except Exception as exc:
            return [self.error_record("Futures", "ALL", volumes_path, exc)]


CLIENTS = {
    "binance": BinanceClient,
    "bybit": BybitClient,
    "bitget": BitgetClient,
    "gate": GateClient,
    "kucoin": KuCoinClient,
    "okex": OKXClient,
    "deribit": DeribitClient,
    "coinbase": CoinbaseClient,
    "krakenspot": KrakenSpotClient,
    "krakenswap": KrakenSwapClient,
}


def fetch_all_fee_records(accounts: Dict[str, str] | None = None) -> List[FeeRecord]:
    accounts = accounts or TARGET_ACCOUNTS
    all_records: List[FeeRecord] = []
    for exchange, account in accounts.items():
        client_cls = CLIENTS.get(exchange)
        if client_cls is None:
            all_records.append(
                FeeRecord.error(
                    exchange=exchange,
                    account=account,
                    product="",
                    symbol="",
                    endpoint="",
                    note="No client implementation found.",
                )
            )
            continue
        try:
            credentials = load_account_credentials(exchange, account)
            client = client_cls(account, credentials)
            all_records.extend(client.fetch())
        except Exception as exc:
            all_records.append(
                FeeRecord.error(
                    exchange=exchange,
                    account=account,
                    product="",
                    symbol="",
                    endpoint="load_account_credentials",
                    note=str(exc),
                )
            )
    return all_records


def fee_records_to_rows(records: Iterable[FeeRecord]) -> List[Dict[str, str]]:
    return [record.to_row() for record in records]


def fee_records_to_json(records: Iterable[FeeRecord]) -> str:
    return json.dumps(fee_records_to_rows(records), ensure_ascii=False, indent=2)
