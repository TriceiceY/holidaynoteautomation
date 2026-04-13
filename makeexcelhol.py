from AutoStatsFunctions import Assignments, Autocalendar
import pandas as pd
import argparse
import os
import sys
from openpyxl import Workbook
from openpyxl import load_workbook
from openpyxl.worksheet.datavalidation import DataValidation
from openpyxl.utils import get_column_letter
import re
import win32com.client

def create_dataframe():
# Retrieve autocalendar entries and sort by EDM assignment
    a = Autocalendar()
    dw_sql = a.get_dw()
    dw_list = a.parse_entries()
    a = Assignments()
    dw_list = a.assign(dw_list, attach=True)
    
# Create a dataframe with columns and data from autocalendar   
    df = pd.DataFrame(dw_list, columns=[
        '', 'database', 'group', 'country', 'update', 'time', 'edm',
        'holidays (YYYY-MM-DD)', 'action', 'move to date (YYYY-MM-DD) leave blank if n/a',
        'initial', 'procedures'
    ])
    return df
    
def format_dataframe(df):
# Strip whitespace from object columns
    df_obj = df.select_dtypes('object')
    df[df_obj.columns] = df_obj.apply(lambda x: x.str.strip() if isinstance(x, str) else x)

# Parse command-line argument for EDM manager
    parser = argparse.ArgumentParser()
    parser.add_argument('manager', metavar='edm', help='The updates of the specified EDM are put into the outputted Excel file. Type "all" if no specified EDM')
    args = parser.parse_args()
    manager = sys.argv[1].lower()

# Filter DataFrame by EDM manager
    matches = [c for c in df['edm'] if c == manager]
    if manager != "all" and not matches:
        raise ValueError('Please put in name of EDM. Type "all" if no specified EDM')
    if args.manager != "all":
        df = df[df['edm'] == manager]
    return df
        
def dataframe_to_excel(df):
# Save DataFrame to .xlsx file
    output_file = "edm.xlsx"
    with pd.ExcelWriter(output_file, engine='openpyxl') as writer:
        df.to_excel(writer, index=False, sheet_name='Sheet1')
    wb = load_workbook(output_file)
    ws = wb.active
    
# Apply autofilter
    ws.auto_filter.ref = ws.dimensions
    
# Freeze header row
    ws.freeze_panes = ws['A2']
    
# Adjust column widths
    for col in ws.columns:
        max_length = max(len(str(cell.value)) if cell.value is not None else 0 for cell in col)
        adjusted_width = max_length + 6
        col_letter = get_column_letter(col[0].column)
        ws.column_dimensions[col_letter].width = adjusted_width
        ws.column_dimensions['A'].width = 20
        
# Apply date formatting to columns H and J
    for row in range(2, ws.max_row + 1):
        ws[f'H{row}'].number_format = 'yyyy-mm-dd'
        ws[f'J{row}'].number_format = 'yyyy-mm-dd'
    wb.create_sheet('actions_list')
    wb.save('edm.xlsx')
    
# Data validation for actions so that user only does specified actions
    ws = wb['actions_list']                                                        
    ws["A2"] = "Checkoff"
    ws["A3"] = "Just leave a note"
    ws["A4"] = "Move to next day"
    ws["A5"] = "Move to previous day"
    ws["A6"] = "Move to specified date"
    actions = 'actions_list!$A$%s:$A$%s'%(2, 6)
    dv = DataValidation(type="list", formula1='=' + actions,  allow_blank=True)
    ws = wb['Sheet1']
    ws.add_data_validation(dv)
    dv_app = "I2:I" + str(ws.max_row)
    dv.add(dv_app)
    wb.save(output_file)
    return wb
    
def xlsx_to_xlsm(file):
# Open the Excel file
    excel = win32com.client.Dispatch("Excel.Application")
    excel.Visible = False
    output_file = "edm.xlsx"
    wb_macro = excel.Workbooks.Open(os.path.abspath(output_file))
    macro_file = os.path.abspath("edm.xlsm")
    wb_macro.SaveAs(macro_file, FileFormat=52)
    sheet = wb_macro.Sheets("Sheet1") 

#Create button that spans all of column A until the end of the data in the worksheet
    sheet_range = sheet.UsedRange.Rows.Count
    button_range = f"A2:A{sheet_range}"
    sheet.Range(button_range).Merge()
    left = sheet.Range("A2").Left
    top = sheet.Range("A2").Top
    merged_range = sheet.Range(button_range)
    height = merged_range.Height
    button = sheet.Buttons().Add(left, top, 100, height)
    button.Text = "Duplicate Row"
    button.OnAction = "DuplicateRow"
    vba_module = wb_macro.VBProject.VBComponents.Add(1)  # 1 = vbext_ct_StdModule (Standard Module)

# Add VBA code that duplicates the selected row
    vba_code = """
    Sub DuplicateRow()
        Dim currentRow As Long
        currentRow = ActiveCell.Row
        Rows(currentRow).Copy
        Rows(currentRow + 1).Insert Shift:=xlDown
    End Sub
    """
    vba_module.CodeModule.AddFromString(vba_code)
    wb_macro.Save()
    wb_macro.Close()
    excel.Quit()
    
if __name__ == '__main__':
    autocal_data = create_dataframe()
    formatted_df = format_dataframe(autocal_data)
    xlsx_file = dataframe_to_excel(formatted_df)
    xlsx_to_xlsm(xlsx_file)
    print('EDM.XLSM has been created')
    print('Fill in holiday instructions and run exceltojsonfin.py')