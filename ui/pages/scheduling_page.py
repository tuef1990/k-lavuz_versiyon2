from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel,
                             QPushButton, QTableWidget, QTableWidgetItem, QHeaderView,
                             QDateTimeEdit, QRadioButton, QButtonGroup, QProgressBar,
                             QProgressDialog, QAbstractItemView, QDoubleSpinBox, QStyledItemDelegate,
                             QScrollArea, QFrame, QSpacerItem, QSizePolicy, QComboBox, QMessageBox,
                             QFileDialog, QDateEdit, QTimeEdit, QCheckBox, QDialog,
                             QDialogButtonBox, QSpinBox, QLineEdit)
from PyQt6.QtCore import Qt, QDateTime, pyqtSignal, QDate
from datetime import datetime
import math
import os


class _EkUretimDialog(QDialog):
    """Ek üretim listesi giriş dialog'u: dinamik satırlar, ürün combo + adet."""

    def __init__(self, product_options, info_text="", parent=None):
        super().__init__(parent)
        self.setWindowTitle("Ek Üretim Listesi")
        self.setMinimumWidth(540)
        self._product_options = list(product_options)
        self._rows: list = []

        root = QVBoxLayout(self)

        if info_text:
            info = QLabel(info_text)
            info.setWordWrap(True)
            info.setStyleSheet(
                "background:#EFF6FF; color:#1E40AF; border:1px solid #BFDBFE;"
                "border-radius:6px; padding:10px; font-size:12px;"
            )
            root.addWidget(info)

        hint = QLabel(
            "Sırayla yapılmasını istediğiniz ürün ve adetleri girin. "
            "Listedeki sıraya göre üretilirler. Kapasite tamamlanmazsa bir sonraki "
            "ürünü kullanır."
        )
        hint.setWordWrap(True)
        hint.setStyleSheet("color:#475569; font-size:11px;")
        root.addWidget(hint)

        self._rows_container = QVBoxLayout()
        self._rows_container.setSpacing(6)
        root.addLayout(self._rows_container)

        add_btn = QPushButton("+ Satır Ekle")
        add_btn.setStyleSheet(
            "QPushButton { background:#EFF6FF; color:#1E40AF; "
            "border:1.5px solid #BFDBFE; border-radius:6px; padding:6px 14px; "
            "font-weight:600; }"
            "QPushButton:hover { background:#DBEAFE; }"
        )
        add_btn.clicked.connect(self._add_row)
        root.addWidget(add_btn, alignment=Qt.AlignmentFlag.AlignLeft)

        btn_box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        btn_box.button(QDialogButtonBox.StandardButton.Ok).setText("Onayla ve Çalıştır")
        btn_box.button(QDialogButtonBox.StandardButton.Cancel).setText("İptal")
        btn_box.accepted.connect(self.accept)
        btn_box.rejected.connect(self.reject)
        root.addWidget(btn_box)

        # Default 1 satır
        self._add_row()

    def _add_row(self):
        row_w = QWidget()
        h = QHBoxLayout(row_w)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(8)
        type_combo = QComboBox()
        type_combo.setEditable(False)
        for t in self._product_options:
            type_combo.addItem(t)
        type_combo.addItem("Diğer")
        type_combo.setMinimumWidth(110)
        h.addWidget(type_combo, stretch=1)
        type_input = QLineEdit()
        type_input.setPlaceholderText("yeni tip")
        type_input.setFixedWidth(100)
        type_input.hide()
        h.addWidget(type_input)
        name_input = QLineEdit()
        name_input.setPlaceholderText("ürün ismi")
        name_input.setMinimumWidth(180)
        h.addWidget(name_input, stretch=2)
        qty = QSpinBox()
        qty.setRange(1, 1000)
        qty.setValue(1)
        qty.setSuffix(" adet")
        qty.setFixedWidth(90)
        h.addWidget(qty)
        del_btn = QPushButton("✕")
        del_btn.setFixedSize(28, 28)
        del_btn.setStyleSheet(
            "QPushButton { background:#FEF2F2; color:#DC2626; "
            "border:1px solid #FCA5A5; border-radius:4px; }"
            "QPushButton:hover { background:#FEE2E2; }"
        )
        h.addWidget(del_btn)

        def _on_type_changed(text):
            type_input.setVisible(text == "Diğer")

        type_combo.currentTextChanged.connect(_on_type_changed)

        self._rows.append((row_w, type_combo, type_input, name_input, qty))
        self._rows_container.addWidget(row_w)
        del_btn.clicked.connect(lambda _, w=row_w: self._remove_row(w))

    def _remove_row(self, row_widget):
        for i, row in enumerate(self._rows):
            if row[0] is row_widget:
                self._rows.pop(i)
                row_widget.setParent(None)
                row_widget.deleteLater()
                break

    def get_list(self) -> list:
        result = []
        for _w, type_combo, type_input, name_input, qty in self._rows:
            selected = type_combo.currentText().strip()
            ptype = type_input.text().strip() if selected == "Diğer" else selected
            pname = name_input.text().strip()
            n = qty.value()
            if ptype and pname and n > 0:
                result.append({
                    "product_type": ptype,
                    "product_name": pname,
                    "qty": n,
                })
        return result


# Removed PriorityDelegate as requested

class SchedulingPage(QWidget):
    schedule_completed = pyqtSignal(object)
    excel_load_requested = pyqtSignal()
    excel_clear_requested = pyqtSignal()

    def __init__(self, data_manager, parent=None):
        super().__init__(parent)
        self.data_manager = data_manager
        self.priority_overrides = {}
        # Üretilen miktarlar artık data_manager.state.produced_amounts'ta;
        # bu bir property gibi davranan kolaylık erişimi. Ürün Bilgileri tablosuyla senkron.
        self._init_ui()

    def _init_ui(self):
        # Base Layout
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

       
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setStyleSheet("background-color: #F7FAFC;")
        main_layout.addWidget(scroll)

        # Content Widget
        content_widget = QWidget()
        content_widget.setObjectName("ContentArea")
        scroll.setWidget(content_widget)
        
        layout = QVBoxLayout(content_widget)
        layout.setSpacing(25)
        layout.setContentsMargins(40, 40, 40, 40)

        # 1. HEADER SECTION
        header_container = QWidget()
        header_layout = QVBoxLayout(header_container)
        header_layout.setContentsMargins(0, 0, 0, 0)
        
        title = QLabel("Üretim Çizelgeleme ve Optimizasyon")
        title.setObjectName("PageTitle")
        header_layout.addWidget(title)

        subtitle = QLabel(
            "Üretim hedefleri ve kısıtları doğrultusunda olay-güdümlü simülasyon motorunu yapılandırın."
        )
        subtitle.setObjectName("PageSubtitle")
        header_layout.addWidget(subtitle)
        
        layout.addWidget(header_container)

        # 2. CONFIGURATION SECTION (Unified Yapılandırma)
        config_card = QFrame()
        config_card.setStyleSheet("""
            QFrame {
                background-color: white;
                border-radius: 12px;
                border: 1px solid #E2E8F0;
            }
        """)
        config_layout = QVBoxLayout(config_card)
        config_layout.setContentsMargins(30, 25, 30, 25)
        config_layout.setSpacing(20)

        # --- İlk olarak widgetları oluştur ---
        self.period_combo = QComboBox()
        self.period_combo.addItem("📅 Aylık Planlama (1 Ay)", "monthly")
        self.period_combo.addItem("⏱️ Haftalık Planlama (7 Gün)", "weekly")
        self.period_combo.addItem("🎯 Serbest Seçim (Özel Aralık)", "custom")
        self.period_combo.setCurrentIndex(1)  # Default: Haftalık
        self.period_combo.setFixedWidth(300)
        self.period_combo.setStyleSheet("color: #2D3748; background-color: white; padding: 8px;")

        self.start_date = QDateEdit(QDate.currentDate())
        self.start_date.setCalendarPopup(True)
        self.start_date.setDisplayFormat("dd.MM.yyyy")
        self.start_date.setMinimumWidth(150)
        self.start_date.setStyleSheet("""
            QDateEdit {
                color: #2D3748; 
                background-color: white; 
                border: 1px solid #CBD5E0; 
                border-radius: 6px; 
                padding: 5px;
            }
            QDateEdit::drop-down {
                subcontrol-origin: padding;
                subcontrol-position: top right;
                width: 25px;
                border-left: 1px solid #CBD5E0;
                background-color: #F1F5F9;
                border-top-right-radius: 6px;
                border-bottom-right-radius: 6px;
            }
            QDateEdit::down-arrow {
                image: none;
                border-left: 4px solid transparent;
                border-right: 4px solid transparent;
                border-top: 5px solid #475569;
                width: 0;
                height: 0;
            }
        """)

        from PyQt6.QtCore import QTime
        self.start_time = QTimeEdit(QTime(7, 0))
        self.start_time.setDisplayFormat("HH:mm")
        self.start_time.setStyleSheet("color: #2D3748; background-color: white; border: 1px solid #CBD5E0; border-radius: 6px; padding: 10px;")

        self.end_date = QDateEdit(QDate.currentDate().addMonths(1))
        self.end_date.setCalendarPopup(True)
        self.end_date.setDisplayFormat("dd.MM.yyyy")
        self.end_date.setMinimumWidth(150)
        self.end_date.setStyleSheet("""
            QDateEdit {
                color: #2D3748; 
                background-color: #F8FAFC; 
                border: 1px solid #CBD5E0; 
                border-radius: 6px; 
                padding: 5px;
            }
            QDateEdit:disabled { background-color: #EDF2F7; color: #A0AEC0; }
            QDateEdit::drop-down {
                subcontrol-origin: padding;
                subcontrol-position: top right;
                width: 25px;
                border-left: 1px solid #CBD5E0;
                background-color: #F1F5F9;
                border-top-right-radius: 6px;
                border-bottom-right-radius: 6px;
            }
            QDateEdit::down-arrow {
                image: none;
                border-left: 4px solid transparent;
                border-right: 4px solid transparent;
                border-top: 5px solid #475569;
                width: 0;
                height: 0;
            }
        """)
        self.end_date.setEnabled(False)

        self.end_time = QTimeEdit(QTime(7, 0))
        self.end_time.setDisplayFormat("HH:mm")
        self.end_time.setStyleSheet("color: #2D3748; background-color: #F8FAFC; border: 1px solid #CBD5E0; border-radius: 6px; padding: 10px;")
        self.end_time.setEnabled(False)

        self.algo_combo = QComboBox()
        self.algo_combo.addItem("Sevkiyat Destekli Yaklaşım")
        self.algo_combo.addItem("Makina Verimli Dengeli Yaklaşım")
        self.algo_combo.addItem("Optimal Yaklaşım")
        self.algo_combo.setFixedWidth(300)
        self.algo_combo.setStyleSheet("color: #2D3748; background-color: white; padding: 8px;")

        # Hafta numarası girişi — 0-3 arası tamsayı
        from PyQt6.QtWidgets import QSpinBox
        self.week_spinbox = QSpinBox()
        self.week_spinbox.setRange(0, 3)
        self.week_spinbox.setValue(0)
        self.week_spinbox.setFixedWidth(80)
        self.week_spinbox.setStyleSheet(
            "color: #1E293B; background: white; border: 1.5px solid #CBD5E1; "
            "border-radius: 6px; padding: 6px 8px; font-size: 14px; font-weight: 700;"
        )
        self.week_spinbox.setToolTip(
            "Mevcut ayın hafta numarasını girin (0–3).\n"
            "  0  →  Ayın 1. haftası  →  Kalan ÷ 4\n"
            "  1  →  Ayın 2. haftası  →  Kalan ÷ 3\n"
            "  2  →  Ayın 3. haftası  →  Kalan ÷ 2\n"
            "  3  →  Ayın 4. haftası  →  Kalanın tamamı\n\n"
            "Kalan = Aylık hedef − Bu ay üretilen\n"
        )

        # --- Layout'a ekle ---
        # 1. Periyot Satırı
        period_row = QHBoxLayout()
        period_row.addWidget(QLabel("<b>Planlama Periyodu:</b>"))
        period_row.addWidget(self.period_combo)
        period_row.addStretch()
        config_layout.addLayout(period_row)

        line1 = QFrame()
        line1.setFrameShape(QFrame.Shape.HLine)
        line1.setStyleSheet("color: #EDF2F7;")
        config_layout.addWidget(line1)

        # 2. Tarih Satırı
        date_row = QHBoxLayout()
        
        # Başlangıç Grubu
        start_group = QVBoxLayout()
        start_group.addWidget(QLabel("<b>Başlangıç:</b>"))
        start_widgets = QHBoxLayout()
        start_widgets.addWidget(self.start_date)
        start_widgets.addWidget(self.start_time)
        start_group.addLayout(start_widgets)
        date_row.addLayout(start_group)
        
        date_row.addSpacing(40)

        # Bitiş Grubu
        end_group = QVBoxLayout()
        end_group.addWidget(QLabel("<b>Bitiş:</b>"))
        end_widgets = QHBoxLayout()
        end_widgets.addWidget(self.end_date)
        end_widgets.addWidget(self.end_time)
        end_group.addLayout(end_widgets)
        date_row.addLayout(end_group)
        
        config_layout.addLayout(date_row)

        # 3. Algoritma Satırı
        algo_row = QHBoxLayout()
        algo_row.addWidget(QLabel("<b>Planlama Algoritması:</b>"))
        algo_row.addWidget(self.algo_combo)
        algo_row.addStretch()
        config_layout.addLayout(algo_row)

        line2 = QFrame()
        line2.setFrameShape(QFrame.Shape.HLine)
        line2.setStyleSheet("color: #EDF2F7;")
        config_layout.addWidget(line2)

        # 4. Hafta Numarası Satırı (aylık modda gizleniyor)
        self.week_row_widget = QWidget()
        week_row = QHBoxLayout(self.week_row_widget)
        week_row.setContentsMargins(0, 0, 0, 0)
        week_row.setSpacing(12)

        week_label = QLabel("<b>Hafta Numarası:</b>")
        week_label.setToolTip("0–3 arası tam sayı. Öncelik formülünde (4 – hafta_no) paydasında kullanılır.")
        week_row.addWidget(week_label)
        week_row.addWidget(self.week_spinbox)

        # Hafta bağlamı kutusu — kullanıcıya değer anlamını gösterir
        context_frame = QFrame()
        context_frame.setStyleSheet(
            "background:#F8FAFC; border:1px solid #E2E8F0; border-radius:6px;"
        )
        context_lay = QHBoxLayout(context_frame)
        context_lay.setContentsMargins(10, 6, 10, 6)
        context_lay.setSpacing(14)

        def _wbadge(num, label, color):
            w = QLabel(f"<b>{num}</b> = {label}")
            w.setStyleSheet(f"color:{color}; font-size:12px; background:transparent; border:none;")
            return w

        context_lay.addWidget(_wbadge("0", "1. Hafta", "#059669"))
        context_lay.addWidget(_wbadge("1", "2. Hafta", "#0891B2"))
        context_lay.addWidget(_wbadge("2", "3. Hafta", "#D97706"))
        context_lay.addWidget(_wbadge("3", "4. Hafta (son)", "#DC2626"))
        week_row.addWidget(context_frame)

        week_note = QLabel("Gelecek hafta işleri öncelik −0.001 alır")
        week_note.setStyleSheet(
            "color:#7C3AED; font-size:11px; font-weight:600; background:transparent;"
        )
        week_row.addWidget(week_note)
        week_row.addStretch()
        config_layout.addWidget(self.week_row_widget)

        # Aylık modda spinbox 0'a kilitlenir (kullanıcı değiştiremez); scheduler 7 günde bir kendi artırır
        def _update_week_lock():
            is_monthly = self.period_combo.currentData() == "monthly"
            if is_monthly:
                self.week_spinbox.setValue(0)
            self.week_spinbox.setEnabled(not is_monthly)
        self.period_combo.currentIndexChanged.connect(lambda _: _update_week_lock())
        _update_week_lock()

        # 5. Hafta Sonu Vardiya Ayarları
        line_we = QFrame()
        line_we.setFrameShape(QFrame.Shape.HLine)
        line_we.setStyleSheet("color: #EDF2F7;")
        config_layout.addWidget(line_we)

        # Yardım overlay'i için hafta sonu bölümünü tek bir widget'a sar
        self.weekend_section = QWidget()
        weekend_lay = QVBoxLayout(self.weekend_section)
        weekend_lay.setContentsMargins(0, 0, 0, 0)
        weekend_lay.setSpacing(10)
        config_layout.addWidget(self.weekend_section)

        we_title = QLabel("<b>Hafta Sonu Vardiya Ayarları</b>")
        weekend_lay.addWidget(we_title)

        cb_style = """
            QCheckBox { color: #1E293B; font-size: 13px; spacing: 6px; }
            QCheckBox::indicator { width: 16px; height: 16px; border-radius: 4px;
                border: 1.5px solid #CBD5E1; background: white; }
            QCheckBox::indicator:checked { background: #2563EB; border-color: #2563EB; }
        """

        # Cumartesi satırı
        sat_row = QHBoxLayout()
        sat_row.setSpacing(16)
        sat_lbl = QLabel("Cumartesi:")
        sat_lbl.setFixedWidth(90)
        sat_lbl.setStyleSheet("color: #374151; font-weight: 600;")
        sat_row.addWidget(sat_lbl)
        self._sat_checks: list[QCheckBox] = []
        for i in range(3):
            cb = QCheckBox(f"Vardiya {i + 1}")
            cb.setStyleSheet(cb_style)
            cb.stateChanged.connect(self._save_weekend_shifts)
            self._sat_checks.append(cb)
            sat_row.addWidget(cb)
        sat_row.addStretch()
        weekend_lay.addLayout(sat_row)

        # Pazar satırı
        sun_row = QHBoxLayout()
        sun_row.setSpacing(16)
        sun_lbl = QLabel("Pazar:")
        sun_lbl.setFixedWidth(90)
        sun_lbl.setStyleSheet("color: #374151; font-weight: 600;")
        sun_row.addWidget(sun_lbl)
        self._sun_checks: list[QCheckBox] = []
        for i in range(3):
            cb = QCheckBox(f"Vardiya {i + 1}")
            cb.setStyleSheet(cb_style)
            cb.stateChanged.connect(self._save_weekend_shifts)
            self._sun_checks.append(cb)
            sun_row.addWidget(cb)
        sun_row.addStretch()
        weekend_lay.addLayout(sun_row)

        # Checkbox başlangıç değerlerini yükle
        self._load_weekend_shifts()

        layout.addWidget(config_card)
        
       

        # 3. PRODUCTION TARGETS TABLE
        targets_section = QWidget()
        targets_layout = QVBoxLayout(targets_section)
        targets_layout.setContentsMargins(0, 0, 0, 0)

        lbl_targets = QLabel("Üretim Hedefleri")
        lbl_targets.setObjectName("SectionTitle")
        targets_layout.addWidget(lbl_targets)
        
        self.target_table = QTableWidget(0, 3)
        self.target_table.setHorizontalHeaderLabels(
            ["Ürün Tipi", "Kalan Aylık Hedef", "Excel Verisi"]
        )
        self.target_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        # Tablo geneli düzenlenebilir olsun (sütun bazlı kısıtlamayı data dolarken yapacağız)
        self.target_table.setMinimumHeight(250)  
        self.target_table.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.target_table.setAlternatingRowColors(True)
        self.target_table.setStyleSheet("""
            QTableWidget {
                background-color: white;
                border: 1px solid #E2E8F0;
                border-radius: 8px;
                gridline-color: #F1F5F9;
            }
            QHeaderView::section {
                background-color: #F8FAFC;
                padding: 10px;
                border: none;
                border-bottom: 2px solid #E2E8F0;
                font-weight: bold;
            }
        """)
        targets_layout.addWidget(self.target_table)
        layout.addWidget(targets_section)

        # Signal Connections
        self.period_combo.currentIndexChanged.connect(self.update_target_table)
        self.period_combo.currentIndexChanged.connect(self.sync_dates)
        self.start_date.dateChanged.connect(self.sync_dates)
        self.start_time.timeChanged.connect(self.update_target_table)
        self.end_date.dateChanged.connect(self.update_target_table)
        self.end_time.timeChanged.connect(self.update_target_table)
        
        # Initial call
        self.sync_dates()

        # Removed PRIORITY CALCULATION section as requested to simplify the UI

        # Excel ile çalışma — yüklü Excel = bu haftanın iş listesi
        excel_row_widget = QWidget()
        excel_row = QHBoxLayout(excel_row_widget)
        excel_row.setContentsMargins(0, 8, 0, 0)
        excel_row.setSpacing(10)

        self._excel_status_label = QLabel("📊  Excel verisi yüklü değil")
        self._excel_status_label.setStyleSheet(
            "color:#475569; font-size:13px; font-weight:600; background:transparent;"
        )
        excel_row.addWidget(self._excel_status_label)
        excel_row.addStretch()

        self._btn_excel_load = QPushButton("Excel Yükle")
        self._btn_excel_load.setFixedHeight(32)
        self._btn_excel_load.setCursor(Qt.CursorShape.PointingHandCursor)
        self._btn_excel_load.setStyleSheet(
            "QPushButton { background:#EFF6FF; color:#1D4ED8; "
            "border:1.5px solid #93C5FD; border-radius:6px; padding:0 14px; "
            "font-weight:600; font-size:12px; }"
            "QPushButton:hover { background:#DBEAFE; }"
        )
        self._btn_excel_load.clicked.connect(self.excel_load_requested.emit)
        excel_row.addWidget(self._btn_excel_load)

        self._btn_excel_clear = QPushButton("Kaldır")
        self._btn_excel_clear.setFixedHeight(32)
        self._btn_excel_clear.setCursor(Qt.CursorShape.PointingHandCursor)
        self._btn_excel_clear.setStyleSheet(
            "QPushButton { background:#FEF2F2; color:#DC2626; "
            "border:1.5px solid #FCA5A5; border-radius:6px; padding:0 14px; "
            "font-weight:600; font-size:12px; }"
            "QPushButton:hover { background:#FEE2E2; }"
        )
        self._btn_excel_clear.clicked.connect(self.excel_clear_requested.emit)
        self._btn_excel_clear.hide()
        excel_row.addWidget(self._btn_excel_clear)

        layout.addWidget(excel_row_widget)
        self._refresh_excel_status()
        self.data_manager.products_changed.connect(self._refresh_excel_status)
        # Üretilen miktar Ürün Bilgileri tablosundan değişirse hedef tablosu yenilensin
        self.data_manager.products_changed.connect(self.update_target_table)

        # Ek üretim seçimi
        ek_row = QHBoxLayout()
        ek_row.setContentsMargins(0, 8, 0, 0)
        self.cb_ek_uretim = QCheckBox("Ek üretim ekle")
        self.cb_ek_uretim.setStyleSheet("color:#1E293B;font-size:13px;font-weight:600;")
        self.cb_ek_uretim.setToolTip(
            "İşaretlerseniz Çalıştır'a bastığınızda hangi ürünleri ek üretim olarak yapacağınızı "
            "girebileceğiniz bir pencere açılır. İşaretlemezseniz ek üretim olmaz."
        )
        ek_row.addWidget(self.cb_ek_uretim)
        ek_row.addStretch()
        layout.addLayout(ek_row)

        # 4. GENERATE BUTTON (Moved below the table)
        spacer = QSpacerItem(20, 10, QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Expanding)
        layout.addItem(spacer)

        self.btn_generate = QPushButton("▶  Üretim Simülasyonunu Başlat")
        self.btn_generate.setFixedHeight(56)
        self.btn_generate.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_generate.setStyleSheet("""
            QPushButton {
                background-color: #059669;
                color: white;
                font-weight: 800;
                font-size: 17px;
                border: none;
                border-radius: 10px;
                letter-spacing: 0.5px;
            }
            QPushButton:hover  { background-color: #047857; }
            QPushButton:pressed { background-color: #065F46; }
        """)
        self.btn_generate.clicked.connect(self.on_generate_schedule)
        layout.addWidget(self.btn_generate)

        # Initial target table update
        self.update_target_table()

    # =====================================================
    # MEVCUT METOTLAR
    # =====================================================

    # ── Hafta Sonu Vardiya Ayarları ──────────────────────────────────────────
    def _load_weekend_shifts(self):
        """data_manager'dan weekend_shifts okuyup checkbox'ları günceller."""
        ws = getattr(self.data_manager.state, "weekend_shifts", {"saturday": [0], "sunday": []})
        saturday = ws.get("saturday", [0])
        sunday = ws.get("sunday", [])
        for i, cb in enumerate(self._sat_checks):
            cb.blockSignals(True)
            cb.setChecked(i in saturday)
            cb.blockSignals(False)
        for i, cb in enumerate(self._sun_checks):
            cb.blockSignals(True)
            cb.setChecked(i in sunday)
            cb.blockSignals(False)

    def _save_weekend_shifts(self):
        """Checkbox değişikliğini data_manager'a kaydeder."""
        saturday = [i for i, cb in enumerate(self._sat_checks) if cb.isChecked()]
        sunday = [i for i, cb in enumerate(self._sun_checks) if cb.isChecked()]
        self.data_manager.state.weekend_shifts = {"saturday": saturday, "sunday": sunday}
        self.data_manager.save_state()

    # ─────────────────────────────────────────────────────────────────────────

    def update_target_table(self):
        project_data = self.data_manager.state
        excel_products = getattr(self.data_manager, "excel_products", None)
        period_data = self.period_combo.currentData()

        # Periyot gün farkını hesapla (Özel seçim için)
        start_date = self.start_date.date()
        end_date = self.end_date.date()
        days_diff = start_date.daysTo(end_date)
        if days_diff <= 0: days_diff = 1 # Minimum 1 gün

        excel_only = getattr(self.data_manager, "excel_only_mode", False)
        excel_types = {ep.product_type for ep in excel_products} if excel_products else set()

        # Excel tiplerini topla: aynı tipten kaç adet var → hepsini say (gelecek tarihli dahil)
        excel_qty_by_type = {}   # product_type → toplam adet
        excel_name_by_type = {}  # product_type → display_name (ilk eşleşen)
        excel_products_list = getattr(self.data_manager, "excel_products", None) or []
        for ep in excel_products_list:
            excel_qty_by_type[ep.product_type] = excel_qty_by_type.get(ep.product_type, 0) + ep.quantity
            if ep.product_type not in excel_name_by_type:
                excel_name_by_type[ep.product_type] = ep.display_name

        ep_by_name = {ep.display_name: ep for ep in excel_products_list}

        products_to_show = []

        # Excel ürünlerini tip bazında birleştirerek ekle
        if excel_products:
            for pt, total_qty in excel_qty_by_type.items():
                display_name = excel_name_by_type[pt]
                products_to_show.append((pt, display_name, total_qty, "Excel"))

        # Sadece Excel modu kapalıysa tablodaki ürünleri de ekle
        if not excel_only:
            for p in project_data.products:
                if period_data == "monthly":
                    base_target = p.monthly_target
                elif period_data == "weekly":
                    base_target = math.ceil(p.monthly_target / 4)
                else:
                    base_target = math.ceil(p.monthly_target * days_diff / 30)
                source = "Excel" if p.type in excel_types else "—"
                products_to_show.append((p.type, p.display_name, base_target, source))

        # Duplicate product_type satırlarını teklestir (aynı tip için sadece bir satır)
        seen_types = set()
        unique_rows = []
        for row in products_to_show:
            pt = row[0]
            if pt not in seen_types:
                seen_types.add(pt)
                unique_rows.append(row)

        self.target_table.blockSignals(True)
        self.target_table.setRowCount(len(unique_rows))

        excel_only_types = getattr(self.data_manager, "excel_only_types", set())

        from PyQt6.QtGui import QColor, QBrush
        for i, (pt, display_name, base_target, source) in enumerate(unique_rows):
            # Kolon 0: Ürün Tipi
            item_name = QTableWidgetItem(pt)
            item_name.setFlags(item_name.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.target_table.setItem(i, 0, item_name)

            # Kalan Aylık Hedef = Aylık Hedef − Üretilen
            # Excel yüklemesinden bağımsız: hem aylık hedef hem üretilen, state.products'taki
            # bu tipe ait ürünün kendi display_name'i üzerinden okunur.
            prod = next((p for p in project_data.products if p.type == pt), None)
            table_monthly = prod.monthly_target if prod else 0
            produced_key = prod.display_name if prod else display_name
            produced = self.data_manager.state.produced_amounts.get(produced_key, 0)
            remaining = table_monthly - produced
            excel_qty = excel_qty_by_type.get(pt)

            # Kolon 1: Kalan Aylık Hedef = aylık hedef - üretilen
            item_remaining = QTableWidgetItem(str(remaining))
            item_remaining.setFlags(item_remaining.flags() & ~Qt.ItemFlag.ItemIsEditable)
            item_remaining.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.target_table.setItem(i, 1, item_remaining)

            # Kolon 2: Excel Verisi
            if excel_qty is not None:
                excel_text = str(excel_qty)
                excel_color = QColor("#1D4ED8")
            else:
                excel_text = "girilmedi"
                excel_color = QColor("#94A3B8")
            item_excel = QTableWidgetItem(excel_text)
            item_excel.setFlags(item_excel.flags() & ~Qt.ItemFlag.ItemIsEditable)
            item_excel.setForeground(QBrush(excel_color))
            item_excel.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.target_table.setItem(i, 2, item_excel)

        self.target_table.blockSignals(False)

    def sync_dates(self):
        """Başlangıç tarihine göre bitiş tarihini 1 hafta veya 1 ay olarak kısıtla."""
        start_date_val = self.start_date.date()
        period_data = self.period_combo.currentData()
        
        if period_data == "weekly":
            # 1 Hafta sonrası
            end_date_val = start_date_val.addDays(7)
            self.end_date.setEnabled(False)
            self.end_time.setEnabled(False)
            self.end_date.setStyleSheet("color: #2D3748; background-color: #F8FAFC; border: 1px solid #CBD5E0; border-radius: 6px; padding: 10px;")
            self.end_time.setStyleSheet("color: #2D3748; background-color: #F8FAFC; border: 1px solid #CBD5E0; border-radius: 6px; padding: 10px;")
        elif period_data == "monthly":
            # 1 Ay sonrası
            end_date_val = start_date_val.addMonths(1)
            self.end_date.setEnabled(False)
            self.end_time.setEnabled(False)
            self.end_date.setStyleSheet("color: #2D3748; background-color: #F8FAFC; border: 1px solid #CBD5E0; border-radius: 6px; padding: 10px;")
            self.end_time.setStyleSheet("color: #2D3748; background-color: #F8FAFC; border: 1px solid #CBD5E0; border-radius: 6px; padding: 10px;")
        else:
            # Serbest Seçim - Düzenlenebilir
            self.end_date.setMinimumDate(start_date_val)
            self.end_date.setEnabled(True)
            self.end_time.setEnabled(True)
            self.end_date.setStyleSheet("""
                QDateEdit {
                    color: #2D3748; 
                    background-color: white; 
                    border: 1.5px solid #059669; 
                    border-radius: 6px; 
                    padding: 5px;
                }
                QDateEdit::drop-down {
                    subcontrol-origin: padding;
                    subcontrol-position: top right;
                    width: 25px;
                    border-left: 1.5px solid #059669;
                    background-color: #ECFDF5;
                    border-top-right-radius: 6px;
                    border-bottom-right-radius: 6px;
                }
                QDateEdit::down-arrow {
                    image: none;
                    border-left: 4px solid transparent;
                    border-right: 4px solid transparent;
                    border-top: 5px solid #059669;
                    width: 0;
                    height: 0;
                }
            """)
            self.end_time.setStyleSheet("color: #2D3748; background-color: white; border: 1.5px solid #059669; border-radius: 6px; padding: 10px;")
            return # Bitiş tarihini otomatik ezme
        
        self.end_date.setDate(end_date_val)
        self.end_time.setTime(self.start_time.time())

    # Removed manual on_calculate_priorities and on_priority_changed methods.

    def _refresh_excel_status(self):
        """Excel yüklü durumuna göre label ve buton görünürlüğünü günceller."""
        excel_products = getattr(self.data_manager, "excel_products", None)
        loaded = bool(excel_products)
        if loaded:
            count = len(excel_products)
            self._excel_status_label.setText(f"📊  Excel yüklü ({count} satır) — bu haftanın iş listesi")
            self._excel_status_label.setStyleSheet(
                "color:#1D4ED8; font-size:13px; font-weight:700; background:transparent;"
            )
            self._btn_excel_clear.show()
        else:
            self._excel_status_label.setText("📊  Excel verisi yüklü değil")
            self._excel_status_label.setStyleSheet(
                "color:#475569; font-size:13px; font-weight:600; background:transparent;"
            )
            self._btn_excel_clear.hide()

    def _make_scheduler(self):
        from algorithms.priority_scheduler import PriorityBasedScheduler
        from algorithms.priority_scheduler_v2 import PriorityBasedSchedulerV2
        idx = self.algo_combo.currentIndex()
        if idx == 1:
            return PriorityBasedSchedulerV2()
        if idx == 2:
            from algorithms.mathematical_scheduler import MathematicalScheduler
            return MathematicalScheduler()
        return PriorityBasedScheduler()

    def _calc_assembly_working_hours(self, start, end) -> float:
        """Period içinde Assembly'nin GERÇEKTEN çalışabileceği toplam saat
        (allowed vardıyalar + weekend_shifts'e göre)."""
        from datetime import timedelta
        ws = getattr(self.data_manager.state, "weekend_shifts", {"saturday": [0], "sunday": []})
        shifts = self.data_manager.state.shift_data.get("Assembly", [])
        if not shifts:
            return 0.0

        def _shift_hours(s) -> float:
            try:
                sh, sm = map(int, s["start"].split(":"))
                eh, em = map(int, s["end"].split(":"))
                start_dec = sh + sm / 60.0
                end_dec = eh + em / 60.0
                if end_dec > start_dec:
                    return end_dec - start_dec
                return 24.0 - start_dec + end_dec  # gece yarısını geçen
            except Exception:
                return 0.0

        total = 0.0
        cur = start.date()
        end_d = end.date()
        while cur <= end_d:
            wd = cur.weekday()
            if wd == 6:
                allowed = ws.get("sunday", [])
            elif wd == 5:
                allowed = ws.get("saturday", [0])
            else:
                allowed = list(range(len(shifts)))
            for idx in allowed:
                if 0 <= idx < len(shifts):
                    total += _shift_hours(shifts[idx])
            cur += timedelta(days=1)
        return total

    def _calc_idle_assembly_capacity(self, result, start, end) -> tuple:
        """Assembly boş kapasitesi: aylık hedef bittikten SONRA period sonuna kadar
        kalan izinli vardıya saatleri (weekend_shifts kuralına göre).
        Dönüş: (idle_hours, approx_pieces)."""
        # Son Assembly batch bitiş zamanını bul
        from datetime import datetime as _dt, timedelta as _td, time as _time
        asm_ends = [e.end_time for e in result.schedule
                    if e.step_name.lower() == "assembly"]
        if not asm_ends:
            # Hiç Assembly işi yok → tüm period boş
            idle = self._calc_assembly_working_hours(start, end)
        else:
            last_end = max(asm_ends)
            # Conservative: son batch'in günü "kullanılmış" say, sonraki günden itibaren say
            day_after = last_end.date() + _td(days=1)
            day_after_dt = _dt.combine(day_after, _time.min)
            if day_after_dt >= end:
                idle = 0.0
            else:
                idle = self._calc_assembly_working_hours(day_after_dt, end)
        # Ortalama Assembly süresi ve kapasitesi
        try:
            pt = self.data_manager.state.production_time_data or {}
            asm_times = [t.get("Assembly", 0) for t in pt.values() if (t.get("Assembly", 0) or 0) > 0]
            avg_t = (sum(asm_times) / len(asm_times)) if asm_times else 3.5
            cap = self.data_manager.state.capacity_data or {}
            asm_caps = []
            for stages in cap.values():
                vals = stages.get("Assembly", [])
                if vals:
                    try:
                        asm_caps.append(int(vals[0]))
                    except Exception:
                        pass
            avg_cap = (sum(asm_caps) / len(asm_caps)) if asm_caps else 10.0
        except Exception:
            avg_t, avg_cap = 3.5, 10.0
        # Assembly'de setup yok → her batch süresi = avg_t (sadece process_time)
        # Kapasite tablosundaki değer (avg_cap) ile çarpılarak adet bulunur
        approx = int((idle / avg_t) * avg_cap) if avg_t > 0 else 0
        return idle, approx

    def on_generate_schedule(self):
        # Optimal Yaklaşım seçiliyse ve ürün sayısı limiti aşıyorsa simülasyonu başlatma
        if self.algo_combo.currentIndex() == 2:
            from algorithms.mathematical_scheduler import MAX_PRODUCTS
            from PyQt6.QtWidgets import QMessageBox
            if len(self.data_manager.state.products) >= MAX_PRODUCTS:
                box = QMessageBox(self)
                box.setIcon(QMessageBox.Icon.Warning)
                box.setWindowTitle("Optimal Yaklaşım")
                box.setText("Np Hard Problemdir Parça adedi 5'ten fazla ise çözdürülemez")
                box.setStandardButtons(QMessageBox.StandardButton.Ok)
                box.exec()
                return

        excel_products = getattr(self.data_manager, "excel_products", None)
        is_excel_mode = excel_products is not None and len(excel_products) > 0

        # Aylık modda kullanıcı hafta giremez; kod 0'dan başlar ve scheduler her 7 günde bir kendi artırır
        week_number = 0 if self.period_combo.currentData() == "monthly" else self.week_spinbox.value()

        if is_excel_mode:
            progress_text = "Excel verisiyle simülasyon motoru çalışıyor..."
        else:
            progress_text = "Simülasyon motoru çalışıyor, üretim çizelgesi oluşturuluyor..."

        from PyQt6.QtCore import QDateTime
        start_dt = QDateTime(self.start_date.date(), self.start_time.time())
        end_dt = QDateTime(self.end_date.date(), self.end_time.time())
        start = start_dt.toPyDateTime()
        end = end_dt.toPyDateTime()
        period = self.period_combo.currentData()

        progress = QProgressDialog(progress_text, None, 0, 0, self)
        progress.setWindowTitle("Zeka İşleniyor")
        progress.setWindowModality(Qt.WindowModality.WindowModal)
        progress.show()

        scheduler = self._make_scheduler()

        try:
            # Aşama 1: Ek üretim olmadan çalıştır (her durumda)
            result = scheduler.solve(
                self.data_manager.state, start, end, period,
                self.priority_overrides,
                excel_products=excel_products,
                week_number=week_number,
                produced_amounts=self.data_manager.state.produced_amounts,
                excel_only=getattr(self.data_manager, "excel_only_mode", False),
            )
            progress.close()

            # Ek üretim checkbox'ı işaretliyse: kullanıcıya liste gir, sonra 2. çalıştır
            if hasattr(self, "cb_ek_uretim") and self.cb_ek_uretim.isChecked():
                idle_h, approx = self._calc_idle_assembly_capacity(result, start, end)
                info = (
                    f"Aylık hedef bittikten sonra Assembly'de yaklaşık {idle_h:.1f} saatlik "
                    f"boş kapasite kalıyor (~{approx} parça yapılabilir).\n\n"
                    f"Aşağıya yapmak istediğiniz ek üretim ürünlerini sıralı girin."
                )
                product_options = sorted({p.type for p in self.data_manager.state.products if p.type})
                dlg = _EkUretimDialog(product_options, info_text=info, parent=self)
                if dlg.exec() == QDialog.DialogCode.Accepted:
                    extra_list = dlg.get_list()
                    if extra_list:
                        progress2 = QProgressDialog(
                            "Ek üretim ile yeniden çalıştırılıyor...", None, 0, 0, self
                        )
                        progress2.setWindowTitle("Zeka İşleniyor")
                        progress2.setWindowModality(Qt.WindowModality.WindowModal)
                        progress2.show()
                        scheduler2 = self._make_scheduler()
                        result = scheduler2.solve(
                            self.data_manager.state, start, end, period,
                            self.priority_overrides,
                            excel_products=excel_products,
                            week_number=week_number,
                            produced_amounts=self.data_manager.state.produced_amounts,
                            excel_only=getattr(self.data_manager, "excel_only_mode", False),
                            extra_production_list=extra_list,
                        )
                        progress2.close()

            self.schedule_completed.emit(result)
        except Exception as e:
            progress.close()
            import traceback
            traceback.print_exc()
            from PyQt6.QtWidgets import QMessageBox
            # Optimal Yaklaşım (MIP) hatalarını ayrı popup ile göster
            err_msg = str(e)
            is_mip_error = (
                "Optimal Yaklaşım" in err_msg
                or "MIP" in err_msg
                or "mip" in err_msg.lower()
            )
            if is_mip_error:
                box = QMessageBox(self)
                box.setIcon(QMessageBox.Icon.Warning)
                box.setWindowTitle("Optimal Yaklaşım")
                box.setText("Np Hard Problemdir Parça adedi 5'ten fazla ise çözdürülemez")
                box.setStandardButtons(QMessageBox.StandardButton.Ok)
                box.exec()
            else:
                QMessageBox.critical(
                    self, "Hata",
                    f"Çizelgeleme simülasyonu sırasında bir hata oluştu:\n\n{err_msg}"
                )
