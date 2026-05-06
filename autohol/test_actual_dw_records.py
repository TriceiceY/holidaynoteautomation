import argparse
import sys
from datetime import datetime
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from autohol.dw_source import Autocalendar


def parse_args():
    parser = argparse.ArgumentParser(
        description="Smoke test for retrieving actual DW records from AutoCalendar."
    )
    parser.add_argument(
        "--date-from",
        required=True,
        help="Start date in YYYY-MM-DD format.",
    )
    parser.add_argument(
        "--date-to",
        required=True,
        help="End date in YYYY-MM-DD format.",
    )
    parser.add_argument(
        "--country",
        help="Optional country name filter, e.g. 'UK'.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=20,
        help="Maximum number of rows to print. Default: 20.",
    )
    return parser.parse_args()


def parse_iso_date(raw_value: str, field_name: str):
    try:
        return datetime.strptime(raw_value, "%Y-%m-%d").date()
    except ValueError as exc:
        raise ValueError(f"{field_name} must be in YYYY-MM-DD format.") from exc


def format_value(value):
    if value is None:
        return ""
    if hasattr(value, "strftime"):
        if hasattr(value, "hour"):
            return value.strftime("%I:%M:%S %p")
        return value.strftime("%Y-%m-%d")
    return str(value)


def fetch_actual_dw_records(date_from, date_to, country=None, limit=20):
    autocal = Autocalendar()
    con, cursor = autocal.connect_to_db()

    sql = """
        SELECT
            dwr.fdRecID,
            dwr.fdTemplateID,
            dwr.fddDate2Show,
            dwr.fdTime,
            cnt.fdCountryName AS fdCountryName,
            dwdb.fdDatabaseName AS fdDatabaseName,
            dwt.fdGroup AS fdGroup,
            dwt.fdMessageBoard AS fdMessageBoard,
            dwt.fdUpdateTrigger AS fdUpdateTrigger,
            dwt.fdUpdateProc AS fdUpdateProc,
            dwr.fdDone
        FROM tblcalendar_dw_records dwr
        JOIN tblcalendar_dw_templates dwt
          ON dwt.fdTemplateID = dwr.fdTemplateID
        JOIN tblcalendar_countries cnt
          ON cnt.fdCountryID = dwt.fdCountryID
        JOIN tblcalendar_dw_database dwdb
          ON dwdb.fdDatabaseID = dwt.fdDatabaseID
        WHERE DATE(dwr.fddDate2Show) >= ?
          AND DATE(dwr.fddDate2Show) <= ?
    """

    params = [date_from.isoformat(), date_to.isoformat()]

    if country:
        sql += "\n  AND cnt.fdCountryName = ?"
        params.append(country)

    sql += "\nORDER BY dwr.fddDate2Show, cnt.fdCountryName, dwr.fdRecID\nLIMIT ?"
    params.append(limit)

    try:
        cursor.execute(sql + ";", params)
        rows = cursor.fetchall()
        columns = [column[0] for column in cursor.description]
    finally:
        cursor.close()
        con.close()

    normalized_rows = []
    for row in rows:
        normalized_rows.append(
            {column: format_value(getattr(row, column)) for column in columns}
        )
    return normalized_rows


def print_summary(date_from, date_to, country, limit, row_count):
    print("Actual DW Records Retrieval Test")
    print(f"date_from={date_from.isoformat()}")
    print(f"date_to={date_to.isoformat()}")
    print(f"country={country or 'ALL'}")
    print(f"limit={limit}")
    print(f"rows_returned={row_count}")
    print("")


def print_rows(rows):
    for row in rows:
        print(
            " | ".join(
                [
                    f"fdRecID={row['fdRecID']}",
                    f"fdTemplateID={row['fdTemplateID']}",
                    f"fddDate2Show={row['fddDate2Show']}",
                    f"fdTime={row['fdTime']}",
                    f"fdCountryName={row['fdCountryName']}",
                    f"fdDatabaseName={row['fdDatabaseName']}",
                    f"fdGroup={row['fdGroup']}",
                    f"fdMessageBoard={row['fdMessageBoard']}",
                    f"fdUpdateTrigger={row['fdUpdateTrigger']}",
                    f"fdUpdateProc={row['fdUpdateProc']}",
                    f"fdDone={row['fdDone']}",
                ]
            )
        )


def main():
    try:
        args = parse_args()
        date_from = parse_iso_date(args.date_from, "--date-from")
        date_to = parse_iso_date(args.date_to, "--date-to")

        if date_from > date_to:
            raise ValueError("--date-from must be less than or equal to --date-to.")
        if args.limit <= 0:
            raise ValueError("--limit must be greater than 0.")

        rows = fetch_actual_dw_records(
            date_from=date_from,
            date_to=date_to,
            country=args.country,
            limit=args.limit,
        )
        print_summary(date_from, date_to, args.country, args.limit, len(rows))

        if not rows:
            print("0 rows found. Query ran successfully.")
            return 0

        print_rows(rows)
        return 0

    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
