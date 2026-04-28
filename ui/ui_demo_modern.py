import sys

from PyQt6.QtWidgets import QApplication, QCalendarWidget, QMessageBox

try:
    # import the existing PlannerWindow without modifying ui_demo.py
    from ui.ui_demo import PlannerWindow
except Exception:
    # fallback if run as script from repo root
    from ui_demo import PlannerWindow

MODERN_STYLE = '''
QMainWindow { background: #f5f8fb; }
QGroupBox { font-weight: 600; border: 1px solid #e1e8f5; border-radius: 8px; margin-top:6px; padding:8px; background: transparent; }
QGroupBox::title { subcontrol-origin: margin; subcontrol-position: top left; padding: 0 6px; }
QLabel { color: #223047; }
QPushButton {
    background: qlineargradient(x1:0,y1:0,x2:0,y2:1, stop:0 #4a83d8, stop:1 #3571c6);
    color: white;
    border: none;
    border-radius: 6px;
    padding: 6px 10px;
}
QPushButton:disabled { background: #9fb5e0; color:#eaf2ff; }
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
'''


CALENDAR_QSS = '''
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
'''


class ModernPlannerWindow(PlannerWindow):
    def get_selected_row_ids(self):
        selected_rows = self.get_selected_row_indexes()
        return [
            self.current_page_rows[row_idx]["_row_id"]
            for row_idx in selected_rows
        ]

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
        action_date = self.get_today_string()

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

        selected_row_ids = self.get_selected_row_ids()
        selected_row_data = [
            row for row in self.current_page_rows
            if row.get("_row_id") in selected_row_ids
        ]

        if not self.confirm_overwrite_actions(selected_row_data, planned_action):
            return

        if planned_action == "MARK_DONE":
            if not self.confirm_mark_done_action(selected_row_data):
                return

        for row in self.filtered_planner_rows:
            if row.get("_row_id") in selected_row_ids:
                row["planned_action"] = planned_action
                row["planned_note"] = planned_note
                row["move_mode"] = move_mode if planned_action == "MOVE_DATE" else ""
                row["move_to_date"] = move_to_date if planned_action == "MOVE_DATE" else ""
                row["move_to_time"] = move_to_time if planned_action == "MOVE_TIME" else ""

        self.load_current_page()
        self.update_action_count()
        self.note_input.setPlainText("AUTOHOL: ")

    def clear_action_for_selected_rows(self):
        selected_rows = self.get_selected_row_indexes()
        self.summary_selected.setText(f"Rows Selected: {len(selected_rows)}")

        if not selected_rows:
            QMessageBox.warning(self, "No selection", "Please select one or more rows.")
            return

        selected_row_ids = self.get_selected_row_ids()

        for row in self.filtered_planner_rows:
            if row.get("_row_id") in selected_row_ids:
                row["planned_action"] = ""
                row["planned_note"] = ""
                row["move_mode"] = ""
                row["move_to_date"] = ""
                row["move_to_time"] = ""

        self.load_current_page()
        self.update_action_count()
        self.note_input.setPlainText("AUTOHOL: ")

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
        if not self.confirm_save_summary(action_rows):
            return
        super().save_planner_log()

    def get_today_string(self):
        from datetime import datetime

        return datetime.now().strftime("%Y-%m-%d")


def apply_modern_style(window):
    window.setStyleSheet(MODERN_STYLE)


def apply_modern_calendar(window):
    attached = False
    # holiday_date_input
    if hasattr(window, 'holiday_date_input'):
        cal = QCalendarWidget()
        cal.setGridVisible(False)
        cal.setStyleSheet(CALENDAR_QSS)
        window.holiday_date_input.setCalendarWidget(cal)
        setattr(window, '_modern_calendar_widget_holiday', cal)
        attached = True

    # custom_date_input (custom holiday section)
    if hasattr(window, 'custom_date_input'):
        cal2 = QCalendarWidget()
        cal2.setGridVisible(False)
        cal2.setStyleSheet(CALENDAR_QSS)
        window.custom_date_input.setCalendarWidget(cal2)
        setattr(window, '_modern_calendar_widget_custom', cal2)
        attached = True

    if not attached:
        print("Warning: PlannerWindow has no date inputs ('holiday_date_input' or 'custom_date_input') to wire calendar.")


def main():
    app = QApplication(sys.argv)
    win = ModernPlannerWindow()
    apply_modern_style(win)
    apply_modern_calendar(win)
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
