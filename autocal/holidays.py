# This file is for JSON loader + date window functions

import json
from datetime import datetime, timedelta

def next_week_window(today=None):
    today = today or datetime.now().date()
    days_ahead = (0 - today.weekday() + 7) % 7
    if days_ahead == 0:
        days_ahead = 7
    start = today + timedelta(days=days_ahead)
    end = start + timedelta(days=6)
    return start, end

def load_holiday_dict(json_path: str):
    with open(json_path, "r") as f:
        return json.load(f)

def holidays_for_country(holiday_dict, country: str):
    return [
        datetime.strptime(s, "%Y-%m-%d").date()
        for s in holiday_dict.get(country.lower(), [])
    ]