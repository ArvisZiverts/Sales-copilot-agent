"""Print the most recent rows from the leads sheet.

    python -m scripts.show_leads          # last 5
    python -m scripts.show_leads 20       # last 20
    python -m scripts.show_leads --watch  # poll until a new row appears

Handy for checking a submission landed without opening the browser, and for
eyeballing whether the ICP scores are actually discriminating.
"""

import sys
import time

from app.clients.sheets import HEADERS, _worksheet

WIDE = {"icp_reason", "icebreaker", "primary_service", "company_size_signal"}


def fetch() -> list[list[str]]:
    rows = _worksheet().get_all_values()
    return rows[1:] if rows else []


def render(rows: list[list[str]], limit: int) -> None:
    if not rows:
        print("No leads yet.")
        return
    for row in rows[-limit:]:
        record = dict(zip(HEADERS, row + [""] * (len(HEADERS) - len(row))))
        score = record.get("icp_score") or "-"
        print("=" * 78)
        print(f"{record.get('full_name', '?')}  <{record.get('email', '')}>")
        print(f"  score {score}/10   status={record.get('status')}   "
              f"confidence={record.get('data_confidence')}   {record.get('timestamp')}")
        if record.get("error"):
            print(f"  ERROR: {record['error']}")
        print(f"  sources: {record.get('sources')}")
        for key in ("website", "linkedin_url", "industry", "niche"):
            if record.get(key):
                print(f"  {key:16} {record[key]}")
        for key in ("primary_service", "company_size_signal", "icp_reason", "icebreaker"):
            if record.get(key):
                print(f"\n  {key}:\n    {record[key]}")
        print()


def main() -> None:
    args = [a for a in sys.argv[1:]]
    watch = "--watch" in args
    args = [a for a in args if a != "--watch"]
    limit = int(args[0]) if args else 5

    if not watch:
        render(fetch(), limit)
        return

    baseline = len(fetch())
    print(f"{baseline} rows now — polling for a new one (Ctrl-C to stop)...")
    while True:
        time.sleep(10)
        rows = fetch()
        if len(rows) > baseline:
            print(f"\nNew row after {len(rows) - baseline} change(s):\n")
            render(rows, len(rows) - baseline)
            return
        print(".", end="", flush=True)


if __name__ == "__main__":
    main()
