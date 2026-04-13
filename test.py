from datetime import date
from autohol.dw_source import Autocalendar, Assignments
from autohol.holidays import load_holiday_records
from autohol.future_holiday_planner import (
    filter_entries_for_user,
    get_holiday_countries_for_date,
    get_user_holiday_countries,
    filter_entries_for_countries,
    build_window_task_candidates,
    annotate_holiday_context,
    build_planner_rows,
)

a = Autocalendar()
a.get_dw()
entries = a.parse_entries()

b = Assignments()
assigned_entries = b.assign(entries, attach=True)

holiday_dict = load_holiday_records(r"data/Q++ Worldwide Public Holidays ISO-2026.CSV")

planner_user = "binru"
selected_date = date(2026, 4, 3)

user_entries = filter_entries_for_user(assigned_entries, planner_user)
holiday_countries = get_holiday_countries_for_date(holiday_dict, selected_date)
user_holiday_countries = get_user_holiday_countries(user_entries, holiday_countries)
country_filtered_entries = filter_entries_for_countries(user_entries, user_holiday_countries)
candidate_rows = build_window_task_candidates(country_filtered_entries, selected_date)
annotated_rows = annotate_holiday_context(candidate_rows, holiday_dict, selected_date)
planner_rows = build_planner_rows(annotated_rows, planner_user, selected_date)

print("Planner rows:", len(planner_rows))
for row in planner_rows[:3]:
    print({
        "country": row["country"],
        "holiday_date": row["holiday_date"],
        "holiday_name": row["holiday_name"],
        "holiday_type": row["holiday_type"],
        "target_date": row["target_date"],
    })