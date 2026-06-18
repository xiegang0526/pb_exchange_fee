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
- `send_slack_fee_report.py`
  日报入口。抓取费率、和昨天对比、生成 Slack 表格消息，并落地本地 HTML 报表。
- `exchange_fee/account_store.py`
  Redis 账号读取。优先用 `redis-py`，没有安装时自动回退到 `redis-cli`。
- `exchange_fee/clients.py`
  各交易所费率抓取逻辑。
- `exchange_fee/reference_table.py`
  规范化 `tablefee.tsv`。
- `exchange_fee/pipeline.py`
  公共数据流水线，给抓取脚本和日报脚本共用。
- `exchange_fee/slack_report.py`
  负责历史快照、昨日对比、Slack payload 和 HTML 报表。

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
- `exchange_fee.normalized.tsv`
- `exchange_fee.normalized.json`
- `exchange_account_levels.tsv`
- `exchange_account_levels.json`

## 每日 Slack 日报

建议通过环境变量传 webhook，不要把真实 URL 写进代码仓库：

```bash
cd /home/trader/pb_exchange_fee
export FEE_REPORT_WEBHOOK_URL='your-webhook-url'
python3 send_slack_fee_report.py
```

如果你只想先生成结果、不真正发消息：

```bash
python3 send_slack_fee_report.py --dry-run
```

日报脚本会额外生成：

- `history/YYYY-MM-DD.normalized.json`
  每天的标准化费率快照，用来和昨天做 diff。
- `history/YYYY-MM-DD.slack_payloads.json`
  实际将要推给 Slack 的 payload 归档。
- `reports/YYYY-MM-DD.html`
  本地 HTML 报表，样式接近截图中的表格。

## 定时任务

仓库里提供了一个 `cron` 示例：

- `cron.daily_fee_report.example`

默认用 `Asia/Shanghai` 时区，每天 `09:30` 执行。部署前把里面的 webhook 替换成环境变量或实盘机注入值更稳。

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
