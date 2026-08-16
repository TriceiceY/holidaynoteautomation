"""Standalone person-first assignment and yearly holiday planning logic.

This module deliberately has no UI or database dependency.  Callers supply DW
or MQA template dictionaries and holiday records, which makes the rules easy to
test before they are integrated into the main application.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
import csv
import os
from pathlib import Path
import re
from typing import Any, Iterable, Mapping, Sequence

from autohol.future_holiday_planner import is_template_scheduled_on_date
from autohol.holidays import normalize_country


UNASSIGNED = "unassigned"
GROUP_DATABASES = {"intdaily", "intwkly"}


def normalize_text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip()).casefold()


def person_key(value: Any) -> str:
    """Return a matching key that treats ``Ryan T`` and ``RyanT`` alike."""
    return re.sub(r"[^a-z0-9]", "", normalize_text(value))


def first_group(value: Any) -> str:
    return normalize_text(value).split(",", 1)[0].strip()


def parse_date(value: Any) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return datetime.strptime(str(value).strip(), "%Y-%m-%d").date()


@dataclass(frozen=True)
class Owner:
    team: str = UNASSIGNED
    edm: str = UNASSIGNED
    source: str = UNASSIGNED


@dataclass(frozen=True)
class AssignmentPaths:
    dw: Path
    dw_custom: Path
    mqa: Path
    mqa_custom: Path
    country: Path
    intdaily_gpa: Path
    intwkly_gpa: Path

    @classmethod
    def from_directory(cls, directory: str | os.PathLike[str]) -> "AssignmentPaths":
        root = Path(directory)
        return cls(
            dw=root / "dw.csv",
            dw_custom=root / "dw_custom.CSV",
            mqa=root / "mqa.csv",
            mqa_custom=root / "mqa_custom.csv",
            country=root / "country_assignments.CSV",
            intdaily_gpa=root / "intdaily.gpa",
            intwkly_gpa=root / "INTWKLY.GPA",
        )


@dataclass
class ResponsibilityProfile:
    person: str
    managed_countries: list[str]
    managed_groups: dict[str, list[str]]
    assigned_tasks: list[dict[str, Any]]


@dataclass
class AssignmentCatalog:
    """Loaded assignment sources and their precedence rules."""

    dw_general: dict[str, Owner] = field(default_factory=dict)
    dw_custom: dict[tuple[str, str, str, str], Owner] = field(default_factory=dict)
    mqa_general: dict[str, Owner] = field(default_factory=dict)
    mqa_custom: dict[tuple[str, str, str], Owner] = field(default_factory=dict)
    country_managers: dict[str, str] = field(default_factory=dict)
    country_display_names: dict[str, str] = field(default_factory=dict)
    group_managers: dict[tuple[str, str], str] = field(default_factory=dict)
    edm_team_map: dict[str, str] = field(default_factory=dict)
    issues: list[str] = field(default_factory=list)

    @classmethod
    def load(cls, paths: AssignmentPaths) -> "AssignmentCatalog":
        catalog = cls()
        catalog._load_dw(paths.dw)
        catalog._load_general_mqa(paths.mqa)
        catalog._load_dw_custom(paths.dw_custom)
        catalog._load_mqa_custom(paths.mqa_custom)
        catalog._load_country_managers(paths.country)
        catalog._load_gpa("intdaily", paths.intdaily_gpa)
        catalog._load_gpa("intwkly", paths.intwkly_gpa)
        return catalog

    @staticmethod
    def _rows(path: Path, *, errors: str = "replace") -> list[list[str]]:
        if not path.exists():
            raise FileNotFoundError(path)
        with path.open("r", encoding="utf-8-sig", errors=errors, newline="") as handle:
            return list(csv.reader(handle))

    def _record(
        self,
        target: dict[Any, Owner],
        key: Any,
        owner: Owner,
        source: str,
        line_number: int,
    ) -> None:
        previous = target.get(key)
        if previous and (previous.team, previous.edm) != (owner.team, owner.edm):
            self.issues.append(
                f"Conflicting {source} assignment for {key!r} at line {line_number}; "
                f"using {owner.edm!r} instead of {previous.edm!r}."
            )
        target[key] = owner

    def _load_dw(self, path: Path) -> None:
        rows = self._rows(path)
        for line_number, row in enumerate(rows[1:], 2):
            if len(row) >= 3 and normalize_text(row[0]):
                key = normalize_text(row[0])
                self._record(
                    self.dw_general,
                    key,
                    Owner(
                        normalize_text(row[1]) or UNASSIGNED,
                        normalize_text(row[2]) or UNASSIGNED,
                        "dw.csv",
                    ),
                    "DW general",
                    line_number,
                )
            if len(row) >= 6 and normalize_text(row[4]):
                self.edm_team_map[person_key(row[4])] = normalize_text(row[5]) or UNASSIGNED

    def _load_general_mqa(self, path: Path) -> None:
        rows = self._rows(path)
        for line_number, row in enumerate(rows[1:], 2):
            if len(row) < 3 or not normalize_text(row[0]):
                continue
            key = normalize_text(row[0])
            self._record(
                self.mqa_general,
                key,
                Owner(
                    normalize_text(row[1]) or UNASSIGNED,
                    normalize_text(row[2]) or UNASSIGNED,
                    "mqa.csv",
                ),
                "MQA general",
                line_number,
            )

    def _load_dw_custom(self, path: Path) -> None:
        rows = self._rows(path)
        for line_number, row in enumerate(rows[1:], 2):
            if len(row) < 6:
                continue
            key = tuple(normalize_text(value) for value in row[:4])
            if not key[0]:
                continue
            self._record(
                self.dw_custom,
                key,
                Owner(
                    normalize_text(row[4]) or UNASSIGNED,
                    normalize_text(row[5]) or UNASSIGNED,
                    "dw_custom.CSV",
                ),
                "DW custom",
                line_number,
            )

    def _load_mqa_custom(self, path: Path) -> None:
        rows = self._rows(path)
        for line_number, row in enumerate(rows[1:], 2):
            if len(row) < 5:
                continue
            key = tuple(normalize_text(value) for value in row[:3])
            if not key[0]:
                continue
            self._record(
                self.mqa_custom,
                key,
                Owner(
                    normalize_text(row[3]) or UNASSIGNED,
                    normalize_text(row[4]) or UNASSIGNED,
                    "mqa_custom.csv",
                ),
                "MQA custom",
                line_number,
            )

    def _load_country_managers(self, path: Path) -> None:
        rows = self._rows(path)
        header_index = next(
            (
                index
                for index, row in enumerate(rows)
                if "COUNTRY" in row and "INTDAILY/ INTWKLY: (who manages)" in row
            ),
            None,
        )
        if header_index is None:
            raise ValueError(f"Country assignment header was not found in {path}.")
        header = rows[header_index]
        country_index = header.index("COUNTRY")
        manager_index = header.index("INTDAILY/ INTWKLY: (who manages)")

        for row in rows[header_index + 1 :]:
            if len(row) <= max(country_index, manager_index):
                continue
            display_country = row[country_index].strip()
            manager = row[manager_index].strip()
            if not display_country:
                continue
            country = normalize_country(display_country)
            self.country_display_names[country] = display_country
            if manager:
                self.country_managers[country] = manager

    def _load_gpa(self, database: str, path: Path) -> None:
        group_pattern = re.compile(r"^[A-Za-z]\d+$")
        owner_pattern = re.compile(r"^(?:DBM|EDM)\s*:\s*(.+?)\s*$", re.IGNORECASE)
        current_owner = ""

        with path.open("r", encoding="utf-8-sig", errors="ignore") as handle:
            for raw_line in handle:
                line = raw_line.strip()
                if not line or set(line) <= {"=", "-", "_", "*"}:
                    continue
                owner_match = owner_pattern.match(line)
                if owner_match:
                    current_owner = owner_match.group(1).strip()
                    continue

                first_token = line.split()[0]
                if group_pattern.fullmatch(first_token):
                    if current_owner:
                        self.group_managers[(database, normalize_text(first_token))] = current_owner
                    continue

                # Section labels such as "Historical and Test/Automation Groups"
                # are not people and must not inherit the preceding owner.
                current_owner = ""

    def resolve_task(self, entry: Mapping[str, Any]) -> Owner:
        template = normalize_text(entry.get("template") or "dw")
        database = normalize_text(entry.get("database"))
        country = normalize_text(entry.get("country"))
        group = normalize_text(entry.get("group"))
        update = normalize_text(entry.get("update"))

        if template == "mqa" or database == "mqa":
            custom_key = (country, group, update)
            if custom_key in self.mqa_custom:
                return self.mqa_custom[custom_key]
            return self.mqa_general.get(country, Owner(source="mqa.csv"))

        custom_key = (database, country, group, update)
        if custom_key in self.dw_custom:
            return self.dw_custom[custom_key]

        if database in GROUP_DATABASES:
            manager = self.group_managers.get((database, first_group(group)))
            if manager:
                return Owner(
                    self.edm_team_map.get(person_key(manager), UNASSIGNED),
                    normalize_text(manager),
                    f"{database}.gpa",
                )

        return self.dw_general.get(database, Owner(source="dw.csv"))

    def managed_countries(self, person: str) -> list[str]:
        key = person_key(person)
        countries = [
            self.country_display_names.get(country, country)
            for country, manager in self.country_managers.items()
            if person_key(manager) == key
        ]
        return sorted(countries, key=str.casefold)

    def managed_groups(self, person: str) -> dict[str, list[str]]:
        key = person_key(person)
        result: dict[str, list[str]] = defaultdict(list)
        for (database, group), manager in self.group_managers.items():
            if person_key(manager) == key:
                result[database].append(group.upper())
        return {database: sorted(groups) for database, groups in sorted(result.items())}

    def assigned_tasks(
        self, person: str, entries: Iterable[Mapping[str, Any]]
    ) -> list[dict[str, Any]]:
        key = person_key(person)
        result = []
        for entry in entries:
            owner = self.resolve_task(entry)
            if person_key(owner.edm) != key:
                continue
            task = dict(entry)
            task.update({"team": owner.team, "edm": owner.edm, "assignment_source": owner.source})
            result.append(task)
        return result

    def profile(
        self, person: str, entries: Iterable[Mapping[str, Any]]
    ) -> ResponsibilityProfile:
        return ResponsibilityProfile(
            person=person,
            managed_countries=self.managed_countries(person),
            managed_groups=self.managed_groups(person),
            assigned_tasks=self.assigned_tasks(person, entries),
        )


def qualifying_holidays(
    holiday_records: Iterable[Mapping[str, Any]], country: str, year: int
) -> list[dict[str, Any]]:
    """Return every holiday observance for the requested country and year."""
    country_key = normalize_country(country)
    result = []
    for record in holiday_records:
        if normalize_country(str(record.get("country") or "")) != country_key:
            continue
        holiday_date = parse_date(record.get("holiday_date"))
        if holiday_date.year != year:
            continue
        item = dict(record)
        item["holiday_date"] = holiday_date
        result.append(item)
    return sorted(result, key=lambda item: (item["holiday_date"], str(item.get("holiday_name", ""))))


def _occurrence_key(task: Mapping[str, Any], target_date: date) -> tuple[str, str]:
    task_id = str(task.get("actual_record_id") or task.get("templateID") or "").strip()
    if not task_id:
        task_id = "|".join(
            normalize_text(task.get(field)) for field in ("database", "country", "group", "update")
        )
    return task_id, target_date.isoformat()


def build_yearly_occurrences(
    tasks: Sequence[Mapping[str, Any]],
    holidays: Sequence[Mapping[str, Any]],
    *,
    days_before: int = 7,
    days_after: int = 7,
) -> list[dict[str, Any]]:
    """Build unique scheduled occurrences and retain all holiday contexts.

    Overlapping holiday windows do not create duplicate actionable rows.  The
    row instead contains every holiday that caused it to be included.
    """
    occurrences: dict[tuple[str, str], dict[str, Any]] = {}

    for holiday in holidays:
        holiday_date = parse_date(holiday.get("holiday_date"))
        context = {
            "holiday_date": holiday_date.isoformat(),
            "holiday_name": str(holiday.get("holiday_name") or "").strip(),
            "holiday_observance": str(holiday.get("holiday_observance") or "").strip(),
        }
        start = holiday_date - timedelta(days=days_before)
        end = holiday_date + timedelta(days=days_after)
        current = start
        while current <= end:
            for task in tasks:
                if not is_template_scheduled_on_date(task, current):
                    continue
                key = _occurrence_key(task, current)
                if key not in occurrences:
                    row = dict(task)
                    row["original_scheduling_date"] = current.isoformat()
                    row["holiday_contexts"] = []
                    occurrences[key] = row
                if context not in occurrences[key]["holiday_contexts"]:
                    occurrences[key]["holiday_contexts"].append(context)
            current += timedelta(days=1)

    return sorted(
        occurrences.values(),
        key=lambda row: (
            row["original_scheduling_date"],
            str(row.get("templateID") or ""),
            str(row.get("update") or "").casefold(),
        ),
    )


def plan_country_year(
    catalog: AssignmentCatalog,
    person: str,
    country: str,
    year: int,
    entries: Sequence[Mapping[str, Any]],
    holiday_records: Sequence[Mapping[str, Any]],
    *,
    days_before: int = 7,
    days_after: int = 7,
) -> list[dict[str, Any]]:
    managed = {normalize_country(value) for value in catalog.managed_countries(person)}
    country_key = normalize_country(country)
    if country_key not in managed:
        raise ValueError(f"{person!r} is not the configured INTDAILY/INTWKLY manager for {country!r}.")

    tasks = [
        entry
        for entry in entries
        if normalize_text(entry.get("database")) in GROUP_DATABASES
        and normalize_country(str(entry.get("country") or "")) == country_key
    ]
    holidays = qualifying_holidays(holiday_records, country, year)
    return build_yearly_occurrences(
        tasks, holidays, days_before=days_before, days_after=days_after
    )


def plan_task_year(
    catalog: AssignmentCatalog,
    person: str,
    task: Mapping[str, Any],
    year: int,
    holiday_records: Sequence[Mapping[str, Any]],
    *,
    days_before: int = 7,
    days_after: int = 7,
) -> list[dict[str, Any]]:
    owner = catalog.resolve_task(task)
    if person_key(owner.edm) != person_key(person):
        raise ValueError(f"{person!r} is not the resolved owner of the selected task.")
    country = str(task.get("country") or "").strip()
    if not country or normalize_country(country) in {"", "various"}:
        raise ValueError("The selected task does not have one usable holiday country.")
    holidays = qualifying_holidays(holiday_records, country, year)
    task_with_owner = dict(task)
    task_with_owner.update(
        {"team": owner.team, "edm": owner.edm, "assignment_source": owner.source}
    )
    return build_yearly_occurrences(
        [task_with_owner], holidays, days_before=days_before, days_after=days_after
    )
