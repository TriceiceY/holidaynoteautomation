# file: auto_holiday_notes_v2.py
# Reads QPP holiday CSV file, filters next week (Mon→Sun),
# then posts one note to the matching autocalendar record found by Country+Date.

import pyodbc
import re
import sys
import argparse
from datetime import datetime, date, timedelta
import csv
import os



def get_odbc_driver():
    drivers = pyodbc.drivers()
    version = 0.0
    latest_driver = None
    for driver in drivers:
        match = re.search('MySQL ODBC (\d+[.]\d+).* Driver', driver)
        if match:
            if float(match[1]) > version:
                latest_driver = match[0]
                version = float(match[1])
    if latest_driver:
        return latest_driver
    print('Unable to find a MySQL ODBC driver. Contact operations.')
    sys.exit(1)


def connect_to_db(MDB):
    global con
    global cursor
    con = pyodbc.connect(MDB, ansi=True)
    cursor = con.cursor()

  
def find_records_by_country_and_date(country: str, target_date: date):
    sql = """
        SELECT
            dwr.*,
            cnt.fdCountryName,
            dwdb.fdDatabaseName AS fdDatabaseName,
            dwt.fdGroup         AS fdGroup,
            dwt.fdMessageBoard  AS fdMessageBoard
        FROM tblcalendar_dw_templates dwt
        JOIN tblcalendar_countries cnt
          ON cnt.fdCountryID = dwt.fdCountryID
        JOIN tblcalendar_dw_records dwr
          ON dwt.fdTemplateID = dwr.fdTemplateID
        JOIN tblcalendar_dw_database dwdb
          ON dwdb.fdDatabaseID = dwt.fdDatabaseID
        WHERE dwr.fdDone=0 
            AND cnt.fdCountryName = ?
            AND DATE(dwr.fddDate2Show) = ?
    """
    params = [country, target_date.strftime("%Y-%m-%d")]
    cursor.execute(sql + ";", params)
    rows = cursor.fetchall()
    rows.sort(key=lambda r: r.fddDate2Show)
    return rows


def load_holiday_dict_from_csv(csv_path):
    """
    Build a dict like:
      {
        "country1": [date(2026,2,16), date(2026,2,17), ...],
        "country2": [...]
      }

    Rules:
    - Reads QPP holidays CSV file
    - Converts 'Holiday Date' Excel serial -> Python date
    - Ignores rows where Holiday Observance == 'Regional' (case-insensitive exact match)
    """
    holiday_dict = {}

    with open(csv_path, "r", encoding="latin1", newline="") as f:
        reader = csv.DictReader(f, delimiter=";")

        for row in reader:
            country = (row.get("Country Name") or "").strip()
            observance = (row.get("Holiday Observance") or "").strip()

            if not country:
                continue

            # Ignore only exact "Regional" (case-insensitive)
            if observance.lower() == "regional":
                continue

            raw_date = (row.get("Holiday Date") or "").strip()
            if not raw_date:
                continue

            try:
                # CSV stores Excel serial dates (e.g., 46023)
                serial = int(float(raw_date))
                # Excel serial origin (Windows Excel)
                hdate = (datetime(1899, 12, 30) + timedelta(days=serial)).date()
            except Exception:
                continue

            key = country.lower()
            holiday_dict.setdefault(key, set()).add(hdate)

    # convert sets to sorted lists
    return {k: sorted(v) for k, v in holiday_dict.items()}



def log_matches_csv(log_path, matches):
    folder = os.path.dirname(log_path)
    if folder:
        os.makedirs(folder, exist_ok=True)

    fieldnames = [
        "country","holiday_date","fdRecID",
        "database","group","update",
        "action_type","result",
        "old_note","new_note"
    ]

    file_exists = os.path.exists(log_path) and os.path.getsize(log_path) > 0

    with open(log_path, "a", newline="", encoding="latin1") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        if not file_exists:
            writer.writeheader()

        for row in matches:
            clean = {k: row.get(k, "") for k in fieldnames}
            writer.writerow(clean)


def format_note(old_note, new_note, separator=" | "):
    old_note = "" if old_note is None else str(old_note)
    parts = [p.strip() for p in old_note.split(separator) if p.strip()]
    kept = [p for p in parts if not p.startswith("AUTOHOL:")]
    kept.append(new_note)
    return separator.join(kept)[:200]


def write_note(record, note):
    final_note = note
    if record.fdNotes is not None:
        final_note = format_note(record.fdNotes, note)[:200]
    cursor.execute(
        "UPDATE tblcalendar_dw_records SET fdNotes=? WHERE fdRecID=?;",
        (final_note, record.fdRecID)
    )
    con.commit()
    return final_note


def build_note(hdate):
    return f"AUTOHOL: Holiday, {hdate:%m/%d/%Y}"


def next_week_window(today=None):
    """Next Monday → next Sunday (inclusive)."""
    today = today or datetime.now().date()
    days_ahead = (0 - today.weekday() + 7) % 7
    if days_ahead == 0:
        days_ahead = 7
    #start = today + timedelta(days=days_ahead)
    start = today
    end = start + timedelta(days=30)
    return start, end


## Create a function that returns a list of action dicts. It should NOT write to DB. 
def plan_actions(records, country, hdate, note_text):
    actions = []
    for rec in records:
        old = (rec.fdNotes or "")
        new = format_note(old, note_text)[:200]

        if new == old:
            action_type = "SKIP_NO_CHANGE"
        else:
            action_type = "UPDATE_NOTE"

        actions.append({
            "country": country,
            "holiday_date": hdate.strftime("%Y-%m-%d"),
            "fdRecID": rec.fdRecID,
            "database": getattr(rec, "fdDatabaseName", ""),
            "group": getattr(rec, "fdGroup", ""),
            "update": getattr(rec, "fdMessageBoard", ""),
            "action_type": action_type,
            "old_note": old[:200],
            "new_note": new[:200],
            "result": "PLANNED", 
        })
    return actions



def apply_actions(actions, dry_run, country_filter=None):
    wrote = 0
    for a in actions:
        if a["action_type"] != "UPDATE_NOTE":
            a["result"] = "SKIP_NO_CHANGE"
            continue

        if dry_run:
            a["result"] = "DRY_RUN"
            continue

        if country_filter and a["country"] not in country_filter:
            a["result"] = "FILTERED_OUT"
            continue

        cursor.execute(
            "UPDATE tblcalendar_dw_records SET fdNotes=? WHERE fdRecID=?;",
            (a["new_note"], a["fdRecID"])
        )
        a["result"] = "WROTE"
        wrote += 1

    if not dry_run and wrote > 0:
        con.commit()
    return wrote


def parse_args():
    p = argparse.ArgumentParser()
    p.add_argument("--write", action="store_true",
                   help="Actually write notes to DB. Default is dry-run (no writes).")
    p.add_argument("--max-updates", type=int, default=50,
                   help="Safety cap: refuse to write if planned updates exceed this number (default 50).")
    p.add_argument("--csv-path", default=r"C:\Users\JiebingYin\OneDrive - Haver Analytics\python files\HolidayNoteAutomation\Q++ Worldwide Public Holidays ISO-2026.CSV")
    p.add_argument("--log-path",  default=r"C:\Users\JiebingYin\OneDrive - Haver Analytics\python files\HolidayNoteAutomation\holiday_notes_match_log.csv")
    return p.parse_args()


def main(dry_run=True, max_updates=50, csv_path=None, log_path=None):

    country_filter = None  # or None for full run

    print("[INFO] DRY RUN — no notes will be written." if dry_run
        else "[INFO] WRITE MODE — notes WILL be written.")
    print(f"[INFO] Safety cap max_updates = {max_updates}")
    
    countries_with_holidays = set()
    holiday_pairs = 0   # (# of (country, holiday_date) pairs in the window)

    LOG_PATH = log_path

    CSV_PATH = csv_path
    holidayDict = load_holiday_dict_from_csv(CSV_PATH)


    start, end = next_week_window()
    print(f"[INFO] Next-week window: {start} → {end}")

    # --- connect DB ---
    odbc_driver = get_odbc_driver()
    connect_to_db(
        f'DRIVER={{{odbc_driver}}};SERVER=10.1.4.6;PORT=3306;DATABASE=autocalendar;UID=autocal;PWD=AutoCal_Pwd'
    )

    # --- countries that appear on the DW calendar next week ---
    cursor.execute("""
        SELECT DISTINCT cnt.fdCountryName
        FROM tblcalendar_dw_templates dwt
        JOIN tblcalendar_countries cnt
        ON cnt.fdCountryID = dwt.fdCountryID
        JOIN tblcalendar_dw_records dwr
        ON dwr.fdTemplateID = dwt.fdTemplateID
        WHERE dwr.fdDone = 0
        AND DATE(dwr.fddDate2Show) BETWEEN ? AND ?;
    """, (start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d")))
    countries = [r[0] for r in cursor.fetchall()]
    print(f"[INFO] Countries on DW calendar next week: {len(countries)}")

    log_rows = []
    found_records = 0
    misses = 0

    for country in countries:
        if country.lower() not in holidayDict:
            print(f"[WARN] {country} not in holiday CSV.")
            continue

        holiday_list = holidayDict.get(country.lower(), [])
        
        if not holiday_list:
            continue

        week_holidays = sorted({d for d in holiday_list if start <= d <= end})
        if not week_holidays:
            continue

        countries_with_holidays.add(country)
        holiday_pairs += len(week_holidays)

        for hdate in week_holidays:
            records = find_records_by_country_and_date(country, hdate)

            seen = set()
            unique_records = []
            for r in records:
                rid = getattr(r, "fdRecID", None)
                if rid not in seen:
                    seen.add(rid)
                    unique_records.append(r)
            records = unique_records

            if not records:
                print(f"[MISS] No not-done DW records for {country} on {hdate}")
                misses += 1
                continue

            note = build_note(hdate)

            # ---- PLAN ONLY (no DB writes here) ----
            planned = plan_actions(records, country, hdate, note)
            log_rows.extend(planned)

            found_records += len(records)

            for a in planned:
                if a["action_type"] == "UPDATE_NOTE":
                    print(f'[PLAN] UPDATE fdRecID={a["fdRecID"]} {country} {a["holiday_date"]}')
                else:
                    print(f'[PLAN] SKIP   fdRecID={a["fdRecID"]} {country} {a["holiday_date"]} (no change)')

    planned_updates = sum(1 for a in log_rows if a["action_type"] == "UPDATE_NOTE")

    eligible_updates = sum(
        1 for a in log_rows
        if a["action_type"] == "UPDATE_NOTE"
        and (country_filter is None or a["country"] in country_filter)
    )

    if not dry_run and eligible_updates > max_updates:
        # mark in log and abort write
        for a in log_rows:
            if a["action_type"] == "UPDATE_NOTE" and (country_filter is None or a["country"] in country_filter):
                a["result"] = "BLOCKED_MAX_UPDATES"

        print(f"[ERROR] Refusing to write {eligible_updates} updates (> {max_updates}). "
            f"Run with --max-updates N if intended.")
        written = 0
    else:
        written = apply_actions(
            log_rows,
            dry_run=dry_run,
            country_filter=country_filter
        )
  
    if log_rows:

        log_matches_csv(LOG_PATH, log_rows)
        print(f"[INFO] Logged {len(log_rows)} matched rows to: {LOG_PATH}")
    else:
        print("[INFO] No matched rows to log.")

    # summary
    planned_updates = sum(1 for a in log_rows if a.get("action_type") == "UPDATE_NOTE")
    planned_skips   = sum(1 for a in log_rows if a.get("action_type") == "SKIP_NO_CHANGE")

    print("\n[SUMMARY]")
    print(f"  Countries with holidays: {len(countries_with_holidays)}")
    print(f"  Holiday (country,date) pairs: {holiday_pairs}")
    print(f"  Matched records: {found_records}")
    print(f"  Planned updates: {planned_updates}")
    print(f"  Planned skips:   {planned_skips}")
    print(f"  Misses:          {misses}")
    print(f"  Written updates: {written} {'(dry run)' if dry_run else ''}")


    # close connection
    try:
        cursor.close()
    except Exception:
        pass
    try:
        con.close()
    except Exception:
        pass
    
if __name__ == "__main__":
    args = parse_args()
    dry_run = not args.write
    main(dry_run=dry_run, max_updates=args.max_updates, csv_path=args.csv_path, log_path=args.log_path)
