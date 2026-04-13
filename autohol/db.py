# This file is for connection + query helpers

import pyodbc
from datetime import date


def connect(conn_str: str):
    conn = pyodbc.connect(conn_str, ansi=True)
    cursor = conn.cursor()
    return conn, cursor

def find_records_by_country_and_date(cursor, country: str, target_date: date):
    sql = """
        SELECT
            dwr.*,
            cnt.fdCountryName,
            dwdb.fdDatabaseName AS fdDatabaseName,
            dwt.fdGroup         AS fdGroup,
            dwt.fdMessageBoard  AS fdMessageBoard
        FROM tblcalendar_dw_templates dwt
        JOIN tblcalendar_countries cnt
          ON cnt.fdCountryID = dwt.fdCountryID
        JOIN tblcalendar_dw_records dwr
          ON dwt.fdTemplateID = dwr.fdTemplateID
        JOIN tblcalendar_dw_database dwdb
          ON dwdb.fdDatabaseID = dwt.fdDatabaseID
        WHERE dwr.fdDone=0 
            AND cnt.fdCountryName = ?
            AND DATE(dwr.fddDate2Show) = ?
    """
    params = [country, target_date.strftime("%Y-%m-%d")]
    cursor.execute(sql + ";", params)
    rows = cursor.fetchall()
    rows.sort(key=lambda r: (r.fddDate2Show or "", r.fdRecID))
    return rows