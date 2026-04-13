# This file is for command line entry point (dry-run/write)

import csv
import os
import argparse
from autocal.config import DEFAULT_CSV_PATH, DEFAULT_LOG_PATH, get_conn_str
from autohol.db import connect, find_records_by_country_and_date
from autocal.holidays import load_holiday_dict, holidays_for_country, resolve_window
from autocal.planner import build_note, plan_actions
from autocal.actions import apply_actions
from autocal.export_ui import write_ui_snapshot_json
import json
from datetime import datetime



def write_audit_log_csv(path, rows):
    """
    Append audit rows (log for review/debugging).
    """
    folder = os.path.dirname(path)
    if folder:
        os.makedirs(folder, exist_ok=True)

    fieldnames = [
        "timestamp",
        "run_id",
        "module",
        "action_type",
        "result",
        "fdRecID",
        "fddDate2Show",
        "database",
        "country",
        "group",
        "update",
        "old_note",
        "new_note",
        "error",
    ]

    exists = os.path.exists(path) and os.path.getsize(path) > 0
    with open(path, "a", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        if not exists:
            w.writeheader()
        for r in rows:
            w.writerow(r)



def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--start-date", default="", help="Optional custom start date in YYYY-MM-DD")
    ap.add_argument("--end-date", default="", help="Optional custom end date in YYYY-MM-DD")
    ap.add_argument("--csv-path", default=DEFAULT_CSV_PATH)
    ap.add_argument("--log-path",  default=DEFAULT_LOG_PATH)
    ap.add_argument("--ui-json-path", default=r"data/logs/ui_plan_snapshot.json")
    ap.add_argument("--write", action="store_true")
    ap.add_argument("--max-updates", type=int, default=50)
    args = ap.parse_args()

    dry_run = not args.write

    run_id = datetime.now().strftime("%Y%m%d_%H%M%S")
    run_ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    try:
        start, end, window_mode = resolve_window(args.start_date, args.end_date)
    except ValueError as e:
        print(f"[ERROR] {e}")
        return

    print(f"[INFO] Holiday Check Window: {start} → {end} ({window_mode})")
    print("[INFO] DRY RUN" if dry_run else "[INFO] WRITE MODE")

    holiday_dict = load_holiday_dict(args.csv_path)

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
            seen = set()
            unique_recs = []
            for r in recs:
                rid = getattr(r, "fdRecID", None)
                if rid not in seen:
                    seen.add(rid)
                    unique_recs.append(r)
            recs = unique_recs

            if not recs:
                continue
            note = build_note(hdate)
            actions.extend(plan_actions(recs, country, hdate, note))

    eligible = sum(1 for a in actions if a["action_type"] == "UPDATE_NOTE")

    if not dry_run and eligible > args.max_updates:
        print(f"[ERROR] Refusing to write {eligible} updates (> {args.max_updates}).")
        for a in actions:
            if a["action_type"] == "UPDATE_NOTE":
                a["result"] = "BLOCKED_MAX_UPDATES"
        wrote = 0
    else:
        wrote = apply_actions(conn, cursor, actions, dry_run=dry_run)

    # Build run meta + summary
    summary = {
        "countries_on_calendar": len(countries),
        "countries_with_holidays": len({a["country"] for a in actions}),
        "holiday_pairs": len({(a["country"], a["holiday_date"]) for a in actions}),
        "matched_records": len(actions),
        "planned_updates": sum(1 for a in actions if a["action_type"] == "UPDATE_NOTE"),
        "planned_skips": sum(1 for a in actions if a["action_type"] == "SKIP_NO_CHANGE"),
        "written": wrote,
    }

    run_meta = {
        "run_id": run_id,
        "created_at": run_ts,
        "window_start": str(start),
        "window_end": str(end),
        "source_file": args.csv_path,
        "dry_run": dry_run,
        "schema_version": "1.0"
    }

    # Audit rows (append CSV)
    audit_rows = []
    for a in actions:
        audit_rows.append({
            "timestamp": run_ts,
            "run_id": run_id,
            "module": "holiday_note",
            "action_type": a.get("action_type", ""),
            "result": a.get("result", ""),
            "fdRecID": a.get("fdRecID", ""),
            "fddDate2Show": a.get("fddDate2Show", ""),
            "database": a.get("database", ""),
            "country": a.get("country", ""),
            "group": a.get("group", ""),
            "update": a.get("update", ""),
            "old_note": a.get("old_note", ""),
            "new_note": a.get("new_note", ""),
            "error": a.get("error", ""),
        })

    write_audit_log_csv(args.log_path, audit_rows)
    print(f"[INFO] Logged {len(audit_rows)} audit rows to: {args.log_path}")

    # UI snapshot (overwrite JSON each run)
    ui_count = write_ui_snapshot_json(args.ui_json_path, run_meta, summary, actions)
    print(f"[INFO] Wrote UI snapshot ({ui_count} records) to: {args.ui_json_path}")
    
    print(f"[INFO] Logged {len(actions)} rows to: {args.log_path}")
    print(f"[SUMMARY] planned_updates={sum(1 for a in actions if a['action_type']=='UPDATE_NOTE')}, "
          f"planned_skips={sum(1 for a in actions if a['action_type']=='SKIP_NO_CHANGE')}, "
          f"written={wrote}")

    cursor.close()
    conn.close()

if __name__ == "__main__":
    main()