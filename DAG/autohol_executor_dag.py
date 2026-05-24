"""
Airflow DAG entrypoints for the AutoHoliday executor.

Business logic lives in autohol_executor.py so it can be imported and tested
without requiring Airflow.
"""

from __future__ import annotations

from autohol_executor import (
    DEFAULT_BATCH_LIMIT,
    DEFAULT_ERROR_DIR,
    DEFAULT_PLANNER_JSON_DIR,
    DEFAULT_PROCESSED_DIR,
    airflow_executor_kwargs,
    execute_planner_batch,
)


try:
    import pendulum
    from airflow.decorators import dag, task
    from airflow.models.param import Param

    AIRFLOW_AVAILABLE = True
except Exception:
    pendulum = None
    dag = None
    task = None
    Param = None
    AIRFLOW_AVAILABLE = False


if AIRFLOW_AVAILABLE:
    AIRFLOW_PARAMS = {
        "planner_json_dir": Param(DEFAULT_PLANNER_JSON_DIR, type="string"),
        "processed_dir": Param(DEFAULT_PROCESSED_DIR, type="string"),
        "error_dir": Param(DEFAULT_ERROR_DIR, type="string"),
        "batch_limit": Param(DEFAULT_BATCH_LIMIT, type="integer", minimum=1),
        "dry_run": Param(False, type="boolean"),
    }

    @dag(
        dag_id="autohol_executor_taskflow",
        start_date=pendulum.datetime(2026, 1, 1, tz="America/New_York"),
        schedule=None,
        catchup=False,
        params=AIRFLOW_PARAMS,
        tags=["autohol", "autocalendar"],
    )
    def build_autohol_executor_taskflow():
        @task
        def run_executor(**context):
            return execute_planner_batch(**airflow_executor_kwargs(**context))

        run_executor()

    autohol_executor_taskflow = build_autohol_executor_taskflow()
