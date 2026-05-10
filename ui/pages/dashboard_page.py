import os
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QFrame, QScrollArea, QGridLayout
)
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QPixmap

# ──────────────────────────────────────────────────────────────────────────────
# Proje kök dizini ve Resimler yolu
_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.dirname(os.path.dirname(_THIS_DIR))
IMAGES_DIR = os.path.join(_PROJECT_ROOT, "images")

class StaticProductCard(QFrame):
    """Statik ürün kartı — sadece bilgi amaçlı, etkileşimsiz."""

    def __init__(self, product_type: str, parent=None):
        super().__init__(parent)
        self.setObjectName("StaticProductCard")
        self.setFixedSize(180, 200)
        self.setStyleSheet("""
            QFrame#StaticProductCard {
                background-color: white;
                border: 1px solid #E2E8F0;
                border-radius: 12px;
            }
        """)
        
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 12)
        lay.setSpacing(0)

        # Resim alanı
        img_frame = QFrame()
        img_frame.setFixedHeight(140)
        img_frame.setObjectName("ImgFrame")
        img_frame.setStyleSheet("""
            QFrame#ImgFrame {
                background-color: white;
                border-top-left-radius: 12px;
                border-top-right-radius: 12px;
                border-bottom: 1px solid #E2E8F0;
            }
        """)
        img_lay = QVBoxLayout(img_frame)
        img_lay.setContentsMargins(0, 0, 0, 0)
        
        img_lbl = QLabel()
        img_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        
        # Resim yüklemeyi dene
        img_path = os.path.join(IMAGES_DIR, f"{product_type}.png")
        if os.path.exists(img_path):
            px = QPixmap(img_path)
            if not px.isNull():
                # Card size is 180x220, img area is 180x140. 
                # Use KeepAspectRatio with a bit of padding (e.g. 170x130) to ensure it fits nicely
                scaled_px = px.scaled(
                    170, 130, 
                    Qt.AspectRatioMode.KeepAspectRatio, 
                    Qt.TransformationMode.SmoothTransformation
                )
                img_lbl.setPixmap(scaled_px)
        else:
            img_lbl.setText("📦")
            img_lbl.setStyleSheet("font-size: 44px; color: #CBD5E1;")

        img_lay.addWidget(img_lbl)
        lay.addWidget(img_frame)

        # Bilgi alanı
        info_lay = QVBoxLayout()
        info_lay.setContentsMargins(12, 10, 12, 0)
        info_lay.setSpacing(2)

        type_lbl = QLabel(product_type)
        type_lbl.setStyleSheet("font-size: 14px; font-weight: 800; color: #1E293B; background: transparent;")
        type_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)

        info_lay.addWidget(type_lbl)
        lay.addLayout(info_lay)
        lay.addStretch()


# ──────────────────────────────────────────────────────────────────────────────
class DashboardPage(QWidget):
    navigate_to = pyqtSignal(int)

    def __init__(self, data_manager, parent=None):
        super().__init__(parent)
        self.data_manager = data_manager
        self._init_ui()

    def _init_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setStyleSheet("background-color: #F8FAFC;")
        root.addWidget(scroll)

        content = QWidget()
        self._lay = QVBoxLayout(content)
        self._lay.setSpacing(24)
        self._lay.setContentsMargins(32, 32, 32, 32)
        scroll.setWidget(content)

        self._build_banner()
        self._build_flow_section()
        self._build_products_section()
        self._build_quick_actions()
        self._lay.addStretch()

    def _build_banner(self):
        banner = QFrame()
        banner.setStyleSheet("""
            QFrame {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #1E3A5F, stop:1 #2563EB);
                border-radius: 12px;
            }
        """)
        bl = QHBoxLayout(banner)
        bl.setContentsMargins(24, 20, 24, 20)

        txt = QVBoxLayout()
        t = QLabel("Hoş Geldiniz!")
        t.setStyleSheet("font-size: 24px; font-weight: 800; color: white; background: transparent;")
        s = QLabel("Üretim hattı durumunu ve ürün kataloğunu buradan takip edebilirsiniz.")
        s.setStyleSheet("font-size: 13px; color: #BFDBFE; background: transparent;")
        txt.addWidget(t)
        txt.addWidget(s)
        bl.addLayout(txt, 1)

        btn = QPushButton("Yeni Planlama Başlat")
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.setFixedSize(180, 40)
        btn.setStyleSheet("""
            QPushButton { background-color: white; color: #1D4ED8; border-radius: 6px; font-weight: 700; }
            QPushButton:hover { background-color: #EFF6FF; }
        """)
        btn.clicked.connect(lambda: self.navigate_to.emit(6))
        bl.addWidget(btn, 0, Qt.AlignmentFlag.AlignVCenter)
        self._lay.addWidget(banner)

    def _build_flow_section(self):
        t = QLabel("🏭  Üretim Hattı Şeması")
        t.setStyleSheet("font-size: 16px; font-weight: 700; color: #0F172A; background: transparent;")
        sub = QLabel("Üretim sürecinin istasyon bazlı akış diyagramı.")
        sub.setStyleSheet("font-size: 12px; color: #64748B; background: transparent;")
        self._lay.addWidget(t)
        self._lay.addWidget(sub)

        container = QFrame()
        container.setStyleSheet("background-color: white; border: 1px solid #E2E8F0; border-radius: 12px;")
        cl = QVBoxLayout(container)
        cl.setContentsMargins(15, 15, 15, 15)

        try:
            from ui.widgets.flow_diagram import FlowDiagram
            self._flow = FlowDiagram(self.data_manager)
            self._flow.setMinimumHeight(240)

            flow_scroll = QScrollArea()
            flow_scroll.setWidgetResizable(True)
            flow_scroll.setFixedHeight(250)
            flow_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
            flow_scroll.setFrameShape(QFrame.Shape.NoFrame)
            flow_scroll.setStyleSheet("background: transparent;")
            flow_scroll.setWidget(self._flow)

            cl.addWidget(flow_scroll)
        except Exception as e:
             cl.addWidget(QLabel(f"Şema yüklenemedi: {e}"))

        self._lay.addWidget(container)

    def _build_products_section(self):
        t = QLabel("📦  Ürün Kataloğu")
        t.setStyleSheet("font-size: 16px; font-weight: 700; color: #0F172A; background: transparent;")
        sub = QLabel("Sistemde üretilen ana ürün grupları.")
        sub.setStyleSheet("font-size: 12px; color: #64748B; background: transparent;")
        self._lay.addWidget(t)
        self._lay.addWidget(sub)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFixedHeight(250)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setStyleSheet("background: transparent;")

        cards_widget = QWidget()
        cards_widget.setStyleSheet("background: transparent;")
        cards_row = QHBoxLayout(cards_widget)
        cards_row.setContentsMargins(0, 5, 12, 5)
        cards_row.setSpacing(16)

        # Kullanıcının eklediği resimli ürün listesi
        static_products = ["K31 deneme test","K20","K40","K12","K11"]
        for p_type in static_products:
            cards_row.addWidget(StaticProductCard(p_type))
        
        cards_row.addStretch()
        scroll.setWidget(cards_widget)
        self._lay.addWidget(scroll)

    def _build_quick_actions(self):
        t = QLabel("⚡  Hızlı Erişim")
        t.setStyleSheet("font-size: 16px; font-weight: 700; color: #0F172A; background: transparent;")
        self._lay.addWidget(t)

        grid = QGridLayout()
        grid.setSpacing(12)
        actions = [
            ("📦  Ürün Bilgileri",   1, "#3B82F6"),
            ("⚙️  Üretim Süreleri",  2, "#6366F1"),
            ("📊  Kapasite Tablosu", 4, "#8B5CF6"),
            ("▶  Planlama Yap",      6, "#059669"),
            ("📈  Sonuçları İncele",  7, "#0891B2"),
        ]
        for i, (label, idx, color) in enumerate(actions):
            btn = self._make_action_btn(label, idx, color)
            grid.addWidget(btn, i // 3, i % 3)
        self._lay.addLayout(grid)

    def _make_action_btn(self, text: str, page_idx: int, color: str) -> QPushButton:
        btn = QPushButton(text)
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.setMinimumHeight(54)
        btn.setStyleSheet(f"""
            QPushButton {{
                background-color: white; color: {color}; border: 2px solid {color}30;
                border-radius: 10px; font-weight: 700; text-align: left; padding-left: 20px;
            }}
            QPushButton:hover {{ background-color: {color}10; border-color: {color}; }}
        """)
        btn.clicked.connect(lambda checked=False, i=page_idx: self.navigate_to.emit(i))
        return btn

    def set_last_result(self, _result):
        pass
