from __future__ import annotations

import html
import json
import os
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Iterable, List
from zoneinfo import ZoneInfo

import requests


MAX_TABLE_ROWS_PER_MESSAGE = 99
MAX_CHANGE_LINES_IN_MESSAGE = 20
MAX_DESCRIPTION_CHARS = 1200
MAX_EXCHANGE_SECTIONS_PER_MESSAGE = 3
DEFAULT_GENERIC_TOPIC = "pb-exchange-fee"


def format_report_date(dt: datetime) -> str:
    return f"{dt.day} {dt.strftime('%B %Y')}"


def _history_path(base_dir: str, report_date: datetime) -> str:
    return os.path.join(base_dir, "history", f"{report_date.date().isoformat()}.normalized.json")


def _html_report_path(base_dir: str, report_date: datetime) -> str:
    return os.path.join(base_dir, "reports", f"{report_date.date().isoformat()}.html")


def _payload_archive_path(base_dir: str, report_date: datetime) -> str:
    return os.path.join(base_dir, "history", f"{report_date.date().isoformat()}.webhook_payloads.json")


def load_json_file(path: str) -> list[dict[str, str]] | None:
    if not os.path.exists(path):
        return None
    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle)


def write_json_file(path: str, data: object) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(data, handle, ensure_ascii=False, indent=2)


def _is_valid_normalized_row(row: dict[str, str]) -> bool:
    product = (row.get("product") or "").strip()
    maker = (row.get("maker_rate_percent") or row.get("maker_rate") or "").strip()
    taker = (row.get("taker_rate_percent") or row.get("taker_rate") or "").strip()
    return bool(product and (maker or taker))


def _filter_normalized_rows(rows: Iterable[dict[str, str]]) -> list[dict[str, str]]:
    return [row for row in rows if _is_valid_normalized_row(row)]


def _format_percent_display(value: str) -> str:
    cleaned = (value or "").strip()
    if not cleaned:
        return ""
    if not cleaned.endswith("%"):
        return cleaned
    number = cleaned[:-1].strip()
    if not number:
        return ""
    negative = number.startswith("-")
    if negative:
        number = number[1:]
    if "." in number:
        number = number.rstrip("0").rstrip(".")
    if not number:
        number = "0"
    if negative and number != "0":
        number = f"-{number}"
    return f"{number}%"


def _format_vip_display(value: str) -> str:
    cleaned = (value or "").strip()
    if not cleaned:
        return "N/A"
    return cleaned


def _chunk_text_sections(sections: list[str], prefix_lines: list[str]) -> list[str]:
    chunks: list[str] = []
    current_lines = list(prefix_lines)

    for section in sections:
        candidate_lines = current_lines + ([""] if current_lines else []) + [section]
        candidate_text = "\n".join(candidate_lines).strip()
        if len(candidate_text) > MAX_DESCRIPTION_CHARS and current_lines != prefix_lines:
            chunks.append("\n".join(current_lines).strip())
            current_lines = list(prefix_lines) + [section]
        else:
            current_lines = candidate_lines

    final_text = "\n".join(current_lines).strip()
    if final_text:
        chunks.append(final_text)
    return chunks


def _chunk_bullet_lines(header: str, bullet_lines: list[str], prefix_lines: list[str]) -> list[str]:
    if not bullet_lines:
        return _chunk_text_sections([header], prefix_lines)

    chunks: list[str] = []
    current_lines = list(prefix_lines) + [header]

    for bullet in bullet_lines:
        candidate_lines = current_lines + [bullet]
        candidate_text = "\n".join(candidate_lines).strip()
        if len(candidate_text) > MAX_DESCRIPTION_CHARS and len(current_lines) > len(prefix_lines) + 1:
            chunks.append("\n".join(current_lines).strip())
            current_lines = list(prefix_lines) + [header, bullet]
        else:
            current_lines = candidate_lines

    final_text = "\n".join(current_lines).strip()
    if final_text:
        chunks.append(final_text)
    return chunks


def _build_exchange_sections(normalized_rows: list[dict[str, str]]) -> list[str]:
    grouped: dict[tuple[str, str], list[dict[str, str]]] = defaultdict(list)
    order: list[tuple[str, str]] = []

    for row in normalized_rows:
        key = (row["exchange"], row["vip_tier"])
        if key not in grouped:
            order.append(key)
        grouped[key].append(row)

    sections: list[str] = []
    for exchange, vip_tier in order:
        rows = grouped[(exchange, vip_tier)]
        vip_display = _format_vip_display(vip_tier)
        vip_header = vip_display if vip_display.upper().startswith("VIP") else f"VIP {vip_display}"
        lines = [f"{exchange} | {vip_header}"]
        for row in rows:
            maker = _format_percent_display(row["maker_rate_percent"])
            taker = _format_percent_display(row["taker_rate_percent"])
            lines.append(f"{row['product']}: Maker {maker}, Taker {taker}")
        sections.append("\n".join(lines))
    return sections


def _report_intro_lines(
    title: str,
    report_time: datetime,
    normalized_rows: list[dict[str, str]],
    changes: list[str],
) -> list[str]:
    return [
        title,
        f"Last updated: {format_report_date(report_time)}",
        f"Rows: {len(normalized_rows)} normalized products",
        f"Changes vs yesterday: {len(changes)}",
    ]


def flatten_table_rows(normalized_rows: Iterable[dict[str, str]]) -> list[list[str]]:
    rows: list[list[str]] = [["Exchange", "VIP Tier", "Trading", "Fee Type", "Fee rate"]]
    for row in _filter_normalized_rows(normalized_rows):
        rows.append(
            [
                row["exchange"],
                _format_vip_display(row["vip_tier"]),
                row["product"],
                "Maker",
                _format_percent_display(row["maker_rate_percent"]),
            ]
        )
        rows.append(
            [
                row["exchange"],
                _format_vip_display(row["vip_tier"]),
                row["product"],
                "Taker",
                _format_percent_display(row["taker_rate_percent"]),
            ]
        )
    return rows


def diff_normalized_rows(
    current_rows: Iterable[dict[str, str]],
    previous_rows: Iterable[dict[str, str]] | None,
) -> list[str]:
    current_rows = _filter_normalized_rows(current_rows)
    previous_rows = _filter_normalized_rows(previous_rows or [])
    if not current_rows:
        return []
    current_map = {(row["exchange"], row["product"]): row for row in current_rows}
    previous_map = {(row["exchange"], row["product"]): row for row in previous_rows}
    changes: list[str] = []

    for key in sorted(current_map):
        current = current_map[key]
        previous = previous_map.get(key)
        if previous is None:
            changes.append(
                f"{current['exchange']} | {current['product']} added: "
                f"Maker {_format_percent_display(current['maker_rate_percent'])}, "
                f"Taker {_format_percent_display(current['taker_rate_percent'])}"
            )
            continue

        if current["vip_tier"] != previous.get("vip_tier", ""):
            changes.append(
                f"{current['exchange']} | {current['product']} VIP: "
                f"{previous.get('vip_tier', '')} -> {current['vip_tier']}"
            )
        if current["maker_rate_percent"] != previous.get("maker_rate_percent", ""):
            changes.append(
                f"{current['exchange']} | {current['product']} Maker: "
                f"{_format_percent_display(previous.get('maker_rate_percent', ''))} -> "
                f"{_format_percent_display(current['maker_rate_percent'])}"
            )
        if current["taker_rate_percent"] != previous.get("taker_rate_percent", ""):
            changes.append(
                f"{current['exchange']} | {current['product']} Taker: "
                f"{_format_percent_display(previous.get('taker_rate_percent', ''))} -> "
                f"{_format_percent_display(current['taker_rate_percent'])}"
            )

    for key in sorted(previous_map):
        if key not in current_map:
            previous = previous_map[key]
            changes.append(
                f"{previous['exchange']} | {previous['product']} removed "
                f"(Maker {_format_percent_display(previous.get('maker_rate_percent', ''))}, "
                f"Taker {_format_percent_display(previous.get('taker_rate_percent', ''))})"
            )

    return changes


def _table_cell(text: str) -> dict[str, str]:
    return {"type": "raw_text", "text": text}


def _truncate_cell(text: str, width: int) -> str:
    text = (text or "").strip()
    if len(text) <= width:
        return text
    if width <= 3:
        return text[:width]
    return text[: width - 3] + "..."


def _render_text_table(rows: list[list[str]]) -> str:
    if not rows:
        return ""
    widths = [18, 12, 24, 8, 12]
    rendered_lines: list[str] = []
    for index, row in enumerate(rows):
        cells = [_truncate_cell(cell, widths[col]).ljust(widths[col]) for col, cell in enumerate(row)]
        rendered_lines.append(" | ".join(cells))
        if index == 0:
            rendered_lines.append("-+-".join("-" * width for width in widths))
    return "\n".join(rendered_lines)


def build_change_report_messages(
    normalized_rows: list[dict[str, str]],
    changes: list[str],
    report_time: datetime,
) -> list[str]:
    normalized_rows = _filter_normalized_rows(normalized_rows)
    intro_lines = _report_intro_lines("Exchange Fee Changes", report_time, normalized_rows, changes)

    if not normalized_rows:
        return _chunk_text_sections(
            [
                "Data status\n"
                "No valid fee rows were generated today. Please check account credentials, Redis access, or upstream exchange APIs."
            ],
            intro_lines,
        )

    if not changes:
        return _chunk_text_sections(["Fee changes vs yesterday\nNo fee changes detected."], intro_lines)

    bullet_lines = [f"- {line}" for line in changes]
    messages = _chunk_bullet_lines("Fee changes vs yesterday", bullet_lines, intro_lines)

    if len(messages) <= 1:
        return messages

    final_messages: list[str] = []
    for index, message in enumerate(messages, start=1):
        lines = message.splitlines()
        if lines:
            lines[0] = f"Exchange Fee Changes ({index}/{len(messages)})"
        final_messages.append("\n".join(lines))
    return final_messages


def build_detail_report_messages(
    normalized_rows: list[dict[str, str]],
    changes: list[str],
    report_time: datetime,
) -> list[str]:
    normalized_rows = _filter_normalized_rows(normalized_rows)
    intro_lines = _report_intro_lines("Exchange Fee Details", report_time, normalized_rows, changes)

    if not normalized_rows:
        return _chunk_text_sections(
            [
                "Data status\n"
                "No valid fee rows were generated today. Please check account credentials, Redis access, or upstream exchange APIs."
            ],
            intro_lines,
        )

    exchange_sections = _build_exchange_sections(normalized_rows)
    messages: list[str] = []
    for index in range(0, len(exchange_sections), MAX_EXCHANGE_SECTIONS_PER_MESSAGE):
        exchange_chunk = exchange_sections[index : index + MAX_EXCHANGE_SECTIONS_PER_MESSAGE]
        messages.extend(_chunk_text_sections(exchange_chunk, intro_lines))

    if len(messages) <= 1:
        return messages

    final_messages: list[str] = []
    for index, message in enumerate(messages, start=1):
        lines = message.splitlines()
        if lines:
            lines[0] = f"Exchange Fee Details ({index}/{len(messages)})"
        final_messages.append("\n".join(lines))
    return final_messages


def build_text_report_messages(
    normalized_rows: list[dict[str, str]],
    changes: list[str],
    report_time: datetime,
) -> list[str]:
    return [*build_change_report_messages(normalized_rows, changes, report_time), *build_detail_report_messages(normalized_rows, changes, report_time)]


def _build_generic_payloads(
    descriptions: list[str],
    report_time: datetime,
    *,
    title_base: str,
    message_type: str,
    urgency: str,
    topic: str,
) -> list[dict[str, object]]:
    report_date = report_time.date().isoformat()
    payloads: list[dict[str, object]] = []

    for index, description in enumerate(descriptions, start=1):
        chunk_suffix = f" ({index}/{len(descriptions)})" if len(descriptions) > 1 else ""
        title = f"{title_base}{chunk_suffix}"
        chunk_topic = f"{topic}-{report_date}-{message_type}-{index}"
        payloads.append(
            {
                "title": title,
                "srcType": "generic",
                "urgency": urgency,
                "description": description,
                "labels": {
                    "env": "production",
                    "app": "pb-exchange-fee",
                    "report_date": report_date,
                    "topic": chunk_topic,
                    "message_type": message_type,
                    "chunk": str(index),
                },
                "groupKey": f"pb_exchange_fee:{report_date}:{message_type}:{index}",
                "groupLabels": ["app", "env", "report_date", "message_type", "chunk"],
                "topic": chunk_topic,
            }
        )

    return payloads


def build_generic_webhook_payloads(
    normalized_rows: list[dict[str, str]],
    changes: list[str],
    report_time: datetime,
    *,
    topic: str = DEFAULT_GENERIC_TOPIC,
) -> list[dict[str, object]]:
    has_valid_rows = bool(_filter_normalized_rows(normalized_rows))
    urgency = "p1" if not has_valid_rows else "p2"
    change_payloads = _build_generic_payloads(
        build_change_report_messages(normalized_rows, changes, report_time),
        report_time,
        title_base="Exchange Fee Changes",
        message_type="changes",
        urgency=urgency,
        topic=topic,
    )
    detail_payloads = _build_generic_payloads(
        build_detail_report_messages(normalized_rows, changes, report_time),
        report_time,
        title_base="Exchange Fee Details",
        message_type="detail",
        urgency=urgency,
        topic=topic,
    )
    return [*change_payloads, *detail_payloads]


def build_slack_payloads(
    normalized_rows: list[dict[str, str]],
    changes: list[str],
    report_time: datetime,
) -> list[dict[str, object]]:
    normalized_rows = _filter_normalized_rows(normalized_rows)
    flattened_rows = flatten_table_rows(normalized_rows)
    header_row = flattened_rows[0]
    data_rows = flattened_rows[1:]
    table_chunks = [
        data_rows[index : index + MAX_TABLE_ROWS_PER_MESSAGE]
        for index in range(0, len(data_rows), MAX_TABLE_ROWS_PER_MESSAGE)
    ] or [[]]

    payloads: list[dict[str, object]] = []
    total_changes = len(changes)
    preview_changes = changes[:MAX_CHANGE_LINES_IN_MESSAGE]

    for index, chunk in enumerate(table_chunks, start=1):
        blocks: list[dict[str, object]] = []
        title_suffix = f" ({index}/{len(table_chunks)})" if len(table_chunks) > 1 else ""

        if index == 1:
            blocks.append(
                {
                    "type": "header",
                    "text": {
                        "type": "plain_text",
                        "text": f"Exchange Fee Daily Report{title_suffix}",
                    },
                }
            )
            blocks.append(
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": (
                            f"*Last updated:* {format_report_date(report_time)}  \n"
                            f"*Rows:* {len(normalized_rows)} normalized products  \n"
                            f"*Changes vs yesterday:* {total_changes}"
                        ),
                    },
                }
            )
            if not normalized_rows:
                blocks.append(
                    {
                        "type": "section",
                        "text": {
                            "type": "mrkdwn",
                            "text": (
                                "*Data status*\n"
                                "- No valid fee rows were generated today. "
                                "Please check account credentials, Redis access, or upstream exchange APIs."
                            ),
                        },
                    }
                )
            if total_changes:
                change_text = "\n".join(f"- {line}" for line in preview_changes)
                if total_changes > len(preview_changes):
                    change_text += f"\n- ... and {total_changes - len(preview_changes)} more changes"
                blocks.append(
                    {
                        "type": "section",
                        "text": {
                            "type": "mrkdwn",
                            "text": f"*Fee changes vs yesterday*\n{change_text}",
                        },
                    }
                )
            else:
                blocks.append(
                    {
                        "type": "section",
                        "text": {
                            "type": "mrkdwn",
                            "text": (
                                "*Fee changes vs yesterday*\n"
                                + (
                                    "- No valid fee rows today, so day-over-day diff was skipped."
                                    if not normalized_rows
                                    else "- No fee changes detected."
                                )
                            ),
                        },
                    }
                )
            blocks.append({"type": "divider"})

        if normalized_rows:
            table_rows = [header_row, *chunk]
            blocks.append(
                {
                    "type": "table",
                    "column_settings": [
                        {"align": "left", "is_wrapped": True},
                        {"align": "center"},
                        {"align": "left", "is_wrapped": True},
                        {"align": "center"},
                        {"align": "right"},
                    ],
                    "rows": [[_table_cell(cell) for cell in row] for row in table_rows],
                }
            )

        payloads.append(
            {
                "text": f"Exchange Fee Daily Report - {format_report_date(report_time)}",
                "blocks": blocks,
            }
        )
    return payloads


def send_webhook_payloads(webhook_url: str, payloads: Iterable[dict[str, object]]) -> list[dict[str, object]]:
    responses: list[dict[str, object]] = []
    for payload in payloads:
        response = requests.post(webhook_url, json=payload, timeout=15)
        responses.append(
            {
                "status_code": response.status_code,
                "body": response.text[:1000],
            }
        )
        response.raise_for_status()
    return responses


def render_html_report(
    normalized_rows: list[dict[str, str]],
    changes: list[str],
    report_time: datetime,
) -> str:
    normalized_rows = _filter_normalized_rows(normalized_rows)
    grouped: dict[tuple[str, str], list[dict[str, str]]] = defaultdict(list)
    for row in normalized_rows:
        grouped[(row["exchange"], row["vip_tier"])].append(row)

    table_sections: list[str] = []
    for (exchange, vip_tier), rows in grouped.items():
        exchange_rowspan = len(rows) * 2
        first_exchange_row = True
        for row in rows:
            product = html.escape(row["product"])
            maker = html.escape(row["maker_rate_percent"])
            taker = html.escape(row["taker_rate_percent"])
            exchange_html = ""
            vip_html = ""
            if first_exchange_row:
                exchange_html = f'<td class="exchange-cell" rowspan="{exchange_rowspan}">{html.escape(exchange)}</td>'
                vip_html = f'<td class="vip-cell" rowspan="{exchange_rowspan}">{html.escape(vip_tier)}</td>'
                first_exchange_row = False
            table_sections.append(
                "<tr>"
                f"{exchange_html}"
                f"{vip_html}"
                f'<td class="product-cell" rowspan="2">{product}</td>'
                '<td class="fee-type-cell">Maker</td>'
                f'<td class="fee-rate-cell">{maker}</td>'
                "</tr>"
            )
            table_sections.append(
                "<tr>"
                '<td class="fee-type-cell">Taker</td>'
                f'<td class="fee-rate-cell">{taker}</td>'
                "</tr>"
            )

    change_items = (
        "".join(f"<li>{html.escape(change)}</li>" for change in changes[:20])
        if changes
        else (
            "<li>No valid fee rows today, so day-over-day diff was skipped.</li>"
            if not normalized_rows
            else "<li>No fee changes detected.</li>"
        )
    )

    if not table_sections:
        table_sections.append(
            '<tr><td class="empty-cell" colspan="5">No valid fee data collected today.</td></tr>'
        )

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Exchange Fee Daily Report</title>
  <style>
    :root {{
      --navy: #10245f;
      --blue: linear-gradient(180deg, #4e73f1 0%, #4266e7 100%);
      --cell: #b7c8e8;
      --grid: #f4f7ff;
      --text: #113c4b;
    }}
    body {{
      margin: 0;
      font-family: "Segoe UI", Arial, sans-serif;
      background: #eef3ff;
      color: var(--text);
    }}
    .wrap {{
      width: min(1400px, calc(100vw - 32px));
      margin: 24px auto 40px;
      box-shadow: 0 24px 60px rgba(15, 26, 67, 0.18);
      border-radius: 12px;
      overflow: hidden;
      background: white;
    }}
    .hero {{
      background: var(--navy);
      color: white;
      display: flex;
      justify-content: space-between;
      align-items: center;
      padding: 28px 36px;
      font-size: 24px;
      font-weight: 600;
    }}
    .changes {{
      background: #f7fbff;
      border-bottom: 4px solid #dce8ff;
      padding: 18px 28px;
      font-size: 16px;
    }}
    .changes h2 {{
      margin: 0 0 10px;
      color: #18306f;
      font-size: 20px;
    }}
    .changes ul {{
      margin: 0;
      padding-left: 22px;
    }}
    table {{
      width: 100%;
      border-collapse: separate;
      border-spacing: 0;
    }}
    th, td {{
      border: 2px solid var(--grid);
      text-align: center;
      padding: 14px 18px;
      font-size: 18px;
    }}
    thead th {{
      background: var(--navy);
      color: white;
      font-size: 21px;
      font-weight: 600;
    }}
    .exchange-cell {{
      background: var(--navy);
      color: white;
      font-size: 24px;
      width: 18%;
    }}
    .vip-cell {{
      background: var(--blue);
      color: white;
      font-size: 22px;
      width: 22%;
    }}
    .product-cell, .fee-type-cell, .fee-rate-cell {{
      background: var(--cell);
    }}
    .product-cell {{
      font-size: 22px;
      width: 31%;
    }}
    .fee-type-cell {{
      width: 12%;
    }}
    .fee-rate-cell {{
      width: 17%;
      font-variant-numeric: tabular-nums;
    }}
    .empty-cell {{
      background: var(--cell);
      font-size: 20px;
      padding: 28px 18px;
    }}
    @media (max-width: 900px) {{
      .hero {{
        flex-direction: column;
        gap: 8px;
        align-items: flex-start;
      }}
      th, td {{
        font-size: 14px;
        padding: 10px 8px;
      }}
      .exchange-cell, .vip-cell, .product-cell {{
        font-size: 16px;
      }}
    }}
  </style>
</head>
<body>
  <div class="wrap">
    <div class="hero">
      <div>Exchange Fee Daily Report</div>
      <div>Last updated: {html.escape(format_report_date(report_time))}</div>
    </div>
    <div class="changes">
      <h2>Fee changes vs yesterday</h2>
      <ul>{change_items}</ul>
    </div>
    <table>
      <thead>
        <tr>
          <th>Exchange</th>
          <th>VIP Tier</th>
          <th>Trading</th>
          <th>Fee Type</th>
          <th>Fee rate</th>
        </tr>
      </thead>
      <tbody>
        {''.join(table_sections)}
      </tbody>
    </table>
  </div>
</body>
</html>"""


def generate_report_artifacts(
    base_dir: str,
    normalized_rows: list[dict[str, str]],
    timezone_name: str,
) -> dict[str, object]:
    tz = ZoneInfo(timezone_name)
    report_time = datetime.now(tz)
    previous_time = report_time - timedelta(days=1)
    today_history_path = _history_path(base_dir, report_time)
    previous_history_path = _history_path(base_dir, previous_time)
    previous_rows = load_json_file(previous_history_path)
    changes = diff_normalized_rows(normalized_rows, previous_rows)
    payloads = build_generic_webhook_payloads(normalized_rows, changes, report_time)
    html_report = render_html_report(normalized_rows, changes, report_time)
    html_report_path = _html_report_path(base_dir, report_time)
    os.makedirs(os.path.dirname(html_report_path), exist_ok=True)
    with open(html_report_path, "w", encoding="utf-8") as handle:
        handle.write(html_report)
    write_json_file(today_history_path, normalized_rows)
    write_json_file(_payload_archive_path(base_dir, report_time), payloads)
    return {
        "report_time": report_time,
        "changes": changes,
        "payloads": payloads,
        "html_report_path": html_report_path,
        "today_history_path": today_history_path,
        "previous_history_path": previous_history_path,
    }
