# This file is for holiday CSV loading and holiday metadata helpers

import csv
from datetime import datetime, timedelta


DEFAULT_HOLIDAY_CSV_PATH = r"F:\intdaily\autohol\Q++ Worldwide Public Holidays ISO-2026.CSV"


COUNTRY_TRANSLATE_DICT = {
    "bosnia and herzegovina": ["bosnia", "bosnia & herzegovina"],
    "south korea": ["korea"],
    "kyrgyzstan": ["kyrgyz republic"],
    "macau": ["macao"],
    "macedonia": ["north macedonia"],
    "trinidad and tobago": ["trinidad & tobago"],
    "uae (united arab emirates)": ["uae", "united arab emirates"],
    "uk (united kingdom)": ["uk", "united kingdom"],
    "usa (united states)": ["us", "united states"],
    "antigua and barbuda": ["antigua & barbuda"],
    "bonaire, st eustatius and saba": ["bonaire, st eustatious and saba"],
    "brunei": ["brunei darussalam"],
    "cape verde": ["cape verde (cabo verde)"],
    "congo, dem. rep. (zaire)": ["congo democratic republic"],
    "congo, republic of the": ["congo, republic of"],
    "guinea": ["equatorial guinea"],
    "yemen": ["pdr yemen"],
}


def normalize_country(country: str) -> str:
    country_norm = (country or "").strip().lower()

    if country_norm in COUNTRY_TRANSLATE_DICT:
        return country_norm

    for canonical, aliases in COUNTRY_TRANSLATE_DICT.items():
        if country_norm in aliases:
            return canonical

    return country_norm


def classify_holiday_type(observance: str) -> str:
    """
    Normalize raw holiday observance into 5 planner categories:
    - banks/government
    - banks
    - government
    - regional
    - others
    """
    text = (observance or "").strip().lower()

    has_bank = "bank" in text
    has_government = "government" in text
    has_regional = "regional" in text

    if has_bank and has_government:
        return "banks/government"
    if has_bank:
        return "banks"
    if has_government:
        return "government"
    if has_regional:
        return "regional"
    return "others"


def combine_holiday_types(types):
    type_set = {t for t in types if t}

    if "banks/government" in type_set:
        return "banks/government"
    if "banks" in type_set and "government" in type_set:
        return "banks/government"
    if "banks" in type_set:
        return "banks"
    if "government" in type_set:
        return "government"
    if "regional" in type_set:
        return "regional"
    return "others"


def add_holiday_record(holiday_dict, country, holiday_date, holiday_name, holiday_observance):
    country_key = normalize_country(country)
    holiday_type = classify_holiday_type(holiday_observance)

    holiday_dict.setdefault(country_key, {})
    holiday_dict[country_key].setdefault(holiday_date, [])
    holiday_dict[country_key][holiday_date].append({
        "holiday_name": (holiday_name or "").strip(),
        "holiday_type": holiday_type,
    })


def load_holiday_records(csv_path):
    """
    Build a dict like:
      {
        "country1": {
            date(...): [
                {"holiday_name": "...", "holiday_type": "..."},
                ...
            ]
        }
      }

    Rules:
    - Reads QPP holidays CSV file
    - Converts 'Holiday Date' Excel serial -> Python date
    - Keeps all holiday records, including regional
    """
    holiday_dict = {}

    with open(csv_path, "r", encoding="latin1", newline="") as f:
        reader = csv.DictReader(f, delimiter=";")

        for row in reader:
            country = (row.get("Country Name") or "").strip()
            holiday_name = (row.get("Holiday Name") or "").strip()
            observance = (row.get("Holiday Observance") or "").strip()

            if not country:
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

            add_holiday_record(
                holiday_dict,
                country,
                hdate,
                holiday_name,
                observance,
            )

    return holiday_dict


def get_holiday_records_for_country_date(holiday_dict, country: str, target_date):
    country_key = normalize_country(country)
    return holiday_dict.get(country_key, {}).get(target_date, [])


def is_country_holiday(holiday_dict, country: str, target_date):
    return len(get_holiday_records_for_country_date(holiday_dict, country, target_date)) > 0


def get_combined_holiday_name(holiday_dict, country: str, target_date):
    records = get_holiday_records_for_country_date(holiday_dict, country, target_date)
    names = [r.get("holiday_name", "").strip() for r in records if r.get("holiday_name", "").strip()]
    return ", ".join(names)


def get_combined_holiday_type(holiday_dict, country: str, target_date):
    records = get_holiday_records_for_country_date(holiday_dict, country, target_date)
    types = [r.get("holiday_type", "") for r in records]
    return combine_holiday_types(types)


def load_holiday_dict(csv_path):
    """
    Backward-compatible helper for old logic:
      {
        "country1": [date(...), date(...)]
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
                serial = int(float(raw_date))
                hdate = (datetime(1899, 12, 30) + timedelta(days=serial)).date()
            except Exception:
                continue

            key = normalize_country(country)
            holiday_dict.setdefault(key, set()).add(hdate)

    return {k: sorted(v) for k, v in holiday_dict.items()}


def holidays_for_country(holiday_dict, country: str):
    return holiday_dict.get(normalize_country(country), [])
