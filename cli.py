# This file is for command line entry point (dry-run/write)

import argparse
from autocal.config import DEFAULT_JSON_PATH, DEFAULT_LOG_PATH, get_conn_str
from autocal.db import connect, find_records_by_country_and_date
from autocal.holidays import next_week_window, load_holiday_dict, holidays_for_country
from autocal.planner import build_note, plan_note_updates
from autocal.actions import apply_note_actions
import csv
import os


def log_csv(path, rows):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    fieldnames = ["country","holiday_date","fdRecID","database","group","update",
                  "action_type","result","old_note","new_note","error"]
    exists = os.path.exists(path) and os.path.getsize(path) > 0
    with open(path, "a", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        if not exists:
            w.writeheader()
        w.writerows(rows)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--json-path", default=DEFAULT_JSON_PATH)
    ap.add_argument("--log-path",  default=DEFAULT_LOG_PATH)
    ap.add_argument("--write", action="store_true")
    ap.add_argument("--max-updates", type=int, default=50)
    ap.add_argument("--countries", default="", help="Comma-separated list, e.g. China,Vietnam")
    args = ap.parse_args()

    dry_run = not args.write
    country_filter = {c.strip() for c in args.countries.split(",") if c.strip()} or None

    start, end = next_week_window()
    print(f"[INFO] Window: {start} → {end}")
    print("[INFO] DRY RUN" if dry_run else "[INFO] WRITE MODE")

    holiday_dict = load_holiday_dict(args.json_path)

    conn, cursor = connect(get_conn_str())

    # countries on calendar next week
    cursor.execute("""
        SELECT DISTINCT cnt.fdCountryName
        FROM tblcalendar_dw_templates dwt
        JOIN tblcalendar_countries cnt ON cnt.fdCountryID = dwt.fdCountryID
        JOIN tblcalendar_dw_records dwr ON dwr.fdTemplateID = dwt.fdTemplateID
        WHERE dwr.fdDone = 0
          AND DATE(dwr.fddDate2Show) BETWEEN ? AND ?;
    """, (start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d")))
    countries = [r[0] for r in cursor.fetchall()]

    actions = []
    for country in countries:
        hlist = holidays_for_country(holiday_dict, country)
        week_holidays = sorted({d for d in hlist if start <= d <= end})
        for hdate in week_holidays:
            recs = find_records_by_country_and_date(cursor, country, hdate)
            if not recs:
                continue
            note = build_note(hdate)
            actions.extend(plan_note_updates(recs, country, hdate, note))

    eligible = sum(1 for a in actions if a["action_type"] == "UPDATE_NOTE"
                   and (country_filter is None or a["country"] in country_filter))

    if not dry_run and eligible > args.max_updates:
        print(f"[ERROR] Refusing to write {eligible} updates (> {args.max_updates}).")
        for a in actions:
            if a["action_type"] == "UPDATE_NOTE":
                a["result"] = "BLOCKED_MAX_UPDATES"
        log_csv(args.log_path, actions)
        return

    wrote = apply_note_actions(conn, cursor, actions, dry_run=dry_run, country_filter=country_filter)
    log_csv(args.log_path, actions)

    print(f"[SUMMARY] planned_updates={sum(1 for a in actions if a['action_type']=='UPDATE_NOTE')}, "
          f"planned_skips={sum(1 for a in actions if a['action_type']=='SKIP_NO_CHANGE')}, "
          f"written={wrote}")

    cursor.close()
    conn.close()

if __name__ == "__main__":
    main()