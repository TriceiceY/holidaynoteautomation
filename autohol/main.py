from datetime import date
from holidays import load_holiday_dict, holidays_for_country
from AutoStatsFunctions import Autocalendar, Assignments


def load_dw_entries_with_assignments():
    a = Autocalendar()
    a.get_dw()
    dw_entries = a.parse_entries()

    b = Assignments()
    dw_entries = b.assign(dw_entries, attach=True)
    return dw_entries



def main():
    csv_path = r"C:\Users\JiebingYin\OneDrive - Haver Analytics\python files\HolidayNoteAutomation\Q++ Worldwide Public Holidays ISO-2026.CSV"

    holiday_dict = load_holiday_dict(csv_path)
    dw_entries = load_dw_entries_with_assignments()

    print(holiday_dict)


if __name__ == "__main__":
    main()    