import argparse
import pyodbc
import re
import sys
from datetime import datetime, timedelta
import json
import os
import pandas as pd
import numpy as np

# Convert Excel data to JSON
def excel_to_json(excel_data):
    excel_data_df = pd.read_excel(excel_data, sheet_name='Sheet1') # Puts excel data into pandas dataframe
    actions = []
    for index, row in excel_data_df.iterrows():
        if str(row["holidays (YYYY-MM-DD)"]) == "nan" or str(row["initial"]) == "nan" or row["action"] == "nan": # Skips over the excel rows that have an empty holidays cell, initials cell, or action cell
            continue
        dict_ = {
            key: convert_dates(val) for key, val in dict(row).items() if "Unnamed" not in key
        }
        actions.append(dict_)
    with open(r'F:\automation\holidays\holidays.json', 'w') as json_file:                   # Loads that non-skipped data from excel into a json
        try:
            json.dump(actions, json_file, cls=CustomEncoder)
            print('EDM.XLSM converted to F:\automation\holidays\holidays.json!')
        except Exception as e:
            print(e)
            print('Check date format in EDM.XLSM!') 
    return actions 
def convert_dates(val):                                                                 # Converts excel date to YYYY-MM-DD format
    if isinstance(val, pd._libs.tslibs.timestamps.Timestamp):
        return val.strftime("%Y-%m-%d") 
    else:
        return val        
def readjson():                                                           # Reads JSON file that contains instructions for what changes to be made to autocalendar entries due to holidays
    f = open(r'F:\automation\holidays\holidays.json')
    data = json.load(f)
    f.close()
    return data
    
# Connect to Autocalendar data
def get_odbc_driver():                                                        # Connects to driver to use SQL for editing autocalendar
    drivers = pyodbc.drivers()
    version = 0.0
    latest_driver = None
    for driver in drivers:
        match = re.search('MySQL ODBC (\d+[.]\d+).* Driver', driver)
        if match:
            if float(match[1]) > version:
                latest_driver = match[0]
                version = float(match[1])
    if latest_driver:
        return latest_driver
    print('Unable to find a MySQL ODBC driver. Contact operations.')
    sys.exit(1)    
def next_day(date):                                   # Function that defines what the next weekday is
    datestamp = datetime.now().strftime('%Y-%m-%d')
    timestamp = datetime.now().strftime('%H:%M:%S')
    date = datetime.strptime(date, "%Y-%m-%d")
    if date.weekday() == 4:
        date = date + timedelta(days=3)
    else:
        date = date + timedelta(days=1)
    return date
def prev_day(date):                                   # Function that defines what the previous weekday is
    datestamp = datetime.now().strftime('%Y-%m-%d')
    timestamp = datetime.now().strftime('%H:%M:%S')
    date = datetime.strptime(date, "%Y-%m-%d") 
    if date.weekday() == 0:
        date = date - timedelta(days=3)
    else:
        date = date - timedelta(days=1)
    return date
def connect_to_db(MDB):                                             # Connects to autocalendar server to be able to make changes to autocalendar
    global con
    global cursor
    con = pyodbc.connect(MDB, ansi=True)
    cursor = con.cursor()
def log_notfound(database, country, group, update):                                     # Records specifically when entry was not found
    try:
        cwd = os.getcwd()
        username = os.getlogin()
        with open(r'd:\python\holiday_fails.txt', 'a') as f:
            f.write(f'{datestamp.ljust(8)} | {timestamp.ljust(8)} | Record Not Found      | {database.ljust(10)} |  {country.ljust(8)} | {group.ljust(8)} |  {update.ljust(50)} | {username}\n')
    except:
        pass        
def find_record(database, country, group, update, date):           # Finds specific autocalendar entry using SQL
    cursor.execute('''SELECT *
                   FROM tblcalendar_dw_templates dwt
                   JOIN tblcalendar_countries cnt
                   ON cnt.fdCountryID = dwt.fdCountryID 
                   JOIN tblcalendar_dw_records dwr
                   ON dwt.fdTemplateID = dwr.fdTemplateID
                   JOIN tblcalendar_dw_database dwdb
                   ON dwdb.fdDatabaseID = dwt.fdDatabaseID
                   WHERE fdDone=0 AND fdDatabaseName=? AND fdCountryName=? AND fdGroup=? AND fdMessageBoard=? AND fddDate2Show = ?;''', (database, country, group, update, date))    
    notDoneEntries = cursor.fetchall()
    if not notDoneEntries:
        con.close
        log_notfound(database, country, group, update)
        return None, None
    notDoneEntries.sort(key=lambda entry: entry.fddDate2Show)
    desc = [i[0] for i in cursor.description]
    return notDoneEntries[0], dict(zip(desc, notDoneEntries[0]))
    
# The various possible commands
def format_note(old_note, new_note, separator=' | '): # Formats the note left of autocalendar to account for if there is already a note from R2D2
    split_note  = old_note.split(separator)
    notes = []
    for note in split_note:
        note = note.strip()
        if note[:4] != 'R2D2':
            notes.append(note)
    notes.append(new_note)
    return separator.join(notes)     
def write_note(record, note, initial):                # Leaves a note on the autocalendar record that includes the user's initial
    note = initial + " - " + note
    if record.fdNotes != None:
        note = format_note(record.fdNotes, note)[:200]
    cursor.execute('UPDATE tblcalendar_dw_records SET fdNotes=? WHERE fdRecID=?;', (note, record.fdRecID))
    con.commit()
    con.close
def mark_done(record, initial):                       # Marks off the record using the user's initials as well as the time and date it was marked off. Records a log of when the record was checked off or if there was an error and why
    datestamp = datetime.now().strftime('%Y-%m-%d')
    timestamp = datetime.now().strftime('%H:%M:%S')
    try:
        note = 'Checked off by autocal.py'
        write_note(record, note, initial)
        cursor.execute('UPDATE tblcalendar_dw_records SET fdInitials=?, fdDone=-1, fdDoneDate=NOW() WHERE fdRecID=?;', (initial, record.fdRecID))
        con.commit()
        print(f"check off {record.fdDatabaseName, record.fdGroup, record.fdMessageBoard} for {record.fddDate2Show} successful!")
        with open(r'F:\automation\holidays\holiday_success.log', 'a') as f:
            f.write(f'{datestamp.ljust(8)} | {timestamp.ljust(8)} | Successfully marked off {record.fddDate2Show} for {date}                                   | {database.ljust(10)} |  {country.ljust(8)} | {group.ljust(8)} |  {update.ljust(50)} | {username}\n')
    except Exception as e:
        errorcount += 1
        print(f'*****ERROR*****: Unable to mark off {database, group, update} for {date} because {e}. Error number {errorcount} in this run')
        with open(r'F:\automation\holidays\holiday_fails.log', 'a') as f:
            f.write(f'{datestamp.ljust(8)} | {timestamp.ljust(8)} | Failed to mark off {record.fddDate2Show} for {date} because {e}                             | {database.ljust(10)} |  {country.ljust(8)} | {group.ljust(8)} |  {update.ljust(50)} | {username}\n')
    con.close        
def move_update_specified_date(moveto_date, record, initial):                 # Moves record to another specified date and records a log of this or if there was an error in attempting this
    datestamp = datetime.now().strftime('%Y-%m-%d')
    timestamp = datetime.now().strftime('%H:%M:%S')
    try:
        note = 'Moved by autocalhol.py'
        write_note(record, note, initial)
        cursor.execute('UPDATE tblcalendar_dw_records SET fddDate2Show=? WHERE fdRecID=?;', (moveto_date, record.fdRecID))
        con.commit()
        print(f"move {record.fdDatabaseName, record.fdGroup, record.fdMessageBoard} for {date} to {moveto_date} successful!")
        with open(r'F:\automation\holidays\holiday_success.log', 'a') as f:
            f.write(f'{datestamp.ljust(8)} | {timestamp.ljust(8)} | Successfully moved from {record.fddDate2Show} to {moveto_date}                   | {database.ljust(10)} |  {country.ljust(8)} | {group.ljust(8)} |  {update.ljust(50)} | {username}\n') 
    except Exception as e:
        errorcount += 1
        print(f'*****ERROR*****: Unable to move {database, group, update} for {date} to {moveto_date} because {e}. Error number {errorcount} in this run')
        with open(r'F:\automation\holidays\holiday_fails.log', 'a') as f:
            f.write(f'{datestamp.ljust(8)} | {timestamp.ljust(8)} | Failed to move from {record.fddDate2Show} to {moveto_date}  because {e}          | {database.ljust(10)} |  {country.ljust(8)} | {group.ljust(8)} |  {update.ljust(50)} | {username}\n')
    con.close       
def move_update_plusone(record, initial):                     # Changes date of record to the next weekday
    datestamp = datetime.now().strftime('%Y-%m-%d')
    timestamp = datetime.now().strftime('%H:%M:%S')
    try:
        note = 'Moved by autocalhol.py'
        write_note(record, note, initial)
        cursor.execute('UPDATE tblcalendar_dw_records SET fddDate2Show=? WHERE fdRecID=?;', (next_day(date), record.fdRecID))
        con.commit()
        print(f"move {record.fdDatabaseName, record.fdGroup, record.fdMessageBoard} for {date} to next day successful!")
        with open(r'F:\automation\holidays\holiday_success.log', 'a') as f:
            f.write(f'{datestamp.ljust(8)} | {timestamp.ljust(8)} | Successfully moved from {record.fddDate2Show} to the next day                    | {database.ljust(10)} |  {country.ljust(8)} | {group.ljust(8)} |  {update.ljust(50)} | {username}\n')
    except Exception as e:
        errorcount += 1
        print(f'*****ERROR*****: Unable to move {database, group, update} for {date} to next day because {e}. Error number {errorcount} in this run')
        with open(r'F:\automation\holidays\holiday_fails.log', 'a') as f:
            f.write(f'{datestamp.ljust(8)} | {timestamp.ljust(8)} | Failed to move from {record.fddDate2Show} to the next day  because {e}           | {database.ljust(10)} |  {country.ljust(8)} | {group.ljust(8)} |  {update.ljust(50)} | {username}\n')
    con.close 
def move_update_minusone(record, initial):                    # Changes date of record to the previous weekday
    datestamp = datetime.now().strftime('%Y-%m-%d')
    timestamp = datetime.now().strftime('%H:%M:%S')
    try:
        note = f'Moved by autocalhol.py'
        write_note(record, note, initial)
        cursor.execute('UPDATE tblcalendar_dw_records SET fddDate2Show=? WHERE fdRecID=?;', (prev_day(date), record.fdRecID))
        con.commit()
        print(f"move {record.fdDatabaseName, record.fdGroup, record.fdMessageBoard} for {date} to previous day successful!")
        with open(r'F:\automation\holidays\holiday_success.log', 'a') as f:
            f.write(f'{datestamp.ljust(8)} | {timestamp.ljust(8)} | Successfully moved from {record.fddDate2Show} to the previous day                | {database.ljust(10)} |  {country.ljust(8)} | {group.ljust(8)} |  {update.ljust(50)} | {username}\n')
    except Exception as e:
        errorcount += 1
        print(f'*****ERROR*****: Unable to move {database, group, update} for {date} to previous day because {e}. Error number {errorcount} in this run')
        with open(r'F:\automation\holidays\holiday_fails.log', 'a') as f:
            f.write(f'{datestamp.ljust(8)} | {timestamp.ljust(8)} | Failed to move from {record.fddDate2Show} to the previous day  because {e}       | {database.ljust(10)} |  {country.ljust(8)} | {group.ljust(8)} |  {update.ljust(50)} | {username}\n')
    con.close

# Append what was actually run to master.json        
def append_master_json(new_data, filename=r'F:\automation\holidays\master.json'):
    try:
        with open(filename, 'r') as file:
            data = json.load(file)
        data.append(new_data)
        with open(filename, 'w') as file:
            json.dump(data, file, cls=CustomEncoder, indent=4)       
    except FileNotFoundError:
        print(f"The file {file_path} does not exist.")
    except json.JSONDecodeError:
        print("Error decoding JSON from the file.")
        print(data)
    except Exception as e:
        print(f"An error occurred: {e}")
        
class CustomEncoder(json.JSONEncoder):                             # Handles NaT values when dumping excel data into json
    def default(self, obj):
        if isinstance(obj, pd._libs.tslibs.nattype.NaTType):
            return 'NaT'
        return super().default(obj)
        
if __name__ == '__main__':
    excel_to_json(r'edm.xlsm')
    holidayDict = readjson()                                                          # Assigns data from json to holidayDict variable
    odbc_driver = get_odbc_driver()
    connect_to_db(f'DRIVER={{{odbc_driver}}};SERVER=10.1.4.6;PORT=3306;DATABASE=autocalendar;UID=autocal;PWD=AutoCal_Pwd')
    cwd = os.getcwd()
    username = os.getlogin()
    datestamp = datetime.now().strftime('%Y-%m-%d')
    timestamp = datetime.now().strftime('%H:%M:%S')
    errorcount = 0
    
# Execute the changes in autocalendar
    for i in holidayDict:                                                             # Iterates through the json data and serparates out the concepts
        date = i['holidays (YYYY-MM-DD)']
        database = i['database']
        country = i['country']
        group = i['group']
        update = i['update']
        initial = i['initial']
        action = i['action']
        moved_date = i['move to date (YYYY-MM-DD) leave blank if n/a']
        if date != "":                                                                             # Finds the specific entry in autocalendar using the date of the holiday given and the other paramenters such as database and country
            record, record_dict = find_record(database, country, group, update, date)
        if action not in ['Checkoff', 'Just leave a note', 'Move to next day', 'Move to previous day', 'Move to specified date'] and action != "":   # Outputs an error if action is not one of the expected actions
            errorcount += 1
            print(f'*****ERROR*****: Inputted action {action} for {database, country, group, update} not recognized for {date}. Error number {errorcount} in this run')
            with open(r'F:\automation\holidays\holiday_fails.log', 'a') as f:
                f.write(f'{datestamp.ljust(8)} | {timestamp.ljust(8)} | Inputted action {action} not recognized.      | {database.ljust(10)} |  {country.ljust(8)} | {group.ljust(8)} |  {update.ljust(50)} | {username}\n')
        if date != "" and action != "" and initial != "":                                        # Makes sure that there is a record and makes sure there is something given for the date, action, and initial. Then reads that information and runs the function the json instructs
            if record is not None:                                            
                if action=='Checkoff': 
                    mark_done(record, initial)
                    append_master_json(i)
                if action=='Move to next day':
                    move_update_plusone(record, initial)
                    append_master_json(i)
                if action=='Move to specified date':
                    move_update_specified_date(moved_date, record, initial)
                    append_master_json(i)
                if action=='Move to previous day':
                    move_update_minusone(record, initial)
                    append_master_json(i)
                if action=='Just leave a note':
                    note = 'HOLIDAY, CHECK'
                    try:
                        write_note(record, note, initial)
                        print(f'{record.fdDatabaseName, record.fdGroup, record.fdMessageBoard} was only noted successfully for {date}!')
                        append_master_json(i)
                        with open(r'F:\automation\holidays\holiday_success.log', 'a') as f:
                            f.write(f'{datestamp.ljust(8)} | {timestamp.ljust(8)} | Successfully noted for {record.fddDate2Show} for {date}                                 | {database.ljust(10)} |  {country.ljust(8)} | {group.ljust(8)} |  {update.ljust(50)} | {username}\n')
                    except Exception as e:
                        errorcount += 1
                        print(f'*****ERROR*****: Unable to just note {database, group, update}  for {date} because {e}. Error number {errorcount} in this run')
                        with open(r'F:\automation\holidays\holiday_fails.log', 'a') as f:
                            f.write(f'{datestamp.ljust(8)} | {timestamp.ljust(8)} | Failed to note for {record.fddDate2Show} for {date} because {e}                              | {database.ljust(10)} |  {country.ljust(8)} | {group.ljust(8)} |  {update.ljust(50)} | {username}\n')
            else:
                errorcount += 1
                print(f'*****ERROR*****: Unable to find {database, country, group, update} for {date}. Error number {errorcount} in this run')
                with open(r'F:\automation\holidays\holiday_fails.log', 'a') as f:
                    f.write(f'{datestamp.ljust(8)} | {timestamp.ljust(8)} | Entry not found for specified date in autocalendar                             | {database.ljust(10)} |  {country.ljust(8)} | {group.ljust(8)} |  {update.ljust(50)} | {username}\n')
        elif date != "" and action =="":
            errorcount += 1
            print(f'*****ERROR*****: {database, country, group, update} has an action but no holiday date! Error number {errorcount} in this run')
            with open(r'F:\automation\holidays\holiday_fails.log', 'a') as f:
                f.write(f'{datestamp.ljust(8)} | {timestamp.ljust(8)} | No holiday date listed in EDM.XLSM                             | {database.ljust(10)} |  {country.ljust(8)} | {group.ljust(8)} |  {update.ljust(50)} | {username}\n')
        elif date == "" and action !="":
            errorcount += 1
            print(f'*****ERROR*****: {database, country, group, update} has a holiday date but no action! Error number {errorcount} in this run')
            with open(r'F:\automation\holidays\holiday_fails.log', 'a') as f:
                f.write(f'{datestamp.ljust(8)} | {timestamp.ljust(8)} | No action listed in EDM.XLSM                             | {database.ljust(10)} |  {country.ljust(8)} | {group.ljust(8)} |  {update.ljust(50)} | {username}\n')
        elif date != "" and action != "" and initial == "":
            errorcount += 1
            print(f'*****ERROR*****: {database, country, group, update} needs to have initials! Error number {errorcount} in this run')
            with open(r'F:\automation\holidays\holiday_fails.log', 'a') as f:
                f.write(f'{datestamp.ljust(8)} | {timestamp.ljust(8)} | No initials listed in EDM.XLSM                             | {database.ljust(10)} |  {country.ljust(8)} | {group.ljust(8)} |  {update.ljust(50)} | {username}\n')
    sys.exit()