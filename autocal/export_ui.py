import json
import os
from datetime import datetime


def _safe_str(value):
    """Convert values (including datetime/date) to strings safely for JSON."""
    if value is None:
        return ""
    if isinstance(value, (datetime,)):
        return value.isoformat(sep=" ", timespec="seconds")
    return str(value)


def build_ui_records(actions):
    """
    Convert internal action rows into a UI-friendly record schema.
    This is the JSON your future Streamlit UI will read.

    Expected input: list of action dicts from planner/apply_actions.
    """
    ui_rows = []

    for a in actions:
        ui_rows.append({
            # stable identifiers
            "fdRecID": a.get("fdRecID", ""),

            # calendar record fields for display/filtering
            "fddDate2Show": _safe_str(a.get("fddDate2Show", "")),
            "database": a.get("database", ""),
            "country": a.get("country", ""),
            "group": a.get("group", ""),
            "update": a.get("update", ""),

            # note info
            "note_current": a.get("old_note", ""),
            "note_planned": a.get("new_note", ""),

            # holiday context
            "holiday_date": a.get("holiday_date", ""),

            # planning/execution status
            "action_type": a.get("action_type", ""),   # UPDATE_NOTE / SKIP_NO_CHANGE
            "result": a.get("result", ""),             # PLANNED / DRY_RUN / WROTE / ...
            "module": "holiday_note",

            # UI state defaults (future Streamlit can change these)
            "selected": False,
            "ui_action": "",   # e.g. "note", "mark_done", "move_date"
        })

    return ui_rows



def build_ui_payload(run_meta, summary, ui_records):
    """
    Final JSON structure for UI consumption.
    """
    return {
        "run_meta": run_meta,
        "summary": summary,
        "records": ui_records,
    }



def write_ui_snapshot_json(path, run_meta, summary, actions):
    """
    Build UI payload from actions and overwrite snapshot JSON.
    """
    folder = os.path.dirname(path)
    if folder:
        os.makedirs(folder, exist_ok=True)

    ui_records = build_ui_records(actions)
    payload = build_ui_payload(run_meta, summary, ui_records)

    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)

    return len(ui_records)