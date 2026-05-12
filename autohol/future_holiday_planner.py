from datetime import datetime, timedelta
import csv
import json
import os

from autohol.holidays import (
    normalize_country,
    is_country_holiday,
    get_combined_holiday_name,
    get_combined_holiday_type,
)



def date_window(selected_date, days_before=7, days_after=7):
    return (
        selected_date - timedelta(days=days_before),
        selected_date + timedelta(days=days_after),
    )


def is_template_scheduled_on_date(entry, target_date):
    """
    Return True if the template is expected to run on target_date.

    Rules:
    - If Daily is checked, the entry runs Mon-Fri.
    - Individual weekday flags add those specific days.
    - Therefore:
        * Daily only -> Mon-Fri
        * Daily + Sat + Sun -> every day
        * Daily + Sat -> Mon-Sat
        * Daily + Sun -> Sun + Mon-Fri
    """

    def enabled(value) -> bool:
        return value in (1, -1)

    if isinstance(target_date, str):
        target_date = datetime.strptime(target_date, "%Y-%m-%d").date()

    weekday = target_date.weekday()  # Mon=0 ... Sun=6

    daily_enabled = enabled(entry.get("frq_daily", 0))

    weekday_flags = {
        0: enabled(entry.get("frq_mon", 0)),
        1: enabled(entry.get("frq_tue", 0)),
        2: enabled(entry.get("frq_wed", 0)),
        3: enabled(entry.get("frq_thu", 0)),
        4: enabled(entry.get("frq_fri", 0)),
        5: enabled(entry.get("frq_sat", 0)),
        6: enabled(entry.get("frq_sun", 0)),
    }

    # Daily means Mon-Fri
    if weekday <= 4 and daily_enabled:
        return True

    # Explicit weekday checks also count
    return weekday_flags[weekday]


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


def build_window_task_candidates(entries, selected_date, days_before=7, days_after=7):
    window_start, window_end = date_window(selected_date, days_before, days_after)
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

        row_copy["holiday_name"] = get_combined_holiday_name(
            holiday_dict,
            row_copy.get("country", ""),
            selected_date,
        )
        row_copy["holiday_type"] = get_combined_holiday_type(
            holiday_dict,
            row_copy.get("country", ""),
            selected_date,
        )

        out.append(row_copy)

    return out


def build_planner_rows(candidate_rows, planner_user, selected_date, days_before=7, days_after=7):
    window_start, window_end = date_window(selected_date, days_before, days_after)
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
            "original_scheduling_date": row.get("target_date", ""),
            "time": row.get("time", ""),
            "database": row.get("database", ""),
            "country": row.get("country", ""),
            "group": row.get("group", ""),
            "update": row.get("update", ""),
            "edm": row.get("edm", ""),
            "team": row.get("team", ""),
            "procedures": row.get("procedures", ""),

            "holiday_date": row.get("holiday_date", ""),
            "holiday_name": row.get("holiday_name", ""),
            "holiday_type": row.get("holiday_type", ""),

            "planned_action": "",
            "planned_note": "",
            "move_mode": "",
            "move_to_date": "",
            "move_to_time": "",
            "plan_status": "PLANNED",
        })

    return planner_rows


def write_planner_log_json(path, rows):
    os.makedirs(path, exist_ok=True)
    excluded_keys = {"_row_id"}
    written = 0

    for row in rows:
        cleaned_row = {k: v for k, v in row.items() if k not in excluded_keys}
        original_scheduling_date = (cleaned_row.get("original_scheduling_date") or "").strip() or "unknown-date"
        entry_source = (cleaned_row.get("entry_source") or "").strip().lower()
        if entry_source == "actual":
            source_value = cleaned_row.get("actual_record_id", "")
            source_label = "actual"
        else:
            source_value = cleaned_row.get("templateID", "")
            source_label = "template"

        if not str(source_value).strip():
            source_value = row.get("_row_id", "unknown")

        filename = f"{original_scheduling_date}_{source_label}_{source_value}.json"
        file_path = os.path.join(path, filename)
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(cleaned_row, f, ensure_ascii=False, indent=2)
        written += 1

    return written


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
        "procedures",
        "holiday_date",
        "holiday_name",
        "holiday_type",
        "original_scheduling_date",
        "planned_action",
        "planned_note",
        "move_mode",
        "move_to_date",
        "move_to_time",
        "plan_status",
    ]

    cleaned_rows = []
    for row in rows:
        cleaned_row = {key: row.get(key, "") for key in fieldnames}
        cleaned_rows.append(cleaned_row)

    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(cleaned_rows)

    return len(cleaned_rows)
