import csv
import json
import tempfile
import unittest
from datetime import date
from pathlib import Path

from autohol.future_holiday_planner import (
    build_planner_rows,
    write_planner_log_csv,
    write_planner_log_json,
)


class FutureHolidayPlannerTest(unittest.TestCase):
    def test_build_planner_rows_preserves_actual_record_note_metadata(self):
        rows = build_planner_rows(
            [
                {
                    "templateID": 456,
                    "target_date": "2026-05-27",
                    "database": "TESTDB",
                    "notes": "AUTOHOL: prior note",
                    "record_last_change": "2026-05-24 14:00:00",
                }
            ],
            "ALL_USERS",
            date(2026, 5, 27),
        )

        self.assertEqual(rows[0]["notes"], "AUTOHOL: prior note")
        self.assertEqual(rows[0]["record_last_change"], "2026-05-24 14:00:00")

    def test_planner_log_writers_include_note_metadata(self):
        row = {
            "planner_user": "ALL_USERS",
            "plan_created_at": "2026-05-24 14:00:00",
            "selected_date": "2026-05-27",
            "window_start": "2026-05-27",
            "window_end": "2026-05-27",
            "templateID": "456",
            "database": "TESTDB",
            "country": "US",
            "group": "S06",
            "update": "WSJ Markets Diary (BB)",
            "time": "06:01:22 PM",
            "edm": "unassigned",
            "team": "unassigned",
            "procedures": "",
            "notes": "AUTOHOL: prior note",
            "record_last_change": "2026-05-24 14:00:00",
            "holiday_date": "2026-05-27",
            "holiday_name": "Test Holiday",
            "holiday_type": "banks",
            "original_scheduling_date": "2026-05-27",
            "planned_action": "MOVE_DATE",
            "planned_note": "AUTOHOL: Moved to 2026-05-28",
            "move_mode": "next_calendar_day",
            "move_to_date": "2026-05-28",
            "move_to_time": "",
            "plan_status": "PLANNED",
            "entry_source": "actual",
            "actual_record_id": "123",
        }

        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            json_dir = folder / "json"
            csv_path = folder / "planner.csv"

            write_planner_log_json(str(json_dir), [row])
            write_planner_log_csv(str(csv_path), [row])

            json_payload = json.loads(next(json_dir.glob("*.json")).read_text(encoding="utf-8"))
            with csv_path.open("r", encoding="utf-8-sig", newline="") as f:
                csv_rows = list(csv.DictReader(f))

        self.assertEqual(json_payload["notes"], "AUTOHOL: prior note")
        self.assertEqual(json_payload["record_last_change"], "2026-05-24 14:00:00")
        self.assertEqual(csv_rows[0]["notes"], "AUTOHOL: prior note")
        self.assertEqual(csv_rows[0]["record_last_change"], "2026-05-24 14:00:00")


if __name__ == "__main__":
    unittest.main()
