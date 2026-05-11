import csv
import json
import os
import sys
import calendar as pycalendar
from collections import defaultdict
from datetime import datetime, timedelta

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from PyQt6.QtCore import QDate, QPoint, QTime, Qt
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (
    QApplication,
    QAbstractItemView,
    QCalendarWidget,
    QComboBox,
    QDateEdit,
    QDialog,
    QFileDialog,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QTimeEdit,
    QVBoxLayout,
    QWidget,
)

from autohol.holidays import add_holiday_record, load_holiday_records
from autohol.future_holiday_planner import (
    annotate_holiday_context,
    build_planner_rows,
    build_window_task_candidates,
    date_window,
    filter_entries_for_countries,
    filter_entries_for_user,
    get_holiday_countries_for_date,
    get_user_holiday_countries,
    normalize_country,
    write_planner_log_csv,
    write_planner_log_json,
)
from autohol.dw_source_existing_future import Assignments, Autocalendar


MODERN_STYLE = """
QMainWindow { background: #f5f8fb; }
QGroupBox { font-weight: 600; border: 1px solid #e1e8f5; border-radius: 8px; margin-top: 6px; padding: 8px; background: transparent; }
QGroupBox::title { subcontrol-origin: margin; subcontrol-position: top left; padding: 0 6px; }
QLabel { color: #223047; }
QPushButton {
    background: qlineargradient(x1:0,y1:0,x2:0,y2:1, stop:0 #4a83d8, stop:1 #3571c6);
    color: white;
    border: none;
    border-radius: 6px;
    padding: 6px 10px;
}
QPushButton:disabled { background: #9fb5e0; color: #eaf2ff; }
QPushButton:hover { background: #356bb0; }
QTableWidget {
    background: white;
    alternate-background-color: #f7fbff;
    gridline-color: #e1e8f0;
    selection-background-color: #cfe1ff;
    selection-color: #05293a;
}
QHeaderView::section {
    background: #eef4ff;
    padding: 6px;
    border: 1px solid #d6e4fb;
}
QTextEdit, QPlainTextEdit, QLineEdit, QDateEdit, QTimeEdit, QComboBox {
    background: white;
    border: 1px solid #dfe9f7;
    border-radius: 6px;
    padding: 4px;
}
QTableWidget::item { padding: 4px; }
QScrollBar:vertical { width: 10px; }
"""


CALENDAR_QSS = """
QCalendarWidget {
    background: white;
    border: 1px solid #e6f0ff;
    border-radius: 8px;
}
QCalendarWidget QToolButton {
    background: transparent;
    color: #274060;
    font-weight: 600;
}
QCalendarWidget QAbstractItemView {
    selection-background-color: #cfe1ff;
    selection-color: #05293a;
    outline: none;
}
QCalendarWidget QWidget { color: #223047; }
QCalendarWidget QSpinBox { background: transparent; }
QCalendarWidget QTableView { border: none; }
QCalendarWidget QTableView::item { border-radius: 6px; }
QCalendarWidget::navigation { background: transparent; }
"""


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

        self.search_input.textChanged.connect(self.filter_items)
        self.select_all_button.clicked.connect(self.select_all_visible)
        self.clear_button.clicked.connect(self.clear_all_visible)
        self.ok_button.clicked.connect(self.accept)
        self.cancel_button.clicked.connect(self.reject)

    def set_options(self, options, selected_values=None):
        self.all_options = list(options)
        selected_values = set(selected_values or [])
        use_all_selected = len(selected_values) == 0

        self.list_widget.clear()
        for value in self.all_options:
            item = QListWidgetItem(value)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(
                Qt.CheckState.Checked
                if use_all_selected or value in selected_values
                else Qt.CheckState.Unchecked
            )
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


class HolidayLookupPopup(QDialog):
    def __init__(self, owner, parent=None):
        super().__init__(parent, Qt.WindowType.Popup)
        self.owner = owner
        self.visible_month_date = None
        self.selected_date = None

        self.setWindowTitle("Holiday Date Lookup")
        self.resize(980, 420)

        layout = QVBoxLayout(self)

        header_layout = QHBoxLayout()
        self.prev_button = QPushButton("Previous Month")
        self.next_button = QPushButton("Next Month")
        self.month_label = QLabel("Month: -")
        self.scope_label = QLabel("Managed Countries: -")
        self.scope_label.setWordWrap(True)

        header_layout.addWidget(self.prev_button)
        header_layout.addWidget(self.next_button)
        header_layout.addWidget(self.month_label)
        header_layout.addWidget(self.scope_label)
        header_layout.addStretch()

        self.month_table = QTableWidget()
        self.month_table.setColumnCount(7)
        self.month_table.setRowCount(6)
        self.month_table.setHorizontalHeaderLabels(
            ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
        )
        self.month_table.verticalHeader().setVisible(False)
        self.month_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.month_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.month_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectItems)
        self.month_table.setWordWrap(True)
        self.month_table.setAlternatingRowColors(False)
        self.month_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        for row_index in range(6):
            self.month_table.setRowHeight(row_index, 86)

        self.hint_label = QLabel(
            "Click a day to set Holiday Date. Holidays shown depend on the current Planner User."
        )
        self.hint_label.setWordWrap(True)

        layout.addLayout(header_layout)
        layout.addWidget(self.month_table)
        layout.addWidget(self.hint_label)

        self.prev_button.clicked.connect(lambda: self.shift_month(-1))
        self.next_button.clicked.connect(lambda: self.shift_month(1))
        self.month_table.cellClicked.connect(self.handle_cell_clicked)

    def open_for(self, anchor_widget, selected_date):
        self.selected_date = selected_date
        self.visible_month_date = selected_date.replace(day=1)
        self.refresh_content()

        popup_pos = anchor_widget.mapToGlobal(QPoint(0, anchor_widget.height()))
        self.move(popup_pos)
        self.show()
        self.raise_()
        self.activateWindow()

    def refresh_if_open(self, selected_date):
        if not self.isVisible():
            return
        self.selected_date = selected_date
        self.visible_month_date = selected_date.replace(day=1)
        self.refresh_content()

    def shift_month(self, month_offset):
        month_index = (self.visible_month_date.month - 1) + month_offset
        year = self.visible_month_date.year + (month_index // 12)
        month = (month_index % 12) + 1
        self.visible_month_date = datetime(year, month, 1).date()
        self.refresh_content()

    def build_day_cell_text(self, target_date, day_matches):
        lines = [str(target_date.day)]
        if day_matches:
            first_match = day_matches[0]
            lines.append(f"{first_match['country']} | {first_match['holiday_name']}")
        return "\n".join(lines)

    def build_day_tooltip(self, day_matches):
        return "\n".join(
            f"{match['country']} | {match['holiday_name']}"
            for match in day_matches
        )

    def build_day_item(self, target_date, day_matches):
        item = QTableWidgetItem(self.build_day_cell_text(target_date, day_matches))
        item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
        item.setTextAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        item.setData(Qt.ItemDataRole.UserRole, target_date.isoformat())

        if day_matches:
            item.setBackground(QColor("#fff4d6"))
            item.setForeground(QColor("#3a2f18"))
            item.setToolTip(self.build_day_tooltip(day_matches))
        else:
            item.setBackground(QColor("#ffffff"))
            item.setForeground(QColor("#26374d"))
            item.setToolTip("")

        if target_date == self.selected_date:
            item.setBackground(QColor("#cfe1ff"))
            item.setForeground(QColor("#05293a"))

        return item

    def refresh_content(self):
        year = self.visible_month_date.year
        month = self.visible_month_date.month
        month_matches = self.owner.build_lookup_month_matches(year, month)
        relevant_countries = self.owner.get_lookup_relevant_countries()

        self.month_label.setText(f"Month: {self.visible_month_date.strftime('%B %Y')}")
        if relevant_countries:
            self.scope_label.setText("Managed Countries: " + ", ".join(relevant_countries))
        else:
            self.scope_label.setText("Managed Countries: None")

        self.month_table.clearContents()

        first_day = datetime(year, month, 1).date()
        start_column = first_day.weekday()
        days_in_month = pycalendar.monthrange(year, month)[1]

        for day in range(1, days_in_month + 1):
            target_date = datetime(year, month, day).date()
            row = (start_column + day - 1) // 7
            column = (start_column + day - 1) % 7
            item = self.build_day_item(target_date, month_matches.get(target_date, []))
            self.month_table.setItem(row, column, item)

        for row in range(6):
            for column in range(7):
                if self.month_table.item(row, column) is None:
                    empty_item = QTableWidgetItem("")
                    empty_item.setFlags(Qt.ItemFlag.NoItemFlags)
                    empty_item.setBackground(QColor("#f8fbff"))
                    self.month_table.setItem(row, column, empty_item)

    def handle_cell_clicked(self, row, column):
        item = self.month_table.item(row, column)
        if item is None:
            return
        iso_value = item.data(Qt.ItemDataRole.UserRole)
        if not iso_value:
            return
        clicked_date = datetime.strptime(iso_value, "%Y-%m-%d").date()
        self.owner.holiday_date_input.setDate(QDate(clicked_date.year, clicked_date.month, clicked_date.day))
        self.close()


class HolidayLookupDateEdit(QDateEdit):
    def __init__(self, owner):
        super().__init__(owner)
        self.owner = owner
        self.lookup_popup = HolidayLookupPopup(owner, owner)

    def showPopup(self):
        self.lookup_popup.open_for(self, self.date().toPyDate())

    def hidePopup(self):
        if self.lookup_popup.isVisible():
            self.lookup_popup.hide()

    def refresh_popup_if_open(self):
        self.lookup_popup.refresh_if_open(self.date().toPyDate())


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
        self._holiday_lookup_dw_entries = None

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
        self.user_input.textChanged.connect(self.refresh_all_holiday_lookup_calendars)
        self.holiday_date_input.dateChanged.connect(self.refresh_all_holiday_lookup_calendars)

        self.update_action_editor_visibility()
        self.update_paging_labels()
        self.update_active_filters_label()

    def build_controls_section(self):
        self.controls_box = QGroupBox("Planner Controls")
        layout = QHBoxLayout()

        self.user_input = QLineEdit()
        self.user_input.setPlaceholderText("EDM name (blank = all users)")
        self.user_input.setFixedWidth(160)

        self.holiday_date_input = HolidayLookupDateEdit(self)
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

        layout.addWidget(QLabel("Country:"), 0, 0)
        layout.addWidget(self.custom_country_input, 0, 1)
        layout.addWidget(QLabel("Holiday Date:"), 0, 2)
        layout.addWidget(self.custom_date_input, 0, 3)
        layout.addWidget(QLabel("Holiday Name:"), 0, 4)
        layout.addWidget(self.custom_name_input, 0, 5)
        layout.addWidget(QLabel("Holiday Observance:"), 0, 6)
        layout.addWidget(self.custom_observance_combo, 0, 7)
        layout.addWidget(self.add_custom_holiday_button, 0, 8)

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
        self.prev_date_button.setText("Previous Day")
        self.next_date_button.setText("Next Day")
        self.jump_holiday_button.setText("Jump to Holiday Date")

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
        self.database_filter_button.setText("Database Filter")
        self.country_filter_button.setText("Country Filter")
        self.holiday_type_filter_button.setText("Holiday Type Filter")

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
        self.table.setAlternatingRowColors(True)
        self.table.setWordWrap(False)
        self.table.verticalHeader().setVisible(False)

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
        layout.setHorizontalSpacing(10)
        layout.setVerticalSpacing(8)

        self.action_label = QLabel("Action:")
        self.note_label = QLabel("Note:")
        self.move_mode_label = QLabel("Move Mode:")
        self.move_date_label = QLabel("Move To Date:")
        self.move_time_label = QLabel("Move To Time:")
        self.action_help_label = QLabel("Choose an action to reveal the matching fields.")
        self.action_help_label.setWordWrap(True)

        self.action_combo = QComboBox()
        self.action_combo.addItems(["", "ADD_NOTE", "MARK_DONE", "MOVE_DATE", "MOVE_TIME"])

        self.note_input = QTextEdit()
        self.note_input.setPlainText("AUTOHOL:")
        self.note_input.setFixedHeight(70)

        self.move_mode_combo = QComboBox()
        self.move_mode_combo.addItems(["", "next_business_day", "next_calendar_day", "specific_date"])

        self.move_date_input = QDateEdit()
        self.move_date_input.setCalendarPopup(True)
        self.move_date_input.setDisplayFormat("yyyy-MM-dd")
        self.move_date_input.setDate(QDate.currentDate())

        self.move_time_input = QTimeEdit()
        self.move_time_input.setDisplayFormat("hh:mm:ss AP")
        self.move_time_input.setMinimumTime(QTime(0, 0, 0))
        self.move_time_input.setTime(QTime(0, 0, 0))
        self.move_time_input.setSpecialValueText(" ")

        self.apply_action_button = QPushButton("Apply to Selected Rows")
        self.clear_action_button = QPushButton("Clear Action for Selected Rows")
        self.save_button = QPushButton("Save Planner Log")

        layout.addWidget(self.action_label, 0, 0)
        layout.addWidget(self.action_combo, 0, 1)
        layout.addWidget(self.note_label, 0, 2)
        layout.addWidget(self.note_input, 0, 3, 2, 3)

        layout.addWidget(self.move_mode_label, 1, 0)
        layout.addWidget(self.move_mode_combo, 1, 1)
        layout.addWidget(self.move_date_label, 1, 2)
        layout.addWidget(self.move_date_input, 1, 3)
        layout.addWidget(self.move_time_label, 1, 4)
        layout.addWidget(self.move_time_input, 1, 5)
        layout.addWidget(self.action_help_label, 2, 0, 1, 3)

        layout.addWidget(self.apply_action_button, 2, 3)
        layout.addWidget(self.clear_action_button, 2, 4)
        layout.addWidget(self.save_button, 2, 5)

        self.action_box.setLayout(layout)
        self.main_layout.addWidget(self.action_box)

    def update_action_editor_visibility(self):
        action = self.action_combo.currentText().strip()
        move_mode = self.move_mode_combo.currentText().strip()

        is_move_date = action == "MOVE_DATE"
        is_move_time = action == "MOVE_TIME"
        is_add_note = action == "ADD_NOTE"
        is_mark_done = action == "MARK_DONE"

        self.note_label.setVisible(is_add_note)
        self.note_input.setVisible(is_add_note)
        self.move_mode_label.setVisible(is_move_date)
        self.move_mode_combo.setVisible(is_move_date)

        show_move_date = is_move_date
        self.move_date_label.setVisible(show_move_date)
        self.move_date_input.setVisible(show_move_date)
        self.move_date_input.setEnabled(is_move_date and move_mode == "specific_date")

        show_move_time = is_move_date or is_move_time
        self.move_time_label.setVisible(show_move_time)
        self.move_time_input.setVisible(show_move_time)

        if not action or is_mark_done:
            self.action_help_label.setText("Choose an action to reveal the matching fields.")
        elif is_add_note:
            self.action_help_label.setText("ADD_NOTE uses the note text below and writes it with the AUTOHOL prefix.")
        elif is_move_date:
            self.action_help_label.setText("MOVE_DATE lets you pick a business day, calendar day, or a specific date.")
        else:
            self.action_help_label.setText("MOVE_TIME lets you set a time for the selected rows.")

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
        self.update_selected_count()

    def refresh_current_page(self):
        if self.page_dates and self.current_page_index >= len(self.page_dates):
            self.current_page_index = max(0, len(self.page_dates) - 1)
        self.load_current_page()

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
        if self.page_dates and self.current_page_index > 0:
            self.current_page_index -= 1
            self.load_current_page()

    def go_to_next_page(self):
        if self.page_dates and self.current_page_index < len(self.page_dates) - 1:
            self.current_page_index += 1
            self.load_current_page()

    def go_to_holiday_page(self):
        if self.page_dates:
            self.current_page_index = self.holiday_page_index
            self.load_current_page()

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
                self.table.setItem(row_idx, col_idx, QTableWidgetItem(str(value)))

    def get_selected_row_indexes(self):
        selected = self.table.selectionModel().selectedRows()
        return sorted(index.row() for index in selected)

    def update_selected_count(self):
        self.summary_selected.setText(f"Rows Selected: {len(self.get_selected_row_indexes())}")

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
            13: "move_to_time",
        }

    def handle_header_sort(self, column_index):
        sort_field = self.get_table_column_field_map().get(column_index, "")
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

        self.load_current_page()

    def _parse_time_value(self, value):
        text = (value or "").strip()
        if not text:
            return None
        for fmt in ("%I:%M:%S %p", "%I:%M %p"):
            try:
                return datetime.strptime(text, fmt)
            except ValueError:
                pass
        return None

    def sort_rows(self, rows, sort_field, sort_order):
        if not sort_field:
            return sorted(rows, key=lambda r: r.get("_row_id", 0))

        reverse = sort_order == "descending"

        def sort_key(row):
            value = row.get(sort_field, "")

            if sort_field in {"time", "move_to_time"}:
                parsed = self._parse_time_value(value)
                if parsed is not None:
                    return (0, parsed.time(), row.get("_row_id", 0))
                return (1, (value or "").strip().lower(), row.get("_row_id", 0))

            if sort_field in {"target_date", "holiday_date", "move_to_date"}:
                text = (value or "").strip()
                if text:
                    try:
                        return (0, datetime.strptime(text, "%Y-%m-%d").date(), row.get("_row_id", 0))
                    except ValueError:
                        pass
                return (1, text.lower(), row.get("_row_id", 0))

            return ((value or "").strip().lower(), row.get("_row_id", 0))

        return sorted(rows, key=sort_key, reverse=reverse)

    def require_planner_user_for_custom_holidays(self):
        planner_user = self.user_input.text().strip()
        if not planner_user:
            QMessageBox.warning(
                self,
                "Missing user",
                "Please enter Planner User before adding or importing custom holidays.",
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

    def load_custom_holidays(self):
        path = self.get_custom_holiday_path()
        if not os.path.exists(path):
            return []

        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return data if isinstance(data, list) else []
        except Exception as e:
            QMessageBox.critical(self, "Load Error", f"Failed to load custom holidays:\n{e}")
            return []

    def save_custom_holidays(self, holidays):
        path = self.get_custom_holiday_path()
        os.makedirs(os.path.dirname(path), exist_ok=True)
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
                "Please enter Country, Holiday Name, and Holiday Observance.",
            )
            return

        try:
            datetime.strptime(holiday_date, "%Y-%m-%d")
        except ValueError:
            QMessageBox.warning(self, "Invalid date", "Holiday Date must be in yyyy-MM-dd format.")
            return

        new_country = normalize_country(country)
        holidays = self.load_custom_holidays()

        for item in holidays:
            existing_country = normalize_country(item.get("country", ""))
            existing_date = (item.get("holiday_date") or "").strip()
            existing_name = (item.get("holiday_name") or "").strip()
            if existing_country == new_country and existing_date == holiday_date and existing_name == holiday_name:
                QMessageBox.warning(self, "Duplicate holiday", "This exact custom holiday already exists for this user.")
                return

        holidays.append(
            {
                "country": country,
                "holiday_date": holiday_date,
                "holiday_name": holiday_name,
                "holiday_observance": holiday_observance,
                "source": "custom",
                "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            }
        )

        try:
            self.save_custom_holidays(holidays)
            QMessageBox.information(
                self,
                "Custom Holiday Added",
                f"Added custom holiday:\n{country} | {holiday_date} | {holiday_name} | {holiday_observance}",
            )
            self.custom_country_input.clear()
            self.custom_name_input.clear()
            self.custom_observance_combo.setCurrentIndex(0)
            self.refresh_all_holiday_lookup_calendars()
        except Exception as e:
            QMessageBox.critical(self, "Save Error", f"Failed to save custom holiday:\n{e}")

    def load_merged_holidays(self):
        holiday_dict = load_holiday_records(self.default_holiday_path)

        for item in self.load_custom_holidays():
            country = normalize_country(item.get("country", ""))
            holiday_date = (item.get("holiday_date") or "").strip()
            holiday_name = (item.get("holiday_name") or "").strip()
            holiday_observance = (item.get("holiday_observance") or "").strip()

            if not country or not holiday_date:
                continue

            try:
                hdate = datetime.strptime(holiday_date, "%Y-%m-%d").date()
            except ValueError:
                continue

            add_holiday_record(
                holiday_dict,
                country,
                hdate,
                holiday_name,
                holiday_observance,
            )

        return holiday_dict

    def import_custom_holiday_csv(self):
        if not self.require_planner_user_for_custom_holidays():
            return

        file_path, _ = QFileDialog.getOpenFileName(self, "Select Custom Holiday CSV", "", "CSV Files (*.csv)")
        if not file_path:
            return

        try:
            imported_rows = []
            with open(file_path, "r", encoding="utf-8-sig", newline="") as f:
                reader = csv.DictReader(f)
                required_columns = {"country", "holiday_date", "holiday_name", "holiday_observance"}
                csv_columns = {col.strip() for col in (reader.fieldnames or [])}
                missing_columns = required_columns - csv_columns
                if missing_columns:
                    QMessageBox.warning(
                        self,
                        "Invalid CSV Format",
                        "CSV is missing required columns:\n" + ", ".join(sorted(missing_columns)),
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

                    imported_rows.append(
                        {
                            "country": country,
                            "holiday_date": holiday_date,
                            "holiday_name": holiday_name,
                            "holiday_observance": holiday_observance,
                            "source": "custom_import",
                            "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                        }
                    )

            if not imported_rows:
                QMessageBox.information(self, "No Valid Rows", "No valid custom holiday rows were found in the CSV.")
                return

            existing_holidays = self.load_custom_holidays()
            existing_keys = {
                (
                    normalize_country(item.get("country", "")),
                    (item.get("holiday_date") or "").strip(),
                    (item.get("holiday_name") or "").strip(),
                )
                for item in existing_holidays
            }

            added_count = 0
            for row in imported_rows:
                row_key = (
                    normalize_country(row.get("country", "")),
                    row.get("holiday_date", "").strip(),
                    row.get("holiday_name", "").strip(),
                )
                if row_key not in existing_keys:
                    existing_holidays.append(row)
                    existing_keys.add(row_key)
                    added_count += 1

            self.save_custom_holidays(existing_holidays)
            QMessageBox.information(self, "Import Complete", f"Imported {added_count} new custom holiday rows.")
            self.refresh_all_holiday_lookup_calendars()
        except Exception as e:
            QMessageBox.critical(self, "Import Error", f"Failed to import custom holiday CSV:\n{e}")

    def show_custom_holiday_csv_help(self):
        dialog = QDialog(self)
        dialog.setWindowTitle("Custom Holiday CSV Format")
        dialog.resize(520, 320)

        layout = QVBoxLayout(dialog)

        text_box = QPlainTextEdit()
        text_box.setReadOnly(False)
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
            "UK,2026-04-03,Good Friday,Banks/Government\n"
        )

        close_button = QPushButton("Close")
        close_button.clicked.connect(dialog.accept)

        button_row = QHBoxLayout()
        button_row.addStretch()
        button_row.addWidget(close_button)

        layout.addWidget(text_box)
        layout.addLayout(button_row)
        dialog.exec()

    def load_dw_entries_with_assignments(self):
        a = Autocalendar()
        a.get_dw()
        dw_entries = a.parse_entries()

        b = Assignments()
        return b.assign(dw_entries, attach=True)

    def get_holiday_lookup_dw_entries(self):
        if self._holiday_lookup_dw_entries is None:
            self._holiday_lookup_dw_entries = self.load_dw_entries_with_assignments()
        return self._holiday_lookup_dw_entries

    def get_lookup_relevant_countries(self):
        entries = self.get_holiday_lookup_dw_entries()
        planner_user = self.user_input.text().strip()

        if planner_user:
            entries = filter_entries_for_user(entries, planner_user)

        return sorted({
            normalize_country(entry.get("country", ""))
            for entry in entries
            if normalize_country(entry.get("country", "")) not in {"", "various"}
        })

    def get_lookup_matches_for_date(self, selected_date):
        holiday_dict = self.load_merged_holidays()
        relevant_countries = self.get_lookup_relevant_countries()
        matches = []

        for country in relevant_countries:
            country_records = holiday_dict.get(country, {})
            for holiday in country_records.get(selected_date, []):
                matches.append({
                    "country": country,
                    "holiday_name": (holiday.get("holiday_name") or "").strip() or "-",
                    "holiday_type": (holiday.get("holiday_type") or "").strip() or "-",
                })

        matches.sort(key=lambda item: (item["country"], item["holiday_name"], item["holiday_type"]))
        return matches

    def build_lookup_month_matches(self, year, month):
        holiday_dict = self.load_merged_holidays()
        relevant_countries = self.get_lookup_relevant_countries()
        matches_by_date = defaultdict(list)

        for country in relevant_countries:
            country_records = holiday_dict.get(country, {})
            for holiday_date, holidays in country_records.items():
                if holiday_date.year != year or holiday_date.month != month:
                    continue
                for holiday in holidays:
                    matches_by_date[holiday_date].append({
                        "country": country,
                        "holiday_name": (holiday.get("holiday_name") or "").strip() or "-",
                        "holiday_type": (holiday.get("holiday_type") or "").strip() or "-",
                    })

        return matches_by_date

    def refresh_all_holiday_lookup_calendars(self):
        if isinstance(self.holiday_date_input, HolidayLookupDateEdit):
            self.holiday_date_input.refresh_popup_if_open()

    def load_actual_dw_entries_with_assignments(self, start_date, end_date):
        autocalendar = Autocalendar()
        sql_rows = autocalendar.get_actual_dw_records(start_date, end_date, done_only=True)
        entries = autocalendar.parse_actual_records(sql_rows)
        assignment_loader = Assignments()
        return assignment_loader.assign(entries, attach=True)

    def group_rows_by_target_date(self, rows):
        grouped = defaultdict(list)
        for row in rows:
            target_date = (row.get("target_date") or "").strip()
            if not target_date:
                continue
            grouped[target_date].append(row)
        return grouped

    def choose_rows_by_date_source(self, actual_rows, template_rows, holiday_date, days_before, days_after):
        actual_by_date = self.group_rows_by_target_date(actual_rows)
        template_by_date = self.group_rows_by_target_date(template_rows)

        selected_rows = []
        window_start, window_end = date_window(holiday_date, days_before, days_after)
        current = window_start
        while current <= window_end:
            date_key = current.isoformat()
            if actual_by_date.get(date_key):
                selected_rows.extend(actual_by_date[date_key])
            else:
                selected_rows.extend(template_by_date.get(date_key, []))
            current += timedelta(days=1)

        return selected_rows

    def clear_table(self):
        self.planner_rows = []
        self.filtered_planner_rows = []
        self.page_dates = []
        self.current_page_index = 0
        self.current_page_rows = []
        self.holiday_page_index = 0

        self.load_rows_into_table([])
        self.update_paging_labels()

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
        self.update_active_filters_label()

    def generate_planner_rows(self):
        planner_user = self.user_input.text().strip()
        holiday_date = self.holiday_date_input.date().toPyDate()
        days_before = self.days_before_input.value()
        days_after = self.days_after_input.value()

        try:
            holiday_dict = self.load_merged_holidays()
            window_start, window_end = date_window(holiday_date, days_before, days_after)
            dw_entries = self.load_dw_entries_with_assignments()
            actual_entries = self.load_actual_dw_entries_with_assignments(window_start, window_end)
            holiday_countries = get_holiday_countries_for_date(holiday_dict, holiday_date)

            if planner_user:
                base_template_entries = filter_entries_for_user(dw_entries, planner_user)
                base_actual_entries = filter_entries_for_user(actual_entries, planner_user)
                combined_base_entries = base_template_entries + base_actual_entries
                relevant_countries = get_user_holiday_countries(combined_base_entries, holiday_countries)
                country_filtered_template_entries = filter_entries_for_countries(base_template_entries, relevant_countries)
                country_filtered_actual_entries = filter_entries_for_countries(base_actual_entries, relevant_countries)
                summary_user_text = f"User: {planner_user}"
                planner_user_value = planner_user
            else:
                base_template_entries = [
                    entry for entry in dw_entries
                    if normalize_country(entry.get("country", "")) not in {"", "various"}
                ]
                base_actual_entries = [
                    entry for entry in actual_entries
                    if normalize_country(entry.get("country", "")) not in {"", "various"}
                ]
                combined_base_entries = base_template_entries + base_actual_entries
                relevant_countries = holiday_countries
                country_filtered_template_entries = filter_entries_for_countries(base_template_entries, relevant_countries)
                country_filtered_actual_entries = filter_entries_for_countries(base_actual_entries, relevant_countries)
                summary_user_text = "User: ALL USERS"
                planner_user_value = "ALL_USERS"

            candidate_template_rows = build_window_task_candidates(
                country_filtered_template_entries,
                holiday_date,
                days_before=days_before,
                days_after=days_after,
            )
            candidate_actual_rows = []
            for entry in country_filtered_actual_entries:
                target_date = (entry.get("target_date") or "").strip()
                if not target_date:
                    continue
                row_copy = dict(entry)
                row_copy["is_on_holiday_date"] = target_date == holiday_date.isoformat()
                candidate_actual_rows.append(row_copy)

            annotated_template_rows = annotate_holiday_context(candidate_template_rows, holiday_dict, holiday_date)
            annotated_actual_rows = annotate_holiday_context(candidate_actual_rows, holiday_dict, holiday_date)
            selected_source_rows = self.choose_rows_by_date_source(
                annotated_actual_rows,
                annotated_template_rows,
                holiday_date,
                days_before,
                days_after,
            )

            self.planner_rows = build_planner_rows(
                selected_source_rows,
                planner_user_value,
                holiday_date,
                days_before=days_before,
                days_after=days_after,
            )
            for planner_row, source_row in zip(self.planner_rows, selected_source_rows):
                planner_row["entry_source"] = source_row.get("entry_source", "template")
                planner_row["actual_record_id"] = source_row.get("actual_record_id", "")
                planner_row["fdDone"] = source_row.get("fdDone", "")

            self.filtered_planner_rows = list(self.planner_rows)
            self.update_active_filters_label()
            self.rebuild_date_pages_from_filtered()
            self.load_current_page()

            self.summary_user.setText(summary_user_text)
            self.summary_holiday.setText(f"Holiday Date: {holiday_date.isoformat()}")
            self.summary_window.setText(f"Window: {window_start.isoformat()} to {window_end.isoformat()}")
            self.summary_rows.setText(f"Rows Loaded: {len(self.planner_rows)}")
            self.summary_selected.setText("Rows Selected: 0")
            self.update_action_count()

            if planner_user and not combined_base_entries:
                QMessageBox.information(self, "No assigned entries", f"No DW entries were found for planner user '{planner_user}'.")
                return

            if not relevant_countries:
                QMessageBox.information(self, "No relevant holiday countries", f"No relevant countries were found for {holiday_date.isoformat()}.")
                return

            if not self.planner_rows:
                QMessageBox.information(self, "No planner rows", "No scheduled planner rows were found in the visible window.")
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
        popup.set_options(self.get_filter_options("database"), self.selected_database_filters)
        if popup.exec():
            self.selected_database_filters = popup.get_selected_values()
            self.apply_filters()

    def open_country_filter_popup(self):
        popup = MultiSelectFilterPopup("Country Filter", self)
        popup.set_options(self.get_filter_options("country"), self.selected_country_filters)
        if popup.exec():
            self.selected_country_filters = popup.get_selected_values()
            self.apply_filters()

    def open_holiday_type_filter_popup(self):
        popup = MultiSelectFilterPopup("Holiday Type Filter", self)
        popup.set_options(self.get_filter_options("holiday_type"), self.selected_holiday_type_filters)
        if popup.exec():
            self.selected_holiday_type_filters = popup.get_selected_values()
            self.apply_filters()

    def update_active_filters_label(self):
        parts = []
        tooltip_lines = []

        if self.selected_database_filters:
            parts.append(f"Database({len(self.selected_database_filters)})")
            tooltip_lines.append("Database: " + ", ".join(sorted(self.selected_database_filters)))

        if self.selected_country_filters:
            parts.append(f"Country({len(self.selected_country_filters)})")
            tooltip_lines.append("Country: " + ", ".join(sorted(self.selected_country_filters)))

        if self.selected_holiday_type_filters:
            parts.append(f"Holiday Type({len(self.selected_holiday_type_filters)})")
            tooltip_lines.append("Holiday Type: " + ", ".join(sorted(self.selected_holiday_type_filters)))

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

    def get_next_calendar_day(self, base_date):
        return base_date + timedelta(days=1)

    def get_move_time_value(self):
        current_time = self.move_time_input.time()
        if current_time == QTime(0, 0, 0):
            return ""
        return current_time.toString("hh:mm:ss AP")

    def get_next_business_day(self, base_date):
        next_day = base_date + timedelta(days=1)
        while next_day.weekday() >= 5:
            next_day += timedelta(days=1)
        return next_day

    def resolve_move_to_date(self, row, move_mode):
        row_target_date = row.get("target_date", "")
        if not row_target_date:
            return ""

        base_date = datetime.strptime(row_target_date, "%Y-%m-%d").date()

        if move_mode == "specific_date":
            return self.move_date_input.date().toString("yyyy-MM-dd")
        if move_mode == "next_calendar_day":
            return self.get_next_calendar_day(base_date).isoformat()
        if move_mode == "next_business_day":
            return self.get_next_business_day(base_date).isoformat()
        return ""

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
        return normalized not in {"", "AUTOHOL:"}

    def format_warning_row_details(self, rows):
        if not rows:
            return "No rows selected."

        lines = []
        for row in rows:
            target_date = (row.get("target_date") or "").strip() or "-"
            database = (row.get("database") or "").strip() or "-"
            country = (row.get("country") or "").strip() or "-"
            group = (row.get("group") or "").strip() or "-"
            update = (row.get("update") or "").strip() or "-"
            lines.append(
                f"{target_date} | {database} | {country} | {group} | {update}"
            )

        return "\n".join(lines)

    def confirm_mark_done_action(self, selected_rows):
        message = (
            "You are about to mark the selected rows as done.\n\n"
            f"Selected rows: {len(selected_rows)}\n"
            "date | database | country | group | update\n"
            f"{self.format_warning_row_details(selected_rows)}\n\n"
            "Do you want to continue?"
        )
        result = QMessageBox.question(
            self,
            "Confirm Mark Done",
            message,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        )
        return result == QMessageBox.StandardButton.Yes

    def confirm_overwrite_actions(self, selected_rows, new_action):
        conflicting_rows = [
            row for row in selected_rows
            if (row.get("planned_action") or "").strip()
            and (row.get("planned_action") or "").strip() != new_action
        ]
        if not conflicting_rows:
            return True

        action_counts = {}
        for row in conflicting_rows:
            action = (row.get("planned_action") or "").strip()
            if not action:
                continue
            action_counts[action] = action_counts.get(action, 0) + 1

        existing_action_lines = []
        if action_counts:
            existing_action_lines.append("Existing actions:")
            for action in sorted(action_counts):
                existing_action_lines.append(f"  {action}: {action_counts[action]}")
            existing_action_lines.append("")
        existing_actions_text = "\n".join(existing_action_lines)

        message = (
            f"The selected rows already have different planned actions and will be overwritten by {new_action}.\n\n"
            f"Selected rows: {len(conflicting_rows)}\n"
            f"{existing_actions_text}"
            "date | database | country | group | update\n"
            f"{self.format_warning_row_details(conflicting_rows)}\n\n"
            "Do you want to continue?"
        )
        result = QMessageBox.question(
            self,
            "Overwrite Planned Actions",
            message,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        )
        return result == QMessageBox.StandardButton.Yes

    def confirm_save_summary(self, action_rows):
        action_order = ["ADD_NOTE", "MARK_DONE", "MOVE_DATE", "MOVE_TIME"]
        action_counts = {action: 0 for action in action_order}

        for row in action_rows:
            action = (row.get("planned_action") or "").strip()
            if action in action_counts:
                action_counts[action] += 1

        summary_lines = [
            "Review the planner actions before saving.",
            "",
            f"Total rows to save: {len(action_rows)}",
        ]
        for action in action_order:
            summary_lines.append(f"{action}: {action_counts[action]}")

        result = QMessageBox.question(
            self,
            "Confirm Save Planner Log",
            "\n".join(summary_lines),
            QMessageBox.StandardButton.Save | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        )
        return result == QMessageBox.StandardButton.Save

    def get_selected_row_ids(self):
        row_ids = []
        for page_row_index in self.get_selected_row_indexes():
            if 0 <= page_row_index < len(self.current_page_rows):
                row_ids.append(self.current_page_rows[page_row_index].get("_row_id"))
        return row_ids

    def apply_action_to_selected_rows(self):
        selected_row_ids = self.get_selected_row_ids()
        self.summary_selected.setText(f"Rows Selected: {len(selected_row_ids)}")

        if not selected_row_ids:
            QMessageBox.warning(self, "No selection", "Please select one or more rows.")
            return

        planned_action = self.action_combo.currentText().strip()
        planned_note = self.get_user_note_text()
        move_mode = self.move_mode_combo.currentText().strip()
        move_to_date = self.move_date_input.date().toString("yyyy-MM-dd")
        move_to_time = self.get_move_time_value()
        action_date = datetime.now().strftime("%Y-%m-%d")

        if not planned_action:
            QMessageBox.warning(self, "Missing action", "Please choose a planned action.")
            return
        if planned_action == "ADD_NOTE" and not self.has_custom_note_text(planned_note):
            QMessageBox.warning(self, "Missing note", "ADD_NOTE requires a note.")
            return
        if planned_action == "MOVE_DATE" and not move_mode:
            QMessageBox.warning(self, "Missing move mode", "MOVE_DATE requires a move mode.")
            return
        if planned_action == "MOVE_TIME" and not move_to_time:
            QMessageBox.warning(self, "Missing time", "MOVE_TIME requires a time.")
            return

        selected_row_data = [
            row for row in self.current_page_rows
            if row.get("_row_id") in selected_row_ids
        ]

        if not self.confirm_overwrite_actions(selected_row_data, planned_action):
            return
        if planned_action == "MARK_DONE" and not self.confirm_mark_done_action(selected_row_data):
            return

        for row in self.planner_rows:
            if row.get("_row_id") not in selected_row_ids:
                continue

            final_note = ""
            final_move_to_date = ""
            final_move_to_time = ""

            if planned_action == "ADD_NOTE":
                final_note = planned_note
            elif planned_action == "MARK_DONE":
                final_note = planned_note if self.has_custom_note_text(planned_note) else f"AUTOHOL: Marked as Done {action_date}"
            elif planned_action == "MOVE_DATE":
                final_move_to_date = self.resolve_move_to_date(row, move_mode)
                final_move_to_time = move_to_time
                final_note = planned_note if self.has_custom_note_text(planned_note) else f"AUTOHOL: Moved to {final_move_to_date}"
                if final_move_to_time and not self.has_custom_note_text(planned_note):
                    final_note = f"{final_note} at {final_move_to_time}"
            elif planned_action == "MOVE_TIME":
                final_move_to_time = move_to_time
                final_note = planned_note if self.has_custom_note_text(planned_note) else f"AUTOHOL: Move time set to {final_move_to_time}"

            row["planned_action"] = planned_action
            row["planned_note"] = final_note
            row["move_mode"] = move_mode if planned_action == "MOVE_DATE" else ""
            row["move_to_date"] = final_move_to_date if planned_action == "MOVE_DATE" else ""
            row["move_to_time"] = final_move_to_time if planned_action in {"MOVE_DATE", "MOVE_TIME"} else ""

        self.note_input.setPlainText("AUTOHOL:")
        self.apply_filters_and_refresh()
        self.update_action_count()

    def clear_action_for_selected_rows(self):
        selected_row_ids = self.get_selected_row_ids()
        self.summary_selected.setText(f"Rows Selected: {len(selected_row_ids)}")

        if not selected_row_ids:
            QMessageBox.warning(self, "No selection", "Please select one or more rows.")
            return

        for row in self.planner_rows:
            if row.get("_row_id") in selected_row_ids:
                row["planned_action"] = ""
                row["planned_note"] = ""
                row["move_mode"] = ""
                row["move_to_date"] = ""
                row["move_to_time"] = ""

        self.note_input.setPlainText("AUTOHOL:")
        self.apply_filters_and_refresh()
        self.update_action_count()

    def apply_filters_and_refresh(self):
        self.apply_filters()
        if self.page_dates:
            if self.current_page_index >= len(self.page_dates):
                self.current_page_index = max(0, len(self.page_dates) - 1)
        else:
            self.current_page_index = 0
        self.refresh_current_page()

    def save_planner_log(self):
        action_rows = [row for row in self.planner_rows if (row.get("planned_action") or "").strip()]
        if not action_rows:
            QMessageBox.information(self, "No actions to save", "There are no planner rows with actions to save.")
            return
        if not self.confirm_save_summary(action_rows):
            return

        try:
            json_path, csv_path = self.get_output_log_paths()
            json_count = write_planner_log_json(json_path, action_rows)
            csv_count = write_planner_log_csv(csv_path, action_rows)

            QMessageBox.information(
                self,
                "Planner Log Saved",
                f"Saved {json_count} rows to JSON:\n{json_path}\n\nSaved {csv_count} rows to CSV:\n{csv_path}",
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


def apply_modern_style(window):
    window.setStyleSheet(MODERN_STYLE)


def apply_modern_calendar(window):
    attached = False

    if hasattr(window, "holiday_date_input") and not isinstance(window.holiday_date_input, HolidayLookupDateEdit):
        cal = QCalendarWidget()
        cal.setGridVisible(False)
        cal.setStyleSheet(CALENDAR_QSS)
        window.holiday_date_input.setCalendarWidget(cal)
        setattr(window, "_modern_calendar_widget_holiday", cal)
        attached = True

    if hasattr(window, "custom_date_input"):
        cal2 = QCalendarWidget()
        cal2.setGridVisible(False)
        cal2.setStyleSheet(CALENDAR_QSS)
        window.custom_date_input.setCalendarWidget(cal2)
        setattr(window, "_modern_calendar_widget_custom", cal2)
        attached = True

    if not attached:
        print("Warning: PlannerWindow has no date inputs ('holiday_date_input' or 'custom_date_input') to wire calendar.")


def main():
    app = QApplication(sys.argv)
    window = PlannerWindow()
    apply_modern_style(window)
    apply_modern_calendar(window)
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
