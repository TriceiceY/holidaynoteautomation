"""
Airflow executor for AutoHoliday planner JSON files.

The executor scans planner JSON files, waits until each planned template row
has a matching actual AutoCalendar record, applies the requested action, then
moves the JSON file to a processed or error folder.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
import json
import os
import shutil
from typing import Any

from autohol.dw_source import Autocalendar


DEFAULT_PLANNER_JSON_DIR = r"F:\intdaily\autohol\planner\json"
DEFAULT_PROCESSED_DIR = r"F:\intdaily\autohol\planner\processed"
DEFAULT_ERROR_DIR = r"F:\intdaily\autohol\planner\error"
DEFAULT_BATCH_LIMIT = 100

STATUS_PROCESSED = "processed"
STATUS_PENDING = "pending"
STATUS_ERROR = "error"
STATUS_DRY_RUN = "dry_run"


@dataclass
class ExecutionResult:
    status: str
    source_path: str
    message: str
    record_id: Any = ""
    action: str = ""
    destination_path: str = ""


def utc_now_iso() -> str:
    return datetime.utcnow().replace(microsecond=0).isoformat() + "Z"


def discover_planner_json_files(planner_json_dir: str, batch_limit: int = DEFAULT_BATCH_LIMIT) -> list[str]:
    if not os.path.isdir(planner_json_dir):
        return []

    paths = [
        os.path.join(planner_json_dir, name)
        for name in os.listdir(planner_json_dir)
        if name.lower().endswith(".json") and os.path.isfile(os.path.join(planner_json_dir, name))
    ]
    paths.sort(key=lambda path: (os.path.getmtime(path), os.path.basename(path).lower()))
    return paths[:batch_limit]


def load_planner_row(path: str) -> dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        row = json.load(f)

    if not isinstance(row, dict):
        raise ValueError("Planner JSON must contain one object.")

    return row


def clean_text(value: Any) -> str:
    return str(value or "").strip()


def normalize_action(row: dict[str, Any]) -> str:
    return clean_text(row.get("planned_action")).upper()


def require_value(row: dict[str, Any], key: str) -> str:
    value = clean_text(row.get(key))
    if not value:
        raise ValueError(f"Missing required planner field: {key}")
    return value


def parse_planner_date(value: Any, field_name: str = "date") -> str:
    text = clean_text(value)
    if not text:
        raise ValueError(f"Missing required {field_name}.")

    try:
        return datetime.strptime(text, "%Y-%m-%d").date().isoformat()
    except ValueError as exc:
        raise ValueError(f"{field_name} must use YYYY-MM-DD format: {text}") from exc


def parse_planner_time(value: Any, field_name: str = "time") -> str:
    text = clean_text(value)
    if not text:
        raise ValueError(f"Missing required {field_name}.")

    accepted_formats = ("%I:%M:%S %p", "%I:%M %p", "%H:%M:%S", "%H:%M")
    for fmt in accepted_formats:
        try:
            return datetime.strptime(text, fmt).time().strftime("%H:%M:%S")
        except ValueError:
            continue

    raise ValueError(f"{field_name} has an unsupported time format: {text}")


def append_note(existing_note: Any, new_note: Any) -> str:
    existing = clean_text(existing_note)
    new = clean_text(new_note)

    if not new:
        return existing
    if not existing:
        return new
    return existing + "\n" + new


def row_value(row: Any, name: str, default: Any = "") -> Any:
    if row is None:
        return default
    if isinstance(row, dict):
        return row.get(name, default)
    return getattr(row, name, default)


def fetch_records_by_actual_id(cursor: Any, actual_record_id: Any) -> list[Any]:
    cursor.execute(
        """
        SELECT
            dwr.fdRecID,
            dwr.fdTemplateID,
            dwr.fddDate2Show,
            dwr.fdTime,
            dwr.fdDone,
            dwr.fdDoneDate,
            dwr.fdNotes,
            dwr.fdRecLastChange
        FROM tblcalendar_dw_records dwr
        WHERE dwr.fdRecID = ?
        """,
        [actual_record_id],
    )
    return list(cursor.fetchall())


def fetch_records_by_template_and_date(cursor: Any, template_id: Any, scheduling_date: str) -> list[Any]:
    start_dt = datetime.strptime(scheduling_date, "%Y-%m-%d")
    end_dt = start_dt + timedelta(days=1)

    cursor.execute(
        """
        SELECT
            dwr.fdRecID,
            dwr.fdTemplateID,
            dwr.fddDate2Show,
            dwr.fdTime,
            dwr.fdDone,
            dwr.fdDoneDate,
            dwr.fdNotes,
            dwr.fdRecLastChange
        FROM tblcalendar_dw_records dwr
        WHERE dwr.fdTemplateID = ?
          AND dwr.fddDate2Show >= ?
          AND dwr.fddDate2Show < ?
        ORDER BY dwr.fdRecID
        """,
        [
            template_id,
            start_dt.strftime("%Y-%m-%d %H:%M:%S"),
            end_dt.strftime("%Y-%m-%d %H:%M:%S"),
        ],
    )
    return list(cursor.fetchall())


def validate_actual_record_match(record: Any, planner_row: dict[str, Any]) -> None:
    template_id = clean_text(planner_row.get("templateID"))
    scheduling_date = clean_text(planner_row.get("original_scheduling_date"))

    if template_id and clean_text(row_value(record, "fdTemplateID")) != template_id:
        raise ValueError(
            "actual_record_id points to a record with a different templateID "
            f"({row_value(record, 'fdTemplateID')} != {template_id})."
        )

    if scheduling_date:
        record_date = clean_text(row_value(record, "fddDate2Show"))
        if record_date[:10] != scheduling_date:
            raise ValueError(
                "actual_record_id points to a record with a different scheduling date "
                f"({record_date[:10]} != {scheduling_date})."
            )


def find_matching_actual_record(cursor: Any, planner_row: dict[str, Any]) -> tuple[str, Any | None]:
    actual_record_id = clean_text(planner_row.get("actual_record_id"))
    template_id = clean_text(planner_row.get("templateID"))
    scheduling_date = clean_text(planner_row.get("original_scheduling_date"))

    if actual_record_id:
        matches = fetch_records_by_actual_id(cursor, actual_record_id)
        if not matches:
            raise ValueError(f"No AutoCalendar record found for actual_record_id={actual_record_id}.")
        if len(matches) > 1:
            raise ValueError(f"Multiple AutoCalendar records found for actual_record_id={actual_record_id}.")
        validate_actual_record_match(matches[0], planner_row)
        return STATUS_PROCESSED, matches[0]

    if not template_id:
        raise ValueError("Missing templateID; cannot find an actual AutoCalendar record.")
    if not scheduling_date:
        raise ValueError("Missing original_scheduling_date; cannot find an actual AutoCalendar record.")

    scheduling_date = parse_planner_date(scheduling_date, "original_scheduling_date")
    matches = fetch_records_by_template_and_date(cursor, template_id, scheduling_date)
    if not matches:
        return STATUS_PENDING, None
    if len(matches) > 1:
        raise ValueError(
            "Multiple AutoCalendar records match "
            f"templateID={template_id}, original_scheduling_date={scheduling_date}."
        )

    return STATUS_PROCESSED, matches[0]


def update_record_note(cursor: Any, record_id: Any, note: str) -> None:
    cursor.execute(
        """
        UPDATE tblcalendar_dw_records
        SET fdNotes = ?,
            fdRecLastChange = NOW()
        WHERE fdRecID = ?
        """,
        [note, record_id],
    )


def apply_add_note(cursor: Any, record: Any, planner_row: dict[str, Any], executed_at: datetime) -> None:
    planned_note = require_value(planner_row, "planned_note")
    record_id = row_value(record, "fdRecID")
    final_note = append_note(row_value(record, "fdNotes"), planned_note)
    update_record_note(cursor, record_id, final_note)


def apply_mark_done(cursor: Any, record: Any, planner_row: dict[str, Any], executed_at: datetime) -> None:
    record_id = row_value(record, "fdRecID")
    final_note = append_note(row_value(record, "fdNotes"), planner_row.get("planned_note"))
    done_date = executed_at.date().isoformat()

    cursor.execute(
        """
        UPDATE tblcalendar_dw_records
        SET fdDone = 1,
            fdDoneDate = ?,
            fdNotes = ?,
            fdRecLastChange = NOW()
        WHERE fdRecID = ?
        """,
        [done_date, final_note, record_id],
    )


def apply_move_date(cursor: Any, record: Any, planner_row: dict[str, Any], executed_at: datetime) -> None:
    record_id = row_value(record, "fdRecID")
    move_to_date = parse_planner_date(planner_row.get("move_to_date"), "move_to_date")
    move_to_time = clean_text(planner_row.get("move_to_time"))
    final_note = append_note(row_value(record, "fdNotes"), planner_row.get("planned_note"))

    if move_to_time:
        cursor.execute(
            """
            UPDATE tblcalendar_dw_records
            SET fddDate2Show = ?,
                fdTime = ?,
                fdNotes = ?,
                fdRecLastChange = NOW()
            WHERE fdRecID = ?
            """,
            [move_to_date, parse_planner_time(move_to_time, "move_to_time"), final_note, record_id],
        )
        return

    cursor.execute(
        """
        UPDATE tblcalendar_dw_records
        SET fddDate2Show = ?,
            fdNotes = ?,
            fdRecLastChange = NOW()
        WHERE fdRecID = ?
        """,
        [move_to_date, final_note, record_id],
    )


def apply_move_time(cursor: Any, record: Any, planner_row: dict[str, Any], executed_at: datetime) -> None:
    record_id = row_value(record, "fdRecID")
    move_to_time = parse_planner_time(planner_row.get("move_to_time"), "move_to_time")
    final_note = append_note(row_value(record, "fdNotes"), planner_row.get("planned_note"))

    cursor.execute(
        """
        UPDATE tblcalendar_dw_records
        SET fdTime = ?,
            fdNotes = ?,
            fdRecLastChange = NOW()
        WHERE fdRecID = ?
        """,
        [move_to_time, final_note, record_id],
    )


ACTION_HANDLERS = {
    "ADD_NOTE": apply_add_note,
    "MARK_DONE": apply_mark_done,
    "MOVE_DATE": apply_move_date,
    "MOVE_TIME": apply_move_time,
}


def apply_planner_action(cursor: Any, record: Any, planner_row: dict[str, Any], executed_at: datetime) -> str:
    action = normalize_action(planner_row)
    if not action:
        raise ValueError("Missing planned_action.")

    handler = ACTION_HANDLERS.get(action)
    if handler is None:
        raise ValueError(f"Unsupported planned_action: {action}")

    handler(cursor, record, planner_row, executed_at)
    return action


def unique_destination_path(folder: str, source_path: str) -> str:
    os.makedirs(folder, exist_ok=True)
    base_name = os.path.basename(source_path)
    candidate = os.path.join(folder, base_name)
    if not os.path.exists(candidate):
        return candidate

    stem, ext = os.path.splitext(base_name)
    suffix = datetime.now().strftime("%Y%m%d%H%M%S")
    return os.path.join(folder, f"{stem}_{suffix}{ext}")


def write_result_sidecar(destination_path: str, result: ExecutionResult) -> None:
    payload = {
        "status": result.status,
        "source_path": result.source_path,
        "destination_path": result.destination_path,
        "record_id": result.record_id,
        "action": result.action,
        "message": result.message,
        "executed_at": utc_now_iso(),
    }
    with open(destination_path + ".result.json", "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)


def move_with_result(source_path: str, destination_dir: str, result: ExecutionResult) -> ExecutionResult:
    destination_path = unique_destination_path(destination_dir, source_path)
    shutil.move(source_path, destination_path)
    result.destination_path = destination_path
    write_result_sidecar(destination_path, result)
    return result


def execute_planner_file(
    source_path: str,
    processed_dir: str = DEFAULT_PROCESSED_DIR,
    error_dir: str = DEFAULT_ERROR_DIR,
    dry_run: bool = False,
) -> ExecutionResult:
    row = load_planner_row(source_path)
    action = normalize_action(row)
    autocalendar = Autocalendar()
    con, cursor = autocalendar.connect_to_db()

    try:
        match_status, record = find_matching_actual_record(cursor, row)
        if match_status == STATUS_PENDING:
            con.rollback()
            return ExecutionResult(
                status=STATUS_PENDING,
                source_path=source_path,
                message="Matching actual AutoCalendar record has not been created yet.",
                action=action,
            )

        record_id = row_value(record, "fdRecID")
        if dry_run:
            con.rollback()
            return ExecutionResult(
                status=STATUS_DRY_RUN,
                source_path=source_path,
                message=f"Dry run matched record {record_id}; no action applied and file left in place.",
                record_id=record_id,
                action=action,
            )

        apply_planner_action(cursor, record, row, datetime.now())
        con.commit()
        result = ExecutionResult(
            status=STATUS_PROCESSED,
            source_path=source_path,
            message=f"Applied {action} to AutoCalendar record {record_id}.",
            record_id=record_id,
            action=action,
        )
        return move_with_result(source_path, processed_dir, result)
    except Exception as exc:
        con.rollback()
        result = ExecutionResult(
            status=STATUS_ERROR,
            source_path=source_path,
            message=str(exc),
            action=action,
        )
        return move_with_result(source_path, error_dir, result)
    finally:
        cursor.close()
        con.close()


def execute_planner_batch(
    planner_json_dir: str = DEFAULT_PLANNER_JSON_DIR,
    processed_dir: str = DEFAULT_PROCESSED_DIR,
    error_dir: str = DEFAULT_ERROR_DIR,
    batch_limit: int = DEFAULT_BATCH_LIMIT,
    dry_run: bool = False,
) -> dict[str, Any]:
    files = discover_planner_json_files(planner_json_dir, batch_limit=batch_limit)
    results = [
        execute_planner_file(
            path,
            processed_dir=processed_dir,
            error_dir=error_dir,
            dry_run=dry_run,
        )
        for path in files
    ]

    counts = {
        STATUS_PROCESSED: 0,
        STATUS_PENDING: 0,
        STATUS_ERROR: 0,
        STATUS_DRY_RUN: 0,
    }
    for result in results:
        counts[result.status] = counts.get(result.status, 0) + 1

    return {
        "planner_json_dir": planner_json_dir,
        "processed_dir": processed_dir,
        "error_dir": error_dir,
        "dry_run": dry_run,
        "total_files": len(files),
        "counts": counts,
        "results": [result.__dict__ for result in results],
    }


def parse_bool_param(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "y", "on"}
    return bool(value)


def airflow_executor_kwargs(**context: Any) -> dict[str, Any]:
    params = context.get("params") or {}
    return {
        "planner_json_dir": params.get("planner_json_dir", DEFAULT_PLANNER_JSON_DIR),
        "processed_dir": params.get("processed_dir", DEFAULT_PROCESSED_DIR),
        "error_dir": params.get("error_dir", DEFAULT_ERROR_DIR),
        "batch_limit": int(params.get("batch_limit", DEFAULT_BATCH_LIMIT)),
        "dry_run": parse_bool_param(params.get("dry_run", False)),
    }
