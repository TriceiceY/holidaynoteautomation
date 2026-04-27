from PyQt6.QtWidgets import QApplication, QCalendarWidget
import sys

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


def apply_modern_style(window):
    window.setStyleSheet(MODERN_STYLE)


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
    win = PlannerWindow()
    apply_modern_style(win)
    apply_modern_calendar(win)
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
