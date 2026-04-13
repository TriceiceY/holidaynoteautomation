import os
import sys
import json
from datetime import datetime
import tkinter as tk
from tkinter import ttk
from tkinter import messagebox
from tkcalendar import DateEntry

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)


from autohol.holidays import load_holiday_dict
from autohol.future_holiday_planner import (
    filter_entries_for_user,
    build_window_task_candidates,
    annotate_holiday_context,
    build_planner_rows,
    date_window,
)
from autohol.dw_source import Autocalendar, Assignments


class PlannerApp:
    def __init__(self, root):
        self.root = root
        self.root.title("AutoHoliday Planner")
        self.root.geometry("1500x900")

        # Helps DateEntry behave more consistently on Windows
        style = ttk.Style()
        style.theme_use("clam")

        self.main_frame = ttk.Frame(root, padding=10)
        self.main_frame.pack(fill="both", expand=True)

        self.default_holiday_path = r"data/Q++ Worldwide Public Holidays ISO-2026.CSV"
        self.custom_holiday_path = r"data/custom_holidays.json"
        self.output_json_path = r"data/planner_logs/planner_log.json"
        self.output_csv_path = r"data/planner_logs/planner_log.csv"

        self.planner_rows = []

        self.build_controls_section()
        self.build_custom_holiday_section()
        self.build_summary_section()
        self.build_table_section()
        self.load_rows_into_table(self.planner_rows)
        self.build_action_section()

    # ---------------------------
    # Planner controls
    # ---------------------------
    def build_controls_section(self):
        controls = ttk.LabelFrame(self.main_frame, text="Planner Controls", padding=10)
        controls.pack(fill="x", pady=5)

        ttk.Label(controls, text="Planner User:").grid(row=0, column=0, sticky="w", padx=5, pady=5)

        self.user_var = tk.StringVar()
        ttk.Entry(controls, textvariable=self.user_var, width=25).grid(row=0, column=1, padx=5, pady=5)

        ttk.Label(controls, text="Holiday Date:").grid(row=0, column=2, sticky="w", padx=5, pady=5)

        self.holiday_date_input = DateEntry(
            controls,
            width=12,
            date_pattern="yyyy-mm-dd"
        )
        self.holiday_date_input.grid(row=0, column=3, padx=5, pady=5)

        self.generate_button = ttk.Button(
            controls,
            text="Generate Planner Rows",
            command=self.generate_planner_rows
        )
        self.generate_button.grid(row=0, column=4, padx=5, pady=5)

        self.clear_button = ttk.Button(
            controls,
            text="Clear Table",
            command=self.clear_table
        )
        self.clear_button.grid(row=0, column=5, padx=5, pady=5)

    # ---------------------------
    # Custom holiday section
    # ---------------------------
    def build_custom_holiday_section(self):
        frame = ttk.LabelFrame(self.main_frame, text="Custom Holiday", padding=10)
        frame.pack(fill="x", pady=5)

        ttk.Label(frame, text="Country:").grid(row=0, column=0, sticky="w", padx=5, pady=5)

        self.custom_country_var = tk.StringVar()
        ttk.Entry(frame, textvariable=self.custom_country_var, width=25).grid(row=0, column=1, padx=5, pady=5)

        ttk.Label(frame, text="Holiday Date:").grid(row=0, column=2, sticky="w", padx=5, pady=5)

        self.custom_date_input = DateEntry(
            frame,
            width=12,
            date_pattern="yyyy-mm-dd"
        )
        self.custom_date_input.grid(row=0, column=3, padx=5, pady=5)

        ttk.Label(frame, text="Holiday Name:").grid(row=0, column=4, sticky="w", padx=5, pady=5)

        self.custom_name_var = tk.StringVar()
        ttk.Entry(frame, textvariable=self.custom_name_var, width=30).grid(row=0, column=5, padx=5, pady=5)

        self.add_custom_button = ttk.Button(
            frame,
            text="Add Custom Holiday",
            command=self.add_custom_holiday
        )
        self.add_custom_button.grid(row=0, column=6, padx=5, pady=5)

    # ---------------------------
    # Summary
    # ---------------------------
    def build_summary_section(self):
        frame = ttk.LabelFrame(self.main_frame, text="Summary", padding=10)
        frame.pack(fill="x", pady=5)

        self.summary_user_var = tk.StringVar(value="User: -")
        self.summary_holiday_var = tk.StringVar(value="Holiday Date: -")
        self.summary_window_var = tk.StringVar(value="Window: -")
        self.summary_rows_var = tk.StringVar(value="Rows Loaded: 0")
        self.summary_selected_var = tk.StringVar(value="Rows Selected: 0")
        self.summary_actions_var = tk.StringVar(value="Rows with Actions: 0")

        ttk.Label(frame, textvariable=self.summary_user_var).grid(row=0, column=0, padx=10, pady=5, sticky="w")
        ttk.Label(frame, textvariable=self.summary_holiday_var).grid(row=0, column=1, padx=10, pady=5, sticky="w")
        ttk.Label(frame, textvariable=self.summary_window_var).grid(row=0, column=2, padx=10, pady=5, sticky="w")
        ttk.Label(frame, textvariable=self.summary_rows_var).grid(row=0, column=3, padx=10, pady=5, sticky="w")
        ttk.Label(frame, textvariable=self.summary_selected_var).grid(row=0, column=4, padx=10, pady=5, sticky="w")
        ttk.Label(frame, textvariable=self.summary_actions_var).grid(row=0, column=5, padx=10, pady=5, sticky="w")

    # ---------------------------
    # Planner table
    # ---------------------------
    def build_table_section(self):
        frame = ttk.LabelFrame(self.main_frame, text="Planner Table", padding=10)
        frame.pack(fill="both", expand=True, pady=5)

        columns = (
            "target_date",
            "database",
            "country",
            "group",
            "update",
            "time",
            "templateID",
            "procedures",
            "planned_action",
            "planned_note",
            "move_mode",
            "move_to_date",
        )

        self.tree = ttk.Treeview(frame, columns=columns, show="headings", selectmode="extended")
        self.tree.pack(side="left", fill="both", expand=True)

        for col in columns:
            self.tree.heading(col, text=col)
            self.tree.column(col, width=120, anchor="w")

        scrollbar_y = ttk.Scrollbar(frame, orient="vertical", command=self.tree.yview)
        scrollbar_y.pack(side="right", fill="y")
        self.tree.configure(yscrollcommand=scrollbar_y.set)

        self.tree.bind("<<TreeviewSelect>>", self.update_selected_count)
        self.tree.bind("<Double-1>", self.handle_double_click)

    def load_rows_into_table(self, rows):
        for item in self.tree.get_children():
            self.tree.delete(item)

        for idx, row in enumerate(rows):
            values = (
                row.get("target_date", ""),
                row.get("database", ""),
                row.get("country", ""),
                row.get("group", ""),
                row.get("update", ""),
                row.get("time", ""),
                row.get("templateID", ""),
                row.get("procedures", ""),
                row.get("planned_action", ""),
                row.get("planned_note", ""),
                row.get("move_mode", ""),
                row.get("move_to_date", ""),
            )
            self.tree.insert("", "end", iid=str(idx), values=values)

        self.summary_rows_var.set(f"Rows Loaded: {len(rows)}")
        self.update_action_count()

    def update_selected_count(self, event=None):
        selected = self.tree.selection()
        self.summary_selected_var.set(f"Rows Selected: {len(selected)}")

    def update_action_count(self):
        count = sum(1 for row in self.planner_rows if row.get("planned_action", "").strip())
        self.summary_actions_var.set(f"Rows with Actions: {count}")

    def handle_double_click(self, event=None):
        item_id = self.tree.identify_row(event.y)
        column_id = self.tree.identify_column(event.x)

        if not item_id or not column_id:
            return

        col_index = int(column_id.replace("#", "")) - 1
        columns = (
            "target_date",
            "database",
            "country",
            "group",
            "update",
            "time",
            "templateID",
            "procedures",
            "planned_action",
            "planned_note",
            "move_mode",
            "move_to_date",
        )

        if columns[col_index] != "procedures":
            return

        row_idx = int(item_id)
        path = self.planner_rows[row_idx].get("procedures", "").strip()
        if not path:
            return

        if os.path.exists(path):
            os.startfile(path)
        else:
            messagebox.showwarning("File not found", f"Procedure file does not exist:\n{path}")

    # ---------------------------
    # Action editor
    # ---------------------------
    def build_action_section(self):
        frame = ttk.LabelFrame(self.main_frame, text="Action Editor", padding=10)
        frame.pack(fill="x", pady=5)

        ttk.Label(frame, text="Action:").grid(row=0, column=0, padx=5, pady=5, sticky="w")

        self.action_var = tk.StringVar()
        ttk.Combobox(
            frame,
            textvariable=self.action_var,
            values=["", "ADD_NOTE", "MARK_DONE", "MOVE_DATE"],
            width=15,
            state="readonly",
        ).grid(row=0, column=1, padx=5, pady=5)

        ttk.Label(frame, text="Note:").grid(row=0, column=2, padx=5, pady=5, sticky="w")

        self.note_var = tk.StringVar()
        ttk.Entry(frame, textvariable=self.note_var, width=50).grid(row=0, column=3, padx=5, pady=5)

        ttk.Label(frame, text="Move Mode:").grid(row=0, column=4, padx=5, pady=5, sticky="w")

        self.move_mode_var = tk.StringVar()
        ttk.Combobox(
            frame,
            textvariable=self.move_mode_var,
            values=["", "next_business_day", "next_calendar_day", "specific_date"],
            width=18,
            state="readonly",
        ).grid(row=0, column=5, padx=5, pady=5)

        ttk.Label(frame, text="Move To Date (YYYY-MM-DD):").grid(row=0, column=6, padx=5, pady=5, sticky="w")

        self.move_to_date_var = tk.StringVar()
        ttk.Entry(frame, textvariable=self.move_to_date_var, width=15).grid(row=0, column=7, padx=5, pady=5)

        self.apply_action_button = ttk.Button(
            frame,
            text="Apply to Selected Rows",
            command=self.apply_action_to_selected_rows
        )
        self.apply_action_button.grid(row=0, column=8, padx=5, pady=5)

        self.clear_action_button = ttk.Button(
            frame,
            text="Clear Action",
            command=self.clear_action_for_selected_rows
        )
        self.clear_action_button.grid(row=0, column=9, padx=5, pady=5)

        self.save_button = ttk.Button(
            frame,
            text="Save Planner Log",
            command=self.save_planner_log
        )
        self.save_button.grid(row=0, column=10, padx=5, pady=5)

    def apply_action_to_selected_rows(self):
        selected = self.tree.selection()
        if not selected:
            messagebox.showwarning("No selection", "Please select one or more rows.")
            return

        planned_action = self.action_var.get().strip()
        planned_note = self.note_var.get().strip()
        move_mode = self.move_mode_var.get().strip()
        move_to_date = self.move_to_date_var.get().strip()

        if not planned_action:
            messagebox.showwarning("Missing action", "Please choose a planned action.")
            return

        if planned_action == "ADD_NOTE" and not planned_note:
            messagebox.showwarning("Missing note", "ADD_NOTE requires a note.")
            return

        if planned_action == "MARK_DONE" and not planned_note:
            planned_note = "AUTOHOL: Holiday Marked Off"

        if planned_action == "MOVE_DATE":
            if not move_mode:
                messagebox.showwarning("Missing move mode", "MOVE_DATE requires a move mode.")
                return
            if move_mode == "specific_date" and not move_to_date:
                messagebox.showwarning("Missing move date", "Please enter move_to_date.")
                return
            if not planned_note:
                planned_note = (
                    f"AUTOHOL: Holiday Moved to {move_to_date}"
                    if move_mode == "specific_date"
                    else "AUTOHOL: Holiday Moved"
                )

        for item_id in selected:
            row_idx = int(item_id)
            self.planner_rows[row_idx]["planned_action"] = planned_action
            self.planner_rows[row_idx]["planned_note"] = planned_note
            self.planner_rows[row_idx]["move_mode"] = move_mode if planned_action == "MOVE_DATE" else ""
            self.planner_rows[row_idx]["move_to_date"] = move_to_date if planned_action == "MOVE_DATE" else ""

        self.load_rows_into_table(self.planner_rows)

    def clear_action_for_selected_rows(self):
        selected = self.tree.selection()
        if not selected:
            messagebox.showwarning("No selection", "Please select one or more rows.")
            return

        for item_id in selected:
            row_idx = int(item_id)
            self.planner_rows[row_idx]["planned_action"] = ""
            self.planner_rows[row_idx]["planned_note"] = ""
            self.planner_rows[row_idx]["move_mode"] = ""
            self.planner_rows[row_idx]["move_to_date"] = ""

        self.load_rows_into_table(self.planner_rows)

    def save_planner_log(self):
        messagebox.showinfo("Save", "Placeholder only. Save logic will be added in the next step.")

    # ---------------------------
    # Custom holiday helpers
    # ---------------------------
    def custom_holiday_file_exists(self):
        return os.path.exists(self.custom_holiday_path)

    def load_custom_holidays(self):
        if not os.path.exists(self.custom_holiday_path):
            return []

        try:
            with open(self.custom_holiday_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                return data if isinstance(data, list) else []
        except Exception as e:
            messagebox.showerror("Load error", f"Failed to load custom holidays:\n{e}")
            return []

    def save_custom_holidays(self, holidays):
        folder = os.path.dirname(self.custom_holiday_path)
        if folder:
            os.makedirs(folder, exist_ok=True)

        with open(self.custom_holiday_path, "w", encoding="utf-8") as f:
            json.dump(holidays, f, ensure_ascii=False, indent=2)

    def normalize_country(self, country: str) -> str:
        return (country or "").strip().lower()

    def add_custom_holiday(self):
        country = self.custom_country_var.get().strip()
        holiday_date = self.custom_date_input.get_date().isoformat()
        holiday_name = self.custom_name_var.get().strip()

        if not country or not holiday_name:
            messagebox.showwarning(
                "Missing fields",
                "Please enter country name and holiday name."
            )
            return

        new_country = self.normalize_country(country)
        holidays = self.load_custom_holidays()

        for item in holidays:
            existing_country = self.normalize_country(item.get("country", ""))
            existing_date = (item.get("holiday_date") or "").strip()
            existing_name = (item.get("holiday_name") or "").strip()

            if (
                existing_country == new_country
                and existing_date == holiday_date
                and existing_name == holiday_name
            ):
                messagebox.showwarning(
                    "Duplicate holiday",
                    "This exact custom holiday already exists."
                )
                return

            if (
                existing_country == new_country
                and existing_date == holiday_date
                and existing_name != holiday_name
            ):
                messagebox.showwarning(
                    "Duplicate country/date",
                    f"A custom holiday already exists for {country} on {holiday_date}.\n"
                    f"Existing holiday name: {existing_name}"
                )
                return

        holidays.append({
            "country": country.strip(),
            "holiday_date": holiday_date,
            "holiday_name": holiday_name.strip(),
            "source": "custom",
            "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        })

        try:
            self.save_custom_holidays(holidays)
            messagebox.showinfo(
                "Custom holiday added",
                f"Added custom holiday:\n{country} | {holiday_date} | {holiday_name}"
            )

            self.custom_country_var.set("")
            self.custom_name_var.set("")
        except Exception as e:
            messagebox.showerror("Save error", f"Failed to save custom holiday:\n{e}")

    # ---------------------------
    # Backend loaders
    # ---------------------------
    def load_dw_entries_with_assignments(self):
        a = Autocalendar()
        a.get_dw()
        dw_entries = a.parse_entries()

        b = Assignments()
        dw_entries = b.assign(dw_entries, attach=True)
        return dw_entries

    def load_merged_holidays(self):
        holiday_dict = load_holiday_dict(self.default_holiday_path)

        custom_holidays = self.load_custom_holidays()
        for item in custom_holidays:
            country = self.normalize_country(item.get("country", ""))
            holiday_date = (item.get("holiday_date") or "").strip()

            if not country or not holiday_date:
                continue

            try:
                hdate = datetime.strptime(holiday_date, "%Y-%m-%d").date()
            except ValueError:
                continue

            holiday_dict.setdefault(country, set())
            if isinstance(holiday_dict[country], list):
                holiday_dict[country] = set(holiday_dict[country])
            holiday_dict[country].add(hdate)

        normalized = {}
        for country, dates in holiday_dict.items():
            if isinstance(dates, set):
                normalized[country] = sorted(dates)
            else:
                normalized[country] = dates

        return normalized

    # ---------------------------
    # Planner generation / clear
    # ---------------------------
    def clear_table(self):
        self.planner_rows = []
        self.load_rows_into_table(self.planner_rows)

        self.summary_user_var.set("User: -")
        self.summary_holiday_var.set("Holiday Date: -")
        self.summary_window_var.set("Window: -")
        self.summary_rows_var.set("Rows Loaded: 0")
        self.summary_selected_var.set("Rows Selected: 0")
        self.summary_actions_var.set("Rows with Actions: 0")

    def generate_planner_rows(self):
        planner_user = self.user_var.get().strip()
        holiday_date = self.holiday_date_input.get_date()

        if not planner_user:
            messagebox.showwarning("Missing user", "Please enter planner user.")
            return

        try:
            holiday_dict = self.load_merged_holidays()
            dw_entries = self.load_dw_entries_with_assignments()
            user_entries = filter_entries_for_user(dw_entries, planner_user)

            candidate_rows = build_window_task_candidates(user_entries, holiday_date)
            annotated_rows = annotate_holiday_context(candidate_rows, holiday_dict, holiday_date)
            self.planner_rows = build_planner_rows(annotated_rows, planner_user, holiday_date)

            self.load_rows_into_table(self.planner_rows)

            w_start, w_end = date_window(holiday_date)
            self.summary_user_var.set(f"User: {planner_user}")
            self.summary_holiday_var.set(f"Holiday Date: {holiday_date.isoformat()}")
            self.summary_window_var.set(f"Window: {w_start.isoformat()} to {w_end.isoformat()}")
            self.summary_rows_var.set(f"Rows Loaded: {len(self.planner_rows)}")
            self.summary_selected_var.set("Rows Selected: 0")
            self.update_action_count()

            if not self.planner_rows:
                messagebox.showinfo("No rows", "No planner rows were generated for this user/date.")

        except Exception as e:
            messagebox.showerror("Generate failed", str(e))

    

def main():
    root = tk.Tk()
    app = PlannerApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()