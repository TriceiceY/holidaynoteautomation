# AutoHoliday Planner

## What Is It
AutoHoliday Planner is a planning tool for upcoming holiday scheduling. The planner helps EDMs review and prepare scheduling around holidays. 

The program looks at AutoCalendar DW actual/template entries, matches them to EDM assignments, checks whether the selected date is a holiday for countries related to those entries, and builds a planner table for the holiday date plus a surrounding date window.

## Why It Matters
EDMs do not have to wait until the autocalendar generates records to do the holiday schedulding. Instead, they can pick any holiday date through out the year and schedulding their updates. The planner will create planner output that can be executed by AutoHub Airflow automatically.

## How It Works

1. Load holiday records from the default Q++ holiday CSV.
2. Load custom holidays and merge them with the default holiday set in memory.
3. Load DW template entries and existing DW records from AutoCalendar.
4. Attach assignment ownership to DW entries.
5. Filter to the entered EDM, or use all-users mode when the user field is blank.
6. Find countries that have a holiday on the selected date.
7. Match those holiday countries to relevant DW entries.
8. Build planner rows for the selected date window.
9. Annotate rows with holiday name and normalized holiday type.
10. Let the user filter, sort, apply actions, and save the output log.

## What It Helps With

- Finds which assigned countries are on holiday on a selected date.
- Shows affected DW entries for those countries.
- Shows entries in the planning window, such as one week before and one week after the holiday date.
- Supports single-user mode and all-users mode.
- Supports custom holiday additions and custom holiday CSV imports.
- Lets users apply planning actions such as add note, mark done, move date, or move time.
- Saves planner decisions to JSON and CSV output.

## Main Application

```bash
python ui/autohol_ui.py
```

## User Workflow

1. Open the program.
2. Optionally enter an EDM name. Leave it blank for all-users mode.
3. Choose a holiday date.
4. If a holiday is missing, add it in the custom holiday section.
5. Adjust days before and days after if needed.
6. Click `Generate Planner Rows`.
7. Review the planner table page by page.
8. Use filters or sorting if needed.
9. Select one or more rows.
10. Choose an action in the Action Editor.
11. Save the planner log when finished.

## UI Areas

- `Planner Controls`: choose user, holiday date, and date window.
- `Custom Holiday`: add one holiday manually or import a CSV.
- `Summary`: view selected user, holiday date, window, loaded rows, selected rows, and rows with actions.
- `Date Navigation`: review one date per page with previous, next, and jump-to-holiday-date buttons.
- `Filters`: narrow rows by database, country, and holiday type.
- `Planner Table`: review rows for the current date page.
- `Action Editor`: apply note, date, time, or done actions to selected rows.
- `Save Planner Log`: export action rows to JSON and CSV.

## Available Actions

- `ADD_NOTE`: adds a note using the `AUTOHOL:` prefix.
- `MARK_DONE`: marks the row as done and records the action date in the note.
- `MOVE_DATE`: stores a move mode and move-to date, and can also store a move-to time.
- `MOVE_TIME`: stores a move-to time without changing the date.

`MOVE_DATE` and `MOVE_TIME` can be used together. When `MARK_DONE` is applied, or when an action overwrites an existing action on the same planner row, the app shows a warning listing the affected row details.

## Custom Holidays

Users can add a custom holiday manually in the UI or import custom holidays from CSV. Custom holiday records include country, holiday date, holiday name, and holiday observance.

Custom holidays are merged with the default Q++ holiday file in memory when the planner runs. They do not overwrite the default holiday CSV.

## Output Files

Only planner rows with actions are saved. Output is written as JSON and CSV:

- Individual JSON files for planner action rows, organized by original scheduling date.
- A CSV planner log named for the planner user, or `all_users` when the user field is blank.

## Important Notes

- Planner actions are planning instructions; they do not directly edit DW source records.
- If no relevant holiday countries are found for the selected date, the program tells the user.
- Country value `Various` is not used for holiday-country matching because it cannot be mapped reliably to one country.
- Sorting and filtering are UI tools only; they do not change the underlying DW data.
- For move-date logic, `next_calendar_day` means the next actual date and `next_business_day` means the next Monday-Friday date.
- For frequency logic, `frq_daily` means Monday-Friday. Daily plus Saturday and Sunday means every day.
- Saving the planner log is the final exported output of the user's planning decisions.



## Airflow Executor Progress

The repository also includes an Airflow DAG for executing saved planner JSON
actions through AutoHub Airflow:

```text
tests/test_autohol_executor.py       Unit tests for executor behavior.
```

The DAG is intentionally thin. It imports the tested executor logic from
`autohol_executor.py`, exposes runtime parameters for the planner JSON,
processed, and error folders, and runs the executor as one TaskFlow task.


From the Airflow UI:

1. Open the Airflow web UI.
2. Find `autohol_executor_taskflow`.
3. Unpause the DAG if needed.
4. Click the trigger/play button.
5. Optionally override the DAG params for `planner_json_dir`, `processed_dir`,
   `error_dir`, `batch_limit`, or `dry_run`.


## Setup

Use Python 3.11 or a compatible Python 3 version.

```bash
pip install -r requirements.txt
```

## Required Local Resources

AutoHoliday Planner depends on Haver resources:

- A MySQL ODBC driver available to `pyodbc`.
- AutoCalendar database access.
- Q++ holiday CSV data.
- DW assignment files, including `dw.csv` and `dw_custom.csv`.
- GPA files for INTDAILY and INTWKLY group-based assignments.
- Planner output folders for JSON and CSV logs.

If any default paths differ on your machine, update the relevant path in the UI or helper module before running the planner.

## Project Scripts

```text
ui/autohol_ui.py                      Main PyQt6 user interface.
autohol/holidays.py                   Holiday loading, country normalization, and holiday type helpers.
autohol/dw_source.py                  AutoCalendar reads and assignment mapping.
autohol/future_holiday_planner.py     Planner row generation, filtering, annotation, and log writing.
DAG/autohol_executor_dag.py          Airflow TaskFlow DAG entrypoint.
autohol_executor.py                  Planner JSON executor business logic.
```
