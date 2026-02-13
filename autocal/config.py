# This file is for paths + DB connection string builder

import pyodbc
import re

DEFAULT_JSON_PATH = r"C:\Users\JiebingYin\OneDrive - Haver Analytics\python files\HolidayNoteAutomation\QppHolidays.json"
DEFAULT_LOG_PATH  = r"C:\Users\JiebingYin\OneDrive - Haver Analytics\python files\HolidayNoteAutomation\holiday_notes_match_log.csv"

def get_odbc_driver():
    drivers = pyodbc.drivers()
    version = 0.0
    latest_driver = None

    for driver in drivers:
        match = re.search(r"MySQL ODBC (\d+\.\d+).* Driver", driver)
        if match:
            v = float(match.group(1))
            if v > version:
                version = v
                latest_driver = match.group(0)

    if not latest_driver:
        raise RuntimeError("Unable to find a MySQL ODBC driver. Contact operations.")

    return latest_driver

def get_conn_str():
    odbc_driver = get_odbc_driver()
    return (
        f"DRIVER={{{odbc_driver}}};"
        "SERVER=10.1.4.6;PORT=3306;"
        "DATABASE=autocalendar;"
        "UID=autocal;PWD=AutoCal_Pwd"
    )