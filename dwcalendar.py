import argparse
import pyodbc
import re
import sys
from datetime import datetime, timedelta
import json
import os

def to_haver_date(date, freq='D'):
    '''Function to convert datetime object to Haver format'''
    # variable for year
    if date.year < 2000:
        hyear = date.strftime('%y')
    else:
        hyear = f"1{date.strftime('%y')}"
    # variable for quarter
    if date.month <= 3:
        q = 1
    elif date.month <= 6:
        q = 2
    elif date.month <= 9:
        q = 3
    elif date.month <= 12:
        q = 4
    # possible return
    if freq.upper() == 'D':
        return f"{hyear}{date.strftime('%m%d')}"
    if freq.upper() == 'W':
        return f"{hyear}{date.strftime('%m%d')}W"
    if freq.upper() == 'M':
        return f"{hyear}{date.strftime('%m')}"
    if freq.upper() == 'Q':
        return f"{hyear}{q}"
    if freq.upper() == 'A':
        return f"{hyear}"

def connect_to_db(MDB):
    global con
    global cursor
    con = pyodbc.connect(MDB, ansi=True)
    cursor = con.cursor()

def find_record(database, country, group, update):
    cursor.execute('''SELECT *
                   FROM tblcalendar_dw_templates dwt
                   JOIN tblcalendar_countries cnt
                   ON cnt.fdCountryID = dwt.fdCountryID 
                   JOIN tblcalendar_dw_records dwr
                   ON dwt.fdTemplateID = dwr.fdTemplateID
                   JOIN tblcalendar_dw_database dwdb
                   ON dwdb.fdDatabaseID = dwt.fdDatabaseID
                   WHERE fdDone=0 AND fdDatabaseName=? 
                    AND fdCountryName=? 
                    AND fdGroup=? 
                    AND fdMessageBoard=?;''', (database, country, group, update))    
    notDoneEntries = cursor.fetchall()
    if not notDoneEntries:
        print('Unable to find entry matching specified parameters.')
        con.close
        log_notfound(database, country, group, update)
        sys.exit(1)
    # sorting entries by release dates.
    notDoneEntries.sort(key=lambda entry: entry.fddDate2Show)
    return notDoneEntries[0]

def get_release_date(record, daydiff, includeHoliday=False, includeWeekend=False):
    holidayList = getholidayList(record, includeHoliday)                        # New line
    date = record.fddDate2Show
    subtract = False
    if daydiff < 0:
        subtract = True
    count = 0
    while count < abs(daydiff):
        if subtract:
            date = date - timedelta(days=1)
        else:
            date = date + timedelta(days=1)
        if date.weekday() == 5 or date.weekday() == 6:
            if includeWeekend:
                if date not in holidayList:                                     # New line
                    count += 1
        else:
            if date not in holidayList:                                         # New line
                count += 1
    isHolidayAdjacent(date, holidayList, includeWeekend)                        # New line
    rdate = to_haver_date(date)
    con.close
    return int(rdate)

def format_note(old_note, new_note, separator=' | '):
    split_note  = old_note.split(separator)
    notes = []
    for note in split_note:
        note = note.strip()
        if note[:4] != 'R2D2':
            notes.append(note)
    notes.append(new_note)
    return separator.join(notes)  
    
def write_note(record, note):
    if record.fdNotes != None:
        note = format_note(record.fdNotes, note)[:200]
    cursor.execute('UPDATE tblcalendar_dw_records SET fdNotes=? WHERE fdRecID=?;', (note, record.fdRecID))
    con.commit()
    con.close

def mark_done(record, initial):
    cursor.execute('UPDATE tblcalendar_dw_records SET fdInitials=?, fdDone=-1, fdDoneDate=? WHERE fdRecID=?;', (initial, datetime.now(), record.fdRecID))
    con.commit()
    con.close

def get_odbc_driver():
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

def getholidayList(record, includeHoliday):
    if includeHoliday ==False:
        return []
    try:
        country = record.fdCountryName 
        with open('f:/intdaily/qpp/QppHolidays.json', 'r') as f:
            holidayDict = json.load(f)
        holidayList = [datetime.date(datetime.strptime(i, '%Y-%m-%d')) for i in holidayDict[country.lower()]]
        return holidayList
    except:
        group = record.fdGroup
        update = record.fdMessageBoard
        batch_file = record.fdBatchFile
        with open(r'F:\intdaily\QPP\error_logging.txt', 'a') as f:
            f.write(f'Holiday not found for {country} | {group}, {batch_file}, {update}\n')
        return []
    
def isHolidayAdjacent(date, holidayList, includeWeekend=False):
    """
    Checks if release date is adjacent to a holiday.
    """
    count = 0
    while count < 1:
        date = date - timedelta(days=1)
        if date.weekday() == 5 or date.weekday() == 6:
            if includeWeekend:
                count += 1
        else:
            count += 1
    if date in  holidayList:
        boolArg = 'True'
    else:
        boolArg = 'False'
    with open('isHolidayAdjacent.txt', 'w') as f:
        f.write(f'HolidayAdjacent={boolArg}')

def log_trigger(record):
    try:
        date = datetime.now().strftime('%Y-%m-%d')
        time = datetime.now().strftime('%H:%M:%S')
        group = record.fdGroup
        update = record.fdMessageBoard
        batch_file = record.fdBatchFile
        if not batch_file:
            cwd = os.getcwd()
            batch_file = cwd + "\\" + "NoBatch"
        database = record.fdDatabaseName
        username = os.getlogin()
        with open(r'F:\intdaily\testdb\logging\triggered.txt', 'a') as f:
            f.write(f'{date} | {time} | D/W   | {batch_file.ljust(60)} | {group.ljust(8)} | {database.ljust(10)} | {username.ljust(8)} | {update}\n')
    except:
        try:
            cwd = os.getcwd()
            date = datetime.now().strftime('%Y-%m-%d')
            time = datetime.now().strftime('%H:%M:%S')
            username = os.getlogin()
            with open(r'F:\intdaily\testdb\logging\triggered_baderrors.txt', 'a') as f:
                f.write(f'{date} | {time} | D/W   | {cwd} | {username}\n')   
        except:
            pass
            
def log_notfound(database, country, group, update):
    try:
        date = datetime.now().strftime('%Y-%m-%d')
        time = datetime.now().strftime('%H:%M:%S')
        cwd = os.getcwd()
        batch_file = cwd+"\RecordNotFound"
        username = os.getlogin()
        with open(r'F:\intdaily\testdb\logging\triggered.txt', 'a') as f:
            f.write(f'{date} | {time} | D/W   | {batch_file.ljust(60)} | {group.ljust(8)} | {database.ljust(10)} | {username.ljust(8)} | {update}\n')
    except:
        pass
        
def parse_command_line_args():
    parser = argparse.ArgumentParser(description='Edit DAILY/WEEKLY autocalendar entries via command line.')
    parser.add_argument('database', metavar='database', help='The database name as displayed in the DB column in autocalendar.')
    parser.add_argument('country', metavar='country', help='The country name as displayed in the Country column in autocalendar.')
    parser.add_argument('group', metavar='group', help='The group name as displayed in the Group column in autocalendar.')
    parser.add_argument('update', metavar='update', help='The update name as displayed in the Update column in autocalendar.')
    parser.add_argument('-n', '--note', metavar='', type=str, help='Enter note to put under the Assign/Notes column.')
    parser.add_argument('-r', '--rdate', action='store_true', help='Sets errorlevel to release date on calendar.')
    parser.add_argument('-dd', '--daydiff', metavar='', default=0, type=int, help='Adjustment for -r option. Number of days to add or subtract to the return value.')
    parser.add_argument('-w', '--includeweekend', default=False, action='store_true', help='Include weekends when using daydiff. Defaults to not include weekends.')
    parser.add_argument('-hol', '--includeholiday', default=False, action='store_true', help='Account for holidays when using daydiff. Default to not account for holidays.')
    parser.add_argument('-i', '--initial', metavar='', default='R2D2', type=str, help='The initials to use when marking the update off as done. (Default is R2D2)')
    return parser.parse_args()

if __name__ == '__main__':
    args = parse_command_line_args()
    odbc_driver = get_odbc_driver()
    connect_to_db(f'DRIVER={{{odbc_driver}}};SERVER=10.1.4.6;PORT=3306;DATABASE=autocalendar;UID=autocal;PWD=AutoCal_Pwd')
    record = find_record(args.database, args.country, args.group, args.update)
    if args.rdate:
        log_trigger(record)
        release_date = get_release_date(record, args.daydiff, includeHoliday=args.includeholiday, includeWeekend=args.includeweekend)
        print(release_date)
        sys.exit(release_date)
    if args.note:
        write_note(record, args.note)
        sys.exit()
    mark_done(record, args.initial)
    

