"""
Simülasyon Sayfası — İstasyon Bazlı Kuyruk Görünümü

Kullanıcı bir istasyonu seçince:
  - O istasyonda şu an ne işlendiğini görür
  - Kuyruktaki sıradaki parçaları ve önceliklerini görür
  - Her parçanın "hazır mı" (önceki adımı bitirdi mi) bilgisini görür
"""

from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QSlider, QPushButton, QFrame, QScrollArea,
    QSizePolicy, QButtonGroup
)
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QFont

from models.planning_result import PlanningResult


# ─── İstasyon Tanımları ───────────────────────────────────────────────────────
STAGE_DEFS = [
    {"key": "assembly", "label": "Assembly",  "sub": "Montaj",     "machines": ["Assembly"],            "prev": None},
    {"key": "ftp",      "label": "FTP",       "sub": "Fonks. Test","machines": ["FTP"],                 "prev": "assembly"},
    {"key": "bn",       "label": "B/N",       "sub": "Boyama",     "machines": ["B/N"],                 "prev": "ftp"},
    {"key": "dkk",      "label": "DKK",       "sub": "M1–M4",      "machines": ["M1","M2","M3","M4"],   "prev": "bn"},
    {"key": "rvb",      "label": "RVB",       "sub": "RVB",        "machines": ["RVB"],                 "prev": "dkk"},
    {"key": "atp_stp",  "label": "ATP+STP",   "sub": "M1–M4",      "machines": ["M1","M2","M3","M4"],   "prev": "rvb"},
]
STAGE_BY_KEY = {s["key"]: s for s in STAGE_DEFS}

# Simülasyon adımı → log step/action içinde aranacak anahtar kelimeler
STAGE_LOG_KEYWORDS = {
    "assembly": ["assembly", "ASSEMBLY"],
    "ftp":      ["FTP"],
    "bn":       ["B/N", "bn"],
    "dkk":      ["DKK", "dkk"],
    "rvb":      ["RVB", "rvb"],
    "atp_stp":  ["ATP", "atp_stp"],
}

STEP_LABELS = {
    "assembly": "Assembly", "ftp": "FTP", "bn": "B/N",
    "dkk": "DKK", "rvb": "RVB", "atp_stp": "ATP+STP"
}

ALL_MACHINES = ["Assembly", "FTP", "B/N", "M1", "M2", "M3", "M4", "RVB"]

MACHINE_LABELS = {
    "Assembly": "Assembly", "FTP": "FTP", "B/N": "B/N",
    "M1": "M1", "M2": "M2", "M3": "M3", "M4": "M4", "RVB": "RVB"
}

# Öncelik skoru → renk
PRIO_THRESHOLDS = [
    (0.75, "#DC2626", "#FEF2F2"),  # yüksek
    (0.40, "#D97706", "#FFFBEB"),  # orta
    (0.0,  "#16A34A", "#F0FDF4"),  # düşük
]


def _prio_colors(score: float) -> Tuple[str, str]:
    for thr, fg, bg in PRIO_THRESHOLDS:
        if score >= thr:
            return fg, bg
    return "#6B7280", "#F9FAFB"


def _fmt_td(td: timedelta) -> str:
    total_min = int(td.total_seconds() / 60)
    h, m = divmod(total_min, 60)
    return f"{h}s {m}dk" if h else f"{m}dk"


# ─── StageButton ─────────────────────────────────────────────────────────────
class StageButton(QPushButton):
    STYLE_ON = """
        QPushButton {
            background-color: #1E40AF;
            color: white;
            border: 2px solid #1E40AF;
            border-radius: 10px;
            font-size: 13px;
            font-weight: bold;
            padding: 10px 20px;
        }
    """
    STYLE_OFF = """
        QPushButton {
            background-color: white;
            color: #374151;
            border: 2px solid #D1D5DB;
            border-radius: 10px;
            font-size: 13px;
            font-weight: bold;
            padding: 10px 20px;
        }
        QPushButton:hover {
            background-color: #EFF6FF;
            border-color: #3B82F6;
            color: #1E40AF;
        }
    """

    def __init__(self, label: str, parent=None):
        super().__init__(label, parent)
        self.setCheckable(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setMinimumHeight(44)
        self.setMinimumWidth(100)
        self.setChecked(False)

    def setChecked(self, checked: bool):
        super().setChecked(checked)
        self.setStyleSheet(self.STYLE_ON if checked else self.STYLE_OFF)


# ─── QueueItemRow ─────────────────────────────────────────────────────────────
class QueueItemRow(QFrame):
    """Kuyruktaki tek bir parçanın satır gösterimi."""

    def __init__(self, rank: int, entry, is_current: bool,
                 is_ready: bool, status_text: str,
                 time_until: Optional[timedelta], parent=None):
        super().__init__(parent)
        self.setContentsMargins(0, 0, 0, 0)

        # ── Job türünü job_id'den çıkar (stil aşağıda ayarlanıyor)
        job_tag = ""
        if hasattr(entry, "job_id") and "||" in entry.job_id:
            job_tag = entry.job_id.split("||")[-1]

        # ── Satır arka plan / çerçeve rengi: önce job türüne, sonra duruma bak
        _TAG_META = {
            "Gelecek Hafta":     ("#8B5CF6", "#F5F3FF"),   # purple
            "Bu Hafta":          ("#3B82F6", "#EFF6FF"),   # blue  (hafif)
        }
        _is_excel_tag = job_tag.startswith("Excel")
        if is_current:
            frame_bg, frame_border = "#F0FDF4", "#22C55E"
            border_w = "2px"
        elif job_tag in _TAG_META:
            frame_border, frame_bg = _TAG_META[job_tag]
            border_w = "2px"
        elif _is_excel_tag:
            frame_border, frame_bg = "#0891B2", "#ECFEFF"   # cyan — Excel ürün
            border_w = "2px"
        elif is_ready:
            frame_bg, frame_border = "#FFFBEB", "#FCD34D"
            border_w = "1.5px"
        else:
            frame_bg, frame_border = "#F8FAFC", "#E2E8F0"
            border_w = "1.5px"

        self.setStyleSheet(f"""
            QueueItemRow {{
                background-color: {frame_bg};
                border: {border_w} solid {frame_border};
                border-radius: 10px;
            }}
        """)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(14, 10, 14, 10)
        layout.setSpacing(12)

        # ── Sıra numarası / ŞU AN
        if is_current:
            rank_lbl = QLabel("▶ ŞU AN")
            rank_lbl.setFont(QFont("Segoe UI", 11, QFont.Weight.Bold))
            rank_lbl.setStyleSheet("color: #16A34A; border: none;")
        else:
            rank_lbl = QLabel(f"#{rank}")
            rank_lbl.setFont(QFont("Segoe UI", 12, QFont.Weight.Bold))
            rank_lbl.setStyleSheet("color: #94A3B8; border: none;")
        rank_lbl.setFixedWidth(52)
        layout.addWidget(rank_lbl)

        # ── Ürün tipi + job türü badge (dikey yığın)
        fg, bg = _prio_colors(entry.priority_level)

        ptype_col = QVBoxLayout()
        ptype_col.setSpacing(2)
        ptype_col.setContentsMargins(0, 0, 0, 0)

        p_name_display = f"{entry.product_type} - {entry.product_name}" if entry.product_name else entry.product_type
        ptype_lbl = QLabel(p_name_display)
        ptype_lbl.setFont(QFont("Segoe UI", 12, QFont.Weight.Bold))
        ptype_lbl.setStyleSheet(f"color: {fg}; border: none;")
        ptype_col.addWidget(ptype_lbl)

        # Job türü rozeti
        if job_tag == "Gelecek Hafta":
            tag_lbl = QLabel("GEL.HAFTA")
            tag_lbl.setStyleSheet(
                "color: white; background: #7C3AED; border: none; "
                "border-radius: 3px; padding: 0px 5px; font-size: 9px; font-weight: 800;"
            )
            tag_lbl.setFixedHeight(14)
            ptype_col.addWidget(tag_lbl)
        elif job_tag == "Bu Hafta":
            tag_lbl = QLabel("BU HAFTA")
            tag_lbl.setStyleSheet(
                "color: white; background: #2563EB; border: none; "
                "border-radius: 3px; padding: 0px 5px; font-size: 9px; font-weight: 800;"
            )
            tag_lbl.setFixedHeight(14)
            ptype_col.addWidget(tag_lbl)
        elif _is_excel_tag:
            _date_part = job_tag.split("::")[-1] if "::" in job_tag else None
            _badge_text = f"EXCEL  {_date_part}'den" if _date_part else "EXCEL"
            tag_lbl = QLabel(_badge_text)
            tag_lbl.setStyleSheet(
                "color: white; background: #0891B2; border: none; "
                "border-radius: 3px; padding: 0px 5px; font-size: 9px; font-weight: 800;"
            )
            tag_lbl.setFixedHeight(14)
            ptype_col.addWidget(tag_lbl)

        ptype_widget = QWidget()
        ptype_widget.setLayout(ptype_col)
        ptype_widget.setFixedWidth(200) # Genişliği artırdım (isim sığsın diye)
        ptype_widget.setStyleSheet("background: transparent;")
        layout.addWidget(ptype_widget)

        # ── Grup boyutu
        grp_lbl = QLabel(f"{entry.group_size} adet")
        grp_lbl.setFont(QFont("Segoe UI", 12))
        grp_lbl.setStyleSheet("color: #374151; border: none;")
        grp_lbl.setFixedWidth(70)
        layout.addWidget(grp_lbl)

        # ── Makine
        mach_lbl = QLabel(entry.machine_name.replace("1 Mak", "Tek Mak"))
        mach_lbl.setFont(QFont("Segoe UI", 11))
        mach_lbl.setStyleSheet("color: #6B7280; border: none;")
        mach_lbl.setFixedWidth(70)
        layout.addWidget(mach_lbl)

        # ── Zaman aralığı
        time_lbl = QLabel(
            f"{entry.start_time.strftime('%d.%m %H:%M')} - {entry.end_time.strftime('%H:%M')}"
        )
        time_lbl.setFont(QFont("Segoe UI", 11))
        time_lbl.setStyleSheet("color: #1E293B; border: none;")
        time_lbl.setFixedWidth(165)
        layout.addWidget(time_lbl)

        # ── Öncelik badge
        prio_val = entry.priority_level
        if prio_val < 0:
            prio_text = f"Önc {prio_val:.6f}"
            prio_style = "color: #7C3AED; background: #F5F3FF; border-radius: 5px; padding: 2px 8px; border: none;"
        else:
            prio_text = f"Önc {prio_val:.6f}"
            prio_style = f"color: {fg}; background: {bg}; border-radius: 5px; padding: 2px 8px; border: none;"

        prio_lbl = QLabel(prio_text)
        prio_lbl.setFont(QFont("Segoe UI", 10, QFont.Weight.Bold))
        prio_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        prio_lbl.setStyleSheet(prio_style)
        prio_lbl.setFixedWidth(130)
        layout.addWidget(prio_lbl)

        # ── Durum
        if is_current:
            remain_str = _fmt_td(time_until) if time_until else "—"
            st_lbl = QLabel(f"⏱ {remain_str} kaldı")
            st_lbl.setFont(QFont("Segoe UI", 11, QFont.Weight.Bold))
            st_lbl.setStyleSheet("color: #16A34A; border: none;")
        elif is_ready:
            st_lbl = QLabel("✅ Hazır")
            st_lbl.setFont(QFont("Segoe UI", 11, QFont.Weight.Bold))
            st_lbl.setStyleSheet("color: #D97706; border: none;")
        else:
            st_lbl = QLabel(status_text or "⏳ Bekliyor")
            st_lbl.setFont(QFont("Segoe UI", 10))
            st_lbl.setStyleSheet("color: #94A3B8; border: none;")
        st_lbl.setFixedWidth(130)
        layout.addWidget(st_lbl)

        # ── Setup bilgisi (varsa)
        if entry.setup_time > 0:
            setup_lbl = QLabel(f"🔧 {entry.setup_time:.0f}s")
            setup_lbl.setFont(QFont("Segoe UI", 10))
            setup_lbl.setStyleSheet("color: #F59E0B; border: none;")
            layout.addWidget(setup_lbl)

        layout.addStretch()


# ─── MachineStatusCard ────────────────────────────────────────────────────────
class MachineStatusCard(QFrame):
    """Seçili istasyondaki makine durumu (büyük kart)."""

    STATUS_META = {
        "working":       ("#22C55E", "#F0FDF4", "#166534", "🟢", "ÜRETİMDE"),
        "setup":         ("#F59E0B", "#FFFBEB", "#92400E", "🟡", "SETUP"),
        "daily_setup":   ("#3B82F6", "#EFF6FF", "#1E40AF", "🔵", "GÜNLÜK HAZIRLIK"),
        "initial_setup": ("#3B82F6", "#EFF6FF", "#1E40AF", "🔵", "İLK KULLANIM SETUP"),
        "idle":          ("#D1D5DB", "#F9FAFB", "#6B7280", "⚪", "BOŞ"),
    }

    def __init__(self, machine_name: str, parent=None):
        super().__init__(parent)
        self.machine_name = machine_name
        self.setMinimumWidth(180)
        self.setMinimumHeight(155)
        self._build()
        self.set_idle()

    def _build(self):
        lay = QVBoxLayout(self)
        lay.setContentsMargins(14, 12, 14, 12)
        lay.setSpacing(5)

        # Başlık
        hdr = QHBoxLayout()
        self.icon_lbl = QLabel("⚪")
        self.icon_lbl.setFont(QFont("Segoe UI", 16))
        self.name_lbl = QLabel(MACHINE_LABELS.get(self.machine_name, self.machine_name))
        self.name_lbl.setFont(QFont("Segoe UI", 14, QFont.Weight.Bold))
        hdr.addWidget(self.icon_lbl)
        hdr.addWidget(self.name_lbl)
        hdr.addStretch()
        lay.addLayout(hdr)

        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet("background-color: #E5E7EB;")
        sep.setFixedHeight(1)
        lay.addWidget(sep)

        self.status_lbl = QLabel("BOŞ")
        self.status_lbl.setFont(QFont("Segoe UI", 11, QFont.Weight.Bold))
        lay.addWidget(self.status_lbl)

        self.product_lbl = QLabel("-")
        self.product_lbl.setFont(QFont("Segoe UI", 11))
        lay.addWidget(self.product_lbl)

        self.time_lbl = QLabel("")
        self.time_lbl.setFont(QFont("Segoe UI", 10))
        self.time_lbl.setStyleSheet("color: #6B7280;")
        lay.addWidget(self.time_lbl)

        self.detail_lbl = QLabel("")
        self.detail_lbl.setFont(QFont("Segoe UI", 9))
        self.detail_lbl.setStyleSheet("color: #9CA3AF;")
        lay.addWidget(self.detail_lbl)

        lay.addStretch()

    def _style(self, status: str):
        border, bg, text, icon, label = self.STATUS_META.get(status, self.STATUS_META["idle"])
        self.setStyleSheet(f"""
            MachineStatusCard {{
                background-color: {bg};
                border: 2px solid {border};
                border-radius: 12px;
            }}
        """)
        self.icon_lbl.setText(icon)
        self.status_lbl.setText(label)
        self.status_lbl.setStyleSheet(f"color: {text}; font-weight: bold;")

    def set_idle(self, last_product=None, idle_since=None):
        self._style("idle")
        self.product_lbl.setText(f"Son: {last_product}" if last_product else "—")
        self.time_lbl.setText(f"{idle_since.strftime('%H:%M')}'den beri boş" if idle_since else "")
        self.detail_lbl.setText("")

    def set_working(self, product_type, product_name, step_name, start, end, group_size):
        self._style("working")
        
        # Hangi operasyonun yapıldığını (Ör: DKK, ATP+STP) etikete ekle
        step_str = step_name.upper()
        if step_name == "atp_stp": step_str = "ATP+STP"
        elif step_name == "dkk": step_str = "DKK"
        
        full_name = f"{product_type} - {product_name}" if product_name else product_type
        self.product_lbl.setText(f"📦 {full_name}\n({step_str})")
        self.product_lbl.setWordWrap(True)
        self.time_lbl.setText(f"⏱ {start.strftime('%H:%M')} → {end.strftime('%H:%M')}")
        self.detail_lbl.setText(f"Grup: {group_size} adet" if group_size > 1 else "")

    def set_setup(self, product_type, product_name, setup_time, is_daily=False,
                  is_initial=False, is_transition=False,
                  from_product=None, from_product_name=None,
                  initial_setup_time=0.0, transition_setup_time=0.0):
        is_initial = is_initial or is_daily  # geriye dönük uyumluluk
        self._style("initial_setup" if is_initial else "setup")
        full_name = f"{product_type} - {product_name}" if product_name else (product_type or "")
        self.product_lbl.setText(f"📦 {full_name}")
        self.time_lbl.setText(f"⏱ {setup_time:.1f} saat")
        if is_initial and is_transition:
            parts = []
            if initial_setup_time > 0:
                parts.append(f"İlk kullanım: {initial_setup_time:.1f} saat")
            if transition_setup_time > 0:
                from_name = f"{from_product} - {from_product_name}" if from_product_name else (from_product or "")
                parts.append(f"Geçiş ({from_name} → {full_name}): {transition_setup_time:.1f} saat")
            self.detail_lbl.setText(" | ".join(parts) if parts else "İlk kullanım")
        elif is_initial:
            if transition_setup_time > 0:
                from_name = f"{from_product} - {from_product_name}" if from_product_name else (from_product or "")
                self.detail_lbl.setText(
                    f"İlk kullanım: {initial_setup_time:.1f}s | Geçiş ({from_name}→{full_name}): {transition_setup_time:.1f}s"
                )
            else:
                self.detail_lbl.setText("İlk kullanım setup")
        elif from_product:
            from_name = f"{from_product} - {from_product_name}" if from_product_name else from_product
            self.detail_lbl.setText(f"Ürünler arası geçiş: {from_name} → {full_name}")
        else:
            self.detail_lbl.setText("Ürünler arası geçiş setup")


# ─── LogEntryRow ─────────────────────────────────────────────────────────────
class LogEntryRow(QFrame):
    """Tek bir karar log satırı."""

    ACTION_COLORS = {
        "KARAR_DETAY": ("#22D3EE", "#0E7490"),   # cyan — detay kararlar
        "KARAR":       ("#34D399", "#065F46"),    # yeşil — genel kararlar
        "BEKLEME":     ("#FBBF24", "#78350F"),    # sarı — bekleme
        "DEFAULT":     ("#94A3B8", "#1E293B"),    # gri  — diğer
    }

    def __init__(self, log_entry: dict, parent=None):
        super().__init__(parent)
        action: str = log_entry.get("action", "")
        details: str = log_entry.get("details", "")
        ts: datetime = log_entry.get("timestamp", datetime.now())

        # Renk seç
        if "KARAR_DETAY" in action:
            fg, tag_bg = self.ACTION_COLORS["KARAR_DETAY"]
        elif "KARAR" in action:
            fg, tag_bg = self.ACTION_COLORS["KARAR"]
        elif "BEKLEME" in action or "bekleniyor" in details.lower():
            fg, tag_bg = self.ACTION_COLORS["BEKLEME"]
        else:
            fg, tag_bg = self.ACTION_COLORS["DEFAULT"]

        self.setStyleSheet(f"""
            QFrame {{
                background-color: #1E293B;
                border: 1px solid #334155;
                border-left: 3px solid {fg};
                border-radius: 6px;
                padding: 2px;
            }}
        """)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(10, 6, 10, 6)
        lay.setSpacing(3)

        # Üst satır: zaman + eylem etiketi
        top = QHBoxLayout()
        top.setSpacing(8)

        time_lbl = QLabel(ts.strftime("%d.%m %H:%M"))
        time_lbl.setFont(QFont("Consolas", 9))
        time_lbl.setStyleSheet(f"color: #64748B; border: none; background: transparent;")
        time_lbl.setFixedWidth(80)
        top.addWidget(time_lbl)

        action_lbl = QLabel(action)
        action_lbl.setFont(QFont("Segoe UI", 8, QFont.Weight.Bold))
        action_lbl.setStyleSheet(
            f"color: {fg}; background: {tag_bg}; border: none; "
            f"border-radius: 3px; padding: 1px 5px;"
        )
        action_lbl.setFixedHeight(18)
        top.addWidget(action_lbl)
        top.addStretch()
        lay.addLayout(top)

        # Alt satır: detay metni (tam açıklama)
        detail_lbl = QLabel(details)
        detail_lbl.setFont(QFont("Segoe UI", 10))
        detail_lbl.setStyleSheet("color: #E2E8F0; border: none; background: transparent;")
        detail_lbl.setWordWrap(True)
        lay.addWidget(detail_lbl)


# ─── SimulationPage ──────────────────────────────────────────────────────────
class SimulationPage(QWidget):

    def __init__(self, data_manager, parent=None):
        super().__init__(parent)
        self.data_manager = data_manager
        self.result: Optional[PlanningResult] = None
        self.schedule: list = []
        self.start_time: Optional[datetime] = None
        self.end_time: Optional[datetime] = None

        self.entries_by_machine: Dict[str, list] = {}
        self.entries_by_job: Dict[str, list] = {}
        self.entries_by_step: Dict[str, list] = {}   # step_name → entries
        self.job_product_type: Dict[str, str] = {}
        self.completion_events: list = []
        self.targets: Dict[str, int] = {}
        self.product_types_ordered: List[str] = []

        self._selected_stage: str = STAGE_DEFS[0]["key"]
        self._stage_buttons: Dict[str, StageButton] = {}
        self._machine_cards: Dict[str, MachineStatusCard] = {}

        self._build_ui()

    # ════════════════════════════════════════════════
    # UI KURULUMU
    # ════════════════════════════════════════════════
    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(20, 15, 20, 15)
        root.setSpacing(14)

        # Başlık
        title = QLabel("Üretim Simülasyonu")
        title.setObjectName("PageTitle")
        root.addWidget(title)

        sub = QLabel("İstasyon seçin · kuyruktaki parçaları ve sistem kararlarını izleyin")
        sub.setObjectName("PageSubtitle")
        root.addWidget(sub)

        # Scroll
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("QScrollArea { border: none; background: transparent; }")
        body = QWidget()
        self.body_layout = QVBoxLayout(body)
        self.body_layout.setSpacing(14)
        scroll.setWidget(body)
        root.addWidget(scroll)

        self._build_timeline(self.body_layout)
        self._build_metrics(self.body_layout)
        self._build_machine_overview(self.body_layout)
        self._build_stage_selector(self.body_layout)
        self._build_main_panel(self.body_layout)
        self._build_log_panel(self.body_layout)
        self.body_layout.addStretch()

        # Boş mesaj
        self.empty_label = QLabel(
            "Henüz simülasyon sonucu yok.\nÇizelgeleme sayfasından bir simülasyon çalıştırın."
        )
        self.empty_label.setFont(QFont("Segoe UI", 13))
        self.empty_label.setStyleSheet("color: #94A3B8;")
        self.empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.body_layout.addWidget(self.empty_label)

    def _build_timeline(self, parent_layout):
        box = QFrame()
        box.setStyleSheet("""
            QFrame {
                background-color: #F8FAFC;
                border: 1px solid #E2E8F0;
                border-radius: 12px;
            }
        """)
        lay = QVBoxLayout(box)
        lay.setContentsMargins(16, 12, 16, 12)
        lay.setSpacing(10)

        # Zaman göstergesi satırı
        row = QHBoxLayout()
        self.time_display = QLabel("Simülasyon başlatılmadı")
        self.time_display.setFont(QFont("Segoe UI", 14, QFont.Weight.Bold))
        self.time_display.setStyleSheet("color: #1E40AF; border: none;")
        row.addWidget(self.time_display)
        row.addStretch()
        self.elapsed_label = QLabel("")
        self.elapsed_label.setFont(QFont("Segoe UI", 11))
        self.elapsed_label.setStyleSheet("color: #64748B; border: none;")
        row.addWidget(self.elapsed_label)
        lay.addLayout(row)

        # Slider
        self.timeline_slider = QSlider(Qt.Orientation.Horizontal)
        self.timeline_slider.setMinimum(0)
        self.timeline_slider.setMaximum(100)
        self.timeline_slider.setValue(0)
        self.timeline_slider.setEnabled(False)
        self.timeline_slider.setStyleSheet("""
            QSlider::groove:horizontal {
                border: 1px solid #CBD5E0;
                height: 10px;
                background: qlineargradient(x1:0,y1:0,x2:1,y2:0,
                    stop:0 #3B82F6, stop:0.5 #8B5CF6, stop:1 #22C55E);
                border-radius: 5px;
            }
            QSlider::handle:horizontal {
                background: white;
                border: 3px solid #3B82F6;
                width: 24px; height: 24px;
                margin: -8px 0;
                border-radius: 12px;
            }
            QSlider::handle:horizontal:hover { border-color: #1D4ED8; }
        """)
        self.timeline_slider.valueChanged.connect(self._on_slider_changed)
        lay.addWidget(self.timeline_slider)

        # Tarih aralığı
        rng = QHBoxLayout()
        self.range_start_lbl = QLabel("")
        self.range_start_lbl.setFont(QFont("Segoe UI", 9))
        self.range_start_lbl.setStyleSheet("color: #94A3B8; border: none;")
        self.range_end_lbl = QLabel("")
        self.range_end_lbl.setFont(QFont("Segoe UI", 9))
        self.range_end_lbl.setStyleSheet("color: #94A3B8; border: none;")
        rng.addWidget(self.range_start_lbl)
        rng.addStretch()
        rng.addWidget(self.range_end_lbl)
        lay.addLayout(rng)

        # Kontrol butonları
        btn_style = """
            QPushButton {
                background: white; border: 1px solid #D1D5DB; border-radius: 8px;
                padding: 6px 14px; font-size: 12px; font-weight: bold; color: #374151;
            }
            QPushButton:hover { background: #F3F4F6; border-color: #3B82F6; color: #3B82F6; }
        """
        btns = QHBoxLayout()
        btns.addStretch()
        for text, handler in [
            ("⏮ Başa", self._go_start), ("◀ −1 Saat", self._step_back_1h),
            ("◁ −10 Dk", self._step_back_10m), ("▷ +10 Dk", self._step_fwd_10m),
            ("▶ +1 Saat", self._step_fwd_1h), ("⏭ Sona", self._go_end),
        ]:
            b = QPushButton(text)
            b.setStyleSheet(btn_style)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.clicked.connect(handler)
            btns.addWidget(b)
        btns.addStretch()
        lay.addLayout(btns)

        parent_layout.addWidget(box)

    def _build_metrics(self, parent_layout):
        box = QFrame()
        box.setStyleSheet("""
            QFrame {
                background: qlineargradient(x1:0,y1:0,x2:1,y2:0,stop:0 #1E293B,stop:1 #334155);
                border-radius: 12px;
            }
        """)
        lay = QHBoxLayout(box)
        lay.setContentsMargins(20, 12, 20, 12)
        self.metric_labels: Dict[str, QLabel] = {}

        for key, title, default in [
            ("elapsed",         "Geçen Süre",    "—"),
            ("completed",       "Tamamlanan",    "—"),
            ("setup_total",     "Setup Süresi",  "—"),
            ("active_machines", "Aktif Makine",  "—"),
        ]:
            col = QVBoxLayout()
            t = QLabel(title)
            t.setFont(QFont("Segoe UI", 9))
            t.setStyleSheet("color: #94A3B8; border: none;")
            t.setAlignment(Qt.AlignmentFlag.AlignCenter)
            v = QLabel(default)
            v.setFont(QFont("Segoe UI", 16, QFont.Weight.Bold))
            v.setStyleSheet("color: white; border: none;")
            v.setAlignment(Qt.AlignmentFlag.AlignCenter)
            col.addWidget(t)
            col.addWidget(v)
            lay.addLayout(col)
            self.metric_labels[key] = v

        parent_layout.addWidget(box)

    def _build_stage_selector(self, parent_layout):
        section_lbl = QLabel("İstasyon Seçin")
        section_lbl.setFont(QFont("Segoe UI", 13, QFont.Weight.Bold))
        section_lbl.setStyleSheet("color: #1E293B;")
        parent_layout.addWidget(section_lbl)

        row = QHBoxLayout()
        row.setSpacing(10)
        self._btn_group = QButtonGroup(self)
        self._btn_group.setExclusive(True)

        for i, stage in enumerate(STAGE_DEFS):
            btn = StageButton(stage["label"])
            btn.setToolTip(stage["sub"])
            self._stage_buttons[stage["key"]] = btn
            self._btn_group.addButton(btn, i)
            row.addWidget(btn)

            btn.clicked.connect(lambda checked, k=stage["key"]: self._on_stage_selected(k))

        row.addStretch()

        container = QWidget()
        container.setLayout(row)
        parent_layout.addWidget(container)

        # İlk butonu seç
        self._stage_buttons[self._selected_stage].setChecked(True)

    def _build_main_panel(self, parent_layout):
        """Makine kartları (sol) + kuyruk paneli (sağ)."""
        self.main_panel = QHBoxLayout()
        self.main_panel.setSpacing(14)

        # Sol: makine kartları (seçili istasyona göre dinamik)
        left = QVBoxLayout()
        left.setSpacing(8)
        self.machine_cards_title = QLabel("Makine Durumu")
        self.machine_cards_title.setFont(QFont("Segoe UI", 12, QFont.Weight.Bold))
        self.machine_cards_title.setStyleSheet("color: #1E293B;")
        left.addWidget(self.machine_cards_title)

        self.machine_cards_container = QVBoxLayout()
        self.machine_cards_container.setSpacing(8)
        left.addLayout(self.machine_cards_container)
        left.addStretch()

        left_widget = QWidget()
        left_widget.setLayout(left)
        left_widget.setFixedWidth(220)
        self.main_panel.addWidget(left_widget)

        # Sağ: kuyruk paneli
        self.queue_frame = QFrame()
        self.queue_frame.setStyleSheet("""
            QFrame {
                background-color: white;
                border: 1px solid #E2E8F0;
                border-radius: 12px;
            }
        """)
        queue_outer = QVBoxLayout(self.queue_frame)
        queue_outer.setContentsMargins(16, 14, 16, 14)
        queue_outer.setSpacing(10)

        # Kuyruk başlığı
        self.queue_title = QLabel("Kuyruk")
        self.queue_title.setFont(QFont("Segoe UI", 13, QFont.Weight.Bold))
        self.queue_title.setStyleSheet("color: #1E293B; border: none;")
        queue_outer.addWidget(self.queue_title)

        self.queue_summary = QLabel("")
        self.queue_summary.setFont(QFont("Segoe UI", 10))
        self.queue_summary.setStyleSheet("color: #64748B; border: none;")
        queue_outer.addWidget(self.queue_summary)

        # Sütun başlıkları
        col_hdr = QHBoxLayout()
        col_hdr.setContentsMargins(14, 0, 14, 0)
        col_hdr.setSpacing(14)
        for text, width in [
            ("#",      58), ("Ürün", 50), ("Adet", 65), ("Mak.",38),
            ("Zaman",  155), ("Öncelik", 85), ("Durum", 130),
        ]:
            lbl = QLabel(text)
            lbl.setFont(QFont("Segoe UI", 9, QFont.Weight.Bold))
            lbl.setStyleSheet("color: #94A3B8; border: none;")
            if width:
                lbl.setFixedWidth(width)
            col_hdr.addWidget(lbl)
        col_hdr.addStretch()

        col_hdr_widget = QWidget()
        col_hdr_widget.setLayout(col_hdr)
        queue_outer.addWidget(col_hdr_widget)

        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet("background-color: #E2E8F0; border: none;")
        sep.setFixedHeight(1)
        queue_outer.addWidget(sep)

        # Kuyruk scroll alanı
        self.queue_scroll = QScrollArea()
        self.queue_scroll.setWidgetResizable(True)
        self.queue_scroll.setStyleSheet("""
            QScrollArea { border: none; background: transparent; }
            QScrollBar:vertical { width: 8px; }
        """)
        self.queue_scroll.setMinimumHeight(320)

        self.queue_inner = QWidget()
        self.queue_inner.setStyleSheet("background: transparent;")
        self.queue_inner_layout = QVBoxLayout(self.queue_inner)
        self.queue_inner_layout.setContentsMargins(0, 4, 0, 4)
        self.queue_inner_layout.setSpacing(6)
        self.queue_scroll.setWidget(self.queue_inner)
        queue_outer.addWidget(self.queue_scroll)

        self.queue_empty_lbl = QLabel("Bu istasyonda henüz planlanmış iş yok.")
        self.queue_empty_lbl.setFont(QFont("Segoe UI", 11))
        self.queue_empty_lbl.setStyleSheet("color: #94A3B8; border: none;")
        self.queue_empty_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.queue_inner_layout.addWidget(self.queue_empty_lbl)
        self.queue_inner_layout.addStretch()

        self.main_panel.addWidget(self.queue_frame, stretch=1)

        container = QWidget()
        container.setLayout(self.main_panel)
        parent_layout.addWidget(container)

    def _build_machine_overview(self, parent_layout):
        """Tüm makinelerin kompakt özeti."""
        lbl = QLabel("Tüm Makinelere Genel Bakış")
        lbl.setFont(QFont("Segoe UI", 15, QFont.Weight.Bold))
        lbl.setStyleSheet("color: #1E293B; margin-top: 10px;")
        parent_layout.addWidget(lbl)

        row = QHBoxLayout()
        row.setSpacing(8)
        self._overview_cards: Dict[str, "OverviewCard"] = {}
        for name in ALL_MACHINES:
            card = OverviewCard(name)
            self._overview_cards[name] = card
            row.addWidget(card)

        container = QWidget()
        container.setLayout(row)
        parent_layout.addWidget(container)

    def _build_log_panel(self, parent_layout):
        """Karar Günlüğü paneli — seçili istasyona ait algoritma kararlarını gösterir."""
        lbl = QLabel("Karar Günlüğü")
        lbl.setFont(QFont("Segoe UI", 12, QFont.Weight.Bold))
        lbl.setStyleSheet("color: #1E293B; margin-top: 6px;")
        parent_layout.addWidget(lbl)

        box = QFrame()
        box.setStyleSheet("""
            QFrame {
                background-color: #0F172A;
                border: 1px solid #1E293B;
                border-radius: 12px;
            }
        """)
        lay = QVBoxLayout(box)
        lay.setContentsMargins(16, 14, 16, 14)
        lay.setSpacing(8)

        # Başlık satırı
        header = QHBoxLayout()
        self.log_stage_lbl = QLabel("Assembly — Kararlar")
        self.log_stage_lbl.setFont(QFont("Segoe UI", 11, QFont.Weight.Bold))
        self.log_stage_lbl.setStyleSheet("color: #F1F5F9; border: none;")
        header.addWidget(self.log_stage_lbl)
        header.addStretch()
        self.log_count_lbl = QLabel("0 kayıt")
        self.log_count_lbl.setFont(QFont("Segoe UI", 10))
        self.log_count_lbl.setStyleSheet("color: #64748B; border: none;")
        header.addWidget(self.log_count_lbl)
        lay.addLayout(header)

        # Scroll alanı
        self.log_scroll = QScrollArea()
        self.log_scroll.setWidgetResizable(True)
        self.log_scroll.setStyleSheet("""
            QScrollArea { border: none; background: transparent; }
            QScrollBar:vertical { width: 8px; background: #1E293B; border-radius: 4px; }
            QScrollBar::handle:vertical { background: #475569; border-radius: 4px; }
        """)
        self.log_scroll.setMinimumHeight(220)
        self.log_scroll.setMaximumHeight(340)

        self.log_inner = QWidget()
        self.log_inner.setStyleSheet("background: transparent;")
        self.log_inner_layout = QVBoxLayout(self.log_inner)
        self.log_inner_layout.setContentsMargins(0, 0, 0, 0)
        self.log_inner_layout.setSpacing(5)
        self.log_inner_layout.addStretch()
        self.log_scroll.setWidget(self.log_inner)
        lay.addWidget(self.log_scroll)

        parent_layout.addWidget(box)

    def _update_log_panel(self, current_time: datetime):
        """Seçili istasyon + mevcut zamana göre log satırlarını yenile."""
        if not self.result or not getattr(self.result, "raw_audit_logs", None):
            return

        stage = self._selected_stage
        keywords = STAGE_LOG_KEYWORDS.get(stage, [])

        def _matches(log: dict) -> bool:
            step = log.get("step", "")
            action = log.get("action", "")
            return any(kw in step or kw in action for kw in keywords)

        relevant = [
            log for log in self.result.raw_audit_logs
            if log.get("timestamp") <= current_time and _matches(log)
        ]

        # Başlığı güncelle
        stage_label = STAGE_BY_KEY.get(stage, {}).get("label", stage)
        self.log_stage_lbl.setText(f"{stage_label} — Kararlar")
        self.log_count_lbl.setText(f"{len(relevant)} kayıt")

        # Mevcut satırları temizle
        while self.log_inner_layout.count():
            item = self.log_inner_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        # Son 60 kaydı göster
        for log in relevant[-60:]:
            row = LogEntryRow(log)
            self.log_inner_layout.addWidget(row)

        self.log_inner_layout.addStretch()

        # En alta kaydır
        QTimer.singleShot(30, lambda: self.log_scroll.verticalScrollBar().setValue(
            self.log_scroll.verticalScrollBar().maximum()
        ))

    # ════════════════════════════════════════════════
    # SONUÇ YÜKLEME
    # ════════════════════════════════════════════════
    def set_result(self, result: PlanningResult):
        self.result = result
        self.schedule = result.schedule
        self.empty_label.hide()

        # Priority history: scheduler her recalc'ta snapshot bıraktı, slider'a göre lookup için sakla
        # Format: {f"{product_type}||{tag}": [(iso_time_str, score), ...]}
        raw_history = getattr(result, "priority_history", {}) or {}
        self.priority_history = {}
        for key, snaps in raw_history.items():
            parsed = []
            for t, s in snaps:
                if isinstance(t, str):
                    parsed.append((datetime.fromisoformat(t), s))
                else:
                    parsed.append((t, s))
            parsed.sort(key=lambda x: x[0])
            self.priority_history[key] = parsed

        if not self.schedule:
            return

        self.start_time = min(e.start_time for e in self.schedule)
        self.end_time   = max(e.end_time   for e in self.schedule)

        self._preprocess_schedule()
        self._setup_machine_cards_for_stage(self._selected_stage)

        total_minutes = max(1, int((self.end_time - self.start_time).total_seconds() / 60))
        self.timeline_slider.setMaximum(total_minutes)
        self.timeline_slider.setEnabled(True)
        self.timeline_slider.setValue(0)

        self.range_start_lbl.setText(self.start_time.strftime("%d.%m.%Y %H:%M"))
        self.range_end_lbl.setText(self.end_time.strftime("%d.%m.%Y %H:%M"))

        self._on_slider_changed(0)

    def _preprocess_schedule(self):
        self.entries_by_machine = {}
        self.entries_by_job = {}
        self.entries_by_step = {}
        self.job_product_type = {}

        for e in self.schedule:
            self.entries_by_machine.setdefault(e.machine_name, []).append(e)
            self.entries_by_job.setdefault(e.job_id, []).append(e)
            self.entries_by_step.setdefault(e.step_name, []).append(e)
            self.job_product_type[e.job_id] = e.product_type

        for lst in self.entries_by_machine.values():
            lst.sort(key=lambda x: x.start_time)
        for lst in self.entries_by_job.values():
            lst.sort(key=lambda x: x.start_time)
        for lst in self.entries_by_step.values():
            lst.sort(key=lambda x: x.start_time)

        # Tamamlanma olayları
        self.completion_events = []
        seen = set()
        for e in self.schedule:
            if e.step_name == "atp_stp" and e.job_id not in seen:
                seen.add(e.job_id)
                self.completion_events.append((e.end_time, e.product_type))
        self.completion_events.sort(key=lambda x: x[0])

        # Hedefler
        self.targets = {}
        self.product_types_ordered = []
        if self.result and self.result.remaining_targets:
            for rt in self.result.remaining_targets:
                self.targets[rt.product_type] = rt.period_target
                self.product_types_ordered.append(rt.product_type)

    def _setup_machine_cards_for_stage(self, stage_key: str):
        """Seçili istasyona göre sol paneldeki makine kartlarını yeniden oluştur."""
        # Eski kartları temizle
        while self.machine_cards_container.count():
            item = self.machine_cards_container.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self._machine_cards.clear()

        stage = STAGE_BY_KEY[stage_key]
        self.machine_cards_title.setText(f"{stage['label']} — Makine Durumu")

        for mname in stage["machines"]:
            card = MachineStatusCard(mname)
            self._machine_cards[mname] = card
            self.machine_cards_container.addWidget(card)

    # ════════════════════════════════════════════════
    # STAGE SEÇİMİ
    # ════════════════════════════════════════════════
    def _on_stage_selected(self, stage_key: str):
        self._selected_stage = stage_key
        for k, btn in self._stage_buttons.items():
            btn.setChecked(k == stage_key)

        if self.start_time:
            self._setup_machine_cards_for_stage(stage_key)
            val = self.timeline_slider.value()
            target_time = self.start_time + timedelta(minutes=val)
            state = self._compute_state_at(target_time)
            self._update_display(target_time, state)

    # ════════════════════════════════════════════════
    # PRIORITY LOOKUP (slider zamanına göre)
    # ════════════════════════════════════════════════
    def _entry_history_key(self, entry) -> str:
        jid = getattr(entry, "job_id", "") or ""
        if "||Ek Üretim" in jid: tag = "Ek Üretim"
        elif "||Gelecek Hafta" in jid: tag = "Gelecek Hafta"
        elif "||Excel" in jid: tag = "Excel"
        elif "||Bu Hafta" in jid: tag = "Bu Hafta"
        else: tag = ""
        return f"{entry.product_type}||{tag}"

    def _priority_at(self, entry, target_time: datetime) -> float:
        """Slider zamanı ≤ olan en son snapshot'ı dön. Yoksa entry.priority_level fallback."""
        history = getattr(self, "priority_history", {}).get(self._entry_history_key(entry))
        if not history:
            return entry.priority_level
        # Geriden ilk t ≤ target_time'ı bul
        result = history[0][1]
        for t, score in history:
            if t <= target_time:
                result = score
            else:
                break
        return result

    # ════════════════════════════════════════════════
    # SLIDER KONTROLÜ
    # ════════════════════════════════════════════════
    def _on_slider_changed(self, value):
        if not self.start_time:
            return
        t = self.start_time + timedelta(minutes=value)
        state = self._compute_state_at(t)
        self._update_display(t, state)

    def _go_start(self):   self.timeline_slider.setValue(0)
    def _go_end(self):     self.timeline_slider.setValue(self.timeline_slider.maximum())
    def _step_back_1h(self): self.timeline_slider.setValue(max(0, self.timeline_slider.value() - 60))
    def _step_back_10m(self):self.timeline_slider.setValue(max(0, self.timeline_slider.value() - 10))
    def _step_fwd_10m(self): self.timeline_slider.setValue(min(self.timeline_slider.maximum(), self.timeline_slider.value() + 10))
    def _step_fwd_1h(self):  self.timeline_slider.setValue(min(self.timeline_slider.maximum(), self.timeline_slider.value() + 60))

    # ════════════════════════════════════════════════
    # DURUM HESAPLAMA
    # ════════════════════════════════════════════════
    def _compute_state_at(self, target_time: datetime) -> dict:
        # Makine durumları
        machines = {}
        for mname in ALL_MACHINES:
            entries = self.entries_by_machine.get(mname, [])
            machines[mname] = self._find_machine_state(entries, target_time)

        # Tamamlanan ürünler
        completed: Dict[str, int] = {}
        for end_time, ptype in self.completion_events:
            if end_time <= target_time:
                completed[ptype] = completed.get(ptype, 0) + 1
            else:
                break

        # Job durumları
        in_machine: Dict[str, int] = {}
        in_machine_names: Dict[str, set] = {}
        waiting: Dict[str, int] = {}
        for job_id, entries in self.entries_by_job.items():
            ptype = self.job_product_type.get(job_id)
            if not ptype:
                continue
            completed_step = None
            is_in_machine = False
            cur_machine = ""
            for entry in entries:
                if entry.start_time <= target_time < entry.end_time:
                    is_in_machine = True
                    cur_machine = entry.machine_name
                    break
                elif entry.end_time <= target_time:
                    completed_step = entry.step_name
            if is_in_machine:
                in_machine[ptype] = in_machine.get(ptype, 0) + 1
                if ptype not in in_machine_names:
                    in_machine_names[ptype] = set()
                in_machine_names[ptype].add(cur_machine)
            elif completed_step is not None and completed_step != "atp_stp":
                waiting[ptype] = waiting.get(ptype, 0) + 1
            elif completed_step is None and entries and entries[0].start_time > target_time:
                waiting[ptype] = waiting.get(ptype, 0) + 1

        # Kuyruk verisi seçili istasyon için
        queue_data = self._compute_queue_for_stage(self._selected_stage, target_time)

        total_setup = sum(
            e.setup_time for e in self.schedule
            if e.start_time <= target_time and e.setup_time > 0
        )
        active_count = sum(
            1 for m in machines.values()
            if m["status"] in ("working", "setup", "initial_setup", "daily_setup")
        )
        elapsed = (target_time - self.start_time).total_seconds() / 3600.0

        return {
            "machines": machines,
            "completed": completed,
            "in_machine": in_machine,
            "in_machine_names": in_machine_names,
            "waiting": waiting,
            "queue_data": queue_data,
            "total_setup": total_setup,
            "active_count": active_count,
            "elapsed_hours": elapsed,
            "total_completed": sum(completed.values()),
        }

    def _find_machine_state(self, entries: list, target_time: datetime) -> dict:
        for i, entry in enumerate(entries):
            if entry.start_time <= target_time < entry.end_time:
                setup_end = (
                    entry.start_time + timedelta(hours=entry.setup_time)
                    if entry.setup_time > 0 else entry.start_time
                )
                if entry.setup_time > 0 and target_time < setup_end:
                    init_t = getattr(entry, 'initial_setup_time', 0.0)
                    trans_t = getattr(entry, 'transition_setup_time', 0.0)
                    # Hangi setup tipinde olduğumuzu belirle
                    init_end = entry.start_time + timedelta(hours=init_t) if init_t > 0 else entry.start_time
                    if init_t > 0 and target_time < init_end:
                        status = "initial_setup"
                    elif trans_t > 0:
                        status = "setup"
                    else:
                        status = "initial_setup" if init_t > 0 else "setup"
                    # Önceki entry'den "nereden" geldiğini bul
                    prev_entry = entries[i - 1] if i > 0 else None
                    from_product = prev_entry.product_type if prev_entry else None
                    from_product_name = prev_entry.product_name if prev_entry else None
                    return {
                        "status": status,
                        "product_type": entry.product_type,
                        "product_name": entry.product_name,
                        "step_name": entry.step_name,
                        "group_size": entry.group_size,
                        "start_time": entry.start_time,
                        "end_time": entry.end_time,
                        "setup_time": entry.setup_time,
                        "initial_setup_time": init_t,
                        "transition_setup_time": trans_t,
                        "from_product": from_product,
                        "from_product_name": from_product_name,
                    }
                return {
                    "status": "working",
                    "product_type": entry.product_type,
                    "product_name": entry.product_name,
                    "step_name": entry.step_name,
                    "group_size": entry.group_size,
                    "start_time": entry.start_time,
                    "end_time": entry.end_time,
                    "setup_time": entry.setup_time,
                }
        last = next((e for e in reversed(entries) if e.end_time <= target_time), None)
        return {
            "status": "idle",
            "last_product": last.product_type if last else None,
            "last_product_name": last.product_name if last else None,
            "idle_since": last.end_time if last else None,
        }

    def _compute_queue_for_stage(self, stage_key: str, target_time: datetime) -> dict:
        """Seçili istasyon için kuyruk durumunu hesapla (Aynı ürünleri gruplayarak)."""
        stage = STAGE_BY_KEY[stage_key]
        prev_key = stage["prev"]

        stage_entries = self.entries_by_step.get(stage_key, [])

        currently: list = []   # (entry, remaining_timedelta)
        raw_queue: list = []   # {entry, is_ready, status_text, time_until}

        for entry in stage_entries:
            if entry.start_time <= target_time < entry.end_time:
                remaining = entry.end_time - target_time
                currently.append((entry, remaining))
            elif entry.start_time > target_time:
                # Önceki adım kontrolü
                if prev_key is None:
                    is_ready = True
                    status_text = "⏳ Sırada bekliyor"
                else:
                    job_entries = self.entries_by_job.get(entry.job_id, [])
                    prev_entry = next(
                        (e for e in job_entries if e.step_name == prev_key), None
                    )
                    if prev_entry and prev_entry.end_time <= target_time:
                        is_ready = True
                        status_text = "⏳ Sırada bekliyor"
                    elif prev_entry:
                        is_ready = False
                        prev_lbl = STEP_LABELS.get(prev_key, prev_key)
                        end_time_str = prev_entry.end_time.strftime('%H:%M')
                        status_text = f"⏳ Geliş: {end_time_str} ({prev_lbl})"
                    else:
                        is_ready = False
                        status_text = "Önceki adımda"

                raw_queue.append({
                    "entry": entry,
                    "is_ready": is_ready,
                    "status_text": status_text,
                    "time_until": entry.start_time - target_time,
                })

        def _extract_tag(entry) -> str:
            """job_id'den hafta etiketini çıkar."""
            jid = getattr(entry, "job_id", "") or ""
            return jid.split("||", 1)[-1] if "||" in jid else ""

        # Ortak MockEntry Sınıfı
        class MockEntry:
            def __init__(self, d):
                self.product_type = d["product_type"]
                self.product_name = d.get("product_name", "") # Yeni alan
                self.group_size = d["total_qty"]
                self.priority_level = d["max_prio"]
                self.start_time = d["earliest_start"]
                self.end_time = d["latest_end"]
                self.setup_time = d["total_setup"]
                # QueueItemRow'un week badge gösterebilmesi için job_id formatını koru
                tag = d.get("job_tag", "")
                self.job_id = f"_group||{tag}" if tag else "_group"
                if len(d["machines"]) > 1:
                    self.machine_name = f"{len(d['machines'])} Mak"
                else:
                    self.machine_name = list(d["machines"])[0]

        # --- ŞU AN İŞLENENLERİ GRUPLA (ürün adı + hafta etiketine göre ayrı tut) ---
        grouped_curr = {}
        curr_order = []
        for e, remaining in currently:
            tag = _extract_tag(e)
            key = (e.product_type, e.product_name, tag)
            prio_now = self._priority_at(e, target_time)
            if key not in grouped_curr:
                curr_order.append(key)
                grouped_curr[key] = {
                    "product_type": e.product_type,
                    "product_name": e.product_name,
                    "job_tag": tag,
                    "total_qty": 1,
                    "max_prio": prio_now,
                    "min_remaining": remaining,
                    "earliest_start": e.start_time,
                    "latest_end": e.end_time,
                    "batch_count": 1,
                    "machines": {e.machine_name},
                    "total_setup": e.setup_time
                }
            else:
                g = grouped_curr[key]
                g["total_qty"] += 1
                g["max_prio"] = max(g["max_prio"], prio_now)
                g["min_remaining"] = min(g["min_remaining"], remaining)
                g["earliest_start"] = min(g["earliest_start"], e.start_time)
                g["latest_end"] = max(g["latest_end"], e.end_time)
                g["batch_count"] += 1
                g["machines"].add(e.machine_name)
                g["total_setup"] += e.setup_time

        grouped_currently = []
        for key in curr_order:
            g = grouped_curr[key]
            grouped_currently.append((MockEntry(g), g["min_remaining"]))

        # --- KUYRUĞU GRUPLA (ürün adı + hafta etiketi farklıysa ayrı satır göster) ---
        grouped_data = {}
        queue_order = []

        # Queue item'ları için: bu istasyondaki şu anki batch'in BİTİŞ zamanına göre lookup
        # (= "current batch finishes, recalc happens, here's the new state for everyone")
        # Böylece queue'daki K20, currently işlenen K20'den farklı (post-batch) priority alır
        current_end = max((e.end_time for e, _ in currently), default=target_time)

        for item in raw_queue:
            e = item["entry"]
            tag = _extract_tag(e)
            key = (e.product_type, e.product_name, item["is_ready"], item["status_text"], tag)
            prio_now = self._priority_at(e, current_end)

            if key not in grouped_data:
                queue_order.append(key)
                grouped_data[key] = {
                    "product_type": e.product_type,
                    "product_name": e.product_name,
                    "job_tag": tag,
                    "is_ready": item["is_ready"],
                    "status_text": item["status_text"],
                    "total_qty": 1,
                    "max_prio": prio_now,
                    "min_time_until": item["time_until"],
                    "earliest_start": e.start_time,
                    "latest_end": e.end_time,
                    "batch_count": 1,
                    "machines": {e.machine_name},
                    "total_setup": e.setup_time
                }
            else:
                g = grouped_data[key]
                g["total_qty"] += 1
                g["max_prio"] = max(g["max_prio"], prio_now)
                g["min_time_until"] = min(g["min_time_until"], item["time_until"])
                g["earliest_start"] = min(g["earliest_start"], e.start_time)
                g["latest_end"] = max(g["latest_end"], e.end_time)
                g["batch_count"] += 1
                g["machines"].add(e.machine_name)
                g["total_setup"] += e.setup_time

        queue = []
        for key in queue_order:
            g = grouped_data[key]
            queue.append({
                "entry": MockEntry(g),
                "is_ready": g["is_ready"],
                "status_text": g["status_text"],
                "time_until": g["min_time_until"],
                "is_grouped": g["batch_count"] > 1
            })

        ready_count = sum(1 for q in raw_queue if q["is_ready"]) # Özet için gerçek rakam kalsın

        return {
            "stage": stage,
            "currently": grouped_currently,
            "real_currently_count": len(currently),
            "queue": queue,
            "ready_count": ready_count,
            "real_queue_count": len(raw_queue)
        }

    # ════════════════════════════════════════════════
    # GÖRSEL GÜNCELLEME
    # ════════════════════════════════════════════════
    def _update_display(self, target_time: datetime, state: dict):
        # Zaman göstergesi
        day_names = ["Pzt", "Sal", "Çar", "Per", "Cum", "Cmt", "Paz"]
        day_name = day_names[target_time.weekday()]
        self.time_display.setText(
            f"{target_time.strftime('%d.%m.%Y')} {day_name}  {target_time.strftime('%H:%M')}"
        )
        h = state["elapsed_hours"]
        d, rem_h = divmod(int(h), 24)
        rem_m = int((h % 1) * 60)
        self.elapsed_label.setText(f"Geçen: {d}g {rem_h}s {rem_m}dk")

        # Metrikler
        self.metric_labels["elapsed"].setText(f"{d}g {rem_h}s")
        total_target = sum(self.targets.values())
        self.metric_labels["completed"].setText(f"{state['total_completed']} / {total_target}")
        self.metric_labels["setup_total"].setText(f"{state['total_setup']:.1f} saat")
        self.metric_labels["active_machines"].setText(f"{state['active_count']} / {len(ALL_MACHINES)}")

        # Sol panel: seçili istasyon makine kartları
        machines = state["machines"]
        for mname, card in self._machine_cards.items():
            ms = machines.get(mname, {"status": "idle"})
            if ms["status"] == "working":
                card.set_working(
                    ms["product_type"], ms["product_name"], ms["step_name"],
                    ms["start_time"], ms["end_time"], ms["group_size"]
                )
            elif ms["status"] in ("setup", "initial_setup", "daily_setup"):
                card.set_setup(
                    ms.get("product_type"), ms.get("product_name"), ms.get("setup_time", 0),
                    is_initial=(ms["status"] == "initial_setup"),
                    is_transition=(ms["status"] == "setup"),
                    from_product=ms.get("from_product"),
                    from_product_name=ms.get("from_product_name"),
                    initial_setup_time=ms.get("initial_setup_time", 0.0),
                    transition_setup_time=ms.get("transition_setup_time", 0.0),
                )
            else:
                l_name = ms.get("last_product_name", "")
                card.set_idle(
                    f"{ms.get('last_product')} - {l_name}" if l_name else ms.get("last_product"),
                    ms.get("idle_since")
                )

        # Kuyruk paneli
        self._update_queue_panel(state["queue_data"], target_time)

        # Karar günlüğü paneli
        self._update_log_panel(target_time)

        # Genel bakış kartları
        for mname, card in self._overview_cards.items():
            ms = machines.get(mname, {"status": "idle"})
            card.update_state(ms)

    def _update_queue_panel(self, queue_data: dict, target_time: datetime):
        """Kuyruk listesini temizle ve yeniden oluştur."""
        # Eski satırları temizle
        while self.queue_inner_layout.count():
            item = self.queue_inner_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        stage = queue_data["stage"]
        currently = queue_data["currently"]
        queue = queue_data["queue"]
        ready_count = queue_data["ready_count"]

        # Başlık ve özet
        self.queue_title.setText(f"{stage['label']} — Bekleme Kuyruğu")

        total_raw = queue_data.get("real_queue_count", len(queue))
        total_unique = len(queue)
        
        if not currently and not queue:
            self.queue_summary.setText("Bu istasyonda henüz veya artık iş yok.")
            self.queue_empty_lbl = QLabel("Bu istasyonda planlanmış iş bulunamadı.")
            self.queue_empty_lbl.setFont(QFont("Segoe UI", 11))
            self.queue_empty_lbl.setStyleSheet("color: #94A3B8; border: none;")
            self.queue_empty_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self.queue_inner_layout.addWidget(self.queue_empty_lbl)
            self.queue_inner_layout.addStretch()
            return

        parts = []
        if currently:
            total_curr_qty = sum(item[0].group_size for item in currently)
            parts.append(f"Şu an işleniyor: Toplam {total_curr_qty} adet")
        if total_unique > 0:
            parts.append(f"Bekleyenler: {ready_count} hazır")
            not_ready_cnt = sum(1 for q in queue if not q["is_ready"])
            if not_ready_cnt > 0:
                parts.append(f"Gelecek: {not_ready_cnt} grup")
        self.queue_summary.setText("  ·  ".join(parts))

        # Şu an işlenen satırlar
        if currently:
            section_lbl = QLabel("ŞU AN İŞLENİYOR")
            section_lbl.setFont(QFont("Segoe UI", 10, QFont.Weight.Bold))
            section_lbl.setStyleSheet("color: #16A34A; border: none; padding-top: 4px;")
            self.queue_inner_layout.addWidget(section_lbl)

            for entry, remaining in currently:
                row = QueueItemRow(0, entry, is_current=True,
                                   is_ready=True, status_text="",
                                   time_until=remaining)
                self.queue_inner_layout.addWidget(row)

        # İçerikleri ayır (Assembly harici)
        ready_queue = [q for q in queue if q["is_ready"]]
        not_ready_queue = [q for q in queue if not q["is_ready"]]

        # Kuyruk satırları (Hazır / Bekleyen)
        if ready_queue:
            section_lbl2 = QLabel("SIRADAKİLER (HAZIR)")
            section_lbl2.setFont(QFont("Segoe UI", 10, QFont.Weight.Bold))
            section_lbl2.setStyleSheet("color: #374151; border: none; padding-top: 6px;")
            self.queue_inner_layout.addWidget(section_lbl2)

            for rank, item in enumerate(ready_queue, start=1):
                row = QueueItemRow(
                    rank, item["entry"],
                    is_current=False,
                    is_ready=True,
                    status_text=item["status_text"],
                    time_until=item["time_until"],
                )
                self.queue_inner_layout.addWidget(row)
        
        # Gelecek satırları (Henüz o istasyona ulaşmamış)
        if not_ready_queue:
            section_lbl3 = QLabel("GELECEK İŞLER")
            section_lbl3.setFont(QFont("Segoe UI", 10, QFont.Weight.Bold))
            section_lbl3.setStyleSheet("color: #8B5CF6; border: none; padding-top: 10px;")
            self.queue_inner_layout.addWidget(section_lbl3)

            for rank, item in enumerate(not_ready_queue, start=1):
                row = QueueItemRow(
                    rank, item["entry"],
                    is_current=False,
                    is_ready=False,
                    status_text=item["status_text"],
                    time_until=item["time_until"],
                )
                self.queue_inner_layout.addWidget(row)

        self.queue_inner_layout.addStretch()


# ─── OverviewCard (kompakt genel bakış) ──────────────────────────────────────
class OverviewCard(QFrame):
    STATUS_META = {
        "working":       ("#22C55E", "#F0FDF4", "🟢"),
        "setup":         ("#F59E0B", "#FFFBEB", "🟡"),
        "daily_setup":   ("#3B82F6", "#EFF6FF", "🔵"),
        "initial_setup": ("#3B82F6", "#EFF6FF", "🔵"),
        "idle":          ("#D1D5DB", "#F9FAFB", "⚪"),
    }

    def __init__(self, machine_name: str, parent=None):
        super().__init__(parent)
        self.machine_name = machine_name
        self.setFixedHeight(110)
        self.setMinimumWidth(125)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(12, 10, 12, 10)
        lay.setSpacing(4)

        top = QHBoxLayout()
        self.icon_lbl = QLabel("⚪")
        self.icon_lbl.setFont(QFont("Segoe UI", 16))
        self.name_lbl = QLabel(MACHINE_LABELS.get(machine_name, machine_name))
        self.name_lbl.setFont(QFont("Segoe UI", 14, QFont.Weight.Bold))
        top.addWidget(self.icon_lbl)
        top.addWidget(self.name_lbl)
        top.addStretch()
        lay.addLayout(top)

        self.product_lbl = QLabel("—")
        self.product_lbl.setFont(QFont("Segoe UI", 12, QFont.Weight.Bold))
        self.product_lbl.setStyleSheet("color: #374151;")
        lay.addWidget(self.product_lbl)

        self.status_lbl = QLabel("BOŞ")
        self.status_lbl.setFont(QFont("Segoe UI", 10, QFont.Weight.Bold))
        self.status_lbl.setStyleSheet("color: #6B7280;")
        lay.addWidget(self.status_lbl)

        self._apply("idle")

    def _apply(self, status: str):
        border, bg, icon = self.STATUS_META.get(status, self.STATUS_META["idle"])
        self.setStyleSheet(f"""
            OverviewCard {{
                background: {bg};
                border: 1.5px solid {border};
                border-radius: 8px;
            }}
        """)
        self.icon_lbl.setText(icon)

    def update_state(self, ms: dict):
        status = ms.get("status", "idle")
        self._apply(status)
        if status == "working":
            step_nm = ms.get("step_name", "")
            step_str = step_nm.upper()
            if step_nm == "atp_stp": step_str = "ATP+STP"
            
            self.product_lbl.setText(f"{ms.get('product_type', '')} ({step_str})")
            self.status_lbl.setText("Üretimde")
        elif status in ("setup", "daily_setup", "initial_setup"):
            step_nm = ms.get("step_name", "")
            step_str = step_nm.upper() if step_nm else ""
            if step_nm == "atp_stp": step_str = "ATP+STP"

            p_text = f"{ms.get('product_type', '')}"
            if step_str: p_text += f" ({step_str})"
            self.product_lbl.setText(p_text)
            self.status_lbl.setText("İlk Kullanım Setup" if status == "initial_setup" else "Setup")
        else:
            self.product_lbl.setText(ms.get("last_product") or "—")
            self.status_lbl.setText("Boş")
