import json
import os
import sys
import tempfile
import types
import unittest
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
        self.close_called = False

    def rollback(self):
        self.rollback_called = True

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


if __name__ == "__main__":
    unittest.main()
