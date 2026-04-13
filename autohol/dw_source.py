import csv
import glob
import os
from typing import Any
import pyodbc
import re




class Autocalendar:
   """
   Cleaned DW loader for the holiday planner project.
   Responsibilities:
   - connect to AutoCalendar DB
   - load DW templates
   - parse DW template rows into dictionaries
   """
   def __init__(self):
       self.odbc_driver = None
       self.dw_sql_entries = []
       self.get_odbc_driver()

   def get_odbc_driver(self):
       drivers = pyodbc.drivers()
       latest_driver = None
       version = 0.0
       for driver in drivers:
           match = re.search(r"MySQL ODBC (\d+[.]\d+).* Driver", driver)
           if match:
               if float(match[1]) > version:
                   latest_driver = match[0]
                   version = float(match[1])
       if not latest_driver:
           raise RuntimeError("Unable to find a MySQL ODBC driver.")
       self.odbc_driver = latest_driver

   def connect_to_db(self):
       conn_str = (
           f"DRIVER={{{self.odbc_driver}}};"
           f"SERVER=10.1.4.6;"
           f"PORT=3306;"
           f"DATABASE=autocalendar;"
           f"UID=autocal;"
           f"PWD=AutoCal_Pwd"
       )
       con = pyodbc.connect(conn_str, ansi=True)
       cursor = con.cursor()
       return con, cursor
   
   def get_dw(self):
       con, cursor = self.connect_to_db()
       cursor.execute(
           """
           SELECT *
           FROM tblcalendar_dw_templates dwt
           JOIN tblcalendar_countries cnt
             ON cnt.fdCountryID = dwt.fdCountryID
           JOIN tblcalendar_dw_database dwdb
             ON dwdb.fdDatabaseID = dwt.fdDatabaseID;
           """
       )
       self.dw_sql_entries = cursor.fetchall()
       cursor.close()
       con.close()

       return self.dw_sql_entries
   
   def parse_entries(self, dedupe_by_identifier: bool = False):
       """
       Parse DW SQL rows into planner-friendly dictionaries.
       Parameters
       ----------
       dedupe_by_identifier : bool
           If True, deduplicate by (database, country, group, update).
           For your planner, I recommend False so each templateID is preserved.
       """
       entries = []
       identifiers = set()
       for entry in self.dw_sql_entries:
           entry_dic = {
               "templateID": entry.fdTemplateID,
               "database": "" if not entry.fdDatabaseName else entry.fdDatabaseName,
               "group": "" if not entry.fdGroup else entry.fdGroup,
               "country": "" if not entry.fdCountryName else entry.fdCountryName,
               "update": "" if not entry.fdMessageBoard else entry.fdMessageBoard,
               "time": "" if not entry.fdTime else entry.fdTime.strftime("%I:%M:%S %p"),
               "auto": "" if not entry.fdBatchFile else entry.fdBatchFile,
               "trigger": entry.fdUpdateTrigger,
               "priority": entry.fdPriority,
               "assign": "" if not entry.fdAssign else entry.fdAssign,
               "procedures": "" if not entry.fdUpdateProc else entry.fdUpdateProc,
               "frq_sun": entry.fdFrqSun,
               "frq_mon": entry.fdFrqMon,
               "frq_tue": entry.fdFrqTue,
               "frq_wed": entry.fdFrqWed,
               "frq_thu": entry.fdFrqThu,
               "frq_fri": entry.fdFrqFri,
               "frq_sat": entry.fdFrqSat,
               "frq_daily": entry.fdFrqDaily,
               "template": "DW",
           }
           entries.append(entry_dic)

       return entries
   

class Assignments:
    """
    An assignment object is an object that contains assignments
    for given identifiers. An identifier is a tuple with lower case elements.
    For DW teamplate (database, country, group, update)
    For the MQA template ("mqa", country, group, update)

    The assignment files are found in f:\\automation\\stats\\assignments
    mqa.csv contains assignments for the MQA template entries. The assignments
    are done by country (as they appear in the autocalendar).
    mqa_custom.csv contains specific updates and assign to a particular
    team/EDM. These will take precedence over the general assignments.
    DW.csv contains assignments for the DW template entries.
    The general assignments are done by database. For some databases,
    such as INTDAILY and INTWKLY the assignments are done by group. These will
    have "ByGroup" in the Team and DBM fields next to the database.
    The group lists for INTDAILY and INTWKLY are maintained in
    f:\\intdaily\\qa\\grplist and f:\\intwkly\\qa\\grplist

    Parameters
    ----------
    dw_assignments : str (Optional)
        path to the dw.csv file.
        default f:\\automation\\stats\\assignments\\dw.csv
    dw_assignments_custom : str (Optional)
        path to the dw_custom.csv file.
        default f:\\automation\\stats\\assignments\\dw_custom.csv
    mqa_assignments : str (Optional)
        path to the mqa.csv file.
        default f:\\automation\\stats\\assignments\\mqa.csv
    mqa_assignments_custom : str (Optional)
        path to the mqa_custom file.
        default f:\\automation\\stats\\assignments\\mqa_custom.csv
    """

    def __init__(
        self,
        dw_assignments="f:\\automation\\stats\\assignments\\dw.csv",
        mqa_assignments="f:\\automation\\stats\\assignments\\mqa.csv",
        dw_assignments_custom="f:\\automation\\stats\\assignments\\dw_custom.csv",
        mqa_assignments_custom="f:\\automation\\stats\\assignments\\mqa_custom.csv",
        intdaily_gpa="f:\\intdaily\\qa\\GRPLIST\\INTDAILY.GPA",
        intwkly_gpa="f:\\intwkly\\qa\\GRPLIST\\INTWKLY.GPA",
        ):
        self.dw_assignments_path = dw_assignments
        self.mqa_assignments_path = mqa_assignments
        self.dw_assignments_custom_path = dw_assignments_custom
        self.mqa_assignments_custom_path = mqa_assignments_custom
        self.intdaily_gpa_path = intdaily_gpa
        self.intwkly_gpa_path = intwkly_gpa

        self.dw_assignments, self.dw_edm_team_map, self.mqa_assignments = self.get_assignment_dicts(
            dw_assignments, mqa_assignments
        )
        self.custom_assignments = self.get_custom_assignments(
            dw_assignments_custom, mqa_assignments_custom
        )
        self.gpa_assignments = self.get_gpa_assignments(
            intdaily_gpa, intwkly_gpa
        )


    def make_identifier(self, entry: dict) -> tuple:
        template = (entry.get("template") or "").strip().lower()
        database = (entry.get("database") or "").strip().lower()
        country = (entry.get("country") or "").strip().lower()
        group = (entry.get("group") or "").strip().lower()
        update = (entry.get("update") or "").strip().lower()

        if template == "mqa":
            return ("mqa", country, group, update)

        return (database, country, group, update)


    def assign(self, entries: Any, attach: bool = False):
        if isinstance(entries, dict):
            entries = [entries]
            single = True
        else:
            single = False

        results = {}
        updated_entries = []

        for entry in entries:
            identifier = self.make_identifier(entry)
            assignment = self.assign_identifier(identifier)
            results[identifier] = assignment

            if attach:
                new_entry = dict(entry)
                new_entry.update(assignment)
                updated_entries.append(new_entry)

        if attach:
            return updated_entries[0] if single else updated_entries

        return results


    def assign_identifier(self, identifier: tuple):
        if not isinstance(identifier, tuple) or len(identifier) != 4:
            raise ValueError("Identifier must be a tuple of length 4.")

        database, country, group, update = identifier
        database = (database or "").strip().lower()
        country = (country or "").strip().lower()
        group = (group or "").strip().lower()
        update = (update or "").strip().lower()

        # 1) custom assignment takes precedence
        if identifier in self.custom_assignments:
            custom = self.custom_assignments[identifier]
            return {
                "team": custom["team"] or "unassigned",
                "edm": custom["edm"] or "unassigned",
            }

        # 2) MQA general assignment
        if database == "mqa":
            if country in self.mqa_assignments:
                base = self.mqa_assignments[country]
                return {
                    "team": base["team"] or "unassigned",
                    "edm": base["edm"] or "unassigned",
                }
            return {"team": "unassigned", "edm": "unassigned"}

        # 3) INTDAILY / INTWKLY special GPA mapping
        if database in {"intdaily", "intwkly"}:
            first_group = group.split(",")[0].strip().lower() if group else ""
            if not first_group:
                return {"team": "unassigned", "edm": "unassigned"}

            gpa_key = (database, first_group)
            if gpa_key not in self.gpa_assignments:
                return {"team": "unassigned", "edm": "unassigned"}

            edm = self.gpa_assignments[gpa_key]
            team = self.dw_edm_team_map.get(edm, "unassigned")
            return {
                "team": team or "unassigned",
                "edm": edm or "unassigned",
            }

        # 4) DW database-level assignment
        if database in self.dw_assignments:
            base = self.dw_assignments[database]
            return {
                "team": base["team"] or "unassigned",
                "edm": base["edm"] or "unassigned",
            }

        return {"team": "unassigned", "edm": "unassigned"}


    @staticmethod
    def get_assignment_dicts(dw_csv, mqa_csv):
        if not os.path.exists(dw_csv):
            raise FileNotFoundError(f"{dw_csv} does not exist.")
        if not os.path.exists(mqa_csv):
            raise FileNotFoundError(f"{mqa_csv} does not exist.")

        dw_assignments = {}
        dw_edm_team_map = {}

        with open(dw_csv, "r", encoding="utf-8-sig", newline="") as f:
            lines = list(csv.reader(f))

        # Right-side table: EDM -> Team
        for line in lines[1:]:
            if len(line) >= 6:
                edm = (line[4] or "").strip().lower()
                team = (line[5] or "").strip().lower()
                if edm:
                    dw_edm_team_map[edm] = team

        # Left-side table: database -> team, dbm(edm)
        for line in lines[1:]:
            if len(line) < 3:
                continue
            database = (line[0] or "").strip().lower()
            team = (line[1] or "").strip().lower()
            edm = (line[2] or "").strip().lower()
            if not database:
                continue
            dw_assignments[database] = {
                "team": team or "unassigned",
                "edm": edm or "unassigned",
            }

        mqa_assignments = {}
        with open(mqa_csv, "r", encoding="utf-8-sig", newline="") as f:
            lines = list(csv.reader(f))

        for line in lines[1:]:
            if len(line) < 3:
                continue
            country = (line[0] or "").strip().lower()
            team = (line[1] or "").strip().lower()
            edm = (line[2] or "").strip().lower()
            if not country:
                continue
            mqa_assignments[country] = {
                "team": team or "unassigned",
                "edm": edm or "unassigned",
            }

        return dw_assignments, dw_edm_team_map, mqa_assignments

    @staticmethod
    def get_custom_assignments(custom_dw, custom_mqa):
        custom_assignments = {}

        if not os.path.exists(custom_dw):
            raise FileNotFoundError(f"{custom_dw} does not exist.")
        if not os.path.exists(custom_mqa):
            raise FileNotFoundError(f"{custom_mqa} does not exist.")

        # mqa_custom.csv
        with open(custom_mqa, "r", encoding="utf-8-sig", newline="") as f:
            lines = list(csv.reader(f))
        for line in lines[1:]:
            if len(line) < 5:
                continue
            identifier = (
                "mqa",
                (line[0] or "").strip().lower(),
                (line[1] or "").strip().lower(),
                (line[2] or "").strip().lower(),
            )
            team = (line[3] or "").strip().lower() or "unassigned"
            edm = (line[4] or "").strip().lower() or "unassigned"
            custom_assignments[identifier] = {"team": team, "edm": edm}

        # dw_custom.csv
        with open(custom_dw, "r", encoding="utf-8-sig", newline="") as f:
            lines = list(csv.reader(f))
        for line in lines[1:]:
            if len(line) < 6:
                continue
            identifier = (
                (line[0] or "").strip().lower(),
                (line[1] or "").strip().lower(),
                (line[2] or "").strip().lower(),
                (line[3] or "").strip().lower(),
            )
            team = (line[4] or "").strip().lower() or "unassigned"
            edm = (line[5] or "").strip().lower() or "unassigned"
            custom_assignments[identifier] = {"team": team, "edm": edm}

        return custom_assignments
    

    @staticmethod
    def clean_gpa_owner_line(line: str) -> str:
        line = line.strip().lower()

        # remove common prefixes
        line = re.sub(r"^(dbm|edm)\s*:\s*", "", line)

        # collapse extra spaces
        line = re.sub(r"\s+", " ", line).strip()

        return line
    

    @staticmethod
    def get_gpa_assignments(intdaily_gpa, intwkly_gpa):
        """
        Build:
            (database, group) -> edm

        GPA parsing rules:
        - ignore separator lines like ========
        - treat entry lines as lines whose first token looks like a group code
        such as T11, J54, R90
        - treat other non-empty lines as potential DBM/EDM headers
        """
        result = {}

        group_code_pattern = re.compile(r"^[A-Za-z]\d+$")

        for database, path in [("intdaily", intdaily_gpa), ("intwkly", intwkly_gpa)]:
            if not os.path.exists(path):
                continue

            current_edm = None

            with open(path, "r", encoding="utf-8-sig", errors="ignore") as f:
                for raw_line in f:
                    line = raw_line.strip()
                    if not line:
                        continue

                    # Ignore separator lines like ======== or --------
                    if set(line) <= {"=", "-", "_", "*"}:
                        continue

                    first_token = line.split()[0].strip()

                    # Entry line: first token is a group code like T11 / J54 / R90
                    if group_code_pattern.match(first_token):
                        if current_edm is not None:
                            result[(database, first_token.lower())] = current_edm
                        continue

                    # Otherwise treat line as a DBM/EDM header
                    current_edm = Assignments.clean_gpa_owner_line(line)

        return result
    
