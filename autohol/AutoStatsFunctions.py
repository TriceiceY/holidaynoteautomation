import sys
from datetime import datetime, timedelta
from pprint import pprint
import csv
import os
import glob
from typing import Union
from typing import Any
from collections.abc import Iterable
from collections import ChainMap
import warnings
import re
from collections import OrderedDict
import pandas as pd
import logging
import pyodbc
from functools import lru_cache
from pandas.tseries.offsets import BMonthEnd 

# import pysnooper
import configparser
import copy

config = configparser.ConfigParser()
config.optionxform = str
config.read("g:\\batch\\autostats.ini")

logger = logging.getLogger()


class Identifier:

    """
    Gets identifier from an auto file or dictionary (entry)
    which has keys "database", "country", "group", "update".
    An identifier is a tuple with lower case elements.
    For DW teamplate (database, country, group, update)
    For the MQA template ("mqa", country, group, update)

    Parameters
    ----------
    obj : Any
        Object can be an auto file or dictionary
    objtype: str (Optional)
        Type of input object. Can be "auto" or "entry".
        By default "infer" will infer the object type
    """

    def __init__(self, obj=None, objtype="infer"):
        self.obj = obj
        self.objtype = objtype
        self.identifier = None
        self.orig_fields = None # template, db, country, group, update
        if obj:
            self.identify(obj, objtype=objtype)
        self._cache = dict()
        self._orig_fields_cache = dict()

    def identify(self, obj, objtype="infer"):
        # logger.debug("Identifier object called. Getting identifier.")
        objtype = objtype.lower()
        if objtype not in ["infer", "auto", "entry"]:
            raise ValueError(
                'Objtype parameter has to be one of "infer", "auto" or "entry"'
            )
        if objtype == "infer":
            objtype = self.infer_type(obj)
        if objtype == "auto":
            return self.get_identifier_from_auto(obj)
        else:
            return self.get_identifier_from_entry(obj)

    def infer_type(self, obj):
        if isinstance(obj, dict):
            # logger.debug('Inferred type "entry"')
            self.objtype = "entry"
            return "entry"
        if isinstance(obj, str) and (
            obj.lower().endswith(".auto") or obj.lower().endswith(".bat")
        ):
            # logger.debug('Inferred type "auto"')
            self.objtype = "auto"
            return "auto"
        raise TypeError("Input object has to be a dict, auto or batch file.")

    def get_identifier_from_entry(self, entry):
        if (
            "database" not in entry
            or "country" not in entry
            or "group" not in entry
            or "update" not in entry
        ):
            raise ValueError("Entry does not contain required fields.")
        db, country, group, update = (
            entry["database"].lower(),
            entry["country"].lower(),
            entry["group"].lower(),
            entry["update"].lower(),
        )
        identifier = (
            (db, country, group, update)
            if entry["template"].replace("/", "").lower() == "dw"
            else ("mqa", country, group, update)
        )
        self.identifier = identifier
        self.orig_fields = None
        return identifier

    # @lru_cache()
    def get_identifier_from_auto(self, auto):
        """The identifier is a touple of database, country, group, update"""
        if auto.lower().endswith(".bat"):
            auto = auto.lower().replace(".bat", ".auto")
        if auto in self._cache:
            self.identifier = self._cache[auto]
            self.orig_fields = self._orig_fields_cache[auto]            
            return self._cache[auto]
        if not os.path.exists(auto):
            raise FileNotFoundError(f"Auto file {auto} does not exist.")
            
        template_parameters = self.get_template_parameters(auto)
        if (
            "db" not in template_parameters
            or "country" not in template_parameters
            or "group" not in template_parameters
            or "update" not in template_parameters
        ):
            raise ValueError("Auto file does not contain required fields.")
        if template_parameters["TEMPLATE"] == "D/W":
            identifier = (
                template_parameters["db"].lower(),
                template_parameters["country"].lower(),
                template_parameters["group"].lower(),
                template_parameters["update"].lower(),
            )
            orig_fields = (
                "DW",
                template_parameters["db"],
                template_parameters["country"],
                template_parameters["group"],
                template_parameters["update"],
            )
        else:
            identifier = (
                "mqa",
                template_parameters["country"].lower(),
                template_parameters["group"].lower(),
                template_parameters["update"].lower(),
            )            
            orig_fields = (
                "MQA",
                template_parameters["db"],
                template_parameters["country"],
                template_parameters["group"],
                template_parameters["update"],
            )            

        self._cache[auto] = identifier
        self._orig_fields_cache[auto] = orig_fields
        self.identifier = identifier
        self.orig_fields = orig_fields
        return identifier

    def get_template_parameters(self, autoFile):
        autoFileSection = None
        templateParameters = {}

        with open(autoFile, "r", encoding="utf-8", errors="ignore") as f:
            autoFile = f.read().splitlines()
        for index, line in enumerate(autoFile):
            line = line.strip()
            if "TEMPLATE" in line and "=" in line:
                param, value = line.split("=")
                templateParameters["TEMPLATE"] = value.strip()
            if "template parameters" in line.lower():
                autoFileSection = "params"
                continue
            if "update commands" in line.lower():
                autoFileSection = "cmds"
                continue
            if autoFileSection == "params":
                if "=" in line:
                    param, value = [i.strip() for i in line.split("=", 1)]
                    templateParameters[param] = value

        return templateParameters


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
    ):
        self.dw_assignments = dw_assignments
        self.mqa_assignments = mqa_assignments
        self.dw_assignments_custom = dw_assignments_custom
        self.mqa_assignments_custom = mqa_assignments_custom
        self.dw_assignments, self.mqa_assignments = self.get_assignment_dicts(
            dw_assignments, mqa_assignments
        )
        self.custom_assignments = self.get_custom_assignments(
            dw_assignments_custom, mqa_assignments_custom
        )
        self._assignment_dict = dict()

    def assign(self, identifier_object: Any, attach: bool = False) -> Union[None, dict]:
        """
        Assigns to certain EDM and Team given an identifier object.

        Parameters
        ----------
        identifier_object : value
            An identifier object could be a tuple representing a single
            identifier, an iterable of identifiers, a dictionary or
            iterable of dictionaries which keys are tuple identifiers,
            a dictionary or iterable of dictionaries which one of the keys
            is "identifier", a dictionary or iterable of dictionaries which
            has the following keys: "database", "country", "group", "update",
            "template".
        attach : bool (Optional, default = False)
            if False, it will assign the identifier/identifiers and add to
            existing assignments. Returns the results of the current assignment
            if True, it will attach assignments to the input object and
            return the object with assignments attached. This is only
            possible when the input object is a dictionary or iterable
            of dictionaries and it does not have only 1 key.
        """
        identifier_object = copy.deepcopy(identifier_object)
        assignment_func, iterable, idtype = self.get_assignment_func(identifier_object)
        new_assignments = {}
        if iterable == "list":
            for index, identifier in enumerate(identifier_object):
                a = assignment_func(identifier)
                new_assignments.update(a)
                if attach:
                    identifier_object[index].update(a[list(a.keys())[0]])
        elif iterable == "dict":
            for key, dict_ in identifier_object.items():
                identifier = key if idtype == 5 else dict_
                a = assignment_func(identifier)
                new_assignments.update(a)
                if attach:
                    identifier_object[key].update(a[list(a.keys())[0]])
        else:
            a = assignment_func(identifier_object)
            new_assignments.update(a)
            if attach:
                identifier_object[index].update(a[list(a.keys())[0]])
        return identifier_object if attach else new_assignments

    def get_assignment_func(self, identifier_object: Any) -> int:
        """
        Finds the type of the identifier_object

        Parameters
        ----------
        identifier_object : Any
            An identifier object could be a tuple representing a single
            identifier, an iterable of identifiers, a dictionary or
            iterable of dictionaries which keys are tuple identifiers,
            a dictionary or iterable of dictionaries which one of the keys
            is "identifier", a dictionary or iterable of dictionaries which
            has the following keys: "database", "country", "group", "update",
            "template".

        Returns
        ----------
        Assignment function, iterable (bool), type of identifier object

        Identifier object types:
        1: Identifier is a single tuple
        2: Dict with single key of tuple identifier
        3: Dict with more than 1 key, which one of the keys is "identifier"
        4: Dict with more than one key. Does not has a "identifier" key
           Has keys: "database", "country", "group", "update", "template"
        """
        if not isinstance(identifier_object, (tuple, dict)) and isinstance(
            identifier_object, Iterable
        ):
            iterable = "list"
            identifier_object = identifier_object[0]

        elif (
            isinstance(identifier_object, dict)
            and len(identifier_object.keys()) > 1
            and isinstance(list(identifier_object.values())[0], dict)
        ):
            iterable = "dict"
            if isinstance(list(identifier_object.keys())[0], tuple):
                identifier_object = list(identifier_object.keys())[0]
            else:
                identifier_object = list(identifier_object.values())[0]
        else:
            iterable = "none"
        if not isinstance(identifier_object, (tuple, dict)):
            raise TypeError(
                f"Identifier object input cannot be of type {type(identifier_object)}"
            )
        if isinstance(identifier_object, tuple):

            def assignment_func(identifier_object):
                return self.assign_identifier(identifier_object)

            idtype = 5 if iterable == "dict" else 1
            return assignment_func, iterable, idtype

        # type will be dict

        if len(identifier_object.keys()) == 1:

            def assignment_func(identifier_object):
                identifier = list(identifier_object.keys())[0]
                return self.assign_identifier(identifier)

            return assignment_func, iterable, 2
        else:
            if "identifier" in identifier_object.keys():

                def assignment_func(identifier_object):
                    identifier = identifier_object["identifier"]
                    return self.assign_identifier(identifier)

                return assignment_func, iterable, 3
            elif all(
                i in identifier_object.keys()
                for i in ["database", "country", "group", "update", "template"]
            ):

                def assignment_func(identifier_object):
                    identify = Identifier()
                    identifier = identify.identify(identifier_object, objtype="entry")
                    return self.assign_identifier(identifier)

                return assignment_func, iterable, 4

            else:
                raise ValueError("Idnetifier could not be found in input object.")

    def assign_identifier(self, identifier: tuple):
        """Returns the main team, team and EDM for identifier"""
        dw_assignments = self.dw_assignments
        mqa_assignments = self.mqa_assignments
        custom_assignments = self.custom_assignments
        main_teams = {}
        for struct in config.items("teamstruct"):
            main_team, teams = struct
            for team in teams.split(","):
                main_teams[team.strip()] = main_team
        if not isinstance(identifier, tuple):
            raise TypeError(
                f'Identifier "{identifier}" of wrong type {type(identifier)}'
            )
        if len(identifier) != 4:
            raise ValueError("Identifier has to be a tuple of length 4.")

        if identifier in custom_assignments:
            team = custom_assignments[identifier]["team"]
            edm = custom_assignments[identifier]["edm"]
            main_team = "unassigned" if team not in main_teams else main_teams[team]
            result = {
                "main_team": main_team,
                "team": team,
                "edm": edm,
            }
            self._assignment_dict[identifier] = result
            return {identifier: result}

        database, country, group, update = identifier
        if database == "mqa":
            dbctry = country.lower()
            assignment_dict = mqa_assignments
        else:
            dbctry = database.lower()
            assignment_dict = dw_assignments

        if dbctry not in assignment_dict:
            result = {
                "main_team": "unassigned",
                "team": "unassigned",
                "edm": "unassigned",
            }
            self._assignment_dict[identifier] = result
            return {identifier: result}

        edm = assignment_dict[dbctry]["edm"]

        if edm == "bygroup":
            if group:
                group = group.split(",")[0].strip().lower()
            else:
                result = {
                    "main_team": "unassigned",
                    "team": "unassigned",
                    "edm": "unassigned",
                }
                self._assignment_dict[identifier] = result
                return {identifier: result}
            if group not in dw_assignments[dbctry]:
                result = {
                    "main_team": "unassigned",
                    "team": "unassigned",
                    "edm": "unassigned",
                }
                self._assignment_dict[identifier] = result
                return {identifier: result}
            edm = dw_assignments[dbctry][group]["edm"]
            team = dw_assignments[dbctry][group]["team"]
            main_team = "unassigned" if team not in main_teams else main_teams[team]
        else:
            team = assignment_dict[dbctry]["team"]
            main_team = "unassigned" if team not in main_teams else main_teams[team]

        if not team:
            team = "unassigned"
        if not edm:
            edm = "unassigned"

        result = {
            "main_team": main_team,
            "team": team,
            "edm": edm,
        }
        self._assignment_dict[identifier] = result
        return {identifier: result}

    def attach_to(self, entries: Union[dict, Iterable]) -> Union[dict, Iterable]:
        """
        Attaches assignments to a dictionary or itearable of dictionaries.
        """
        identify = Identifier()
        _, iterable, idtype = self.get_assignment_func(entries)
        if idtype < 3:
            raise TypeError(
                f"Assignments cannot be attached to object of type {type(entries)}"
            )
        if iterable == "list":
            for index, entry in enumerate(entries):
                identifier = identify.identify(entry, objtype="entry")
                if identifier in self._assignment_dict:
                    entries[index].update(self._assignment_dict[identifier])
                else:
                    warnings.warn(
                        "Identifier for some entries not found in current assignments. "
                        "Some entries not Assigned.",
                        stacklevel=2,
                    )
        elif iterable == "dict":
            for key, dict_ in entries.items():
                identifier = key if idtype == 5 else identify.identify(dict_, objtype="entry")
                if identifier in self._assignment_dict:
                    entries[key].update(self._assignment_dict[identifier])
                else:
                    warnings.warn(
                        "Identifier for some entries not found in current assignments. "
                        "Some entries not Assigned.",
                        stacklevel=2,
                    )
        else:
            identifier = identify.identify(entries, objtype="entry")
            if identifier in self._assignment_dict:
                entries.update(self._assignment_dict[identifier])
            else:
                warnings.warn(
                    "Identifier for some entries not found in current assignments. "
                    "Some entries not Assigned.",
                    stacklevel=2,
                )
        return entries

    def get_all(self):
        return self._assignment_dict

    def get(self, identifier: tuple, fallback="notsetfallback") -> dict:
        if identifier not in self._assignment_dict:
            if fallback == "notsetfallback":
                raise KeyError(f"Identifier {identifier} not found.")
            return fallback
        return self._assignment_dict[identifier]

    @staticmethod
    def get_assignment_dicts(
        dw_csv="f:\\automation\\stats\\assignments\\dw.csv",
        mqa_csv="f:\\automation\\stats\\assignments\\mqa.csv",
    ):
        for csvfl in [dw_csv, mqa_csv]:
            if not os.path.exists(csvfl):
                print(f"{csvfl} does not exist.")
                sys.exit(1)

        dw_assignments = {}
        dw_teams = {}
        with open(dw_csv, "r") as f:
            lines = list(csv.reader(f))
        for line in lines[1:]:
            edm, team = line[4].lower(), line[5].lower()
            if edm.strip():
                dw_teams[edm] = team
        for line in lines[1:]:
            db, team, edm = line[0].lower(), line[1].lower(), line[2].lower()
            dw_assignments[db] = {
                "team": team,
                "edm": edm,
            }
            if edm == "bygroup":
                grp_lists = glob.glob(f"f:\\{db}\\qa\\grplist\\*manage.lst")
                for grp_list in grp_lists:
                    edm = grp_list.split("_")[1].strip().lower()
                    team = "unassigned" if edm not in dw_teams else dw_teams[edm]
                    with open(grp_list, "r") as f:
                        groups = [
                            i.strip().lower()
                            for i in f.read().splitlines()
                            if i.strip()
                        ]
                    for grp in groups:
                        dw_assignments[db][grp] = {"team": team, "edm": edm}

        mqa_assignments = {}
        with open(mqa_csv, "r") as f:
            lines = list(csv.reader(f))
        for line in lines[1:]:
            db, team, edm = line[0].lower(), line[1].lower(), line[2].lower()
            mqa_assignments[db] = {
                "team": team,
                "edm": edm,
            }

        return dw_assignments, mqa_assignments

    @staticmethod
    def get_custom_assignments(
        custom_dw="f:\\automation\\stats\\assignments\\dw_custom.csv",
        custom_mqa="f:\\automation\\stats\\assignments\\mqa_custom.csv",
    ):
        custom_assignments = {}
        for index, csvfl in enumerate([custom_mqa, custom_dw]):
            if not os.path.exists(csvfl):
                print(f"{csvfl} does not exist.")
                sys.exit(1)

            with open(csvfl, "r") as f:
                lines = list(csv.reader(f))

            for line in lines[1:]:
                if index == 0:
                    identifier = (
                        "mqa",
                        line[0].lower(),
                        line[1].lower(),
                        line[2].lower(),
                    )
                    team = line[3].lower()
                    edm = line[4].lower()
                else:
                    identifier = (
                        line[0].lower(),
                        line[1].lower(),
                        line[2].lower(),
                        line[3].lower(),
                    )
                    team = line[4].lower()
                    edm = line[5].lower()

                if not edm:
                    edm = "unassigned"
                if not team:
                    team = "unassigned"
                custom_assignments[identifier] = {
                    "team": team,
                    "edm": edm,
                }

        return custom_assignments


class LogParser:
    """
    Parses the RunAuto log file. It can group by id and add event summary fields.

    Parameters
    ----------
    numdays : int (Optional)
        number of days you want to retrieve from logs. By default will retrieve
        last 30 days
    logfile : str (Optional)
        Path to the log file.
        default f:\\automation\\logs\\runauto.log
    """

    def __init__(self, logfile: str = "f:\\automation\\logging\\runauto.log"):
        self.logfile = logfile
        self.numdays = None
        self.start_date = None  # general start date from all parsing
        self.end_date = None  # general end date from all parsing
        self.raw_fieldnames = None
        self._logs = list()
        self._logs_hashed = set()
        self._new_record_parsed = False
        self._new_record_by_event_id = False
        self.current_view = None
        self.summarized = False
        self._df = None
        self._logs_by_line = list()
        self._logs_by_event_id = dict()
        self._logs_by_identifier = dict()
        self._server_names = ["test_dbm", "Az-AppSrv5-Svc", "Az-AutoSrv1-Svc"]
        self._templ_param_cache = dict()

    def parse(
        self, numdays: int = 30, start_date: str = None, end_date: str = None
    ) -> None:
        self.current_view = "raw"
        self._new_record_parsed = True
        self._df = None
        start_date, end_date = self.get_date_range(numdays, start_date, end_date)
        logs_to_parse = self.get_logs_to_parse(start_date, end_date)
        for index, logfile in enumerate(logs_to_parse):
            check_start = index == 0
            check_end = all([index + 1 == len(logs_to_parse), end_date])
            self.parse_logfile(logfile, check_start, check_end, start_date, end_date)
        self._logs = self._logs_by_line.copy()

    def groupby(
        self,
        by: str,
        summarize: bool = True,
        exclude_manual: bool = True,
        exclude_ddrive_autos: bool = True,
        split_externals=False
    ) -> None:
        by = by.lower()
        if by not in ["eventid", "identifier"]:
            raise ValueError('Groupby can be by "eventid" or "identifier"')
        self._df = None
        if by == "eventid":
            self._group_by_event_id(summarize=summarize, split_externals=split_externals)
        if by == "identifier":
            self._group_by_event_id(summarize=True, split_externals=split_externals)
            self._group_by_identifier(
                summarize=summarize,
                exclude_manual=exclude_manual,
                exclude_ddrive_autos=exclude_ddrive_autos,
            )

    def to_dict(self):
        return self._logs

    def to_df(self, *args, **kwargs):
        if self._df is None:
            orient = "columns" if self.current_view == "raw" else "index"
            self._df = pd.DataFrame.from_dict(
                self._logs, orient=orient, *args, **kwargs
            )
        return self._df

    def to_csv(
        self, filename, sortby: list = [], ascending: bool = True, *args, **kwargs
    ):
        df = self.to_df()
        if sortby:
            df = df.sort_values(by=sortby, ascending=ascending)
        df.to_csv(filename, *args, **kwargs)
        logger.info(f"Saved to {filename}")

    def to_excel(
        self, filename, sortby: list = [], ascending: bool = True, *args, **kwargs
    ):
        df = self.to_df()
        if sortby:
            df = df.sort_values(by=sortby, ascending=ascending)
        df.to_excel(filename, *args, **kwargs)

    def get_fieldnames(self):
        if self.current_view == "raw":
            return list(self._logs[0].keys())
        return list(list(self._logs.values())[0].keys())

    def get_date_range(self, numdays: int, start_date: str, end_date: str) -> None:
        if start_date:
            if not re.match(r"^\d{4}-\d{2}-\d{2}$", start_date):
                print('Start Date should be in "YYYY-MM-DD" format.')
                sys.exit(1)
            self.start_date = (
                start_date
                if (not self.start_date or start_date < self.start_date)
                else self.start_date
            )
        else:
            if end_date:
                if not re.match(r"^\d{4}-\d{2}-\d{2}$", end_date):
                    print('End Date should be in "YYYY-MM-DD" format.')
                    sys.exit(1)
                self.end_date = (
                    end_date
                    if (not self.end_date or end_date > self.end_date)
                    else self.end_date
                )
                dt_end_date = datetime.strptime(end_date, "%Y-%m-%d")
            else:
                dt_end_date = datetime.today()
                self.end_date = dt_end_date.strftime("%Y-%m-%d")
            start_date = (dt_end_date - timedelta(numdays)).strftime("%Y-%m-%d")
            self.start_date = (
                start_date
                if (not self.start_date or start_date < self.start_date)
                else self.start_date
            )
        return start_date, end_date

    def get_logs_to_parse(self, start_date, end_date) -> list:
        """Determine the backups we will use depending on history"""
        logfiles = []
        backups = [self.logfile] + glob.glob(f"{self.logfile}.?")
        for logfile in backups:
            with open(logfile, "r", encoding="utf-8") as f:
                if not self.raw_fieldnames:
                    self.raw_fieldnames = [i.strip() for i in next(f).split("|")]
                    next(f)
                else:
                    [next(f) for _ in range(2)]
                log_start_date = next(f).split()[0]
            if not end_date or end_date >= log_start_date:
                logfiles.append(logfile.lower())
            if log_start_date < start_date:
                return sorted(logfiles, reverse=True)
        return sorted(logfiles, reverse=True)

    def parse_logfile(self, logfile, check_start, check_end, start_date, end_date):
        logger.debug(f"Parsing {logfile}")
        with open(logfile, "r") as f:
            [next(f) for _ in range(2)]
            loglines = csv.DictReader(
                f, fieldnames=self._format_fieldnames(), restval="", delimiter="|"
            )

            for entry in loglines:
                try:
                    fmt_entry = self.format_log_entry(entry)
                except:
                    logger.warning(
                        f"Failed to parse line: [Event ID {entry['event_id'].strip()}]"
                        f" [Message {entry['message'].strip()}]"
                    )
                    continue
                else:
                    inrange, check_start, check_end = self._is_event_in_range(
                        fmt_entry, check_start, check_end, start_date, end_date
                    )
                    if check_end == "break":
                        break
                    if inrange:
                        line_id = (
                            fmt_entry["event_id"],
                            fmt_entry["time"],
                            fmt_entry["message"],
                        )
                        if line_id not in self._logs_hashed:
                            self._logs_by_line.append(fmt_entry)
                            self._logs_hashed.add(line_id)

    def _group_by_identifier(
        self, summarize=True, exclude_manual=True, exclude_ddrive_autos=True
    ):
        # TODO: Check if settings for exclud_manual and
        # exclude_ddrive_autos has changed
        self.current_view = "by_identifier"
        logger.info("Grouping by identifier.")
        if not self._new_record_by_event_id and summarize == self.summarized:
            logger.debug("Grouping by identifier. No new logs parsed and same summary.")
            return

        logger.debug(
            f"Grouping by identifier. New records: {self._new_record_by_event_id}. Diff"
            f" summary: {summarize != self.summarized}"
        )

        self._new_record_by_event_id = False
        self.summarized = summarize

        if not self._logs_by_event_id:
            warnings.warn(
                "No logs found",
                stacklevel=2,
            )
            return

        events = {}

        skip_modes = {"Testing"}
        identify = Identifier()
        for event_id, event in self._logs_by_event_id.items():
            if exclude_manual:
                skip_modes.add("Manual")
            if event["runmode"] in skip_modes:
                continue
            if exclude_ddrive_autos:
                if event["auto"].lower().startswith("d:"):
                    continue
            try:
                identifier = identify.identify(event["auto"], objtype="auto")
                # We get the fields from the auto file instead of the log file.
                # This is more reliable.
                template, database, country, group, update = identify.orig_fields
            except:
                logger.debug(f"Finding identifier for {event['auto']} failed.")
                identifier = identify.identify(event, objtype="entry")
                template, database, country, group, update = event["template"].replace("/", ""), event["database"], event["country"], event["group"], event["update"]
            if identifier not in events:
                events[identifier] = {
                    "template": template,
                    "database": database,
                    "country": country,
                    "group": group,
                    "update": update,
                    # last kept
                    "auto": event["auto"],
                    "thresholds": event["thresholds"],
                    "runmode": event["runmode"],
                    "event_id": event["event_id"],
                    # all kept
                    "datetimes": [f"{event['date']} {event['time']}"],
                    "locations": [event["location"]],
                    "runtimes": [event["runtime"]],
                    "errors": [event["outcome"]],
                }
            else:
                events[identifier]["thresholds"] = event["thresholds"]
                events[identifier]["runmode"] = event["runmode"]
                events[identifier]["auto"] = event["auto"]
                events[identifier]["event_id"] = event["event_id"]

                events[identifier]["datetimes"].append(
                    f"{event['date']} {event['time']}"
                )
                events[identifier]["locations"].append(event["location"])
                events[identifier]["runtimes"].append(event["runtime"])
                events[identifier]["errors"].append(event["outcome"])

        if summarize:
            for identifier, event in events.items():
                events[identifier]["datemin"] = events[identifier]["datetimes"][0]
                events[identifier]["datemax"] = events[identifier]["datetimes"][-1]
                server_trigger_count = sum(
                    [
                        events[identifier]["locations"].count(i)
                        for i in self._server_names
                    ]
                )
                total_trigger_count = len(events[identifier]["locations"])
                local_trigger_count = total_trigger_count - server_trigger_count
                events[identifier]["local_trigger_pct"] = round(
                    100 * local_trigger_count / total_trigger_count, 2
                )
                events[identifier]["server_trigger_pct"] = round(
                    100 * server_trigger_count / total_trigger_count, 2
                )
                events[identifier]["avg_runtime"] = round(
                    sum(events[identifier]["runtimes"])
                    / len(events[identifier]["runtimes"])
                )
                events[identifier]["trigger_count"] = total_trigger_count
                ok = events[identifier]["errors"].count("OK")
                ok_partial = events[identifier]["errors"].count("OK: Partially Updated")
                errors_data_not_out = events[identifier]["errors"].count(
                    "Errors: Data Not Out"
                )
                errors_exception = events[identifier]["errors"].count(
                    "Errors: Exception"
                )
                errors_incopmlete = events[identifier]["errors"].count(
                    "Errors: Incomplete Update"
                )
                errors_qa = events[identifier]["errors"].count("Errors: QA")
                errors_retrieval = events[identifier]["errors"].count(
                    "Errors: Retreival"
                )
                events[identifier]["ok"] = round(100 * ok / total_trigger_count, 2)
                events[identifier]["ok_partial"] = round(
                    100 * ok_partial / total_trigger_count, 2
                )
                events[identifier]["errors_data_not_out"] = round(
                    100 * errors_data_not_out / total_trigger_count, 2
                )
                events[identifier]["errors_exception"] = round(
                    100 * errors_exception / total_trigger_count, 2
                )
                events[identifier]["errors_incopmlete"] = round(
                    100 * errors_incopmlete / total_trigger_count, 2
                )
                events[identifier]["errors_qa"] = round(
                    100 * errors_qa / total_trigger_count, 2
                )
                events[identifier]["errors_retrieval"] = round(
                    100 * errors_retrieval / total_trigger_count, 2
                )
                del events[identifier]["datetimes"]
                del events[identifier]["locations"]
                del events[identifier]["runtimes"]
                del events[identifier]["errors"]

        self._logs_by_identifier = events
        self._logs = events

    def _group_by_event_id(self, summarize=True, split_externals=False):
        self.current_view = "by_eventid"

        logger.info("Grouping by event id")

        if not self._new_record_parsed and summarize == self.summarized:
            logger.debug("Grouping by event id. No new logs parsed and same summary.")
            self._logs = self._logs_by_event_id.copy()
            return

        logger.debug(
            f"Grouping by event id. New records: {self._new_record_parsed}. Diff"
            f" summary: {summarize != self.summarized}"
        )
        if self._new_record_parsed:
            self._new_record_by_event_id = True
        self._new_record_parsed = False
        self.summarized = summarize

        if not self._logs_by_line:
            warnings.warn(
                "No logs found",
                stacklevel=2,
            )
            return

        events = {}
        for entry in self._logs_by_line:
            try:
                dt_date_time = datetime.strptime(
                    f"{entry['date']} {entry['time']}", "%Y-%m-%d %H:%M:%S"
                )
            except ValueError:
                logger.warning(
                    "Failed to create datetime: [Event ID"
                    f" {entry['event_id']} [DateTime str"
                    f" {entry['date']} {entry['time']}]]"
                )
                continue
            if entry["event_id"] not in events:
                events[entry["event_id"]] = {
                    "template": entry["template"],
                    "database": entry["database"],
                    "country": entry["country"],
                    "group": entry["group"],
                    "update": entry["update"],
                    "location": entry["location"],
                    "thresholds": entry["thresholds"],
                    "runmode": entry["runmode"],
                    "auto": entry["auto"],
                    "date": entry["date"],
                    "time": entry["time"],
                    "event_id": entry["event_id"],
                    "timestamps": [dt_date_time],
                    "lvlmsg": [{entry["level"]: entry["message"]}],
                }
            else:
                events[entry["event_id"]]["timestamps"].append(dt_date_time)
                events[entry["event_id"]]["lvlmsg"].append(
                    {entry["level"]: entry["message"]}
                )

        if summarize:
            summarized_events = dict()
            for _, event in events.items():
                sevents = self.summarize_event(event, split_externals=split_externals)
                for event_id, sevent in sevents.items(): 
                    summarized_events[event_id] = sevent
            
            self._logs_by_event_id = summarized_events
            self._logs = summarized_events

        else:
            self._logs_by_event_id = events
            self._logs = events

    def summarize_event(self,
        event, split_externals=False
    ):
        """This function creates summary of the event. It attaches outcome and
        error info to the event, and creates runtime variable from list of 
        timestamps. It removes variables that are lists (lvlmsg and timestamps).

        It has option to split it by external trigger. 
        In that case, each instance of a external auto trigger, will be treated
        as a subevent and summarized events will be created for each instance.
        This will be done by using the error_auto_file
        to determine what auto failed. The external tregers before that were
        therefore successful, otherwise the update would not reach that section.
        The event id for subevents will be event_id-external{i} where 1 is
        added to i for each subevent.
        """
        outcome, error_message, error_auto_file, error_auto_section = self.get_event_outcome(event["lvlmsg"])
        base_event_id = event["event_id"]
        # Event to be treated as one or event contains only one external triggers
        if not split_externals or (error_auto_file and event["auto"].lower() == error_auto_file.lower()):
            # The failure occured in the first external trigger
            # the event cannot be split and contains only one
            # external triger
            base_event = {
                key: val
                for key, val in event.items()
                if key not in ["lvlmsg", "timestamps"]
            }                 
            base_event["runtime"] = (
                event["timestamps"][-1] - event["timestamps"][0]
            ).total_seconds()
            base_event["outcome"] = outcome
            base_event["error_message"] = error_message
            base_event["error_auto_file"] = error_auto_file
            base_event["error_auto_section"] = error_auto_section

            return {base_event_id: base_event}

        # more than 1 external triggers in the event
        slices = OrderedDict()
        current_auto = event["auto"]
        for tuple_ in zip(event["timestamps"], event["lvlmsg"]):
            timestamp = tuple_[0]
            message = list(tuple_[1].values())[0]  # dont need level
            if "ExternalTrigger" in message:
                current_auto = message.split(":", 1)[1].strip()
            if current_auto not in slices:
                slices[current_auto] = {"timestamps": [], "messages": []}
            slices[current_auto]["timestamps"].append(timestamp)
            slices[current_auto]["messages"].append(message)

        split_events = {}
        base_event = {
            key: val
            for key, val in event.items()
            if key not in ["lvlmsg", "timestamps"]
        }
        # base_event_id = event["event_id"]
        for i, auto in enumerate(slices):
            base_event = {
                key: val
                for key, val in event.items()
                if key not in ["lvlmsg", "timestamps"]
            }            
            event_id = base_event_id if i == 0 else f"{base_event_id}-external{i}"
            # Creating runtime variable from timestamps for the particular
            # external trigger
            timestamps = slices[auto]["timestamps"]
            base_event["runtime"] = (
                timestamps[-1] - timestamps[0]
            ).total_seconds()
            base_event["auto"] = auto
            messages = slices[auto]["messages"]

            if i > 0: # any external trigger that is not the main auto
                base_event["date"] = timestamps[0].strftime("%Y-%m-%d")
                base_event["time"] = timestamps[0].strftime("%H:%M:%S")
                try:
                    template_params = self.get_template_parameters(auto)
                    base_event["database"] = template_params["db"]
                    base_event["country"] = template_params["country"]
                    base_event["group"] = template_params["group"]
                    base_event["update"] = template_params["update"]                    
                except FileNotFoundError:
                    logging.debug(f'Auto file "{auto}" not found.')
                except PermissionError:
                    logger.debug(f"autofile {auto} permission errors.")
                    continue
            if i + 1 == len(slices):
                # last external trigger
                # this means will have the errors from combined event
                base_event["outcome"] = outcome
                base_event["error_message"] = error_message
                base_event["error_auto_file"] = error_auto_file
                base_event["error_auto_section"] = error_auto_section
                split_events[event_id] = base_event
            else:
                # The update for this external trigger was successful
                # Otherwise it would be the last if it errored out
                # All we need to do is determine whether the update was
                # copied up partially or not.
                base_event["outcome"] = (
                    "OK: Partially Updated"
                    if "Did not check off update" in " ".join(messages)
                    else "OK"
                )
                base_event["error_message"] = ""
                base_event["error_auto_file"] = ""
                base_event["error_auto_section"] = ""
                split_events[event_id] = base_event

        return split_events
    
    # @lru_cache()
    def get_template_parameters(self, autoFile):
        if autoFile in self._templ_param_cache:
            return self._templ_param_cache[autoFile]
        autoFileSection = None
        templateParameters = {}

        with open(autoFile, "r", encoding="utf-8", errors="ignore") as f:
            autoFileLines = f.read().splitlines()
        for index, line in enumerate(autoFileLines):
            line = line.strip()
            if "TEMPLATE" in line and "=" in line:
                param, value = line.split("=")
                templateParameters["TEMPLATE"] = value.strip()
            if "template parameters" in line.lower():
                autoFileSection = "params"
                continue
            if "update commands" in line.lower():
                autoFileSection = "cmds"
                continue
            if autoFileSection == "params":
                if "=" in line:
                    param, value = [i.strip() for i in line.split("=", 1)]
                    templateParameters[param] = value

        self._templ_param_cache[autoFile] = templateParameters
        return templateParameters


    def get_event_outcome(self, lvlmsg):
        messages = []
        error_auto_file = None
        error_auto_section = "Main"
        errors = False
        error_type = None
        error_message = None
        for index, log in enumerate(lvlmsg):
            for level, message in log.items():
                messages.append(message)
                if level == "INFO":
                    if "InternalTrigger" in message:
                        if "Copying" in message:
                            error_auto_section = (
                                f"{message.split(':')[1].strip()} - Final Mod"
                            )
                        else:
                            error_auto_section = message.split(":", 1)[1].strip()
                    if "ExternalTrigger" in message:
                        error_auto_file = message.split(":", 1)[1].strip()
                if level == "ERROR":
                    errors = True
                    if "fatal" in message.lower() or "retrieval" in message.lower():
                        error_type = "Errors: Retreival"
                    elif "not out" in message.lower() or "no upd files created" in message.lower():
                        error_type = "Errors: Data Not Out"
                    elif "could not find a calendar entry" in message.lower():
                        error_type = "CalEntry Not Found"
                    else:
                        error_type = "Errors: QA"
                    error_message = message
                if level == "CRITICAL":
                    errors = True
                    error_type = "Errors: Exception"
                    error_message = message
            if index == len(lvlmsg) - 1:
                if not errors:
                    if message != "End of File":
                        errors = True
                        error_type = "Errors: Incomplete Update"
        if not errors:
            if "Did not check off update" in " ".join(messages):
                return "OK: Partially Updated", "", "", ""
            else:
                return "OK", "", "", ""
        return error_type, error_message, error_auto_file, error_auto_section

    # @pysnooper.snoop()
    def _is_event_in_range(
        self, fmt_entry, check_start, check_end, start_date, end_date
    ):
        if not fmt_entry["date"].startswith("202"):
            logger.debug(f"Date [{fmt_entry['date']}] incorrect format. Line skipped.")
            return False, check_start, check_end
        if all([not check_start, not check_end]):
            return True, check_start, check_end
        if check_start:
            if fmt_entry["date"] >= start_date:
                return True, False, check_end
            else:
                return False, check_start, check_end
        if check_end:
            if fmt_entry["date"] <= end_date:
                return True, check_start, check_end
            else:
                return False, check_start, "break"

    def _format_fieldnames(self):
        fieldnames_trans = {
            "tmpl": "template",
            "auto_file": "auto",
            "loc": "location",
        }
        fieldnames = [
            field if field not in fieldnames_trans else fieldnames_trans[field]
            for field in self.raw_fieldnames
        ]
        return fieldnames

    @staticmethod
    def format_log_entry(entry):
        fmt_dict = dict()
        for key, value in entry.items():
            value = value.strip()
            if key == "db_country":
                if "/" in value:
                    fmt_dict["database"] = value.split("/")[0]
                    fmt_dict["country"] = value.split("/", 1)[1]
                else:
                    fmt_dict["database"] = ""
                    fmt_dict["country"] = value
            else:
                fmt_dict[key] = value
        return fmt_dict

class AutomationStatus:
    """
    An automation status object gets and assigns information about the 
    automation status of an identifier. THe automation status is 
    returned as a dictionary with keys:
    1. "autoamated" which is a yes/no variable indicating 
    whether the udpate is automated or not. This includes auto files
    found in WSW in the automation server, email macros in automation
    server and int he batchfile filed of autocalendar.
    2. "trigger", can be email, wsw, autocalendar, batch (triggered
    from another auto file) or na.
    3. "location", can be automated server if the auto file is 
    autocalendar triggered or found in the wsw or outlook macros in
    automation server.

    Parameters
    ----------
    wsw_batches : str (Optional)
        path to the wsw_batches text file.
        default f:\\automation\\stats\\wt_batch_files.txt
        This is the file that contains all the batch/auto files
        that are found to be triggered in WSW of automation server.
        These are retreived regularly through another process and 
        have to be given as an input.
    email_macros : str (Optional)
        path to the email_macros outlook macros.
        default F:\\Automation\\Backup\\Outlook\\Macros
        These are exported macros from Outlook in the automation 
        server. They have to be manually exported regularly.

    """

    def __init__(
        self,
        wsw_batches="f:\\automation\\stats\\wt_batch_files.txt",
        email_macros="F:\\Automation\\Backup\\Outlook\\Macros",            
    ):
        self.wsw_batches = wsw_batches
        self.email_macros = email_macros
        self.view = None
        self.entries = None
        self.auto_status_dict = dict()

    def load_status(self, entries, view="infer"):
        """Gets a identifier status dictionary for all entries.
        
        Parameters
        ----------        
        entries: dict
            These are autocalendar entries that are retrieved through
            the Autocalendar class. They need to be retrieved seperately
            and be provided as an argument.
        view: str (Optional)
            This refers to the entry views under the Autocalendar class
            which can be a list of dictionaries or a dictionary with
            identifier keys and entry dictionary values.
            Possible values are "list", "dict, or "infer" to infer the 
            type from the entry object.
        """
        
        view = view.lower()
        if view not in ["infer", "list", "dict"]:
            raise ValueError(
                'View parameter has to be one of "infer", "list" or "dict"'
            )      

        if view == "infer":
            view = self.infer_view(entries)
        else:
            self.view = view

        self.entries = entries
        wsw_batches = self.wsw_batches
        email_macros = self.email_macros

        # Email auto files
        identify = Identifier()
        for macro in glob.glob(f"{email_macros}\\*.bas"):
            with open(macro, "r") as f:
                lines = f.read().splitlines()
            for line in lines:
                line = line.lower()
                if ("autofilename" in line and "=" in line) or (
                    "batch" in line and "=" in line
                ):
                    auto = line.split("=")[1].strip().replace('"', "")
                    all_auto_files = self._get_external_triggers(auto)
                    # print(auto)
                    for index, auto in enumerate(all_auto_files):
                        try:
                            identifier = identify.identify(auto, objtype="auto")
                        except FileNotFoundError:
                            logger.debug(f"AutoStatusDict: autofile {auto} not found.")
                            continue
                        except ValueError:
                            logger.debug(f"AutoStatusDict: autofile {auto}  does not contain required fields.")
                            continue
                        trigger = "Email" if index == 0 else "Batch"
                        location = "AutoServer"
                        self.auto_status_dict[identifier] = {
                            "automated": "yes",
                            "trigger": trigger,
                            "location": location,
                        }

        # WSW auto files
        with open(wsw_batches, "r") as f:
            lines = [i.strip() for i in f.read().splitlines() if i.strip()]
        for auto in lines:
            all_auto_files = self._get_external_triggers(auto)
            for index, autofile in enumerate(all_auto_files):
                try:
                    identifier = identify.identify(autofile, objtype="auto")
                except FileNotFoundError:
                    logger.debug(f"AutoStatusDict: autofile {auto} not found.")
                    continue  
                except ValueError:
                    logger.debug(f"AutoStatusDict: autofile {auto} value error.")
                    continue
                trigger = "WSW" if index == 0 else "Batch"
                location = "AutoServer"
                self.auto_status_dict[identifier] = {
                    "automated": "yes",
                    "trigger": trigger,
                    "location": location,
                }

        # AT auto files
        trigger_dict = {
            "AT": "Autocal",
            "ET": "Email",
            "WT": "WSW",
            "NA": "NA",
        }

        iterable = entries if view == "list" else entries.values()
        for entry in iterable:
            auto = entry["auto"].lower()
            identifier = identify.identify(entry, objtype="entry")

            if auto and (".bat" in auto or ".auto" in auto):
                trigger = entry["trigger"]
                all_auto_files = self._get_external_triggers(auto)

                if trigger == "AT":
                    location = "AutoServer"
                    for index, autofile in enumerate(all_auto_files):
                        if index > 0:
                            try:
                                identifier = identify.identify(autofile, objtype="auto")
                            except FileNotFoundError:
                                logger.debug(f"AutoStatusDict: autofile {auto} not found.")
                                continue   
                        trigger = "Batch" if index > 0 else "Autocal"
                        self.auto_status_dict[identifier] = {
                            "automated": "yes",
                            "trigger": trigger,
                            "location": location,
                        }

                else:
                    if identifier not in self.auto_status_dict:
                        location = "Local"
                        for index, autofile in enumerate(all_auto_files):
                            if index > 0:
                                try:
                                    identifier = identify.identify(autofile, objtype="auto")
                                except FileNotFoundError:
                                    logger.debug(f"AutoStatusDict: autofile {auto} not found.")
                                    continue      
                                except PermissionError:
                                    logger.debug(f"AutoStatusDict: autofile {auto} permission errors.")
                                    continue
                                except Exception as e:
                                    logger.debug(f"AutoStatusDict: autofile {auto} [{str(e)}].")
                            try:
                                trigger = "Batch" if index > 0 else trigger_dict[trigger]
                            except:
                                trigger = "NA"
                            
                            self.auto_status_dict[identifier] = {
                                "automated": "yes",
                                "trigger": trigger,
                                "location": location,
                            }

            else:
                # conditional due to external triggers, being batch triggered
                # we say the update is not triggered, only when it is not
                # batch triggered. If it is, it would be in the auto_status_dict
                # already. If it is not than we say it is not triggered. If the
                # entry containging the external trigger appears later in the loop
                # it will overwrite this result. So in the end, the batch triggered
                # updates are correctly identified.
                if identifier not in self.auto_status_dict:
                    self.auto_status_dict[identifier] = {
                        "automated": "no",
                        "trigger": "NA",
                        "location": "",
                    }

    def infer_view(self, entries):
        if isinstance(entries, dict):
            # logger.debug('Inferred type "entry"')
            self.view = "dict"
            return "dict"
        if isinstance(entries, list):
            # logger.debug('Inferred type "auto"')
            self.view = "list"
            return "list"
        raise TypeError("Input object has to be a dict, or list of entries.")

    @staticmethod
    def _get_external_triggers(batch):
        # Function to get external triggers from batch files
        queue = [batch]
        all_batches = []
        ext = ".bat" if batch.endswith(".bat") else ".auto"
        sSet = "set" if ext == ".bat" else ""
        while queue:
            next_batch = queue.pop(0)
            all_batches.append(next_batch)
            try:
                with open(next_batch, "r", encoding="utf-8", errors="ignore") as f:
                    lines = [i.lower() for i in f.read().splitlines()]
                external = []
                for line in lines:
                    if (
                        "=" in line
                        and sSet in line
                        and ext in line
                        and "batch" in line
                        and "failbatch" not in line
                    ):
                        external.append(line.split("=")[-1].strip())
                if external:
                    for b in external:
                        queue.append(b)
            except Exception as e:
                # print(e)
                pass
        return all_batches

    def attach_to_entries(self):
        """Attaches the automation status to the entries."""
        if not self.entries:
            warnings.warn(
                "No entries found.",
                stacklevel=2,
            )
            return []
        
        identify = Identifier()
        if self.view == "list":
            new_entries = list()
            for entry in self.entries:
                identifier = identify.identify(entry, objtype="entry")
                for key, val in self.auto_status_dict[identifier].items():
                    entry[key] = val
                new_entries.append(entry)
        elif self.view == "dict":
            new_entries = dict()
            for identifier, entry in self.entries.items():
                for key, val in self.auto_status_dict[identifier].items():
                    entry[key] = val
                new_entries[identifier] = entry
        self.entries = new_entries
        return new_entries


class Autocalendar:
    """
    Connect to autocalendar and retreive all sql entries.
    For DW updates, it will retrieve from edit daily/weekly view.
    For MQA it will retreive all undone entries. Will contain duplicate
    updates.

    Returns
    ----------
    SQL entries.
    """

    def __init__(self):
        self.odbc_driver = None
        self.MDB = None
        self.errorcode = 0
        self.mqa_sql_entries = list()
        self.dw_sql_entries = list()
        self.get_odbc_driver()

    def get_odbc_driver(self):
        drivers = pyodbc.drivers()
        version = 0.0
        latest_driver = None
        for driver in drivers:
            match = re.search("MySQL ODBC (\d+[.]\d+).* Driver", driver)
            if match:
                if float(match[1]) > version:
                    latest_driver = match[0]
                    version = float(match[1])
        if latest_driver:
            self.odbc_driver = latest_driver
        #            return latest_driver
        else:
            print("Unable to find a MySQL ODBC driver. Contact operations.")
            self.ErrorCode = 2

    def connect_to_db(self):
        global con
        global cursor
        odbc_driver = self.odbc_driver
        MDB = f"DRIVER={{{odbc_driver}}};SERVER=10.1.4.6;PORT=3306;DATABASE=autocalendar;UID=autocal;PWD=AutoCal_Pwd"
        con = pyodbc.connect(MDB, ansi=True)
        cursor = con.cursor()
        self.MDB = MDB

    def get_dw(self):
        logger.debug("Getting dw sql entries")
        self.connect_to_db()
        cursor.execute(
            """SELECT *
                        FROM tblcalendar_dw_templates dwt
                        JOIN tblcalendar_countries cnt
                        ON cnt.fdCountryID = dwt.fdCountryID 
                        JOIN tblcalendar_dw_database dwdb
                        ON dwdb.fdDatabaseID = dwt.fdDatabaseID;"""
        )
        entries = cursor.fetchall()
        self.close_connection()
        self.dw_sql_entries = entries
        return entries

    def get_mqa(self):
        logger.debug("Getting dw sql entries")
        self.connect_to_db()
        cursor.execute(
            """SELECT * 
                        FROM tblcalendar_countries countries
                        JOIN tblcalendar_records records
                        ON records.fdCountryID = countries.fdCountryID
                        WHERE fdDone=0;"""
        )
        entries = cursor.fetchall()
        self.close_connection()
        self.mqa_sql_entries = entries
        return entries

    def close_connection(self):
        con.close()

    def parse_entries(self, view="list"):
        """Parses sql entries.
        If view is "list" it will output a list of dictionary entries.
        If view is "dict" it will output a dictionary where the keys
        are identfiers and values are the parsed entries.
        """

        logger.debug("Parsing DW entries.")
        identify = Identifier()
        entries = list() if view == "list" else dict()
        identifiers = set()

        for entry in self.dw_sql_entries:
            entry_dic = {
                "templateID": entry.fdTemplateID,
                "database": "" if not entry.fdDatabaseName else entry.fdDatabaseName,
                "group": "" if not entry.fdGroup else entry.fdGroup,
                "country": "" if not entry.fdCountryName else entry.fdCountryName,
                "update": "" if not entry.fdMessageBoard else entry.fdMessageBoard,
                "time": "" if not entry.fdTime else entry.fdTime.strftime("%H:%M %p"),
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
                "usefuleness": "",
            }
            identifier = identify.identify(entry_dic, objtype="entry")
            if identifier not in identifiers:
                if view == "list":
                    entries.append(entry_dic)
                else:
                    entries[identifier] = entry_dic
                identifiers.add(identifier)

        # Getting unique low frequency entries
        logger.debug("Parsing MQA entries.")

        usefuleness = {}
        for entry in self.mqa_sql_entries:
            entry_dic = {
                "database": "" if not entry.fdDatabase else entry.fdDatabase,
                "group": "" if not entry.fdGroup else entry.fdGroup,
                "country": "" if not entry.fdCountryName else self.format_field(entry.fdCountryName),
                "update": "" if not entry.fdMessageBoard else entry.fdMessageBoard,
                "time": "" if not entry.fdTime else entry.fdTime.strftime("%H:%M %p"),
                "trigger": entry.fdUpdateTrigger,
                "auto": "" if not entry.fdBatchFile else entry.fdBatchFile,
                "priority": entry.fdWCalPriority,
                "assign": "" if not entry.fdAssign else entry.fdAssign,
                "procedures": "" if not entry.fdPressReleaseProc else entry.fdPressReleaseProc,
                "frequency": "" if not entry.fdFrequency else entry.fdFrequency,
                "template": "MQA",
            }
            identifier = identify.identify(entry_dic, objtype="entry")
            if identifier not in identifiers:
                if view == "list":
                    entries.append(entry_dic)
                else:
                    entries[identifier] = entry_dic
                identifiers.add(identifier)

            if identifier not in usefuleness:
                usefuleness[identifier] = []       
            try:
                usefuleness[identifier].append(self.get_usefuleness(entry.fddDate))
            except:
                pass

        print("len entries", len(entries))
        # Attaching usefuleness
        if view == "list":
            for entry_dic in entries:
                identifier = identify.identify(entry_dic, objtype="entry")
                if identifier in usefuleness:
                    entry_dic["usefuleness"] = self.agg_usefuleness(usefuleness[identifier], entry_dic["frequency"])
        else:
            for identifier in entries:
                if identifier in usefuleness:
                    entries[identifier]["usefuleness"] = self.agg_usefuleness(usefuleness[identifier], entry_dic["frequency"])        
        return entries

    def get_dw_freq(self, entry):
        dcount = 0
        dcount += abs(entry.fdFrqSun)
        dcount += abs(entry.fdFrqMon)
        dcount += abs(entry.fdFrqTue)
        dcount += abs(entry.fdFrqWed)
        dcount += abs(entry.fdFrqThu)
        dcount += abs(entry.fdFrqFri)
        dcount += abs(entry.fdFrqSat)
        dcount += 5 * abs(entry.fdFrqDaily)
        if dcount == 1:
            return "W"
        return f"D{dcount}"

    def get_usefuleness(self, dt):
        """EOM, EOM-1, BOM"""
        if dt is None:
            return ""
        if dt.day == 1:
            return "BOM"
        offset = BMonthEnd()
        last_bdate = offset.rollforward(dt).date()
        if dt >= last_bdate:
            return "EOM"
        if dt == last_bdate - timedelta(1):
            return "EOM-1"
        
    def agg_usefuleness(self, useful_list, freq):
        if "EOM" in useful_list or "EOM" in freq:
            return "EOM"
        elif "BOM" in useful_list or "BOM" in freq:
            return "BOM"
        elif "EOM-1" in useful_list:
            return "EOM-1"    
        return ""

    def format_field(self, field):
        fmt_dict = {
            "Czech CWR\r\nCzech Republic CWR\r\nCzech Republic CWR": "Czech CWR"
        }
        if field in fmt_dict:
            return fmt_dict[field]
        return field


