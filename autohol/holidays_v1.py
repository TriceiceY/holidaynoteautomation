# This file is for CSV loader + date window functions

import csv
from datetime import datetime, timedelta

def load_holiday_dict(csv_path):
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


def holidays_for_country(holiday_dict, country: str):
    return holiday_dict.get(country.lower(), [])
