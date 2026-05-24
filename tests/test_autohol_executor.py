import json
import os
import sys
import tempfile
import types
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch


try:
    import pyodbc  # noqa: F401
except ImportError:
    pyodbc_stub = types.SimpleNamespace(drivers=lambda: [])
    sys.modules["pyodbc"] = pyodbc_stub

import autohol_executor


class FakeConnection:
    def __init__(self):
        self.rollback_called = False
        self.commit_called = False
        self.close_called = False

    def rollback(self):
        self.rollback_called = True

    def commit(self):
        self.commit_called = True

    def close(self):
        self.close_called = True


class FakeCursor:
    def __init__(self, rows):
        self.rows = rows
        self.execute_calls = []
        self.close_called = False

    def execute(self, query, params):
        self.execute_calls.append((query, params))

    def fetchall(self):
        return self.rows

    def close(self):
        self.close_called = True


class FakeAutocalendar:
    def __init__(self, connection, cursor):
        self.connection = connection
        self.cursor = cursor

    def connect_to_db(self):
        return self.connection, self.cursor


class AutoholExecutorTest(unittest.TestCase):
    def test_replace_autohol_note_replaces_old_autohol_lines(self):
        result = autohol_executor.replace_autohol_note(
            "AUTOHOL: old note\nAUTOHOL: older note",
            "AUTOHOL: latest note",
        )

        self.assertEqual(result, "AUTOHOL: latest note")

    def test_replace_autohol_note_preserves_manual_lines(self):
        result = autohol_executor.replace_autohol_note(
            "Call source team first.\nAUTOHOL: old note\nManual follow-up.",
            "AUTOHOL: latest note",
        )

        self.assertEqual(result, "Call source team first.\nManual follow-up.\nAUTOHOL: latest note")

    def test_replace_autohol_note_preserves_existing_notes_when_new_note_is_blank(self):
        result = autohol_executor.replace_autohol_note(
            "Manual note.\nAUTOHOL: old note",
            "",
        )

        self.assertEqual(result, "Manual note.\nAUTOHOL: old note")

    def test_airflow_executor_kwargs_maps_params(self):
        result = autohol_executor.airflow_executor_kwargs(
            params={
                "planner_json_dir": "D:/temp/autohol/json",
                "processed_dir": "D:/temp/autohol/processed",
                "error_dir": "D:/temp/autohol/error",
                "batch_limit": "7",
                "dry_run": True,
            }
        )

        self.assertEqual(
            result,
            {
                "planner_json_dir": "D:/temp/autohol/json",
                "processed_dir": "D:/temp/autohol/processed",
                "error_dir": "D:/temp/autohol/error",
                "batch_limit": 7,
                "dry_run": True,
            },
        )

    def test_airflow_executor_kwargs_parses_false_dry_run_string(self):
        result = autohol_executor.airflow_executor_kwargs(params={"dry_run": "false"})

        self.assertFalse(result["dry_run"])

    def test_all_actions_replace_existing_autohol_note(self):
        scenarios = [
            (
                "ADD_NOTE",
                {"planned_note": "AUTOHOL: added"},
                "AUTOHOL: added",
            ),
            (
                "MARK_DONE",
                {"planned_note": "AUTOHOL: marked done"},
                "AUTOHOL: marked done",
            ),
            (
                "MOVE_DATE",
                {"planned_note": "AUTOHOL: moved date", "move_to_date": "2026-01-03"},
                "AUTOHOL: moved date",
            ),
            (
                "MOVE_TIME",
                {"planned_note": "AUTOHOL: moved time", "move_to_time": "07:30 PM"},
                "AUTOHOL: moved time",
            ),
        ]

        for action, extra_fields, expected_note in scenarios:
            with self.subTest(action=action):
                cursor = FakeCursor([])
                record = types.SimpleNamespace(
                    fdRecID=123,
                    fdTemplateID=456,
                    fddDate2Show="2026-01-02 00:00:00",
                    fdNotes="Manual note.\nAUTOHOL: old note",
                )
                planner_row = {
                    "planned_action": action,
                    **extra_fields,
                }

                result = autohol_executor.apply_planner_action(
                    cursor,
                    record,
                    planner_row,
                    datetime(2026, 1, 2, 12, 0, 0),
                )

                self.assertEqual(result["final_notes"], f"Manual note.\n{expected_note}")

    def test_discover_planner_json_files_sorts_by_mtime_then_name_and_limits(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            newest = folder / "z_new.json"
            old_b = folder / "b_old.json"
            old_a = folder / "a_old.json"
            ignored = folder / "ignore.txt"

            for path in [newest, old_b, old_a]:
                path.write_text("{}", encoding="utf-8")
            ignored.write_text("{}", encoding="utf-8")

            os.utime(old_b, (100, 100))
            os.utime(old_a, (100, 100))
            os.utime(newest, (200, 200))

            result = autohol_executor.discover_planner_json_files(str(folder), batch_limit=2)

        self.assertEqual([Path(path).name for path in result], ["a_old.json", "b_old.json"])

    def test_execute_planner_file_dry_run_matches_record_without_moving_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            source_path = Path(tmp) / "planner_row.json"
            source_path.write_text(
                json.dumps(
                    {
                        "actual_record_id": "123",
                        "templateID": "456",
                        "original_scheduling_date": "2026-01-02",
                        "planned_action": "ADD_NOTE",
                        "planned_note": "AUTOHOL:test",
                    }
                ),
                encoding="utf-8",
            )

            record = types.SimpleNamespace(
                fdRecID=123,
                fdTemplateID=456,
                fddDate2Show="2026-01-02 00:00:00",
                fdNotes="",
            )
            connection = FakeConnection()
            cursor = FakeCursor([record])
            fake_autocalendar = FakeAutocalendar(connection, cursor)

            with patch("autohol_executor.Autocalendar", return_value=fake_autocalendar):
                result = autohol_executor.execute_planner_file(str(source_path), dry_run=True)

            self.assertEqual(result.status, autohol_executor.STATUS_DRY_RUN)
            self.assertEqual(result.record_id, 123)
            self.assertEqual(result.action, "ADD_NOTE")
            self.assertTrue(source_path.exists())
            self.assertTrue(connection.rollback_called)
            self.assertTrue(connection.close_called)
            self.assertTrue(cursor.close_called)

    def test_execute_planner_file_processed_sidecar_keeps_note_history(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            source_path = folder / "planner_row.json"
            processed_dir = folder / "processed"
            error_dir = folder / "error"
            source_path.write_text(
                json.dumps(
                    {
                        "actual_record_id": "123",
                        "templateID": "456",
                        "original_scheduling_date": "2026-01-02",
                        "planned_action": "MOVE_DATE",
                        "planned_note": "AUTOHOL: Moved to 2026-01-03",
                        "move_to_date": "2026-01-03",
                    }
                ),
                encoding="utf-8",
            )

            record = types.SimpleNamespace(
                fdRecID=123,
                fdTemplateID=456,
                fddDate2Show="2026-01-02 00:00:00",
                fdNotes="Manual note.\nAUTOHOL: old note",
            )
            connection = FakeConnection()
            cursor = FakeCursor([record])
            fake_autocalendar = FakeAutocalendar(connection, cursor)

            with patch("autohol_executor.Autocalendar", return_value=fake_autocalendar):
                result = autohol_executor.execute_planner_file(
                    str(source_path),
                    processed_dir=str(processed_dir),
                    error_dir=str(error_dir),
                    dry_run=False,
                )

            sidecar_path = Path(result.destination_path + ".result.json")
            payload = json.loads(sidecar_path.read_text(encoding="utf-8"))

            self.assertEqual(result.status, autohol_executor.STATUS_PROCESSED)
            self.assertFalse(source_path.exists())
            self.assertTrue(connection.commit_called)
            self.assertEqual(payload["previous_notes"], "Manual note.\nAUTOHOL: old note")
            self.assertEqual(payload["applied_note"], "AUTOHOL: Moved to 2026-01-03")
            self.assertEqual(payload["final_notes"], "Manual note.\nAUTOHOL: Moved to 2026-01-03")
            self.assertEqual(
                cursor.execute_calls[-1][1],
                ["2026-01-03", "Manual note.\nAUTOHOL: Moved to 2026-01-03", 123],
            )


if __name__ == "__main__":
    unittest.main()
