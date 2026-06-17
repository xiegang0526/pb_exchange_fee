# pb_exchange_fee

这个目录现在已经整理成一个可部署的小项目，目标是做两件事：

1. 从 Redis 读取各交易所账户 API 凭证。
2. 调用各交易所私有费率接口，生成当前账户的费率快照。

同时项目会把现有的 `tablefee.tsv` 规范化成结构化表，方便后续对比。

## 当前覆盖的账户

- `bitget -> mpusstockbg28`
- `bybit -> mpusstockbybit45`
- `binance -> mpusstockbn65`
- `gate -> mpusstockgate52`
- `kucoin -> mpusstockkucoin23`
- `okex -> mpusstockokx45`
- `deribit -> mpusstockderibit15`
- `coinbase -> mpflyottercoinb07`

## 文件说明

- `get_redis_account.py`
  兼容原来的账号查询用途，现在也能作为可复用模块被主程序引用。
- `fetch_exchange_fees.py`
  主入口。批量抓取费率并落地结果文件。
- `exchange_fee/account_store.py`
  Redis 账号读取。优先用 `redis-py`，没有安装时自动回退到 `redis-cli`。
- `exchange_fee/clients.py`
  各交易所费率抓取逻辑。
- `exchange_fee/reference_table.py`
  规范化 `tablefee.tsv`。

## 运行方式

建议使用 `python3`：

```bash
cd /home/trader/pb_exchange_fee
python3 fetch_exchange_fees.py
```

运行后会生成：

- `exchange_fee_snapshot.tsv`
- `exchange_fee_snapshot.json`
- `tablefee.normalized.tsv`

## 依赖

最小依赖只有 `requests`。

```bash
python3 -m pip install requests
```

如果你希望直接通过 Python 连接 Redis，也可以额外装：

```bash
python3 -m pip install redis
```

没有 `redis` 包也能跑，只要实盘机上有 `redis-cli`。

## 部署建议

实盘机建议补这几项：

1. 用独立虚拟环境安装 `requests`，避免和系统 Python 混用。
2. 先单独跑一次 `python3 get_redis_account.py binance mpusstockbn65`，确认 Redis 网络可达。
3. 再跑 `python3 fetch_exchange_fees.py`，先看 `exchange_fee_snapshot.tsv` 里的 `status` 和 `note`。
4. 如果后续要定时执行，可以直接加 `crontab`，例如每小时刷新一次。

## 已知风险

1. 各交易所接口本身存在区域限制和权限限制，私有费率接口可能因为 API Key 权限不足返回 401/403。
2. `tablefee.tsv` 里是参考表，不一定和账户的实时 VIP 或做市计划完全一致。
3. Binance、Bybit、Deribit、Coinbase 等返回的字段口径不完全相同，脚本已经统一成 maker/taker 输出，但个别平台的特殊折扣仍建议以 `raw` 字段复核。
