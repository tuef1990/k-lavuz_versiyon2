from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel, 
                             QPushButton, QTableWidget, QTableWidgetItem, QHeaderView,
                             QScrollArea, QFrame, QTableView)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor, QBrush
from models.planning_result import PlanningResult
from services.metrics_service import MetricsService
from services.gantt_data_service import GanttDataService
from ui.widgets.metrics_card import MetricsCard
from ui.widgets.gantt_chart import GanttChartWidget

class ResultsPage(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.current_result = None
        self._init_ui()

    def _init_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setStyleSheet("background-color: #F7FAFC;")
        main_layout.addWidget(scroll)

        self.content_widget = QWidget()
        scroll.setWidget(self.content_widget)
        
        self.layout = QVBoxLayout(self.content_widget)
        self.layout.setSpacing(25)
        self.layout.setContentsMargins(40, 40, 40, 40)

        # Pre-Result State
        self.placeholder_lbl = QLabel("Henüz çizelge oluşturulmadı. Çizelgeleme sayfasından başlayın.")
        self.placeholder_lbl.setStyleSheet("font-size: 16px; color: #718096; text-align: center;")
        self.placeholder_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.layout.addWidget(self.placeholder_lbl)

        # -----------------------------
        # RESULT COMPONENTS (Hidden initially)
        # -----------------------------
        self.result_container = QWidget()
        res_layout = QVBoxLayout(self.result_container)
        res_layout.setContentsMargins(0, 0, 0, 0)
        res_layout.setSpacing(25)
        
        # 1. HEADER
        title = QLabel("Çizelge Sonuçları ve Optimizasyon Raporu")
        title.setObjectName("PageTitle")
        res_layout.addWidget(title)

        # 2. METRICS CARDS — Satır 1: Temel süreler
        self.metrics_layout = QHBoxLayout()
        self.metrics_layout.setSpacing(15)

        self.card_makespan     = MetricsCard("Toplam Süre",       "-", "⏱️", "#2D5F8A")
        self.card_last_part    = MetricsCard("Son Parça",         "-", "🏁", "#4ECDC4")
        self.card_utilization  = MetricsCard("Ort. Verimlilik",   "-", "📈", "#10B981")
        self.card_setup        = MetricsCard("Toplam Setup",      "-", "🔧", "#F59E0B")

        self.metrics_layout.addWidget(self.card_makespan)
        self.metrics_layout.addWidget(self.card_last_part)
        self.metrics_layout.addWidget(self.card_utilization)
        self.metrics_layout.addWidget(self.card_setup)
        res_layout.addLayout(self.metrics_layout)

        # 3. MACHINE UTILIZATION TABLE
        util_title = QLabel("Makine ve İstasyon Verimlilikleri")
        util_title.setObjectName("SectionTitle")
        res_layout.addWidget(util_title)

        self.util_table = QTableWidget(0, 2)
        self.util_table.setHorizontalHeaderLabels(["Makine / İstasyon", "Verimlilik (%)"])
        self.util_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.util_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.util_table.setFixedHeight(200)
        res_layout.addWidget(self.util_table)

        # 4. GANTT CHART
        gantt_title = QLabel("Üretim Gantt Şeması")
        gantt_title.setObjectName("SectionTitle")
        res_layout.addWidget(gantt_title)

        gantt_desc = QLabel(
            "<b>Göstergeler:</b>  "
            "Düz Renkli → Üretim süresi (her ürün tipi farklı renk)  •  "
            "Çizgili (Taralı) → Kurulum / Setup süresi"
        )
        gantt_desc.setWordWrap(True)
        gantt_desc.setStyleSheet(
            "color: #64748B; font-size: 12px; "
            "background-color: #F8FAFC; border: 1px solid #E2E8F0; "
            "border-radius: 6px; padding: 8px 12px;"
        )
        res_layout.addWidget(gantt_desc)

        self.gantt_scroll = QScrollArea()
        self.gantt_scroll.setWidgetResizable(True)
        self.gantt_scroll.setMinimumHeight(420)
        self.gantt_scroll.setStyleSheet(
            "background-color: white; border: 1px solid #E2E8F0; border-radius: 8px;"
        )
        self.gantt_chart = GanttChartWidget()
        self.gantt_scroll.setWidget(self.gantt_chart)
        res_layout.addWidget(self.gantt_scroll)

        # 5. JOB TÜRÜ ÖZETİ
        job_summary_title = QLabel("Çizelgelenen İş Türleri")
        job_summary_title.setObjectName("SectionTitle")
        res_layout.addWidget(job_summary_title)

        self.job_summary_frame = QFrame()
        self.job_summary_frame.setStyleSheet(
            "background:#F8FAFC; border:1px solid #E2E8F0; border-radius:8px;"
        )
        job_sum_lay = QHBoxLayout(self.job_summary_frame)
        job_sum_lay.setContentsMargins(20, 14, 20, 14)
        job_sum_lay.setSpacing(32)

        self._jc_normal  = self._make_job_chip("Normal İş",          "0", "#059669", "#ECFDF5")
        self._jc_future  = self._make_job_chip("Gelecek Hafta",      "0", "#7C3AED", "#F5F3FF")
        self._jc_excel   = self._make_job_chip("Excel (Devam Eden)", "0", "#0891B2", "#ECFEFF")

        for w in (self._jc_normal, self._jc_future, self._jc_excel):
            job_sum_lay.addWidget(w)
        job_sum_lay.addStretch()
        res_layout.addWidget(self.job_summary_frame)

        # 6. EXPORT BUTTONS
        btn_layout = QHBoxLayout()
        self.btn_excel = QPushButton("📥  Excel Raporu İndir")
        self.btn_excel.setObjectName("ActionButton")
        self.btn_excel.setStyleSheet(
            "QPushButton { background-color: #059669; color: white; font-weight: 600; "
            "padding: 10px 20px; border-radius: 8px; }"
            "QPushButton:hover { background-color: #047857; }"
        )
        self.btn_excel.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_excel.clicked.connect(self.export_excel)

        self.btn_gantt_img = QPushButton("🖼  Gantt Görüntüsü Kaydet")
        self.btn_gantt_img.setStyleSheet(
            "QPushButton { background-color: #2563EB; color: white; font-weight: 600; "
            "padding: 10px 20px; border-radius: 8px; }"
            "QPushButton:hover { background-color: #1D4ED8; }"
        )
        self.btn_gantt_img.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_gantt_img.clicked.connect(self.export_gantt_image)
        
        btn_layout.addWidget(self.btn_excel)
        btn_layout.addWidget(self.btn_gantt_img)
        btn_layout.addStretch()
        
        res_layout.addLayout(btn_layout)
        
        self.result_container.hide()
        self.layout.addWidget(self.result_container)
        self.layout.addStretch()

    # ── Yardımcı: iş türü chip widget'ı ──────────────────────────────────
    def _make_job_chip(self, label: str, value: str,
                       color: str, bg: str) -> QWidget:
        """Renkli iş türü sayaç chip'i."""
        w = QFrame()
        w.setStyleSheet(f"""
            QFrame {{
                background: {bg};
                border: 1.5px solid {color}55;
                border-radius: 8px;
            }}
        """)
        lay = QVBoxLayout(w)
        lay.setContentsMargins(14, 10, 14, 10)
        lay.setSpacing(2)

        val_lbl = QLabel(value)
        val_lbl.setStyleSheet(
            f"font-size: 22px; font-weight: 800; color: {color}; background: transparent;"
        )
        lbl = QLabel(label)
        lbl.setStyleSheet(
            "font-size: 11px; font-weight: 600; color: #475569; background: transparent;"
        )
        lay.addWidget(val_lbl)
        lay.addWidget(lbl)

        # val_lbl referansını widget üzerine sakla
        w._val_lbl = val_lbl
        return w

    def _update_job_chip(self, chip: QWidget, value: str):
        chip._val_lbl.setText(value)

    # ── Sonuç yükleme ────────────────────────────────────────────────────
    def set_result(self, result: PlanningResult):
        self.current_result = result
        self.placeholder_lbl.hide()
        self.result_container.show()
        
        # Metrikleri Hesapla
        metrics = MetricsService.calculate(result)
        
        self.card_makespan.update_value(metrics["makespan_display"])
        self.card_last_part.update_value(metrics["last_part_display"])
        self.card_utilization.update_value(f"%{metrics['avg_utilization']:.1f}")
        self.card_setup.update_value(f"{metrics['total_setup_hours']:.1f} saat")

        # Verimlilik Tablosunu Doldur
        self.util_table.setRowCount(0)
        for machine, util in metrics["machine_utilization"].items():
            row = self.util_table.rowCount()
            self.util_table.insertRow(row)
            self.util_table.setItem(row, 0, QTableWidgetItem(machine))
            
            util_item = QTableWidgetItem(f"%{util:.1f}")
            # Color coding
            if util > 80:
                util_item.setBackground(QColor("#C6F6D5")) # Light green
                util_item.setForeground(QColor("#22543D"))
            elif util > 50:
                util_item.setBackground(QColor("#FEEBC8")) # Light orange
                util_item.setForeground(QColor("#7B341E"))
            else:
                util_item.setBackground(QColor("#FED7D7")) # Light red
                util_item.setForeground(QColor("#742A2A"))
                
            self.util_table.setItem(row, 1, util_item)

        # Gantt Chart'ı Doldur
        gantt_data = GanttDataService.prepare(result.schedule)
        self.gantt_chart.set_data(gantt_data)

        # İş Türü Özeti — unique job_id'ler üzerinden iş türlerini say
        unique_jobs = list({e.job_id for e in result.schedule})
        n_gelecek  = sum(1 for j in unique_jobs if "||Gelecek Hafta" in j)
        n_bu_hafta = sum(1 for j in unique_jobs if "||Bu Hafta" in j)
        n_normal   = len(unique_jobs) - n_gelecek - n_bu_hafta

        # "Normal İş" chip'i: tag içermeyen (aylık planlama) + Bu Hafta (haftalık planlama)
        self._update_job_chip(self._jc_normal,  str(n_normal + n_bu_hafta))
        self._update_job_chip(self._jc_future,  str(n_gelecek))
        # Excel devam eden işleri ayrı gösterilemez (UUID aynı format); bilgilendirici not
        self._update_job_chip(self._jc_excel, "—")

    def export_gantt_image(self):
        from PyQt6.QtWidgets import QFileDialog, QMessageBox
        if not self.current_result: return
        
        file_path, _ = QFileDialog.getSaveFileName(self, "Gantt Şemasını Kaydet", "uretim_gantt.png", "PNG Images (*.png)")
        if file_path:
            success = self.gantt_chart.save_as_image(file_path)
            if success:
                QMessageBox.information(self, "Başarılı", "Gantt şeması başarıyla kaydedildi.")
            else:
                QMessageBox.warning(self, "Hata", "Görüntü kaydedilirken bir hata oluştu.")

    def export_excel(self):
        from PyQt6.QtWidgets import QFileDialog, QMessageBox
        from services.excel_export import ExcelExportService
        
        if not self.current_result: return
        
        file_path, _ = QFileDialog.getSaveFileName(self, "Excel Raporunu Kaydet", "uretim_raporu.xlsx", "Excel Files (*.xlsx)")
        if file_path:
            try:
                success = ExcelExportService.export(self.current_result, file_path)
                if success:
                    QMessageBox.information(self, "Başarılı", "Excel raporu başarıyla kaydedildi.")
            except Exception as e:
                QMessageBox.warning(self, "Hata", f"Rapor kaydedilirken bir hata oluştu:\n{str(e)}")
