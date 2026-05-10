STYLE_SHEET = """
/* ═══════════════════════════════════════════════════════════
   GLOBAL
═══════════════════════════════════════════════════════════ */
QMainWindow, QDialog {
    background-color: #F8FAFC;
    font-family: "Segoe UI", "Inter", "Helvetica Neue", sans-serif;
    font-size: 13px;
    color: #1E293B;
}

QWidget {
    font-family: "Segoe UI", "Inter", "Helvetica Neue", sans-serif;
    font-size: 13px;
    color: #1E293B;
}

/* ── Scrollbars ── */
QScrollBar:vertical {
    border: none;
    background: #F1F5F9;
    width: 6px;
    margin: 0;
}
QScrollBar::handle:vertical {
    background: #CBD5E1;
    min-height: 24px;
    border-radius: 3px;
}
QScrollBar::add-line:vertical,
QScrollBar::sub-line:vertical { height: 0; background: none; }

QScrollBar:horizontal {
    border: none;
    background: #F1F5F9;
    height: 6px;
    margin: 0;
}
QScrollBar::handle:horizontal {
    background: #CBD5E1;
    min-width: 24px;
    border-radius: 3px;
}
QScrollBar::add-line:horizontal,
QScrollBar::sub-line:horizontal { width: 0; background: none; }

/* ── Input Controls ── */
QLineEdit, QDateTimeEdit, QSpinBox, QDoubleSpinBox, QComboBox {
    background-color: white;
    color: #1E293B;
    border: 1.5px solid #CBD5E1;
    border-radius: 6px;
    padding: 7px 10px;
    font-size: 13px;
    selection-background-color: #BFDBFE;
    selection-color: #1D4ED8;
}
QLineEdit:focus, QDateTimeEdit:focus, QSpinBox:focus,
QDoubleSpinBox:focus, QComboBox:focus {
    border-color: #3B82F6;
    outline: none;
}
QLineEdit:disabled, QDateTimeEdit:disabled,
QSpinBox:disabled, QDoubleSpinBox:disabled, QComboBox:disabled {
    background-color: #F8FAFC;
    color: #94A3B8;
}

QComboBox::drop-down {
    border: none;
    width: 22px;
}
QComboBox::down-arrow {
    width: 10px;
    height: 10px;
}
QComboBox QAbstractItemView {
    background-color: white;
    border: 1.5px solid #CBD5E1;
    border-radius: 6px;
    selection-background-color: #EFF6FF;
    selection-color: #1D4ED8;
    padding: 4px;
    outline: none;
}

QSpinBox::up-button, QSpinBox::down-button,
QDoubleSpinBox::up-button, QDoubleSpinBox::down-button {
    border: none;
    background: #F1F5F9;
    width: 18px;
}
QSpinBox::up-button:hover, QSpinBox::down-button:hover,
QDoubleSpinBox::up-button:hover, QDoubleSpinBox::down-button:hover {
    background: #E2E8F0;
}

QDateTimeEdit::drop-down { border: none; width: 22px; }

QRadioButton {
    color: #1E293B;
    spacing: 10px;
    font-size: 13px;
    background: transparent;
}
QRadioButton::indicator {
    width: 16px;
    height: 16px;
}

/* ── Calendar Popup ── */
QCalendarWidget { min-width: 260px; }
QCalendarWidget QAbstractItemView {
    background-color: white;
    color: #1E293B;
    selection-background-color: #3B82F6;
    selection-color: white;
    font-size: 11px;
    padding: 0px !important;
    margin: 0px !important;
    border: none !important;
}
QCalendarWidget QAbstractItemView::item {
    padding: 0px !important;
    margin: 0px !important;
}
QCalendarWidget QWidget#qt_calendar_navigationbar {
    background-color: #F8FAFC;
}
QCalendarWidget QHeaderView::section {
    background-color: white;
    color: #64748B;
    padding: 1px !important;
    border: none;
    font-size: 10px;
}

/* ── Labels ── */
QLabel {
    color: #1E293B;
    background: transparent;
}

/* ═══════════════════════════════════════════════════════════
   SIDEBAR
═══════════════════════════════════════════════════════════ */
#Sidebar {
    background-color: #0F172A;
    min-width: 252px;
    max-width: 252px;
}

#SidebarBrand {
    background-color: #1E293B;
    border-bottom: 1px solid #334155;
}

#SidebarBrandTitle {
    font-size: 16px;
    font-weight: 700;
    color: white;
    background: transparent;
}

#SidebarBrandSub {
    font-size: 10px;
    color: #64748B;
    background: transparent;
}

#SidebarSection {
    color: #94A3B8;
    font-size: 10px;
    font-weight: 700;
    padding: 14px 16px 4px 20px;
    background: transparent;
    letter-spacing: 0.5px;
}

#Sidebar QPushButton {
    background-color: transparent;
    color: #94A3B8;
    border: none;
    padding: 10px 16px 10px 20px;
    text-align: left;
    font-size: 13px;
    font-weight: 500;
    border-radius: 6px;
    margin: 1px 8px;
}
#Sidebar QPushButton:hover {
    background-color: #1E293B;
    color: #E2E8F0;
}
#Sidebar QPushButton[active="true"] {
    background-color: #1D4ED8;
    color: white;
    font-weight: 600;
}

#SidebarFooter {
    color: #64748B;
    font-size: 10px;
    padding: 12px 20px;
    background: transparent;
}

/* ═══════════════════════════════════════════════════════════
   CONTENT AREA
═══════════════════════════════════════════════════════════ */
#ContentArea {
    background-color: white;
    border-top-left-radius: 16px;
    border-bottom-left-radius: 16px;
}

/* ═══════════════════════════════════════════════════════════
   PAGE TYPOGRAPHY
═══════════════════════════════════════════════════════════ */
#PageTitle {
    font-size: 24px;
    font-weight: 800;
    color: #0F172A;
    letter-spacing: -0.3px;
    background: transparent;
}
#PageSubtitle {
    font-size: 13px;
    color: #64748B;
    background: transparent;
}
#HeaderTitle {
    font-size: 20px;
    font-weight: 700;
    color: #0F172A;
    background: transparent;
}
#SectionTitle {
    font-size: 14px;
    font-weight: 600;
    color: #374151;
    background: transparent;
}

/* ═══════════════════════════════════════════════════════════
   TABLES
═══════════════════════════════════════════════════════════ */
QTableView, QTableWidget {
    background-color: white;
    color: #1E293B;
    border: 1px solid #E2E8F0;
    border-radius: 8px;
    gridline-color: #F1F5F9;
    selection-background-color: #DBEAFE;
    selection-color: #1D4ED8;
    alternate-background-color: #F8FAFC;
    outline: none;
}
QTableView::item, QTableWidget::item {
    padding: 10px 12px;
    color: #1E293B;
    border: none;
}
QTableView::item:selected, QTableWidget::item:selected {
    background-color: #DBEAFE;
    color: #1D4ED8;
}
QTableCornerButton::section {
    background-color: #F8FAFC;
    border: none;
    border-right: 1px solid #E2E8F0;
    border-bottom: 1px solid #E2E8F0;
}
QHeaderView::section {
    background-color: #F8FAFC;
    padding: 10px 12px;
    border: none;
    border-bottom: 2px solid #E2E8F0;
    font-weight: 600;
    font-size: 12px;
    color: #475569;
}

/* ═══════════════════════════════════════════════════════════
   BUTTONS
═══════════════════════════════════════════════════════════ */
QPushButton {
    font-size: 13px;
    font-weight: 600;
    border-radius: 6px;
    padding: 8px 16px;
    border: 1.5px solid #CBD5E1;
    color: #1E293B;
    background-color: #F1F5F9;
}
QPushButton:hover {
    background-color: #E2E8F0;
    border-color: #94A3B8;
}
QPushButton:pressed { background-color: #CBD5E1; }
QPushButton:disabled { color: #94A3B8; background-color: #F8FAFC; border-color: #E2E8F0; }

QPushButton#ActionButton {
    background-color: #3B82F6;
    color: white;
    border: none;
    padding: 9px 18px;
    font-weight: 700;
}
QPushButton#ActionButton:hover { background-color: #2563EB; }
QPushButton#ActionButton:pressed { background-color: #1D4ED8; }

QPushButton#DeleteButton {
    background-color: #EF4444;
    color: white;
    border: none;
    padding: 9px 18px;
    font-weight: 700;
}
QPushButton#DeleteButton:hover { background-color: #DC2626; }
QPushButton#DeleteButton:pressed { background-color: #B91C1C; }

QPushButton#SecondaryButton {
    background-color: #F8FAFC;
    color: #334155;
    border: 1.5px solid #CBD5E1;
    padding: 8px 16px;
    font-weight: 600;
}
QPushButton#SecondaryButton:hover {
    background-color: #E2E8F0;
    color: #1E293B;
}

/* ── Progress ── */
QProgressBar {
    background-color: #E2E8F0;
    border-radius: 4px;
    height: 8px;
    text-align: center;
    font-size: 11px;
    color: transparent;
    border: none;
}
QProgressBar::chunk {
    background-color: #3B82F6;
    border-radius: 4px;
}

/* ── Tooltip ── */
QToolTip {
    background-color: #1E293B;
    color: white;
    border: none;
    border-radius: 6px;
    padding: 6px 10px;
    font-size: 12px;
}

/* ── Message Box ── */
QMessageBox { background-color: white; }
QMessageBox QLabel { color: #1E293B; }
QMessageBox QPushButton {
    min-width: 72px;
    padding: 7px 16px;
}

/* ── Horizontal separators (QFrame[frameShape="4"]) ── */
QFrame[frameShape="4"] {
    color: #E2E8F0;
    background-color: #E2E8F0;
    max-height: 1px;
    border: none;
}

/* ── Progress Dialog ── */
QProgressDialog {
    background-color: white;
    border: 1px solid #E2E8F0;
    border-radius: 12px;
}
QProgressDialog QLabel { color: #1E293B; font-size: 14px; }
"""
