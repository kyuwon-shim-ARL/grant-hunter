#!/usr/bin/env python3
"""
create_calendar_events.py - Create Google Calendar events for grant deadlines.

Usage:
    python create_calendar_events.py [--dry-run] [--calendar-id <id>]

Reads grant deadline JSON from extract_deadlines.py output (stdin or auto-runs it).
Creates events with reminders at 14 days, 7 days, and 3 days before deadline.
Skips grants without a known deadline_date.
Skips events that already exist (same title on same date).
"""

import json
import os
import subprocess
import sys
from datetime import datetime, date, timedelta
from pathlib import Path

# Google API
try:
    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import Request
    from googleapiclient.discovery import build
except ImportError:
    print("ERROR: google-api-python-client not installed.", file=sys.stderr)
    print("Run: pip install google-api-python-client google-auth-oauthlib", file=sys.stderr)
    sys.exit(1)

TOKEN_PATH = "/home/kyuwon/projects/email_agent/token.json"
SCOPES = ["https://www.googleapis.com/auth/calendar"]

SCRIPT_DIR = Path(__file__).parent


def get_credentials():
    if not os.path.exists(TOKEN_PATH):
        print(f"ERROR: Token not found at {TOKEN_PATH}", file=sys.stderr)
        sys.exit(1)

    creds = Credentials.from_authorized_user_file(TOKEN_PATH, SCOPES)
    if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())
    return creds


def get_calendar_service(creds):
    return build("calendar", "v3", credentials=creds, cache_discovery=False)


def load_grants():
    """Run extract_deadlines.py and parse its JSON output."""
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


def existing_event_titles(service, calendar_id, time_min, time_max):
    """Return set of (summary, date_str) tuples for existing events in date range."""
    existing = set()
    page_token = None
    while True:
        resp = service.events().list(
            calendarId=calendar_id,
            timeMin=time_min.isoformat() + "Z",
            timeMax=time_max.isoformat() + "Z",
            singleEvents=True,
            pageToken=page_token,
            maxResults=500,
        ).execute()
        for ev in resp.get("items", []):
            summary = ev.get("summary", "")
            start = ev.get("start", {})
            date_str = start.get("date") or start.get("dateTime", "")[:10]
            existing.add((summary, date_str))
        page_token = resp.get("nextPageToken")
        if not page_token:
            break
    return existing


def build_event(grant, deadline_date):
    """Build a Google Calendar event dict for the grant deadline."""
    tier_label = f"Tier {grant['tier']}"
    score = grant.get("score", "?")
    scale = grant.get("scale", "")
    url = grant.get("url", "")
    note = grant.get("note", "")
    uncertain_flag = " [마감일 추정]" if grant.get("uncertain") else ""

    description_parts = [
        f"프로그램: {grant['program_name']}",
        f"분류: {tier_label} (점수: {score})",
        f"규모: {scale}",
        f"마감 원문: {grant['deadline_raw']}{uncertain_flag}",
        f"메모: {note}",
    ]
    if url:
        description_parts.append(f"링크: {url}")

    return {
        "summary": f"[Grant] {grant['program_name']} 마감",
        "description": "\n".join(description_parts),
        "start": {"date": deadline_date.isoformat()},
        "end": {"date": (deadline_date + timedelta(days=1)).isoformat()},
        "reminders": {
            "useDefault": False,
            "overrides": [
                {"method": "email", "minutes": 14 * 24 * 60},
                {"method": "email", "minutes": 7 * 24 * 60},
                {"method": "email", "minutes": 3 * 24 * 60},
                {"method": "popup", "minutes": 3 * 24 * 60},
            ],
        },
        "colorId": "11" if grant["tier"] == 1 else ("5" if grant["tier"] == 2 else "9"),
    }


def main():
    import argparse

    parser = argparse.ArgumentParser(description="Create Google Calendar events for grant deadlines")
    parser.add_argument("--dry-run", action="store_true", help="Print events without creating them")
    parser.add_argument("--calendar-id", default="primary", help="Google Calendar ID (default: primary)")
    args = parser.parse_args()

    grants = load_grants()
    grants_with_date = [g for g in grants if g.get("deadline_date")]

    print(f"Loaded {len(grants)} grants, {len(grants_with_date)} have a known deadline date.")

    if args.dry_run:
        print("\n[DRY RUN] Events that would be created:")
        for g in grants_with_date:
            dl = date.fromisoformat(g["deadline_date"])
            uncertain = " (추정)" if g.get("uncertain") else ""
            print(f"  [{g['tier']}] {g['program_name']} → {dl}{uncertain}")
        print(f"\nTotal: {len(grants_with_date)} events")
        return 0

    creds = get_credentials()
    service = get_calendar_service(creds)

    # Determine date range for dedup check
    dates = [date.fromisoformat(g["deadline_date"]) for g in grants_with_date]
    range_min = datetime.combine(min(dates) - timedelta(days=1), datetime.min.time())
    range_max = datetime.combine(max(dates) + timedelta(days=2), datetime.min.time())

    print("Fetching existing calendar events for dedup...")
    existing = existing_event_titles(service, args.calendar_id, range_min, range_max)
    print(f"Found {len(existing)} existing events in range.")

    created = 0
    skipped = 0

    for grant in grants_with_date:
        dl = date.fromisoformat(grant["deadline_date"])
        event = build_event(grant, dl)
        key = (event["summary"], dl.isoformat())

        if key in existing:
            print(f"  SKIP (already exists): {event['summary']} on {dl}")
            skipped += 1
            continue

        try:
            result = service.events().insert(
                calendarId=args.calendar_id,
                body=event,
            ).execute()
            print(f"  CREATED: {event['summary']} on {dl} → {result.get('htmlLink', '')}")
            created += 1
        except Exception as e:
            print(f"  ERROR creating {event['summary']}: {e}", file=sys.stderr)

    print(f"\nDone. Created: {created}, Skipped (duplicate): {skipped}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
