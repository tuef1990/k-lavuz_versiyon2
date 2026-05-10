import sys
from PyQt6.QtWidgets import (QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
                             QPushButton, QLabel, QStackedWidget, QTableView,
                             QHeaderView, QMessageBox, QFrame, QSpacerItem, QSizePolicy)
from PyQt6.QtCore import Qt, QObject, QEvent, pyqtSlot
from .style import STYLE_SHEET
from core.models import Product, VARDIA_INFO, STAGES
from core.table_models import ProductTableModel, DependentTableModel, SetupMatrixTableModel, ShiftTableModel
from ui.delegates import MultiValueDelegate, TimeRangeDelegate
from ui.pages.dashboard_page import DashboardPage
from ui.pages.scheduling_page import SchedulingPage
from ui.pages.results_page import ResultsPage
from ui.pages.simulation_page import SimulationPage
from ui.pages.step_tester_page import StepTesterPage
from ui.widgets.help_overlay import HelpOverlay


# ──────────────────────────────────────────────────────────────────────────────
class DataTablePage(QWidget):
    """Tablo tabanlı veri sayfası şablonu (başlık + tablo + işlem çubuğu)."""

    def __init__(self, title, description, model, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(32, 32, 32, 32)
        layout.setSpacing(0)
        layout.setObjectName("ContentArea")

        # ── Sayfa başlığı
        header = QWidget()
        header.setObjectName("HeaderContainer")
        header.setStyleSheet("QWidget#HeaderContainer { background: transparent; }")
        header_layout = QVBoxLayout(header)
        header_layout.setContentsMargins(0, 0, 0, 18)
        header_layout.setSpacing(4)

        title_row = QHBoxLayout()
        title_row.setContentsMargins(0, 0, 0, 0)
        title_row.setSpacing(8)

        title_label = QLabel(title)
        title_label.setObjectName("PageTitle")
        title_row.addWidget(title_label)
        title_row.addStretch()

        self.help_btn = QPushButton("!")
        self.help_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.help_btn.setToolTip("Bu sayfayı nasıl kullanırım?")
        self.help_btn.setFixedSize(32, 32)
        self.help_btn.setStyleSheet("""
            QPushButton {
                background-color: #FEF3C7; color: #B45309;
                border: 2px solid #F59E0B; border-radius: 6px;
                font-size: 18px; font-weight: 900;
                font-family: 'Helvetica Neue', Arial, sans-serif;
            }
            QPushButton:hover { background-color: #FDE68A; }
        """)
        self.help_btn.hide()
        title_row.addWidget(self.help_btn)

        desc_label = QLabel(description)
        desc_label.setObjectName("PageSubtitle")
        desc_label.setWordWrap(True)

        header_layout.addLayout(title_row)
        header_layout.addWidget(desc_label)
        layout.addWidget(header)

        # ── Tablo
        self.table_view = QTableView()
        self.table_view.setAlternatingRowColors(True)
        self.table_view.setModel(model)
        self.table_view.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table_view.verticalHeader().setVisible(True)
        self.table_view.verticalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Fixed)
        self.table_view.verticalHeader().setDefaultSectionSize(42)
        self.table_view.setShowGrid(True)
        layout.addWidget(self.table_view)

        # ── İşlem çubuğu
        self.action_bar = QWidget()
        self.action_bar.setObjectName("ActionBar")
        self.action_bar.setStyleSheet(
            "QWidget#ActionBar { background: transparent; border-top: 1px solid #E2E8F0; }"
        )
        self.action_layout = QHBoxLayout(self.action_bar)
        self.action_layout.setContentsMargins(0, 14, 0, 0)
        self.action_layout.setSpacing(10)
        layout.addWidget(self.action_bar)

    def add_action_button(self, text, object_name, callback):
        btn = QPushButton(text)
        btn.setObjectName(object_name)
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.clicked.connect(callback)
        self.action_layout.addWidget(btn)
        return btn

    def add_table(self, title, description, model):
        # Ayırıcı çizgi
        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        line.setStyleSheet("background-color: #E2E8F0; margin: 20px 0; max-height: 1px;")
        self.layout().addWidget(line)

        sub_lbl = QLabel(title)
        sub_lbl.setObjectName("HeaderTitle")
        sub_lbl.setStyleSheet("font-size: 18px; background: transparent;")
        desc_lbl = QLabel(description)
        desc_lbl.setWordWrap(True)
        desc_lbl.setStyleSheet("color: #64748B; font-size: 13px; background: transparent;")
        self.layout().addWidget(sub_lbl)
        self.layout().addWidget(desc_lbl)

        table_view = QTableView()
        table_view.setAlternatingRowColors(True)
        table_view.setModel(model)
        table_view.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        table_view.verticalHeader().setVisible(True)
        table_view.verticalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Fixed)
        table_view.verticalHeader().setDefaultSectionSize(42)
        self.layout().addWidget(table_view)
        return table_view


# ──────────────────────────────────────────────────────────────────────────────
class MainWindow(QMainWindow):
    def __init__(self, data_manager):
        super().__init__()
        self.data_manager = data_manager
        self.setWindowTitle("Pipelining — Üretim Çizelgeleme")
        self.setMinimumSize(1280, 800)
        self.setStyleSheet(STYLE_SHEET)

        # Ana kap
        main_widget = QWidget()
        main_layout = QHBoxLayout(main_widget)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # ── Sidebar
        self.sidebar = QFrame()
        self.sidebar.setObjectName("Sidebar")
        sidebar_layout = QVBoxLayout(self.sidebar)
        sidebar_layout.setContentsMargins(0, 0, 0, 0)
        sidebar_layout.setSpacing(2)

        # Marka alanı
        brand = QFrame()
        brand.setObjectName("SidebarBrand")
        brand_row = QHBoxLayout(brand)
        brand_row.setContentsMargins(16, 18, 16, 18)
        brand_row.setSpacing(10)

        logo_lbl = QLabel("⚙")
        logo_lbl.setStyleSheet("font-size: 24px; color: #60A5FA; background: transparent;")
        brand_row.addWidget(logo_lbl)

        brand_text = QVBoxLayout()
        brand_text.setSpacing(1)
        brand_title = QLabel("Pipelining")
        brand_title.setObjectName("SidebarBrandTitle")
        brand_sub = QLabel("Üretim Optimizasyonu")
        brand_sub.setObjectName("SidebarBrandSub")
        brand_text.addWidget(brand_title)
        brand_text.addWidget(brand_sub)
        brand_row.addLayout(brand_text)
        brand_row.addStretch()
        sidebar_layout.addWidget(brand)

        self.nav_buttons = []

        # Dashboard butonu (index 0)
        sidebar_layout.addSpacing(8)
        self._add_nav_btn(sidebar_layout, "◈  Genel Bakış", 0)

        # Bölüm 1: Veri Tanımlamaları
        self._add_section_label(sidebar_layout, "VERİ TANIMLAMALARI")
        nav_data = [
            ("📦  Ürün Bilgileri",   1),
            ("⚙️  Üretim Süreleri",  2),
            ("⏱  Kurulum Matrisi",   3),
            ("📊  Kapasite Tablosu", 4),
            ("🕐  Vardiya Yönetimi", 5),
        ]
        for text, idx in nav_data:
            self._add_nav_btn(sidebar_layout, text, idx)

        # Bölüm 2: Çizelgeleme
        self._add_section_label(sidebar_layout, "ÇİZELGELEME")
        nav_plan = [
            ("📅  Planlama",   6),
            ("📈  Sonuçlar",   7),
            ("🎬  Simülasyon", 8),
            ("🧪  Adım Testi", 9),
        ]
        for text, idx in nav_plan:
            self._add_nav_btn(sidebar_layout, text, idx)

        sidebar_layout.addStretch()

        # Alt bilgi
        footer = QLabel("v2.0  •  PyQt6")
        footer.setObjectName("SidebarFooter")
        sidebar_layout.addWidget(footer)

        main_layout.addWidget(self.sidebar)

        # ── İçerik alanı
        self.stack = QStackedWidget()
        self.stack.setObjectName("ContentArea")
        main_layout.addWidget(self.stack)

        self._init_pages()
        self.switch_page(0)

        self.setCentralWidget(main_widget)

        # Yardım overlay'i — tüm içerik üstüne çizilen tek instance
        self.help_overlay = HelpOverlay(main_widget)
        self._wire_help_buttons()

    # ── Sidebar yardımcıları ───────────────────────────────────────────────
    def _add_nav_btn(self, layout, text: str, page_idx: int):
        btn = QPushButton(text)
        btn.setProperty("active", "false")
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.clicked.connect(lambda checked=False, i=page_idx: self.switch_page(i))
        layout.addWidget(btn)
        self.nav_buttons.append(btn)

    def _add_section_label(self, layout, text: str):
        lbl = QLabel(text)
        lbl.setObjectName("SidebarSection")
        layout.addWidget(lbl)

    # ── Sayfa başlatma ────────────────────────────────────────────────────
    def _init_pages(self):
        # ── 0: Dashboard (YENİ)
        self.dashboard = DashboardPage(self.data_manager)
        self.dashboard.navigate_to.connect(self.switch_page)
        self.stack.addWidget(self.dashboard)             # index 0

        # ── 1: Ürün Bilgileri
        self.product_model = ProductTableModel(self.data_manager)
        self.p1 = DataTablePage(
            "Ürün Bilgileri",
            "Sistemde tanımlı ürünlerin listesi. Bu tablodaki değişiklikler tüm sayfaları etkiler.",
            self.product_model
        )
        self._p1_btn_new = self.p1.add_action_button("+ Yeni Ürün Ekle",   "ActionButton", self.add_new_product)
        self._p1_btn_delete = self.p1.add_action_button("Seçiliyi Sil",       "DeleteButton", self.delete_selected_product)
        self.stack.addWidget(self.p1)                    # index 1

        # ── 2: Üretim Süreleri
        self.times_model = DependentTableModel(self.data_manager, "production_time_data")
        self.p3 = DataTablePage(
            "Üretim Süreleri",
            "Her ürün için her istasyonda geçen birim üretim süresi (saat).",
            self.times_model
        )
        self.stack.addWidget(self.p3)                    # index 2

        # ── 3: Kurulum Matrisi
        self.matrix_model = SetupMatrixTableModel(self.data_manager)
        self.p4 = DataTablePage(
            "Kurulum Matrisi",
            "Ürünler arası geçiş yaparken gereken hazırlık (set-up) süreleri (saat).",
            self.matrix_model
        )
        self.stack.addWidget(self.p4)                    # index 3

        # ── 4: Kapasite Tablosu
        self.capacity_model = DependentTableModel(self.data_manager, "capacity_data")
        capacity_desc = (
            "İstasyon bazlı günlük/vardiya üretim kapasiteleri.  |  "
            + "  |  ".join(f"{s}: {v}" for s, v in VARDIA_INFO.items())
        )
        self.p2 = DataTablePage("Kapasite Tablosu", capacity_desc, self.capacity_model)
        self.capacity_delegate = MultiValueDelegate(self.p2.table_view)
        for i in range(1, len(STAGES) + 1):
            self.p2.table_view.setItemDelegateForColumn(i, self.capacity_delegate)
        self.stack.addWidget(self.p2)                    # index 4

        # ── 5: Vardiya Yönetimi
        self.shift_model = ShiftTableModel(self.data_manager)
        self.p_shift = DataTablePage(
            "Vardiya Yönetimi",
            "Vardiya sayılarını (1–3) ve saatlerini (SS:DD – SS:DD) tanımlayın.",
            self.shift_model
        )
        self.time_delegate = TimeRangeDelegate(self.p_shift.table_view)
        for i in range(2, 5):
            self.p_shift.table_view.setItemDelegateForColumn(i, self.time_delegate)
        self.stack.addWidget(self.p_shift)               # index 5

        # ── 6: Çizelgeleme
        self.p5 = SchedulingPage(self.data_manager)
        self.p5.schedule_completed.connect(self.handle_schedule_results)
        self.p5.excel_load_requested.connect(self.load_excel_data)
        self.p5.excel_clear_requested.connect(self.clear_excel_data)
        self.stack.addWidget(self.p5)                    # index 6

        # ── 7: Sonuçlar
        self.p6 = ResultsPage()
        self.stack.addWidget(self.p6)                    # index 7

        # ── 8: Simülasyon
        self.p_sim = SimulationPage(self.data_manager)
        self.stack.addWidget(self.p_sim)                 # index 8

        # ── 9: Adım Test Simülatörü
        self.p_step_tester = StepTesterPage(self.data_manager)
        self.p_step_tester.new_product_wizard_requested.connect(self._start_new_product_wizard)
        self.stack.addWidget(self.p_step_tester)         # index 9

        # Wizard durumu
        self._wizard_btn = None
        self._wizard_idx = 0
        self._wizard_pages = []
        self._wizard_products = []

        # Ürün ismi/tipi değişirse wizard listesini güncelle
        self.data_manager.product_updated.connect(self._on_product_updated_wizard_sync)

    # ── Yardım (help) overlay bağlantıları ──────────────────────────────────
    HELP_BTN_STYLE = """
        QPushButton {
            background-color: #FEF3C7; color: #B45309;
            border: 2px solid #F59E0B; border-radius: 6px;
            font-size: 18px; font-weight: 900;
            font-family: 'Helvetica Neue', Arial, sans-serif;
        }
        QPushButton:hover { background-color: #FDE68A; }
    """

    def _attach_floating_help(self, page_widget, callback):
        """Custom sayfa widget'ının üzerine sağ-üst köşeye floating yardım butonu ekler.
        Sayfa resize edildiğinde konumu otomatik güncellenir."""
        btn = QPushButton("!", page_widget)
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.setToolTip("Bu sayfayı nasıl kullanırım?")
        btn.setFixedSize(32, 32)
        btn.setStyleSheet(self.HELP_BTN_STYLE)
        btn.clicked.connect(callback)

        margin_top = 24
        margin_right = 32

        def reposition():
            x = page_widget.width() - btn.width() - margin_right
            btn.move(max(0, x), margin_top)
            btn.raise_()

        # Resize event filter
        class _Resizer(QObject):
            def eventFilter(self, obj, event):
                if event.type() == QEvent.Type.Resize:
                    reposition()
                return False

        resizer = _Resizer(page_widget)
        page_widget.installEventFilter(resizer)
        # Referansı tut ki garbage collect olmasın
        if not hasattr(self, "_help_resizers"):
            self._help_resizers = []
        self._help_resizers.append(resizer)

        reposition()
        btn.show()
        return btn

    def _wire_help_buttons(self):
        """Her sayfa için yardım butonu adımlarını bağlar."""
        # DataTablePage tabanlı sayfalar (help_btn zaten title yanında)
        self.p1.help_btn.show()
        self.p1.help_btn.clicked.connect(self._show_help_products)
        self.p3.help_btn.show()
        self.p3.help_btn.clicked.connect(self._show_help_times)
        self.p4.help_btn.show()
        self.p4.help_btn.clicked.connect(self._show_help_matrix)
        self.p2.help_btn.show()
        self.p2.help_btn.clicked.connect(self._show_help_capacity)
        self.p_shift.help_btn.show()
        self.p_shift.help_btn.clicked.connect(self._show_help_shifts)

        # Custom sayfalar — floating button
        self._attach_floating_help(self.dashboard, self._show_help_dashboard)
        self._attach_floating_help(self.p5, self._show_help_scheduling)
        self._attach_floating_help(self.p6, self._show_help_results)
        self._attach_floating_help(self.p_sim, self._show_help_simulation)
        self._attach_floating_help(self.p_step_tester, self._show_help_step_tester)

    DEMO_PRODUCT_DISPLAY = "DEMO / Test Ürünü"

    def _show_help_products(self):
        # Demo akışı için durum
        self._demo_added = False

        def add_demo():
            existing = {p.display_name for p in self.data_manager.state.products}
            if self.DEMO_PRODUCT_DISPLAY not in existing:
                self.data_manager.add_product(Product("DEMO", "Test Ürünü", 1))
                self._demo_added = True

        def cleanup_demo():
            if not self._demo_added:
                return
            for i, p in enumerate(self.data_manager.state.products):
                if p.display_name == self.DEMO_PRODUCT_DISPLAY:
                    self.data_manager.remove_product(i)
                    break
            self._demo_added = False

        def goto(idx):
            return lambda: self.switch_page(idx)

        steps = [
            (
                self.p1.table_view,
                "Ürün Listesi",
                "Sistemde tanımlı ürünler burada listelenir. Sütunlar: 'Ürün Tipi', "
                "'Aylık Hedef' ve 'Üretilen'. Hücreye tıklayarak değerleri düzenleyebilirsin. "
                "'Üretilen' bu döneme kadar kaç adet üretildiğini tutar; Çizelgeleme "
                "sayfasındaki 'Kalan Aylık Hedef' bu değerden hesaplanır. Aylık hedef ve "
                "üretilen değişiklikleri kapasite, kurulum matrisi ve çizelgeleme dahil "
                "tüm sayfaları etkiler.",
            ),
            (
                self._p1_btn_new,
                "Yeni Ürün Ekle",
                "Manuel olarak yeni bir ürün eklemek için bu butona bas. Ekledikten sonra "
                "kısa bir sihirbaz açılır: önce ürün bilgileri, sonra üretim süreleri, "
                "kurulum matrisi ve kapasite onayı.",
            ),
            (
                self._p1_btn_delete,
                "Seçiliyi Sil",
                "Bu butona bastığında satır numaralarının yerine ❌ işareti çıkar; silmek "
                "istediğin ürünün satır başlığına tıkla. İptal için aynı butona tekrar bas.",
            ),
        ]
        # ── Demo akışı: ürün ekle, tablolardaki yansımayı göster, sonunda temizle
        steps.extend([
            (
                None,
                "Demo: Tablolar Arası Bağlantı",
                "Şimdi geçici olarak 'DEMO / Test Ürünü' adında bir ürün ekleyip diğer "
                "tablolarda nasıl göründüğünü göstereceğim. Demo bittiğinde otomatik temizlenir.",
            ),
            (
                self.p1.table_view,
                "DEMO Ürünü Eklendi",
                "DEMO tipinde bir test ürünü ekledim. Yukarıdaki listede en alt satırda "
                "görebilirsin. Şimdi diğer tablolara nasıl yansıdığını birlikte gezelim.",
                add_demo,
            ),
            (
                self.p3.table_view,
                "Üretim Süreleri Tablosu",
                "DEMO ürünü Üretim Süreleri tablosuna otomatik eklendi. Generic default "
                "süreler atandı (Assembly 3.5h, FTP 1.0h, B/N 12h, DKK 18h, RVB 3h, "
                "ATP+STP 21h). DEMO tipi default listede olmadığı için genel default'lara düştü.",
                goto(2),
            ),
            (
                self.p4.table_view,
                "Kurulum Matrisi",
                "Setup matrisine DEMO için yeni bir satır ve sütun eklendi. DEMO tipi "
                "default listede olmadığı için tüm hücreler 0 — kullanıcının doldurması "
                "beklenir. Diğer ürünlerin DEMO sütununa giden değerleri de boş.",
                goto(3),
            ),
            (
                self.p2.table_view,
                "Kapasite Tablosu",
                "Kapasite tablosuna da DEMO satırı eklendi. Generic kapasite default'larıyla "
                "(Assembly 10, FTP 1, B/N 8, DKK 8, RVB 8, ATP+STP 8) doldurulmuş halde "
                "geldi — vardiya bazında [10,10,10] gibi listeler oluştu.",
                goto(4),
            ),
            (
                self.p1.table_view,
                "Demo Bitti",
                "Gördüğün gibi Ürün Bilgileri'nde yapılan değişiklikler tüm bağlı tablolara "
                "otomatik yansıyor. 'Bitir ✓' butonuna bastığında DEMO ürünü otomatik "
                "kaldırılacak.",
                goto(1),
            ),
        ])

        self.help_overlay.start(steps, on_stop=cleanup_demo)

    def _show_help_times(self):
        steps = [
            (
                self.p3.table_view,
                "Üretim Süreleri Tablosu",
                "Her ürün (satır) ve üretim aşaması (sütun) için birim üretim süresini saat "
                "cinsinden buradan tanımlarsın. Hücreye tıklayıp değeri yazabilirsin. "
                "Bu süreler simülasyon motoruna girdi olarak verilir.",
            ),
            (
                None,
                "Aşamalar (Stages)",
                "Sütunlar üretim adımlarıdır: Assembly → FTP → B/N → DKK → RVB → ATP+STP. "
                "Her aşamadaki süre, o aşamada bir parçanın işlenme süresidir.",
            ),
        ]
        self.help_overlay.start(steps)

    def _show_help_matrix(self):
        steps = [
            (
                self.p4.table_view,
                "Kurulum (Setup) Matrisi",
                "Bir üründen diğerine geçerken gereken hazırlık süresi (saat). Satır 'gelen', "
                "sütun 'sonraki' ürünü gösterir. Köşegen (aynı üründen aynı ürüne) gridir ve "
                "0 olarak sabittir. Hücreye tıklayıp değeri girebilirsin.",
            ),
            (
                None,
                "Default Değerler",
                "Tanımlı tipler (K11, K12, K20, K31, K40) için default setup süreleri kodda "
                "tutulur. Yeni bir ürün eklendiğinde tipi mevcut bir tipe denk gelirse default "
                "değerler otomatik yansır; aynı tipten başka ürün varsa onun değerleri kopyalanır.",
            ),
        ]
        self.help_overlay.start(steps)

    def _show_help_capacity(self):
        steps = [
            (
                self.p2.table_view,
                "Kapasite Tablosu",
                "Her ürün × aşama hücresinde vardiya bazlı kapasite listesi tutulur "
                "(örn. Assembly için [V1, V2, V3]). Hücreye tıklayıp her vardiyanın "
                "kapasite değerini ayrı ayrı düzenleyebilirsin.",
            ),
            (
                None,
                "Vardiya Sayısı",
                "Vardiya sayısı 'Vardiya Yönetimi' sayfasından değiştirilir. Vardiya "
                "sayısı arttıkça/azaldıkça kapasite listeleri otomatik genişler/kısalır.",
            ),
        ]
        self.help_overlay.start(steps)

    def _show_help_shifts(self):
        steps = [
            (
                self.p_shift.table_view,
                "Vardiya Yönetimi",
                "Her aşama için vardiya sayısını (1–3) ve her vardiyanın saat aralığını "
                "(SS:DD – SS:DD) buradan tanımlarsın. Burada yapılan değişiklikler kapasite "
                "tablosundaki vardiya sütun sayısını otomatik etkiler.",
            ),
            (
                None,
                "Hafta Sonu Vardiyaları",
                "Cumartesi/Pazar günü hangi vardiyaların aktif olduğunu Çizelgeleme sayfasından "
                "ayarlayabilirsin (default: Cumartesi 1. vardiya açık, Pazar tam kapalı).",
            ),
        ]
        self.help_overlay.start(steps)

    def _show_help_dashboard(self):
        steps = [
            (
                None,
                "Genel Bakış",
                "Bu sayfa uygulamanın özet panelidir. Hızlı bir bakışta üretim akışını, "
                "tanımlı ürünleri ve hızlı işlem butonlarını görebilirsin.",
            ),
            (
                None,
                "Tipik Akış",
                "1) Ürün Bilgileri → ürünleri ve aylık hedefleri tanımla.  "
                "2) Üretim Süreleri / Kurulum Matrisi / Kapasite → işleme parametrelerini gir.  "
                "3) Vardiya Yönetimi → vardiya saatlerini ayarla.  "
                "4) Çizelgeleme → simülasyonu başlat.  "
                "5) Sonuçlar / Simülasyon → çıktıları incele.",
            ),
        ]
        self.help_overlay.start(steps)

    def _show_help_scheduling(self):
        p = self.p5
        steps = [
            (
                getattr(p, "period_combo", None),
                "Planlama Periyodu",
                "Aylık (1 ay), Haftalık (7 gün) veya Serbest aralık seçebilirsin. Seçim, "
                "scheduler'ın hedef hesabında kullanılır; Aylık seçilirse hafta numarası "
                "0'a kilitlenir.",
            ),
            (
                getattr(p, "start_date", None),
                "Başlangıç ve Bitiş Tarihi",
                "Simülasyonun başladığı tarih ve saat. Periyot 'Haftalık' veya 'Aylık' "
                "seçildiyse bitiş tarihi otomatik hesaplanır ve düzenlenemez (gri görünür). "
                "'Serbest Seçim' modunda bitiş tarihini de elle ayarlayabilirsin.",
            ),
            (
                getattr(p, "algo_combo", None),
                "Planlama Algoritması",
                "Hangi çizelgeleme algoritmasının kullanılacağını seçersin: 'Sevkiyat "
                "Destekli Yaklaşım' (default, öncelik tabanlı), 'Makina Verimli Dengeli Yaklaşım' veya "
                "'Optimal Yaklaşım'. Default seçim çoğu durum için uygundur.",
            ),
            (
                getattr(p, "week_row_widget", None),
                "Hafta Numarası",
                "Mevcut ayın hangi haftasındayız (0=1.hafta, 3=4.hafta). Öncelik formülünde "
                "(4 − hafta_no) paydası olarak kullanılır — hafta ilerledikçe geride kalan "
                "ürünlerin önceliği artar. Aylık modda 0'a kilitlidir; scheduler 7 günde "
                "bir kendisi artırır.",
            ),
            (
                getattr(p, "weekend_section", None),
                "Hafta Sonu Vardiya Ayarları",
                "Cumartesi ve Pazar günleri hangi vardiyaların aktif olacağını işaretle. "
                "Default: Cumartesi 1. vardiya açık, Pazar tamamen kapalı. İşaretlemediğin "
                "vardiyalarda o gün üretim olmaz; simülasyon o aralığı boş geçer.",
            ),
            (
                getattr(p, "_btn_excel_load", None),
                "Excel Yükle",
                "Mevcut sipariş/iş emri Excel'ini buradan yükleyebilirsin. Yükleme "
                "yapıldığında Üretim Hedefleri tablosundaki 'Excel Verisi' sütunu tipe "
                "göre toplam adetle dolar; Excel yüklenmemiş tipler için 'girilmedi' "
                "yazar. Excel yüklemesi 'Kalan Aylık Hedef' sütununu değiştirmez. "
                "'Kaldır' butonu yüklenen veriyi temizler.",
            ),
            (
                getattr(p, "target_table", None),
                "Üretim Hedefleri",
                "Her ürün tipi için iki bilgi gösterilir: 'Kalan Aylık Hedef' ve 'Excel Verisi'. "
                "Kalan Aylık Hedef, Ürün Bilgileri sayfasındaki Aylık Hedef ile Üretilen "
                "değerlerinden otomatik hesaplanır (Aylık Hedef − Üretilen) ve Excel "
                "yüklemesinden etkilenmez. 'Excel Verisi' sütunu o tipe ait Excel'den "
                "yüklenen toplam adedi gösterir; Excel girilmemişse 'girilmedi' yazar.",
            ),
            (
                getattr(p, "cb_ek_uretim", None),
                "Ek Üretim",
                "İşaretlersen Çalıştır'a bastığında hangi ürünleri ek üretim olarak "
                "ekleyeceğini soran bir pencere açılır. Ek üretim, normal hedeflerin "
                "üzerine yapılır ve −1.000 önceliğiyle kalan kapasiteyi doldurur.",
            ),
            (
                getattr(p, "btn_generate", None),
                "Simülasyonu Başlat",
                "Tüm parametreler hazırsa bu butona basarak simülasyonu çalıştır. "
                "Sonuçlar otomatik olarak Sonuçlar ve Simülasyon sayfalarına yansır.",
            ),
        ]
        self.help_overlay.start(steps)

    def _show_help_results(self):
        steps = [
            (
                getattr(self.p6, "card_makespan", None),
                "Metrik Kartları",
                "Toplam üretim süresi, son parça çıkış zamanı, ortalama makine verimliliği "
                "ve toplam setup süresi burada özetlenir.",
            ),
            (
                getattr(self.p6, "util_table", None),
                "Makine Verimlilikleri",
                "Her makine/istasyonun simülasyon boyunca yüzde kaç verimle çalıştığı "
                "renk kodlu olarak listelenir: %80+ yeşil, %50+ turuncu, altı kırmızı.",
            ),
            (
                getattr(self.p6, "gantt_scroll", None),
                "Gantt Şeması",
                "Her makinenin zaman çizelgesi. Düz renkli bloklar üretim, çizgili (taralı) "
                "bloklar setup süresidir. Her ürün tipi farklı renkle gösterilir.",
            ),
            (
                getattr(self.p6, "btn_excel", None),
                "Excel Raporu / Gantt Görüntüsü",
                "Sonuçları Excel olarak indirebilir veya Gantt şemasının görselini PNG olarak "
                "kaydedebilirsin (sağdaki buton).",
            ),
        ]
        self.help_overlay.start(steps)

    def _show_help_simulation(self):
        steps = [
            (
                getattr(self.p_sim, "time_display", None),
                "Zaman Göstergesi",
                "Simülasyondaki şu anki sanal saat. Aşağıdaki kaydırıcıyı sürükleyerek "
                "geriye/ileriye gidebilirsin.",
            ),
            (
                getattr(self.p_sim, "timeline_slider", None),
                "Zaman Çizgisi",
                "Simülasyonun başından sonuna kadar herhangi bir ana atlamak için "
                "kaydırıcıyı sürükle. Tüm makine durumları ve kuyruk o ana göre güncellenir.",
            ),
            (
                getattr(self.p_sim, "machine_cards_title", None),
                "Makine Durumları",
                "Sol panelde her makinenin o andaki durumu: BOŞ / ÜRETİYOR / SETUP. Hangi "
                "ürünü işliyor, ne zaman bitecek bilgileri kart üzerinde gösterilir.",
            ),
            (
                getattr(self.p_sim, "queue_frame", None),
                "Kuyruk",
                "O an işlenmeyi bekleyen iş listesi. Her satır priority skoruyla birlikte "
                "gösterilir; algoritmanın sıralama kararını burada görebilirsin.",
            ),
            (
                getattr(self.p_sim, "log_scroll", None),
                "Karar Günlüğü",
                "Seçili istasyonda algoritmanın o ana kadar verdiği kararlar burada "
                "listelenir. Stage seçimini değiştirdiğinde panel o istasyonun kararlarını "
                "filtreler; zaman çizgisini hareket ettirdiğinde yalnızca o ana kadar "
                "olan kararlar görünür.",
            ),
        ]
        self.help_overlay.start(steps)

    def _show_help_step_tester(self):
        p = self.p_step_tester
        steps = [
            (
                None,
                "Adım Test Simülatörü",
                "Tek bir üretim adımını izole olarak test etmek için tasarlanmıştır. "
                "Bütün scheduler'ı çalıştırmadan, sadece bir adımdaki planlama kararını "
                "denemek istediğinde kullan. Sırayla bütün arayüzü gezelim.",
            ),
            (
                getattr(p, "_step_row_card", None),
                "1. Üretim Adımı Seçimi",
                "Test edeceğin adımı buradan seç: DKK/ATP+STP, RVB, Assembly, FTP, B/N. "
                "Adım değiştiğinde alt bölümler (makine durumu, gelmekte olan ürünler, iş "
                "kuyruğu) otomatik olarak o adıma göre yeniden yapılandırılır.",
            ),
            (
                getattr(p, "_algo_widget", None),
                "Makine Verimli Dengeli Yaklaşım(DKK/ATP+STP ve RVB)",
                "DKK/ATP+STP ve RVB adımlarında görünür. İki farklı planlayıcı arasında "
                "geçiş yapabilirsin: 'Sevkiyat Destekli Yaklaşım' "
                "veya 'Makina Verimli Dengeli Yaklaşım'.  " ,
            ),
            (
                getattr(p, "_machines_card", None),
                "3. Makine Durumu",
                "Test edilen adımdaki makinelerin başlangıç durumunu buradan ayarlarsın. "
                "Üç seçenek var: 'İlk Kullanım' (makine bugün ilk kez çalışıyor — günlük "
                "setup eklenir), 'Kullanıldı, Boş' (son işlediği ürünü gir; bir sonraki "
                "ürüne geçişte setup hesaplanır), 'Şu An Meşgul' (kalan süreyi gir; o "
                "süre dolana kadar makineye iş atanmaz). Ürün için tip + ad alanları "
                "ayrıdır; aynı makinede birden fazla isim varsa virgülle yazabilirsin "
                "(örn 'Ürün A, Ürün B'). DKK/ATP+STP modunda her makine için işlem "
                "türü combo'su (DKK / ATP+STP) da görünür. Bu kart yalnızca DKK/ATP+STP "
                "ve RVB adımlarında çıkar.",
            ),
            (
                getattr(p, "_arrival_card", None),
                "4. Gelmekte Olan Ürünler",
                "Önceki adımdan henüz gelmemiş, ileride gelecek parçaları tanımla. Her satırda "
                "'Gelme süresi' kadar ileride hazır olacak iş ekleyebilirsin. Algoritma bekle/"
                "alma kararını bu parçalara göre verir. Assembly'de (ilk adım) bu kart yoktur.",
            ),
            (
                getattr(p, "_queue_card", None),
                "5. İş Kuyruğu",
                "Test edilecek hazır işleri ekle: Tip (K11, K12...), manuel girilen ürün adı, "
                "adet ve öncelik. Aynı tipten birden fazla satır eklersen algoritma otomatik "
                "tek batch'e gruplar (canonical pid mantığı). 'Diğer...' ile yeni tip ekleyebilirsin.",
            ),
            (
                getattr(p, "_run_btn", None),
                "6. Çalıştır",
                "Tüm parametreler hazırsa bu butona bas. Seçili adımın planlayıcısı bir kez "
                "çağrılır ve TEK BİR planlama kararı üretir (gerçek scheduler'ın aksine "
                "döngü yapmaz). Sonuç ve log panelleri açılır.",
            ),
            (
                getattr(p, "_results_card", None),
                "7. Sonuç Kartları",
                "Hangi makineye hangi ürün atandı, kaç adetlik batch, setup ve işlem süresi "
                "burada gösterilir. Atama yapılmayan makineler için 'Boşta' veya 'Meşgul - "
                "bekleniyor' kartı çıkar. Adım değiştirdiğinde bu panel otomatik temizlenir.",
            ),
            (
                getattr(p, "_log_card", None),
                "8. Karar Logları",
                "Algoritmanın karar verme detayları zaman damgalı olarak listelenir: "
                "KARAR_DETAY (neden bu ürün/batch seçildi), HOLD/BEKLENIYOR (kapasite "
                "dolsun diye bekleme), KURAL-2/3 (özel kurallar). Renkli çubuklar log "
                "tipini gösterir.",
            ),
        ]
        self.help_overlay.start(steps)

    def _on_product_updated_wizard_sync(self, old_name, new_product):
        """Kullanıcı ürün ismini/tipini değiştirirse wizard'daki listede de güncellensin."""
        new_name = new_product.display_name
        if old_name == new_name:
            return
        self._wizard_products = [
            new_name if p == old_name else p
            for p in getattr(self, "_wizard_products", [])
        ]

    def _start_new_product_wizard(self, display_names, include_product_page: bool = False, return_page: int = 9):
        """Yeni ürün tip(ler)i eklendiğinde kullanıcıyı sırayla yönlendiren wizard.

        include_product_page=True → Ürün Bilgileri (1) sayfası ilk adım olur (manuel ekleme durumu).
        return_page → wizard bittiğinde dönülecek sayfa (default: Adım Testi=9).
        """
        from PyQt6.QtWidgets import QMessageBox
        if isinstance(display_names, str):
            display_names = [display_names]
        pages = []
        if include_product_page:
            pages.append((1, "Ürün Bilgileri"))
        pages += [(2, "Üretim Süreleri"), (3, "Kurulum Matrisi"), (4, "Kapasite Tablosu")]
        self._wizard_pages = pages
        self._wizard_idx = 0
        self._wizard_products = list(display_names)
        self._wizard_return_page = return_page
        self._wizard_btn = None
        urunler_md = "\n".join(f"  • {n}" for n in display_names)
        adim_md = "\n".join(f"  {i+1}. {p[1]}" for i, p in enumerate(pages))
        QMessageBox.information(
            self, "Yeni Ürün(ler) Eklendi",
            f"Aşağıdaki ürün(ler) Ürün Bilgileri'ne otomatik eklendi:\n\n"
            f"{urunler_md}\n\n"
            f"Sırayla şu sayfalarda bilgileri kontrol/güncelle:\n{adim_md}\n\n"
            f"Her sayfada 'Devam Et →' butonuna basarak ilerle."
        )
        self._show_wizard_step()

    def _show_wizard_step(self):
        if self._wizard_idx >= len(self._wizard_pages):
            self._end_wizard()
            return
        idx, _ = self._wizard_pages[self._wizard_idx]
        page = self.stack.widget(idx)
        self.switch_page(idx)
        is_last = self._wizard_idx == len(self._wizard_pages) - 1
        btn_text = "✓ Tamamla → Adım Testi" if is_last else "Devam Et →"
        self._wizard_btn = page.add_action_button(btn_text, "ActionButton", self._advance_wizard)

    def _advance_wizard(self):
        # Mevcut sayfadan butonu kaldır
        if self._wizard_btn is not None and self._wizard_idx < len(self._wizard_pages):
            cur_idx, _ = self._wizard_pages[self._wizard_idx]
            cur_page = self.stack.widget(cur_idx)
            cur_page.action_layout.removeWidget(self._wizard_btn)
            self._wizard_btn.setParent(None)
            self._wizard_btn.deleteLater()
            self._wizard_btn = None
        self._wizard_idx += 1
        self._show_wizard_step()

    def _end_wizard(self):
        from PyQt6.QtWidgets import QMessageBox
        ret = getattr(self, "_wizard_return_page", 9)
        self.switch_page(ret)
        urunler = ", ".join(getattr(self, "_wizard_products", []) or [])
        QMessageBox.information(
            self, "Hazır",
            f"{urunler or 'Yeni ürünler'} için tüm bilgiler güncellendi."
        )
        self._wizard_btn = None
        self._wizard_idx = 0
        self._wizard_pages = []
        self._wizard_products = []

    # ── Çizelgeleme sonucu ────────────────────────────────────────────────
    def handle_schedule_results(self, result):
        week_number = self.p5.week_spinbox.value() if hasattr(self, 'p5') else 0
        self.data_manager.apply_schedule_result(result, week_number)

        self.p5.update_target_table()

        self.p6.set_result(result)
        self.p_sim.set_result(result)
        self.dashboard.set_last_result(result)
        self.switch_page(7)   # → Sonuçlar

    # ── Sayfa geçişi ──────────────────────────────────────────────────────
    def switch_page(self, index):
        self.stack.setCurrentIndex(index)
        for i, btn in enumerate(self.nav_buttons):
            btn.setProperty("active", str(i == index).lower())
            btn.style().unpolish(btn)
            btn.style().polish(btn)

        # Çizelgeleme sayfasına geçince hedef tablosunu güncelle
        if index == 6:
            self.p5.update_target_table()

    # ── Excel yükleme ─────────────────────────────────────────────────────
    def load_excel_data(self):
        from PyQt6.QtWidgets import QFileDialog, QMessageBox
        from services.excel_import import ExcelImportService

        file_path, _ = QFileDialog.getOpenFileName(
            self, "Excel Dosyası Seç", "",
            "Excel Dosyaları (*.xlsx *.xls);;Tüm Dosyalar (*)"
        )
        if not file_path:
            return

        products, messages = ExcelImportService.read_excel(file_path)
        if not products:
            QMessageBox.warning(self, "Excel Yükleme Hatası", "\n".join(messages))
            return

        self.data_manager.excel_products = products
        self.data_manager.excel_raw_rows = ExcelImportService.read_raw_rows(file_path)

        # Tablolarda olmayan Excel ürünlerini tespit et, ekle ve wizard'a hazırla
        # KURAL: aynı ürün TİPİ tablolarda yalnızca BİR kez yer alır.
        # Excel'de K12/A, K12/B, K12/C ... gibi farklı isimlerle aynı tip varsa,
        # tablolara sadece İLK ismiyle bir satır eklenir; diğerleri o canonical
        # satıra yönlendirilir (ep.canonical_pid).
        existing_pids = set(self.data_manager.state.production_time_data.keys())
        existing_types: dict[str, str] = {
            p.type: p.display_name for p in self.data_manager.state.products
        }
        canonical_by_type: dict[str, str] = dict(existing_types)
        newly_added_pids: list[str] = []
        for ep in products:
            if ep.product_type in canonical_by_type:
                # Bu tip için zaten canonical pid var (tablodan ya da daha önce eklenen Excel)
                continue
            pid = ep.display_name
            if pid in existing_pids:
                # Aynı display_name tabloda zaten var
                canonical_by_type[ep.product_type] = pid
                continue
            new_p = Product(type=ep.product_type, name=ep.product_name, monthly_target=0)
            self.data_manager.add_product(new_p)
            canonical_by_type[ep.product_type] = pid
            newly_added_pids.append(pid)

        # Her ExcelProduct'a canonical_pid ata (job oluştururken bu kullanılır)
        for ep in products:
            ep.canonical_pid = canonical_by_type.get(ep.product_type, ep.display_name)

        # Excel yüklendiğinde otomatik "sadece Excel" modu — tablo aylık hedefleri yok sayılır
        self.data_manager.excel_only_mode = True
        self.data_manager.products_changed.emit()

        if hasattr(self, 'p5'):
            self.p5.update_target_table()

        file_name = file_path.replace("\\", "/").split("/")[-1]
        QMessageBox.information(self, "Excel Yüklendi",
            f"Excel verisi başarıyla yüklendi!\n\nToplam okunan ürün: {len(products)} satır\nDosya: {file_name}"
        )

        # Tablolarda olmayan ürünler eklendiyse wizard akışını başlat
        if newly_added_pids:
            self._start_new_product_wizard(newly_added_pids)

    def clear_excel_data(self):
        """Excel verisini temizler."""
        self.data_manager.excel_products = None
        self.data_manager.excel_raw_rows = None
        self.data_manager.excel_only_mode = False
        self.data_manager.products_changed.emit()
        if hasattr(self, 'p5'):
            self.p5.update_target_table()

    # ── Ürün işlemleri ────────────────────────────────────────────────────
    def add_new_product(self):
        # İsim çakışmasını engelle
        existing = {p.display_name for p in self.data_manager.state.products}
        idx = 0
        name = "Yeni Ürün"
        while f"KXX / {name}" in existing:
            idx += 1
            name = f"Yeni Ürün {idx + 1}"
        new_prod = Product("KXX", name, 0)
        self.data_manager.add_product(new_prod)
        # Wizard: Ürün Bilgileri → Üretim Süreleri → Kurulum Matrisi → Kapasite onayı
        self._start_new_product_wizard(
            [new_prod.display_name], include_product_page=True, return_page=1
        )

    def delete_selected_product(self):
        is_active = not self.product_model.delete_mode
        self.product_model.set_delete_mode(is_active)

        vh = self.p1.table_view.verticalHeader()
        if is_active:
            vh.setSectionsClickable(True)
            try:
                self.vh_connection = vh.sectionClicked.connect(
                    self._handle_header_delete_click
                )
            except Exception:
                pass
        else:
            vh.setSectionsClickable(False)
            try:
                vh.sectionClicked.disconnect(self._handle_header_delete_click)
            except Exception:
                pass

    def _handle_header_delete_click(self, index):
        if not self.product_model.delete_mode:
            return

        product = self.data_manager.state.products[index]
        confirm = QMessageBox.question(
            self, "Silme Onayı",
            f"'{product.display_name}' ürününü ve tüm ilişkili verilerini silmek istiyor musunuz?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        if confirm == QMessageBox.StandardButton.Yes:
            self.data_manager.remove_product(index)
            self.product_model.set_delete_mode(False)
            vh = self.p1.table_view.verticalHeader()
            vh.setSectionsClickable(False)
            try:
                vh.sectionClicked.disconnect(self._handle_header_delete_click)
            except Exception:
                pass
