from datetime import datetime, timedelta
import csv
import json
import os


def normalize_country(country: str) -> str:
    country_norm = (country or "").strip().lower()
    translate_dict = {

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

    # direct canonical match
    if country_norm in translate_dict:
        return country_norm
    for canonical, aliases in translate_dict.items():
        if country_norm in aliases:
            return canonical

    return country_norm
 


def date_window(selected_date, days_before=7, days_after=7):
    return (
        selected_date - timedelta(days=days_before),
        selected_date + timedelta(days=days_after),
    )


def is_template_scheduled_on_date(entry, target_date):
    """
    Return True if the template is expected to run on target_date.

    Scheduling rules:
    1. If frq_daily is 1 or -1:
       - template runs on Monday-Friday only
    2. Otherwise, use the specific weekday flags:
       - frq_sun ... frq_sat
       - a value of 1 or -1 means enabled
       - 0 means not enabled
    """

    def enabled(value) -> bool:
        return value in (1, -1)
    
    if isinstance(target_date, str):
        target_date = datetime.strptime(target_date, "%Y-%m-%d").date()

    # Rule 1: weekday schedule (Mon-Fri)
    if enabled(entry.get("frq_daily", 0)):
        return target_date.weekday() < 5   # Mon=0 ... Fri=4

    # Rule 2: specific weekday flags
    weekday_map = {
        0: "frq_mon",
        1: "frq_tue",
        2: "frq_wed",
        3: "frq_thu",
        4: "frq_fri",
        5: "frq_sat",
        6: "frq_sun",
    }

    day_field = weekday_map[target_date.weekday()]
    return enabled(entry.get(day_field, 0))


def filter_entries_for_user(entries, planner_user: str):
    planner_user = (planner_user or "").strip().lower()
    out = []

    for entry in entries:
        edm = (entry.get("edm") or "").strip().lower()
        if edm != planner_user:
            continue
        out.append(entry)

    return out


def get_holiday_countries_for_date(holiday_dict, selected_date):
    result = set()
    for country, holiday_dates in holiday_dict.items():
        if selected_date in holiday_dates:
            result.add(normalize_country(country))
    return result


def get_user_holiday_countries(user_entries, holiday_countries_on_date):
    user_countries = {
        normalize_country(entry.get("country", ""))
        for entry in user_entries
        if normalize_country(entry.get("country", "")) not in {"", "various"}
    }
    return user_countries.intersection(holiday_countries_on_date)


def filter_entries_for_countries(entries, countries):
    countries_norm = {normalize_country(c) for c in countries}
    return [
        entry for entry in entries
        if normalize_country(entry.get("country", "")) in countries_norm
    ]


def build_window_task_candidates(entries, selected_date):
    window_start, window_end = date_window(selected_date)
    rows = []

    current = window_start
    while current <= window_end:
        for entry in entries:
            if is_template_scheduled_on_date(entry, current):
                rows.append({
                    **entry,
                    "target_date": current.isoformat(),
                    "is_on_holiday_date": current == selected_date,
                })
        current += timedelta(days=1)

    return rows


def is_country_holiday(holiday_dict, country, target_date):
    country_key = normalize_country(country)
    holidays = holiday_dict.get(country_key, [])
    return target_date in holidays


def is_country_holiday(holiday_dict, country, target_date):
    country_key = normalize_country(country)
    holidays = holiday_dict.get(country_key, [])
    return target_date in holidays


def annotate_holiday_context(rows, holiday_dict, selected_date):
    out = []

    for row in rows:
        row_copy = dict(row)
        target_date = datetime.strptime(row_copy["target_date"], "%Y-%m-%d").date()

        row_copy["holiday_date"] = selected_date.isoformat()
        row_copy["is_country_holiday_on_selected_date"] = is_country_holiday(
            holiday_dict,
            row_copy.get("country", ""),
            selected_date,
        )
        row_copy["is_country_holiday_on_target_date"] = is_country_holiday(
            holiday_dict,
            row_copy.get("country", ""),
            target_date,
        )
        out.append(row_copy)

    return out


def build_planner_rows(candidate_rows, planner_user, selected_date):
    window_start, window_end = date_window(selected_date)
    created_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    planner_rows = []
    for idx, row in enumerate(candidate_rows):
        planner_rows.append({
            "_row_id": idx,
            "planner_user": planner_user,
            "plan_created_at": created_at,
            "selected_date": selected_date.isoformat(),
            "window_start": window_start.isoformat(),
            "window_end": window_end.isoformat(),

            "templateID": row.get("templateID", ""),
            "database": row.get("database", ""),
            "country": row.get("country", ""),
            "group": row.get("group", ""),
            "update": row.get("update", ""),
            "time": row.get("time", ""),
            "edm": row.get("edm", ""),
            "team": row.get("team", ""),
            "procedures": row.get("procedures", ""),

            "holiday_date": row.get("holiday_date", ""),
            "target_date": row.get("target_date", ""),

            "planned_action": "",
            "planned_note": "",
            "move_mode": "",
            "move_to_date": "",
            "plan_status": "PLANNED",
        })

    return planner_rows


def write_planner_log_json(path, rows):
    folder = os.path.dirname(path)
    if folder:
        os.makedirs(folder, exist_ok=True)

    excluded_keys = {"_row_id"}
    cleaned_rows = [
            {k: v for k, v in row.items() if k not in excluded_keys}
            for row in rows
    ]
    with open(path, "w", encoding="utf-8") as f:
        json.dump(cleaned_rows, f, ensure_ascii=False, indent=2)

    return len(cleaned_rows)


def write_planner_log_csv(path, rows):
    folder = os.path.dirname(path)
    if folder:
        os.makedirs(folder, exist_ok=True)

    fieldnames = [
        "planner_user",
        "plan_created_at",
        "selected_date",
        "window_start",
        "window_end",
        "templateID",
        "database",
        "country",
        "group",
        "update",
        "time",
        "edm",
        "team",
        "procedures"
        "holiday_date",
        "target_date",
        "planned_action",
        "planned_note",
        "move_mode",
        "move_to_date",
        "plan_status",
    ]

    cleaned_rows = []
    for row in rows:
        cleaned_row = {key: row.get(key,"") for key in fieldnames}
        cleaned_rows.append(cleaned_row)

    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(cleaned_rows)

    return len(cleaned_rows)
