# file: auto_holiday_notes.py
# Reads holiday json file from F:\ drive, filters next week (Mon→Sun),
# then posts one note to the matching autocalendar record found by Country+Date.

import pyodbc
import re
import sys
from datetime import datetime, date, timedelta
import json
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


def log_matches_csv(log_path, matches):
    folder = os.path.dirname(log_path)
    if folder:
        os.makedirs(folder, exist_ok=True)
    fieldnames = [
        "mode","country","holiday_date",
        "fdRecID","fddDate2Show","fdDone",
        "database","group","update",
        "action","note"
    ]
    file_exists = os.path.exists(log_path) and os.path.getsize(log_path) > 0
    with open(log_path, "a", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        if not file_exists:
            writer.writeheader()
        for row in matches:
            writer.writerow(row)


def format_note(old_note, new_note, separator=' | '):
    if not old_note:
        return new_note
    split_note = str(old_note).split(separator)
    notes = []
    for note in split_note:
        note = note.strip()
        if note[:6] != 'AUTOHOL':
            notes.append(note)
    notes.append(new_note)
    return separator.join(notes)


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
    return f"AUTOHOL: Holiday — {hdate:%Y-%m-%d}"


def next_week_window(today=None):
    """Next Monday → next Sunday (inclusive)."""
    today = today or datetime.now().date()
    days_ahead = (0 - today.weekday() + 7) % 7
    if days_ahead == 0:
        days_ahead = 7
    start = today + timedelta(days=days_ahead)
    end = start + timedelta(days=6)
    return start, end


def main(dry_run=True):

    WRITE_COUNTRIES = {"China"}

    print("[INFO] DRY RUN — no notes will be written." if dry_run
      else "[INFO] WRITE MODE — notes WILL be written.")
    
    JSON_PATH = r"C:\Users\JiebingYin\OneDrive - Haver Analytics\python files\python project\HolidayNote\QppHolidays.json"
    LOG_PATH = r"C:\Users\JiebingYin\OneDrive - Haver Analytics\python files\python project\HolidayNote\holiday_notes_match_log.csv"

    with open(JSON_PATH, "r") as f:
        holidayDict = json.load(f)

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
            print(f"[WARN] {country} not in JSON.")
            continue

        holiday_list = [
            datetime.strptime(s, "%Y-%m-%d").date()
            for s in holidayDict.get(country.lower(), [])
        ]
        
        if not holiday_list:
            continue

        week_holidays = sorted({d for d in holiday_list if start <= d <= end})
        if not week_holidays:
            continue

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

            for rec in records:
                found_records += 1

                should_write = (country in WRITE_COUNTRIES) and (not dry_run)

                if should_write:
                    stored_note = write_note(rec, note)
                    action = "WROTE"
                    mode = "write"
                else:
                    stored_note = note
                    action = "DRY_RUN"
                    mode = "dry_run"

                log_rows.append({
                    "mode": mode,
                    "country": country,
                    "holiday_date": hdate.strftime("%Y-%m-%d"),
                    "fdRecID": getattr(rec, "fdRecID", ""),
                    "fddDate2Show": getattr(rec, "fddDate2Show", ""),
                    "fdDone": getattr(rec, "fdDone", ""),
                    "database": getattr(rec, "fdDatabaseName", ""),
                    "group": getattr(rec, "fdGroup", ""),
                    "update": getattr(rec, "fdMessageBoard", ""),
                    "action": action,
                    "note": stored_note,
                })

                
    if log_rows:

        log_matches_csv(LOG_PATH, log_rows)
        print(f"[INFO] Logged {len(log_rows)} matched rows to: {LOG_PATH}")
    else:
        print("[INFO] No matched rows to log.")

    print("\n[SUMMARY]")
    print(f"  Matched records: {found_records}")
    print(f"  Misses: {misses}")

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
    main(dry_run=False)