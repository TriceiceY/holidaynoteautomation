import os
import sys
import json
import csv
from datetime import datetime

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from PyQt6.QtCore import QDate, Qt
from PyQt6.QtWidgets import (
    QApplication,
    QMainWindow,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QGroupBox,
    QLabel,
    QLineEdit,
    QPushButton,
    QDateEdit,
    QMessageBox,
    QTableWidget,
    QTableWidgetItem,
    QAbstractItemView,
    QComboBox,
    QTextEdit,
    QHeaderView,
    QSpinBox,
    QListWidget,
    QListWidgetItem,
    QDialog, 
    QPlainTextEdit,
    QFileDialog,
    QGridLayout,
    QSizePolicy,
    QTimeEdit,
)

from autohol.holidays import (
    load_holiday_records, normalize_country, add_holiday_record)

from autohol.future_holiday_planner import (
    normalize_country,
    filter_entries_for_user,
    get_holiday_countries_for_date,
    get_user_holiday_countries,
    filter_entries_for_countries,
    build_window_task_candidates,
    annotate_holiday_context,
    build_planner_rows,
    write_planner_log_json,
    write_planner_log_csv,
    date_window,
)

from autohol.dw_source import Autocalendar, Assignments



class MultiSelectFilterPopup(QDialog):
    def __init__(self, title, parent=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setModal(True)
        self.resize(260, 360)

        self.main_layout = QVBoxLayout(self)

        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Search...")
        self.main_layout.addWidget(self.search_input)

        top_button_layout = QHBoxLayout()
        self.select_all_button = QPushButton("Select All")
        self.clear_button = QPushButton("Clear")
        top_button_layout.addWidget(self.select_all_button)
        top_button_layout.addWidget(self.clear_button)
        self.main_layout.addLayout(top_button_layout)

        self.list_widget = QListWidget()
        self.main_layout.addWidget(self.list_widget)

        bottom_button_layout = QHBoxLayout()
        bottom_button_layout.addStretch()
        self.ok_button = QPushButton("OK")
        self.cancel_button = QPushButton("Cancel")
        bottom_button_layout.addWidget(self.ok_button)
        bottom_button_layout.addWidget(self.cancel_button)
        self.main_layout.addLayout(bottom_button_layout)

        self.all_options = []
        self.select_all_button.clicked.connect(self.select_all_visible)
        self.clear_button.clicked.connect(self.clear_all_visible)
        self.ok_button.clicked.connect(self.accept)
        self.cancel_button.clicked.connect(self.reject)

    def set_options(self, options, selected_values=None):
        self.all_options = list(options)
        selected_values = set(selected_values or [])

        # If nothing is selected yet, treat that as "all selected"
        use_all_selected = len(selected_values) == 0

        self.list_widget.clear()
        for value in self.all_options:
            item = QListWidgetItem(value)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)

            if use_all_selected or value in selected_values:
                item.setCheckState(Qt.CheckState.Checked)
            else:
                item.setCheckState(Qt.CheckState.Unchecked)

            self.list_widget.addItem(item)

    def get_selected_values(self):
        selected = set()
        for i in range(self.list_widget.count()):
            item = self.list_widget.item(i)
            if item.checkState() == Qt.CheckState.Checked:
                selected.add(item.text())
        return selected

    def filter_items(self, text):
        text = (text or "").strip().lower()
        for i in range(self.list_widget.count()):
            item = self.list_widget.item(i)
            item.setHidden(text not in item.text().lower())

    def select_all_visible(self):
        for i in range(self.list_widget.count()):
            item = self.list_widget.item(i)
            if not item.isHidden():
                item.setCheckState(Qt.CheckState.Checked)

    def clear_all_visible(self):
        for i in range(self.list_widget.count()):
            item = self.list_widget.item(i)
            if not item.isHidden():
                item.setCheckState(Qt.CheckState.Unchecked)


class PlannerWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("AutoHoliday Planner")
        self.resize(1400, 900)

        self.default_holiday_path = r"F:/intdaily/autohol/Q++ Worldwide Public Holidays ISO-2026.CSV"

        self.planner_rows = []
        self.filtered_planner_rows = []
        self.page_dates = []
        self.current_page_index = 0
        self.current_page_rows = []
        self.holiday_page_index = 0
        self.current_sort_field = ""
        self.current_sort_order = "ascending"

        self.selected_database_filters = set()
        self.selected_country_filters = set()
        self.selected_holiday_type_filters = set()

        central = QWidget()
        self.setCentralWidget(central)
        self.main_layout = QVBoxLayout()
        central.setLayout(self.main_layout)

        self.build_controls_section()
        self.build_custom_holiday_section()
        self.build_summary_section()
        self.build_paging_section()
        self.build_filter_section()
        self.build_table_section()
        self.build_action_section()

        self.load_rows_into_table(self.planner_rows)

        self.table.horizontalHeader().sectionClicked.connect(self.handle_header_sort)
        self.generate_button.clicked.connect(self.generate_planner_rows)
        self.prev_date_button.clicked.connect(self.go_to_previous_page)
        self.next_date_button.clicked.connect(self.go_to_next_page)
        self.jump_holiday_button.clicked.connect(self.go_to_holiday_page)
        self.clear_button.clicked.connect(self.clear_table)
        self.add_custom_holiday_button.clicked.connect(self.add_custom_holiday)
        self.import_custom_holiday_button.clicked.connect(self.import_custom_holiday_csv)
        self.custom_holiday_csv_help_button.clicked.connect(self.show_custom_holiday_csv_help)
        self.apply_action_button.clicked.connect(self.apply_action_to_selected_rows)
        self.clear_action_button.clicked.connect(self.clear_action_for_selected_rows)
        self.action_combo.currentTextChanged.connect(self.update_action_editor_visibility)
        self.move_mode_combo.currentTextChanged.connect(self.update_action_editor_visibility)
        self.database_filter_button.clicked.connect(self.open_database_filter_popup)
        self.country_filter_button.clicked.connect(self.open_country_filter_popup)
        self.holiday_type_filter_button.clicked.connect(self.open_holiday_type_filter_popup)
        self.clear_all_filters_button.clicked.connect(self.clear_all_filters)
        self.save_button.clicked.connect(self.save_planner_log)
        self.table.itemSelectionChanged.connect(self.update_selected_count)
        self.table.cellDoubleClicked.connect(self.handle_table_double_click)

        self.update_action_editor_visibility()
        self.update_paging_labels()
        self.update_active_filters_label()



    # ----------------------------
    # UI sections
    # ----------------------------
    def build_controls_section(self):
        self.controls_box = QGroupBox("Planner Controls")
        layout = QHBoxLayout()

        self.user_input = QLineEdit()
        self.user_input.setPlaceholderText("EDM name (blank = all users)")
        self.user_input.setFixedWidth(160)

        self.holiday_date_input = QDateEdit()
        self.holiday_date_input.setCalendarPopup(True)
        self.holiday_date_input.setDisplayFormat("yyyy-MM-dd")
        self.holiday_date_input.setDate(QDate.currentDate())
        self.holiday_date_input.setFixedWidth(140)

        self.days_before_input = QSpinBox()
        self.days_before_input.setRange(0, 60)
        self.days_before_input.setValue(7)
        self.days_before_input.setFixedWidth(70)

        self.days_after_input = QSpinBox()
        self.days_after_input.setRange(0, 60)
        self.days_after_input.setValue(7)
        self.days_after_input.setFixedWidth(70)

        self.generate_button = QPushButton("Generate Planner Rows")
        self.clear_button = QPushButton("Clear Table")

        layout.addWidget(QLabel("Planner User:"))
        layout.addWidget(self.user_input)
        layout.addWidget(QLabel("Holiday Date:"))
        layout.addWidget(self.holiday_date_input)
        layout.addWidget(QLabel("Days Before:"))
        layout.addWidget(self.days_before_input)
        layout.addWidget(QLabel("Days After:"))
        layout.addWidget(self.days_after_input)
        layout.addWidget(self.generate_button)
        layout.addWidget(self.clear_button)
        layout.addStretch()

        self.controls_box.setLayout(layout)
        self.main_layout.addWidget(self.controls_box)


    def build_custom_holiday_section(self):
        self.custom_holiday_box = QGroupBox("Custom Holiday")
        layout = QGridLayout()
        layout.setHorizontalSpacing(4)
        layout.setVerticalSpacing(6)
        layout.setContentsMargins(6, 6, 6, 6)
        self.custom_country_input = QLineEdit()
        self.custom_country_input.setPlaceholderText("Country name")
        self.custom_country_input.setFixedWidth(140)
        self.custom_date_input = QDateEdit()
        self.custom_date_input.setCalendarPopup(True)
        self.custom_date_input.setDisplayFormat("yyyy-MM-dd")
        self.custom_date_input.setDate(QDate.currentDate())
        self.custom_date_input.setFixedWidth(120)
        self.custom_name_input = QLineEdit()
        self.custom_name_input.setPlaceholderText("Holiday name")
        self.custom_name_input.setFixedWidth(180)
        self.custom_observance_combo = QComboBox()
        self.custom_observance_combo.addItems([
            "",
            "Banks",
            "Government",
            "Regional",
            "Banks/Government",
            "Other",
        ])
        self.custom_observance_combo.setFixedWidth(140)
        self.add_custom_holiday_button = QPushButton("Add Custom Holiday")
        self.import_custom_holiday_button = QPushButton("Import Custom Holiday CSV")
        self.custom_holiday_csv_help_button = QPushButton("CSV Format Help")
        # Row 1
        layout.addWidget(QLabel("Country:"), 0, 0)
        layout.addWidget(self.custom_country_input, 0, 1)
        layout.addWidget(QLabel("Holiday Date:"), 0, 2)
        layout.addWidget(self.custom_date_input, 0, 3)
        layout.addWidget(QLabel("Holiday Name:"), 0, 4)
        layout.addWidget(self.custom_name_input, 0, 5)
        layout.addWidget(QLabel("Holiday Observance:"), 0, 6)
        layout.addWidget(self.custom_observance_combo, 0, 7)
        layout.addWidget(self.add_custom_holiday_button, 0, 8)
        # Row 2
        row2_layout = QHBoxLayout()
        row2_layout.setContentsMargins(0, 0, 0, 0)
        row2_layout.setSpacing(8)
        row2_layout.addWidget(self.import_custom_holiday_button)
        row2_layout.addWidget(self.custom_holiday_csv_help_button)
        row2_layout.addStretch()
        row2_widget = QWidget()
        row2_widget.setLayout(row2_layout)
        layout.addWidget(row2_widget, 1, 0, 1, 9)
        self.custom_holiday_box.setLayout(layout)
        self.main_layout.addWidget(self.custom_holiday_box)

    def build_summary_section(self):
        self.summary_box = QGroupBox("Summary")
        layout = QHBoxLayout()

        self.summary_user = QLabel("User: -")
        self.summary_holiday = QLabel("Holiday Date: -")
        self.summary_window = QLabel("Window: -")
        self.summary_rows = QLabel("Rows Loaded: 0")
        self.summary_selected = QLabel("Rows Selected: 0")
        self.summary_actions = QLabel("Rows with Actions: 0")

        layout.addWidget(self.summary_user)
        layout.addWidget(self.summary_holiday)
        layout.addWidget(self.summary_window)
        layout.addWidget(self.summary_rows)
        layout.addWidget(self.summary_selected)
        layout.addWidget(self.summary_actions)
        layout.addStretch()

        self.summary_box.setLayout(layout)
        self.main_layout.addWidget(self.summary_box)
    

    def build_paging_section(self):
        self.paging_box = QGroupBox("Date Navigation")
        layout = QHBoxLayout()

        self.prev_date_button = QPushButton("← Previous Day")
        self.next_date_button = QPushButton("Next Day →")
        self.jump_holiday_button = QPushButton("Jump to Holiday Date")

        self.page_date_label = QLabel("Viewing Date: -")
        self.page_index_label = QLabel("Page: 0 / 0")

        layout.addWidget(self.prev_date_button)
        layout.addWidget(self.next_date_button)
        layout.addWidget(self.jump_holiday_button)
        layout.addWidget(self.page_date_label)
        layout.addWidget(self.page_index_label)
        layout.addStretch()

        self.paging_box.setLayout(layout)
        self.main_layout.addWidget(self.paging_box)


    def build_filter_section(self):
        self.filter_box = QGroupBox("Filters")
        layout = QHBoxLayout()

        self.database_filter_button = QPushButton("Database ▾")
        self.country_filter_button = QPushButton("Country ▾")
        self.holiday_type_filter_button = QPushButton("Holiday Type ▾")
        self.clear_all_filters_button = QPushButton("Clear All Filters")

        self.active_filters_label = QLabel("Active Filters: None")
        self.active_filters_label.setToolTip("")

        layout.addWidget(self.database_filter_button)
        layout.addWidget(self.country_filter_button)
        layout.addWidget(self.holiday_type_filter_button)
        layout.addWidget(self.clear_all_filters_button)
        layout.addWidget(self.active_filters_label)
        layout.addStretch()

        self.filter_box.setLayout(layout)
        self.main_layout.addWidget(self.filter_box)


    def build_table_section(self):
        self.table_box = QGroupBox("Planner Table")
        layout = QVBoxLayout()

        self.table = QTableWidget()
        self.table.setColumnCount(14)
        self.table.setHorizontalHeaderLabels([
            "target_date",
            "time",
            "database",
            "country",
            "group",
            "update",
            "procedures",
            "holiday_name",
            "holiday_type",
            "planned_action",
            "planned_note",
            "move_mode",
            "move_to_date",
            "move_to_time",
        ])

        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)

        layout.addWidget(self.table)
        self.table_box.setLayout(layout)
        self.main_layout.addWidget(self.table_box)

        header = self.table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        header.setSortIndicatorShown(True)
        header.setSectionsClickable(True)
        header.setSortIndicator(-1, Qt.SortOrder.AscendingOrder)


    def build_action_section(self):
        self.action_box = QGroupBox("Action Editor")
        layout = QGridLayout()
        layout.setHorizontalSpacing(8)
        layout.setVerticalSpacing(6)
        layout.setContentsMargins(6, 6, 6, 6)

        # Row 0: Action + Note
        self.action_combo = QComboBox()
        self.action_combo.addItems(["", "ADD_NOTE", "MARK_DONE", "MOVE_DATE", "MOVE_TIME"])
        self.action_combo.setFixedWidth(140)

        self.note_input = QTextEdit()
        self.note_input.setFixedHeight(70)
        self.note_input.setPlainText("AUTOHOL: ")

        layout.addWidget(QLabel("Action:"), 0, 0)
        layout.addWidget(self.action_combo, 0, 1)
        layout.addWidget(QLabel("Note:"), 0, 2)
        layout.addWidget(self.note_input, 0, 3, 2, 5)

        # Row 1: Move fields
        self.move_mode_combo = QComboBox()
        self.move_mode_combo.addItems(["", "next_business_day", "next_calendar_day", "specific_date"])
        self.move_mode_combo.setFixedWidth(170)

        self.move_date_input = QDateEdit()
        self.move_date_input.setCalendarPopup(True)
        self.move_date_input.setDisplayFormat("yyyy-MM-dd")
        self.move_date_input.setDate(QDate.currentDate())
        self.move_date_input.setFixedWidth(130)

        self.move_time_input = QTimeEdit()
        self.move_time_input.setDisplayFormat("hh:mm:ss AP")
        self.move_time_input.setFixedWidth(130)

        layout.addWidget(QLabel("Move Mode:"), 2, 0)
        layout.addWidget(self.move_mode_combo, 2, 1)
        layout.addWidget(QLabel("Move To Date:"), 2, 2)
        layout.addWidget(self.move_date_input, 2, 3)
        layout.addWidget(QLabel("Move To Time:"), 2, 4)
        layout.addWidget(self.move_time_input, 2, 5)

        # Row 2: Buttons
        self.apply_action_button = QPushButton("Apply to Selected Rows")
        self.clear_action_button = QPushButton("Clear Action for Selected Rows")
        self.save_button = QPushButton("Save Planner Log")

        button_row_layout = QHBoxLayout()
        button_row_layout.setContentsMargins(0, 0, 0, 0)
        button_row_layout.setSpacing(8)
        button_row_layout.addStretch()
        button_row_layout.addWidget(self.apply_action_button)
        button_row_layout.addWidget(self.clear_action_button)
        button_row_layout.addWidget(self.save_button)

        button_row_widget = QWidget()
        button_row_widget.setLayout(button_row_layout)
        layout.addWidget(button_row_widget, 3, 0, 1, 8)

        self.action_box.setLayout(layout)
        self.main_layout.addWidget(self.action_box)


    def update_action_editor_visibility(self):
        action = self.action_combo.currentText().strip()
        move_mode = self.move_mode_combo.currentText().strip()

        is_move_date = action == "MOVE_DATE"
        is_move_time = action == "MOVE_TIME"
        is_move_action = is_move_date or is_move_time

        self.move_mode_combo.setEnabled(is_move_date)
        self.move_date_input.setEnabled(is_move_date and move_mode == "specific_date")
        self.move_time_input.setEnabled(is_move_action)

    # ----------------------------
    # Paging helpers
    # ----------------------------
    def rebuild_date_pages_from_filtered(self):
        self.page_dates = sorted({
            row.get("target_date", "")
            for row in self.filtered_planner_rows
            if row.get("target_date", "")
        })

        self.current_page_index = 0
        self.holiday_page_index = 0

        holiday_date_str = self.holiday_date_input.date().toString("yyyy-MM-dd")
        if holiday_date_str in self.page_dates:
            self.holiday_page_index = self.page_dates.index(holiday_date_str)
            self.current_page_index = self.holiday_page_index


    def get_current_page_date(self):
        if not self.page_dates:
            return None
        return self.page_dates[self.current_page_index]


    def get_rows_for_current_page(self):
        current_date = self.get_current_page_date()
        if current_date is None:
            return []

        return [
            row for row in self.filtered_planner_rows
            if row.get("target_date", "") == current_date
        ]


    def load_current_page(self):
        rows = self.get_rows_for_current_page()
        rows = self.sort_rows(rows, self.current_sort_field, self.current_sort_order)
        self.current_page_rows = rows
        self.load_rows_into_table(self.current_page_rows)
        self.update_paging_labels()


    def update_paging_labels(self):
        if not self.page_dates:
            self.page_date_label.setText("Viewing Date: -")
            self.page_index_label.setText("Page: 0 / 0")
            self.prev_date_button.setEnabled(False)
            self.next_date_button.setEnabled(False)
            self.jump_holiday_button.setEnabled(False)
            return

        current_date = self.page_dates[self.current_page_index]
        self.page_date_label.setText(f"Viewing Date: {current_date}")
        self.page_index_label.setText(f"Page: {self.current_page_index + 1} / {len(self.page_dates)}")

        self.prev_date_button.setEnabled(self.current_page_index > 0)
        self.next_date_button.setEnabled(self.current_page_index < len(self.page_dates) - 1)
        self.jump_holiday_button.setEnabled(True)


    def go_to_previous_page(self):
        if not self.page_dates:
            return
        if self.current_page_index > 0:
            self.current_page_index -= 1
            self.load_current_page()


    def go_to_next_page(self):
        if not self.page_dates:
            return
        if self.current_page_index < len(self.page_dates) - 1:
            self.current_page_index += 1
            self.load_current_page()


    def go_to_holiday_page(self):
        if not self.page_dates:
            return
        self.current_page_index = self.holiday_page_index
        self.load_current_page()


    # ----------------------------
    # Table helpers
    # ----------------------------
    def load_rows_into_table(self, rows):
        self.table.setRowCount(len(rows))

        for row_idx, row in enumerate(rows):
            values = [
                row.get("target_date", ""),
                row.get("time", ""),
                row.get("database", ""),
                row.get("country", ""),
                row.get("group", ""),
                row.get("update", ""),
                row.get("procedures", ""),
                row.get("holiday_name", ""),
                row.get("holiday_type", ""),
                row.get("planned_action", ""),
                row.get("planned_note", ""),
                row.get("move_mode", ""),
                row.get("move_to_date", ""),
                row.get("move_to_time", ""),
            ]

            for col_idx, value in enumerate(values):
                item = QTableWidgetItem(str(value))
                self.table.setItem(row_idx, col_idx, item)
    

    def get_selected_row_indexes(self):
        selected = self.table.selectionModel().selectedRows()
        return sorted(index.row() for index in selected)

    def update_selected_count(self):
        selected_rows = self.get_selected_row_indexes()
        self.summary_selected.setText(f"Rows Selected: {len(selected_rows)}")

    def update_action_count(self):
        count = sum(1 for row in self.planner_rows if row.get("planned_action", "").strip())
        self.summary_actions.setText(f"Rows with Actions: {count}")

    def handle_table_double_click(self, row, column):
        header = self.table.horizontalHeaderItem(column).text()
        if header != "procedures":
            return

        item = self.table.item(row, column)
        if item is None:
            return

        path = item.text().strip()
        if not path:
            return

        if os.path.exists(path):
            os.startfile(path)
        else:
            QMessageBox.warning(self, "File not found", f"Procedure file does not exist:\n{path}")


    # ----------------------------
    # Sorting helpers
    # ----------------------------

    def get_table_column_field_map(self):
        return {
            0: "target_date",
            1: "time",
            2: "database",
            3: "country",
            4: "group",
            5: "update",
            6: "procedures",
            7: "holiday_name",
            8: "holiday_type",
            9: "planned_action",
            10: "planned_note",
            11: "move_mode",
            12: "move_to_date",
        }
    

    def handle_header_sort(self, column_index):
        column_map = self.get_table_column_field_map()
        sort_field = column_map.get(column_index, "")

        if not sort_field:
            return

        header = self.table.horizontalHeader()

        if self.current_sort_field != sort_field:
            self.current_sort_field = sort_field
            self.current_sort_order = "ascending"

            header.setSortIndicator(column_index, Qt.SortOrder.AscendingOrder)

        else:
            if self.current_sort_order == "ascending":
                self.current_sort_order = "descending"
                header.setSortIndicator(column_index, Qt.SortOrder.DescendingOrder)

            elif self.current_sort_order == "descending":
                self.current_sort_field = ""
                self.current_sort_order = ""
                header.setSortIndicator(-1, Qt.SortOrder.AscendingOrder)

            else:
                self.current_sort_order = "ascending"
                header.setSortIndicator(column_index, Qt.SortOrder.AscendingOrder)

        self.rebuild_date_pages_from_filtered()
        self.load_current_page()


    def sort_rows(self, rows, sort_field, sort_order):
        if not sort_field:
            return sorted(rows, key=lambda r: r.get("_row_id", 0))

        reverse = sort_order == "descending"

        def sort_key(row):
            value = row.get(sort_field, "")

            if sort_field == "time":
                text = (value or "").strip()
                if not text:
                    return (1, "")
                try:
                    dt = datetime.strptime(text, "%I:%M %p")
                    return (0, dt.time(), row.get("_row_id", 0))
                except ValueError:
                    return (0, text.lower(), row.get("_row_id", 0))

            return ((value or "").strip().lower(), row.get("_row_id", 0))

        return sorted(rows, key=sort_key, reverse=reverse)


    def apply_sort_to_current_page(self):
        self.current_sort_field = self.sort_field_combo.currentText().strip()
        self.current_sort_order = self.sort_order_combo.currentText().strip() or "ascending"
        self.load_current_page()


    def clear_sort_for_current_page(self):
        self.current_sort_field = ""
        self.current_sort_order = "ascending"
        self.sort_field_combo.setCurrentIndex(0)
        self.sort_order_combo.setCurrentText("ascending")
        self.load_current_page()

    # ----------------------------
    # Custom holiday helpers
    # ----------------------------

    def normalize_country(self, country: str) -> str:
        return (country or "").strip().lower()
    
    
    def require_planner_user_for_custom_holidays(self):
        planner_user = self.user_input.text().strip()
        if not planner_user:
            QMessageBox.warning(
                self,
                "Missing user",
                "Please enter Planner User before adding or importing custom holidays."
            )
            return False
        return True
    
    
    def get_custom_holiday_path(self):
        planner_user = self.user_input.text().strip().lower()

        base_folder = r"F:\intdaily\autohol\custom_hol"
        os.makedirs(base_folder, exist_ok=True)

        if not planner_user:
            return os.path.join(base_folder, "custom_holidays_default.json")

        return os.path.join(base_folder, f"custom_holidays_{planner_user}.json")
    

    
    def custom_holiday_file_exists(self):
        return os.path.exists(self.get_custom_holiday_path())
    

    def load_custom_holidays(self):
        path = self.get_custom_holiday_path()

        if not os.path.exists(path):
            return []

        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
                return data if isinstance(data, list) else []
        except Exception as e:
            QMessageBox.critical(
                self,
                "Load Error",
                f"Failed to load custom holidays:\n{e}"
            )
            return []
        

    def save_custom_holidays(self, holidays):
        path = self.get_custom_holiday_path()
        folder = os.path.dirname(path)
        os.makedirs(folder, exist_ok=True)

        with open(path, "w", encoding="utf-8") as f:
            json.dump(holidays, f, ensure_ascii=False, indent=2)


    def add_custom_holiday(self):
        if not self.require_planner_user_for_custom_holidays():
            return

        country = self.custom_country_input.text().strip()
        holiday_date = self.custom_date_input.date().toString("yyyy-MM-dd")
        holiday_name = self.custom_name_input.text().strip()
        holiday_observance = self.custom_observance_combo.currentText().strip()

        if not country or not holiday_name or not holiday_observance:
            QMessageBox.warning(
                self,
                "Missing fields",
                "Please enter Country, Holiday Name, and Holiday Observance."
            )
            return

        try:
            datetime.strptime(holiday_date, "%Y-%m-%d")
        except ValueError:
            QMessageBox.warning(
                self,
                "Invalid date",
                "Holiday Date must be in yyyy-MM-dd format."
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
                QMessageBox.warning(
                    self,
                    "Duplicate holiday",
                    "This exact custom holiday already exists for this user."
                )
                return

        holidays.append({
            "country": country,
            "holiday_date": holiday_date,
            "holiday_name": holiday_name,
            "holiday_observance": holiday_observance,
            "source": "custom",
            "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        })

        try:
            self.save_custom_holidays(holidays)

            QMessageBox.information(
                self,
                "Custom Holiday Added",
                f"Added custom holiday:\n{country} | {holiday_date} | {holiday_name} | {holiday_observance}"
            )

            self.custom_country_input.clear()
            self.custom_name_input.clear()
            self.custom_observance_combo.setCurrentIndex(0)

        except Exception as e:
            QMessageBox.critical(
                self,
                "Save Error",
                f"Failed to save custom holiday:\n{e}"
            )


    def load_merged_holidays(self):
        holiday_dict = load_holiday_records(self.default_holiday_path)

        custom_holidays = self.load_custom_holidays()
        for item in custom_holidays:
            country = self.normalize_country(item.get("country", ""))
            holiday_date = (item.get("holiday_date") or "").strip()
            holiday_name = (item.get("holiday_name") or "").strip()
            holiday_observance = (item.get("holiday_observance") or "").strip()

            if not country or not holiday_date:
                continue

            try:
                hdate = datetime.strptime(holiday_date, "%Y-%m-%d").date()
            except ValueError:
                continue

            holiday_dict.setdefault(country, [])
            holiday_dict[country].append({
                "date": hdate,
                "holiday_name": holiday_name,
                "holiday_observance": holiday_observance,
                "source": "custom",
            })

        return holiday_dict
    

    def validate_custom_holiday_row(self, row):
        country = (row.get("country") or "").strip()
        holiday_date = (row.get("holiday_date") or "").strip()
        holiday_name = (row.get("holiday_name") or "").strip()
        holiday_observance = (row.get("holiday_observance") or "").strip()

        if not country or not holiday_date or not holiday_name:
            return None, "Missing required field(s): country, holiday_date, or holiday_name."

        try:
            datetime.strptime(holiday_date, "%Y-%m-%d")
        except ValueError:
            return None, f"Invalid holiday_date '{holiday_date}'. Expected YYYY-MM-DD."

        cleaned = {
            "country": country,
            "holiday_date": holiday_date,
            "holiday_name": holiday_name,
            "holiday_observance": holiday_observance,
        }
        return cleaned, None


    def custom_holiday_exists(self, holidays, new_row):
        new_country = normalize_country(new_row.get("country", ""))
        new_date = (new_row.get("holiday_date") or "").strip()
        new_name = (new_row.get("holiday_name") or "").strip()

        for item in holidays:
            existing_country = normalize_country(item.get("country", ""))
            existing_date = (item.get("holiday_date") or "").strip()
            existing_name = (item.get("holiday_name") or "").strip()

            # Exact duplicate
            if (
                existing_country == new_country
                and existing_date == new_date
                and existing_name == new_name
            ):
                return True, "exact"

            # Same country + date, different name
            if (
                existing_country == new_country
                and existing_date == new_date
                and existing_name != new_name
            ):
                return True, "same_country_date"

        return False, ""


    def import_custom_holiday_csv(self):
        if not self.require_planner_user_for_custom_holidays():
            return

        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Select Custom Holiday CSV",
            "",
            "CSV Files (*.csv)"
        )

        if not file_path:
            return

        try:
            imported_rows = []
            with open(file_path, "r", encoding="utf-8-sig", newline="") as f:
                reader = csv.DictReader(f)

                required_columns = {
                    "country",
                    "holiday_date",
                    "holiday_name",
                    "holiday_observance",
                }

                csv_columns = {col.strip() for col in (reader.fieldnames or [])}
                missing_columns = required_columns - csv_columns
                if missing_columns:
                    QMessageBox.warning(
                        self,
                        "Invalid CSV Format",
                        "CSV is missing required columns:\n"
                        + ", ".join(sorted(missing_columns))
                    )
                    return

                for row in reader:
                    country = (row.get("country") or "").strip()
                    holiday_date = (row.get("holiday_date") or "").strip()
                    holiday_name = (row.get("holiday_name") or "").strip()
                    holiday_observance = (row.get("holiday_observance") or "").strip()

                    if not country or not holiday_date or not holiday_name or not holiday_observance:
                        continue

                    try:
                        datetime.strptime(holiday_date, "%Y-%m-%d")
                    except ValueError:
                        continue

                    imported_rows.append({
                        "country": country,
                        "holiday_date": holiday_date,
                        "holiday_name": holiday_name,
                        "holiday_observance": holiday_observance,
                        "source": "custom_import",
                        "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    })

            if not imported_rows:
                QMessageBox.information(
                    self,
                    "No Valid Rows",
                    "No valid custom holiday rows were found in the CSV."
                )
                return

            existing_holidays = self.load_custom_holidays()
            existing_keys = {
                (
                    self.normalize_country(item.get("country", "")),
                    (item.get("holiday_date") or "").strip(),
                    (item.get("holiday_name") or "").strip(),
                )
                for item in existing_holidays
            }

            added_count = 0
            for row in imported_rows:
                row_key = (
                    self.normalize_country(row.get("country", "")),
                    row.get("holiday_date", "").strip(),
                    row.get("holiday_name", "").strip(),
                )
                if row_key not in existing_keys:
                    existing_holidays.append(row)
                    existing_keys.add(row_key)
                    added_count += 1

            self.save_custom_holidays(existing_holidays)

            QMessageBox.information(
                self,
                "Import Complete",
                f"Imported {added_count} new custom holiday rows."
            )

        except Exception as e:
            QMessageBox.critical(
                self,
                "Import Error",
                f"Failed to import custom holiday CSV:\n{e}"
            )


    def show_custom_holiday_csv_help(self):
        dialog = QDialog(self)
        dialog.setWindowTitle("Custom Holiday CSV Format")
        dialog.resize(520, 320)
        layout = QVBoxLayout(dialog)
        text_box = QPlainTextEdit()
        text_box.setReadOnly(True)
        text_box.setPlainText(
            "Required CSV columns:\n"
            "country\n"
            "holiday_date\n"
            "holiday_name\n"
            "holiday_observance\n\n"
            "Date format:\n"
            "YYYY-MM-DD\n\n"
            "Example:\n"
            "country,holiday_date,holiday_name,holiday_observance\n"
        )
        close_button = QPushButton("Close")
        close_button.clicked.connect(dialog.accept)
        button_row = QHBoxLayout()
        button_row.addStretch()
        button_row.addWidget(close_button)
        layout.addWidget(text_box)
        layout.addLayout(button_row)
        dialog.exec()

    # ----------------------------
    # Backend loaders
    # ----------------------------
    def load_dw_entries_with_assignments(self):
        a = Autocalendar()
        a.get_dw()
        dw_entries = a.parse_entries()

        b = Assignments()
        dw_entries = b.assign(dw_entries, attach=True)
        return dw_entries

    # ----------------------------
    # Planner actions
    # ----------------------------
    def clear_table(self):
        self.planner_rows = []
        self.page_dates = []
        self.current_page_index = 0
        self.current_page_rows = []
        self.holiday_page_index = 0

        self.load_rows_into_table([])
        self.update_paging_labels()
        self.filtered_planner_rows = []

        self.summary_user.setText("User: -")
        self.summary_holiday.setText("Holiday Date: -")
        self.summary_window.setText("Window: -")
        self.summary_rows.setText("Rows Loaded: 0")
        self.summary_selected.setText("Rows Selected: 0")
        self.summary_actions.setText("Rows with Actions: 0")

        self.current_sort_field = ""
        self.current_sort_order = ""
        self.table.horizontalHeader().setSortIndicator(-1, Qt.SortOrder.AscendingOrder)

        self.selected_database_filters = set()
        self.selected_country_filters = set()
        self.selected_holiday_type_filters = set()
        self.filtered_planner_rows = []

        self.active_filters_label.setText("Active Filters: None")
        self.active_filters_label.setToolTip("")


    def generate_planner_rows(self):
        planner_user = self.user_input.text().strip()
        holiday_date = self.holiday_date_input.date().toPyDate()
        days_before = self.days_before_input.value()
        days_after = self.days_after_input.value()

        try:
            holiday_dict = self.load_merged_holidays()
            dw_entries = self.load_dw_entries_with_assignments()
            holiday_countries = get_holiday_countries_for_date(holiday_dict, holiday_date)

            if planner_user:
                base_entries = filter_entries_for_user(dw_entries, planner_user)
                relevant_countries = get_user_holiday_countries(base_entries, holiday_countries)
                country_filtered_entries = filter_entries_for_countries(base_entries, relevant_countries)
                summary_user_text = f"User: {planner_user}"
                planner_user_value = planner_user
            else:
                base_entries = [
                    entry for entry in dw_entries
                    if normalize_country(entry.get("country", "")) not in {"", "various"}
                ]
                relevant_countries = holiday_countries
                country_filtered_entries = filter_entries_for_countries(base_entries, relevant_countries)
                summary_user_text = "User: ALL USERS"
                planner_user_value = "ALL_USERS"

            candidate_rows = build_window_task_candidates(
                country_filtered_entries,
                holiday_date,
                days_before=days_before,
                days_after=days_after,
            )
            annotated_rows = annotate_holiday_context(candidate_rows, holiday_dict, holiday_date)
            self.planner_rows = build_planner_rows(
                annotated_rows,
                planner_user_value,
                holiday_date,
                days_before=days_before,
                days_after=days_after,
            )

            self.filtered_planner_rows = list(self.planner_rows)
            self.update_active_filters_label()
            self.rebuild_date_pages_from_filtered()
            self.load_current_page()

            w_start, w_end = date_window(holiday_date, days_before, days_after)
            self.summary_user.setText(summary_user_text)
            self.summary_holiday.setText(f"Holiday Date: {holiday_date.isoformat()}")
            self.summary_window.setText(f"Window: {w_start.isoformat()} to {w_end.isoformat()}")
            self.summary_rows.setText(f"Rows Loaded: {len(self.planner_rows)}")
            self.summary_selected.setText("Rows Selected: 0")
            self.update_action_count()

            if planner_user and not base_entries:
                QMessageBox.information(
                    self,
                    "No assigned entries",
                    f"No DW entries were found for planner user '{planner_user}'."
                )
                return

            if not relevant_countries:
                QMessageBox.information(
                    self,
                    "No relevant holiday countries",
                    f"No relevant countries were found for {holiday_date.isoformat()}."
                )
                return

            if not self.planner_rows:
                QMessageBox.information(
                    self,
                    "No planner rows",
                    "No scheduled planner rows were found in the visible window."
                )

        except Exception as e:
            QMessageBox.critical(self, "Generate failed", str(e))


    def get_filter_options(self, field_name):
        return sorted({
            str(row.get(field_name, "")).strip()
            for row in self.planner_rows
            if str(row.get(field_name, "")).strip()
        })


    def open_database_filter_popup(self):
        popup = MultiSelectFilterPopup("Database Filter", self)
        popup.set_options(
            self.get_filter_options("database"),
            self.selected_database_filters,
        )
        if popup.exec():
            self.selected_database_filters = popup.get_selected_values()
            self.apply_filters()


    def open_country_filter_popup(self):
        popup = MultiSelectFilterPopup("Country Filter", self)
        popup.set_options(
            self.get_filter_options("country"),
            self.selected_country_filters,
        )
        if popup.exec():
            self.selected_country_filters = popup.get_selected_values()
            self.apply_filters()


    def open_holiday_type_filter_popup(self):
        popup = MultiSelectFilterPopup("Holiday Type Filter", self)
        popup.set_options(
            self.get_filter_options("holiday_type"),
            self.selected_holiday_type_filters,
        )
        if popup.exec():
            self.selected_holiday_type_filters = popup.get_selected_values()
            self.apply_filters()

    
    def update_active_filters_label(self):
        parts = []
        tooltip_lines = []

        if self.selected_database_filters:
            parts.append(f"Database({len(self.selected_database_filters)})")
            tooltip_lines.append(
                "Database: " + ", ".join(sorted(self.selected_database_filters))
            )

        if self.selected_country_filters:
            parts.append(f"Country({len(self.selected_country_filters)})")
            tooltip_lines.append(
                "Country: " + ", ".join(sorted(self.selected_country_filters))
            )

        if self.selected_holiday_type_filters:
            parts.append(f"Holiday Type({len(self.selected_holiday_type_filters)})")
            tooltip_lines.append(
                "Holiday Type: " + ", ".join(sorted(self.selected_holiday_type_filters))
            )

        if parts:
            self.active_filters_label.setText("Active Filters: " + ", ".join(parts))
            self.active_filters_label.setToolTip("\n".join(tooltip_lines))
        else:
            self.active_filters_label.setText("Active Filters: None")
            self.active_filters_label.setToolTip("")


    def apply_filters(self):
        filtered = []

        for row in self.planner_rows:
            if self.selected_database_filters and row.get("database", "") not in self.selected_database_filters:
                continue
            if self.selected_country_filters and row.get("country", "") not in self.selected_country_filters:
                continue
            if self.selected_holiday_type_filters and row.get("holiday_type", "") not in self.selected_holiday_type_filters:
                continue
            filtered.append(row)

        self.filtered_planner_rows = filtered
        self.rebuild_date_pages_from_filtered()
        self.load_current_page()
        self.update_active_filters_label()


    def clear_all_filters(self):
        self.selected_database_filters = set()
        self.selected_country_filters = set()
        self.selected_holiday_type_filters = set()

        self.filtered_planner_rows = list(self.planner_rows)
        self.rebuild_date_pages_from_filtered()
        self.load_current_page()
        self.update_active_filters_label()


    def apply_action_to_selected_rows(self):
        selected_rows = self.get_selected_row_indexes()
        self.summary_selected.setText(f"Rows Selected: {len(selected_rows)}")

        if not selected_rows:
            QMessageBox.warning(self, "No selection", "Please select one or more rows.")
            return

        planned_action = self.action_combo.currentText().strip()
        planned_note = self.get_user_note_text()
        move_mode = self.move_mode_combo.currentText().strip()
        move_to_date = self.move_date_input.date().toString("yyyy-MM-dd")
        move_to_time = self.move_time_input.time().toString("hh:mm:ss AP")
        action_date = datetime.now().strftime("%Y-%m-%d")

        if not planned_action:
            QMessageBox.warning(self, "Missing action", "Please choose a planned action.")
            return

        if planned_action == "ADD_NOTE":
            if not self.has_custom_note_text(planned_note):
                QMessageBox.warning(
                    self,
                    "Missing note",
                    "ADD_NOTE requires note text after 'AUTOHOL:'."
                )
                return

        elif planned_action == "MARK_DONE":
            if not self.has_custom_note_text(planned_note):
                planned_note = f"AUTOHOL: Marked as Done {action_date}"

        elif planned_action == "MOVE_DATE":
            if not move_mode:
                QMessageBox.warning(self, "Missing move mode", "MOVE_DATE requires a move mode.")
                return

            if move_mode == "specific_date":
                if not move_to_date:
                    QMessageBox.warning(self, "Missing move date", "Please choose a specific move date.")
                    return
                default_move_note = f"AUTOHOL: Moved to {move_to_date}"
            else:
                default_move_note = f"AUTOHOL: Moved to {action_date}"

            if not self.has_custom_note_text(planned_note):
                planned_note = default_move_note

        elif planned_action == "MOVE_TIME":
            if not move_to_time:
                QMessageBox.warning(self, "Missing move time", "Please choose a new time.")
                return

            if not self.has_custom_note_text(planned_note):
                planned_note = f"AUTOHOL: Moved to {move_to_time}"

        selected_row_ids = [
            self.current_page_rows[row_idx]["_row_id"]
            for row_idx in selected_rows
        ]

        for row in self.filtered_planner_rows:
            if row.get("_row_id") in selected_row_ids:
                row["planned_action"] = planned_action
                row["planned_note"] = planned_note
                row["move_mode"] = move_mode if planned_action == "MOVE_DATE" else ""
                row["move_to_date"] = move_to_date if planned_action == "MOVE_DATE" else ""
                row["move_to_time"] = move_to_time if planned_action == "MOVE_TIME" else ""

        self.load_current_page()
        self.note_input.setPlainText("AUTOHOL: ")

    def clear_action_for_selected_rows(self):
        selected_rows = self.get_selected_row_indexes()
        self.summary_selected.setText(f"Rows Selected: {len(selected_rows)}")

        if not selected_rows:
            QMessageBox.warning(self, "No selection", "Please select one or more rows.")
            return

        selected_row_ids = [
            self.current_page_rows[row_idx]["_row_id"]
            for row_idx in selected_rows
        ]

        for row in self.filtered_planner_rows:
            if row.get("_row_id") in selected_row_ids:
                row["planned_action"] = ""
                row["planned_note"] = ""
                row["move_mode"] = ""
                row["move_to_date"] = ""
                row["move_to_time"] = ""

        self.load_current_page()
        self.note_input.setPlainText("AUTOHOL: ")

    def ensure_autohol_prefix(self, text: str) -> str:
        text = (text or "").strip()

        if not text:
            return "AUTOHOL:"
        if text.startswith("AUTOHOL:"):
            return text
        return f"AUTOHOL:{text}"
    
    def get_user_note_text(self) -> str:
        return self.ensure_autohol_prefix(self.note_input.toPlainText())
    
    def has_custom_note_text(self, note_text: str) -> bool:
        normalized = (note_text or "").strip()
        return normalized not in {"", "AUTOHOL:", "AUTOHOL:"}


    def save_planner_log(self):
        action_rows = [
            row for row in self.planner_rows
            if (row.get("planned_action") or "").strip()
        ]

        if not action_rows:
            QMessageBox.information(
                self,
                "No actions to save",
                "There are no planner rows with actions to save."
            )
            return

        try:
            json_path, csv_path = self.get_output_log_paths()

            json_count = write_planner_log_json(json_path, action_rows)
            csv_count = write_planner_log_csv(csv_path, action_rows)

            QMessageBox.information(
                self,
                "Planner Log Saved",
                (
                    f"Saved {json_count} rows to JSON:\n{json_path}\n\n"
                    f"Saved {csv_count} rows to CSV:\n{csv_path}"
                )
            )

        except Exception as e:
            QMessageBox.critical(self, "Save failed", str(e))


    def get_output_log_paths(self):
        planner_user = self.user_input.text().strip()
        user_part = planner_user.lower() if planner_user else "all_users"

        json_dir = r"F:\intdaily\autohol\planner\json"
        csv_dir = r"F:\intdaily\autohol\planner\csv"

        os.makedirs(json_dir, exist_ok=True)
        os.makedirs(csv_dir, exist_ok=True)

        json_path = os.path.join(json_dir, f"autohol_planner_log_{user_part}.json")
        csv_path = os.path.join(csv_dir, f"autohol_planner_log_{user_part}.csv")

        return json_path, csv_path


def main():
    app = QApplication(sys.argv)
    window = PlannerWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()