import os
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import patch


try:
    import pyodbc  # noqa: F401
except ImportError:
    pyodbc_stub = types.SimpleNamespace(drivers=lambda: [])
    sys.modules["pyodbc"] = pyodbc_stub

from autohol.dw_source import Assignments


FIXTURE_DIR = Path(__file__).parent / "fixtures" / "assignments"
DW_TESTDB = FIXTURE_DIR / "dw_testdb.csv"
MQA_TEST = FIXTURE_DIR / "mqa_test.csv"
DW_CUSTOM_TEST = FIXTURE_DIR / "dw_custom_test.csv"
MQA_CUSTOM_TEST = FIXTURE_DIR / "mqa_custom_test.csv"


class AssignmentsTest(unittest.TestCase):
    def make_assignments(self, dw_assignments=DW_TESTDB):
        return Assignments(
            dw_assignments=str(dw_assignments),
            mqa_assignments=str(MQA_TEST),
            dw_assignments_custom=str(DW_CUSTOM_TEST),
            mqa_assignments_custom=str(MQA_CUSTOM_TEST),
            intdaily_gpa=str(FIXTURE_DIR / "missing_intdaily.gpa"),
            intwkly_gpa=str(FIXTURE_DIR / "missing_intwkly.gpa"),
        )

    def test_testdb_resolves_to_unassigned(self):
        assignments = self.make_assignments()

        result = assignments.assign_identifier(("testdb", "", "", ""))

        self.assertEqual(result, {"team": "unassigned", "edm": "unassigned"})

    def test_dw_database_assignment_reads_left_side_table(self):
        assignments = self.make_assignments()

        self.assertIn("testdb", assignments.dw_assignments)
        self.assertEqual(
            assignments.dw_assignments["testdb"],
            {"team": "unassigned", "edm": "unassigned"},
        )

    def test_existing_dw_database_assignment_still_reads_from_full_fixture(self):
        assignments = self.make_assignments()

        result = assignments.assign_identifier(("daily", "", "", ""))

        self.assertEqual(result, {"team": "dwb", "edm": "jiebing"})

    def test_environment_overrides_are_used_by_default_constructor(self):
        env = {
            "AUTOHOL_DW_ASSIGNMENTS": str(DW_TESTDB),
            "AUTOHOL_MQA_ASSIGNMENTS": str(MQA_TEST),
            "AUTOHOL_DW_ASSIGNMENTS_CUSTOM": str(DW_CUSTOM_TEST),
            "AUTOHOL_MQA_ASSIGNMENTS_CUSTOM": str(MQA_CUSTOM_TEST),
        }

        with patch.dict(os.environ, env, clear=False):
            assignments = Assignments(
                intdaily_gpa=str(FIXTURE_DIR / "missing_intdaily.gpa"),
                intwkly_gpa=str(FIXTURE_DIR / "missing_intwkly.gpa"),
            )

        self.assertEqual(assignments.dw_assignments_path, str(DW_TESTDB))
        self.assertEqual(assignments.mqa_assignments_path, str(MQA_TEST))
        self.assertEqual(assignments.dw_assignments_custom_path, str(DW_CUSTOM_TEST))
        self.assertEqual(assignments.mqa_assignments_custom_path, str(MQA_CUSTOM_TEST))
        self.assertEqual(
            assignments.assign_identifier(("testdb", "", "", "")),
            {"team": "unassigned", "edm": "unassigned"},
        )


if __name__ == "__main__":
    unittest.main()
