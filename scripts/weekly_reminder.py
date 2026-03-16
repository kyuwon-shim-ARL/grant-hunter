#!/usr/bin/env python3
"""
weekly_reminder.py - Send weekly HTML email with upcoming grant deadlines.

Usage:
    python weekly_reminder.py <recipient_email> [--days <N>]

Sends HTML email listing grants with deadlines within the next N days (default: 30).
Color coding:
  - Red:    deadline within 7 days
  - Orange: deadline within 14 days
  - Yellow: deadline within 30 days
  - Green:  deadline > 30 days (shown if --all flag used)

Relies on ~/bin/send-email utility.
"""

import argparse
import json
import subprocess
import sys
from datetime import date, datetime
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent
SEND_EMAIL_BIN = Path.home() / "bin" / "send-email"


def load_grants():
    script = SCRIPT_DIR / "extract_deadlines.py"
    result = subprocess.run(
        [sys.executable, str(script)],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        print(f"ERROR: extract_deadlines.py failed:\n{result.stderr}", file=sys.stderr)
        sys.exit(1)
    return json.loads(result.stdout)["grants"]


def deadline_color(days_until):
    if days_until <= 7:
        return "#d32f2f"   # red
    elif days_until <= 14:
        return "#e65100"   # deep orange
    elif days_until <= 30:
        return "#f57f17"   # amber
    else:
        return "#388e3c"   # green


def urgency_label(days_until):
    if days_until <= 7:
        return "🔴 긴급"
    elif days_until <= 14:
        return "🟠 주의"
    elif days_until <= 30:
        return "🟡 준비"
    else:
        return "🟢 여유"


def tier_badge(tier):
    colors = {1: "#c62828", 2: "#1565c0", 3: "#2e7d32"}
    color = colors.get(tier, "#555")
    return f'<span style="background:{color};color:white;padding:2px 7px;border-radius:3px;font-size:12px;">Tier {tier}</span>'


def build_html(grants_in_range, window_days, today):
    rows = []
    for g in grants_in_range:
        days = g["days_until"]
        dl_str = g["deadline_date"]
        uncertain = " <em style='color:#888'>(추정)</em>" if g.get("uncertain") else ""
        color = deadline_color(days)
        urgency = urgency_label(days)
        url = g.get("url", "")
        name = g["program_name"]
        link = f'<a href="{url}" style="color:#1a237e">{name}</a>' if url else name

        rows.append(f"""
        <tr>
          <td style="padding:8px 12px;border-bottom:1px solid #eee">{tier_badge(g['tier'])}</td>
          <td style="padding:8px 12px;border-bottom:1px solid #eee">{link}</td>
          <td style="padding:8px 12px;border-bottom:1px solid #eee;color:{color};font-weight:bold">
            {dl_str}{uncertain}
          </td>
          <td style="padding:8px 12px;border-bottom:1px solid #eee;color:{color};text-align:center">
            {days}일<br><small>{urgency}</small>
          </td>
          <td style="padding:8px 12px;border-bottom:1px solid #eee;color:#555;font-size:13px">
            {g.get('scale', '')}
          </td>
        </tr>""")

    rows_html = "\n".join(rows) if rows else '<tr><td colspan="5" style="padding:20px;text-align:center;color:#888">향후 {}일 내 마감 Grant 없음</td></tr>'.format(window_days)

    unknown_items = []
    for g in grants_in_range:
        pass  # already filtered

    today_str = today.strftime("%Y년 %m월 %d일")

    return f"""<!DOCTYPE html>
<html>
<head><meta charset="utf-8"><title>Grant 마감 주간 리마인더</title></head>
<body style="font-family:Arial,sans-serif;margin:0;padding:20px;background:#f5f5f5">
  <div style="max-width:800px;margin:0 auto;background:white;border-radius:8px;overflow:hidden;box-shadow:0 2px 8px rgba(0,0,0,0.1)">

    <!-- Header -->
    <div style="background:#1a237e;color:white;padding:20px 24px">
      <h1 style="margin:0;font-size:20px">Grant 마감 주간 리마인더</h1>
      <p style="margin:6px 0 0;opacity:0.8;font-size:14px">{today_str} 기준 | 향후 {window_days}일 이내 마감</p>
    </div>

    <!-- Summary badges -->
    <div style="padding:16px 24px;background:#e8eaf6;display:flex;gap:16px;flex-wrap:wrap">
      <span style="font-size:14px">총 <strong>{len(grants_in_range)}</strong>건</span>
      <span style="color:#d32f2f;font-size:14px">🔴 7일 이내: <strong>{sum(1 for g in grants_in_range if g['days_until'] <= 7)}</strong>건</span>
      <span style="color:#e65100;font-size:14px">🟠 14일 이내: <strong>{sum(1 for g in grants_in_range if 7 < g['days_until'] <= 14)}</strong>건</span>
      <span style="color:#f57f17;font-size:14px">🟡 30일 이내: <strong>{sum(1 for g in grants_in_range if 14 < g['days_until'] <= 30)}</strong>건</span>
    </div>

    <!-- Table -->
    <div style="padding:16px 24px">
      <table style="width:100%;border-collapse:collapse">
        <thead>
          <tr style="background:#f5f5f5">
            <th style="padding:10px 12px;text-align:left;font-size:13px;color:#555">Tier</th>
            <th style="padding:10px 12px;text-align:left;font-size:13px;color:#555">프로그램명</th>
            <th style="padding:10px 12px;text-align:left;font-size:13px;color:#555">마감일</th>
            <th style="padding:10px 12px;text-align:center;font-size:13px;color:#555">D-day</th>
            <th style="padding:10px 12px;text-align:left;font-size:13px;color:#555">규모</th>
          </tr>
        </thead>
        <tbody>
{rows_html}
        </tbody>
      </table>
    </div>

    <!-- Footer -->
    <div style="padding:16px 24px;background:#fafafa;border-top:1px solid #eee;font-size:12px;color:#888">
      <p style="margin:0">* 이탤릭체로 표시된 마감일은 추정값입니다. 각 프로그램 공식 웹사이트에서 최신 공고문을 반드시 재확인하시기 바랍니다.</p>
      <p style="margin:4px 0 0">* 본 메일은 grant_hunter 자동화 시스템에 의해 발송되었습니다.</p>
    </div>
  </div>
</body>
</html>"""


def send_email(recipient, subject, html_body):
    if not SEND_EMAIL_BIN.exists():
        print(f"ERROR: send-email not found at {SEND_EMAIL_BIN}", file=sys.stderr)
        sys.exit(1)

    result = subprocess.run(
        [str(SEND_EMAIL_BIN), recipient, subject, html_body, "--html"],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        print(f"ERROR: send-email failed:\n{result.stderr}", file=sys.stderr)
        sys.exit(1)
    return result.stdout


def main():
    parser = argparse.ArgumentParser(description="Send weekly grant deadline reminder email")
    parser.add_argument("recipient", help="Recipient email address")
    parser.add_argument("--days", type=int, default=30, help="Window in days (default: 30)")
    parser.add_argument("--dry-run", action="store_true", help="Print HTML without sending")
    args = parser.parse_args()

    today = date.today()
    grants = load_grants()

    # Filter: only grants with known deadline_date within the window
    grants_in_range = [
        g for g in grants
        if g.get("deadline_date") and 0 <= g["days_until"] <= args.days
    ]

    # Sort by days_until ascending
    grants_in_range.sort(key=lambda x: x["days_until"])

    print(f"Found {len(grants_in_range)} grants with deadlines in next {args.days} days.")

    html_body = build_html(grants_in_range, args.days, today)

    week_str = today.strftime("%Y.%m.%d")
    subject = f"[Grant Hunter] 주간 마감 리마인더 - {week_str} ({len(grants_in_range)}건)"

    if args.dry_run:
        print(f"\nSubject: {subject}")
        print(f"To: {args.recipient}")
        print("\n--- HTML Body Preview ---")
        print(html_body[:2000], "...(truncated)" if len(html_body) > 2000 else "")
        return 0

    print(f"Sending to {args.recipient}...")
    output = send_email(args.recipient, subject, html_body)
    print(f"Email sent successfully.\n{output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
