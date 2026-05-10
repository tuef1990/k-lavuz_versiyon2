"""
Adım Test Simülatörü — Belirli bir üretim adımını izole olarak test eder.
"""

from datetime import datetime, timedelta
from typing import List, Dict, Optional, Any
import uuid

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QFrame, QScrollArea, QCheckBox, QLineEdit, QComboBox,
    QDoubleSpinBox, QSpinBox, QSizePolicy, QMessageBox,
)
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QFont

from models.job import Job
from models.setup_matrix import SetupMatrix
from core.models import Product
from algorithms.machine_pool import SharedMachinePool
from algorithms.step_planners.dkk_atp_planner import DkkAtpPlanner
from algorithms.step_planners.dkk_atp_planner_v2 import DkkAtpPlannerV2
from algorithms.step_planners.rvb_planner import RvbPlanner
from algorithms.step_planners.rvb_planner_v2 import RvbPlannerV2
from algorithms.step_planners.assembly_planner import AssemblyPlanner
from algorithms.step_planners.ftp_planner import FtpPlanner
from algorithms.step_planners.bn_planner import BnPlanner


# ── Renkler ────────────────────────────────────────────────────────────────────
C = {
    "bg":       "#F8FAFC",
    "white":    "#FFFFFF",
    "border":   "#E2E8F0",
    "border2":  "#CBD5E1",
    "text":     "#1E293B",
    "text2":    "#475569",
    "text3":    "#94A3B8",
    "blue":     "#1E40AF",
    "blue_l":   "#EFF6FF",
    "blue_m":   "#BFDBFE",
    "blue2":    "#3B82F6",
    "green":    "#059669",
    "green_l":  "#ECFDF5",
    "green_b":  "#6EE7B7",
    "red":      "#DC2626",
    "red_l":    "#FEF2F2",
    "red_b":    "#FCA5A5",
    "amber":    "#D97706",
    "amber_l":  "#FFFBEB",
    "purple":   "#7C3AED",
    "purple_l": "#F5F3FF",
    "cyan":     "#0891B2",
    "cyan_l":   "#ECFEFF",
}

# ── Stiller ────────────────────────────────────────────────────────────────────
_INPUT = f"""
    QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox {{
        background: {C['white']}; border: 1.5px solid {C['border2']};
        border-radius: 6px; padding: 5px 8px;
        font-size: 12px; color: {C['text']}; min-height: 28px;
    }}
    QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus {{
        border-color: {C['blue2']};
    }}
"""

_BTN_ADD = f"""QPushButton {{
    background: {C['blue_l']}; color: {C['blue']};
    border: 1.5px solid {C['blue_m']}; border-radius: 6px;
    font-size: 12px; font-weight: 600; padding: 5px 14px;
}}
QPushButton:hover {{ background: {C['blue_m']}; }}"""

_BTN_RUN = f"""QPushButton {{
    background: {C['green']}; color: white;
    border: none; border-radius: 8px;
    font-size: 14px; font-weight: 700; padding: 12px 48px;
}}
QPushButton:hover {{ background: #047857; }}
QPushButton:disabled {{ background: {C['text3']}; }}"""

_BTN_DEL = f"""QPushButton {{
    background: {C['red_l']}; color: {C['red']};
    border: 1px solid {C['red_b']}; border-radius: 5px;
    font-size: 12px; font-weight: 700;
}}
QPushButton:hover {{ background: #FEE2E2; }}"""


# ── Adım tanımları ─────────────────────────────────────────────────────────────
_ALL_STEP_LABELS = ["Assembly", "FTP", "B/N", "DKK", "RVB", "ATP+STP"]
_SUBSTEP_MAP = {
    "DKK": "dkk", "ATP+STP": "atp_stp", "RVB": "rvb",
    "Assembly": "assembly", "FTP": "ftp", "B/N": "bn",
}

STEP_CONFIGS = {
    "dkk_atp":  {"label": "DKK / ATP+STP", "substeps": ["dkk", "atp_stp"],
                 "substep_labels": ["DKK", "ATP+STP"],
                 "machines": ["M1", "M2", "M3", "M4"], "multi_machine": True},
    "rvb":      {"label": "RVB",      "substeps": ["rvb"],
                 "substep_labels": ["RVB"],      "machines": ["RVB"],      "multi_machine": False},
    "assembly": {"label": "Assembly", "substeps": ["assembly"],
                 "substep_labels": ["Assembly"], "machines": ["Assembly"], "multi_machine": False},
    "ftp":      {"label": "FTP",      "substeps": ["ftp"],
                 "substep_labels": ["FTP"],      "machines": ["FTP"],      "multi_machine": False},
    "bn":       {"label": "B/N",      "substeps": ["bn"],
                 "substep_labels": ["B/N"],      "machines": ["B/N"],      "multi_machine": False},
}

# Her seçili adım için "Gelmekte Olan Ürünler" combo'sunda gösterilecek upstream adım listesi
# Pipeline sırası: Assembly → FTP → B/N → DKK → RVB → ATP+STP
UPSTREAM_STEPS = {
    "assembly": [],  # ilk adım — gelmekte olan ürün yok
    "ftp":      ["Assembly"],
    "bn":       ["Assembly", "FTP"],
    "dkk_atp":  ["Assembly", "FTP", "B/N", "RVB"],  # DKK B/N'den, ATP+STP RVB'den
    "rvb":      ["Assembly", "FTP", "B/N", "DKK"],
}

# Her adım için default upstream (immediate previous step)
DEFAULT_UPSTREAM = {
    "ftp":      "Assembly",
    "bn":       "FTP",
    "dkk_atp":  "B/N",   # DKK için B/N; kullanıcı ATP+STP isterse RVB'ye değiştirebilir
    "rvb":      "DKK",
}


# ── Yardımcılar ────────────────────────────────────────────────────────────────
def _lbl(text, size=12, bold=False, color=None):
    w = QLabel(text)
    w.setStyleSheet(
        f"color:{color or C['text2']}; font-size:{size}px;"
        f" font-weight:{'700' if bold else '400'}; border:none; background:transparent;"
    )
    return w

def _sep():
    f = QFrame()
    f.setFrameShape(QFrame.Shape.HLine)
    f.setFixedHeight(1)
    f.setStyleSheet(f"background:{C['border']}; border:none;")
    return f

def _card():
    f = QFrame()
    f.setStyleSheet(
        f"QFrame{{background:{C['white']}; border:1.5px solid {C['border']}; border-radius:12px;}}"
    )
    return f


# ── Logger ─────────────────────────────────────────────────────────────────────
class _Logger:
    def __init__(self):
        self.logs: List[Dict[str, Any]] = []

    def add_log(self, time, action, details, step):
        self.logs.append({"timestamp": time, "action": action, "details": details, "step": step})


DIGER_LABEL = "Diğer"


def _open_product_dialog(parent) -> Optional[str]:
    """Yeni ürün için iki ayrı input gösteren dialog. 'Tip / İsim' string döner ya da None."""
    from PyQt6.QtWidgets import QDialog, QFormLayout, QLineEdit, QDialogButtonBox
    dlg = QDialog(parent)
    dlg.setWindowTitle("Yeni Ürün")
    dlg.setMinimumWidth(320)
    form = QFormLayout(dlg)
    t_in = QLineEdit()
    t_in.setPlaceholderText("örn K11")
    n_in = QLineEdit()
    n_in.setPlaceholderText("örn Ürün A")
    form.addRow("Ürün Tipi:", t_in)
    form.addRow("Ürün Adı:", n_in)
    btn_box = QDialogButtonBox(
        QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
    )
    btn_box.accepted.connect(dlg.accept)
    btn_box.rejected.connect(dlg.reject)
    form.addRow(btn_box)
    if dlg.exec() == QDialog.DialogCode.Accepted:
        t, n = t_in.text().strip(), n_in.text().strip()
        if t and n:
            return f"{t} / {n}"
    return None


def _attach_product_picker(combo: 'QComboBox', parent_widget):
    """Combo'ya 'Diğer...' item'ı ekler ve seçildiğinde dialog açan handler bağlar."""
    if combo.findText(DIGER_LABEL) < 0:
        combo.addItem(DIGER_LABEL)

    def _on_activated(idx: int):
        if combo.itemText(idx) != DIGER_LABEL:
            return
        result = _open_product_dialog(parent_widget)
        if result:
            pos = combo.count() - 1  # "Diğer..."dan ÖNCE ekle
            existing = combo.findText(result)
            if existing >= 0:
                combo.setCurrentIndex(existing)
            else:
                combo.insertItem(pos, result)
                combo.setCurrentIndex(pos)
        else:
            combo.setCurrentIndex(0)

    combo.activated.connect(_on_activated)


def _open_type_dialog(parent) -> Optional[str]:
    """Yeni ürün tipi için tek input dialog (örn 'K99'). String döner ya da None."""
    from PyQt6.QtWidgets import QDialog, QFormLayout, QLineEdit, QDialogButtonBox
    dlg = QDialog(parent)
    dlg.setWindowTitle("Yeni Ürün Tipi")
    dlg.setMinimumWidth(280)
    form = QFormLayout(dlg)
    t_in = QLineEdit()
    t_in.setPlaceholderText("örn K99")
    form.addRow("Ürün Tipi:", t_in)
    btn_box = QDialogButtonBox(
        QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
    )
    btn_box.accepted.connect(dlg.accept)
    btn_box.rejected.connect(dlg.reject)
    form.addRow(btn_box)
    if dlg.exec() == QDialog.DialogCode.Accepted:
        t = t_in.text().strip()
        if t:
            return t
    return None


def _attach_type_picker(combo: 'QComboBox', parent_widget):
    """Tip combo'suna 'Diğer...' ekler; seçildiğinde yeni tip girme dialog'u açar."""
    if combo.findText(DIGER_LABEL) < 0:
        combo.addItem(DIGER_LABEL)

    def _on_activated(idx: int):
        if combo.itemText(idx) != DIGER_LABEL:
            return
        result = _open_type_dialog(parent_widget)
        if result:
            pos = combo.count() - 1  # "Diğer..."dan önce ekle
            existing = combo.findText(result)
            if existing >= 0:
                combo.setCurrentIndex(existing)
            else:
                combo.insertItem(pos, result)
                combo.setCurrentIndex(pos)
        else:
            combo.setCurrentIndex(0)

    combo.activated.connect(_on_activated)


# ── MachineConfigCard ──────────────────────────────────────────────────────────
_STATE_LABELS = ["İlk Kullanım", "Kullanıldı, Boş", "Şu An Meşgul"]
_STATE_ICONS  = ["🔧", "✅", "⚙️"]
_STATE_DESC   = [
    "+2 saatlik günlük setup eklenir.",
    "Son ürünü girerek setup hesabı yapılır.",
    "Kalan süre dolana kadar atama yapılmaz.",
]

class MachineConfigCard(QFrame):
    """Makine durumu: İlk Kullanım / Kullanıldı / Meşgul."""

    def __init__(self, machine_name: str,
                 type_options: Optional[List[str]] = None,
                 type_to_name: Optional[Dict[str, str]] = None,
                 show_substep: bool = False,
                 parent=None):
        super().__init__(parent)
        self.machine_name = machine_name
        self._type_options = type_options or []
        self._type_to_name = dict(type_to_name or {})
        self._show_substep = show_substep
        self.setMinimumWidth(240)
        self.setMaximumWidth(320)
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Minimum)
        self.setStyleSheet(
            f"MachineConfigCard{{background:{C['white']};border:1.5px solid {C['border']};"
            "border-radius:12px;}}"
        )

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ── Başlık bandı (renk durumla değişiyor — pastel arka plan + koyu metin)
        self._hdr = QWidget()
        self._hdr.setFixedHeight(44)
        hl = QHBoxLayout(self._hdr)
        hl.setContentsMargins(16, 0, 16, 0)
        self._hdr_name = QLabel(machine_name)
        self._hdr_name.setFont(QFont("Segoe UI", 15, QFont.Weight.Bold))
        hl.addWidget(self._hdr_name)
        hl.addStretch()
        self._hdr_status = QLabel("")
        self._hdr_status.setStyleSheet("background:transparent;border:none;font-size:11px;font-weight:700;")
        hl.addWidget(self._hdr_status)
        root.addWidget(self._hdr)

        # ── Gövde
        body = QWidget()
        body.setStyleSheet("background:transparent;")
        bl = QVBoxLayout(body)
        bl.setContentsMargins(16, 14, 16, 16)
        bl.setSpacing(12)
        root.addWidget(body)

        # Durum combo
        lbl_durum = QLabel("Durum")
        lbl_durum.setStyleSheet(
            f"color:{C['text']};font-size:12px;font-weight:700;border:none;background:transparent;"
        )
        bl.addWidget(lbl_durum)

        self._combo = QComboBox()
        for icon, label in zip(_STATE_ICONS, _STATE_LABELS):
            self._combo.addItem(f"{icon}  {label}")
        self._combo.setStyleSheet(f"""
            QComboBox {{
                background:{C['white']};border:2px solid {C['blue_m']};border-radius:8px;
                padding:7px 12px;font-size:13px;font-weight:600;color:{C['text']};
                min-height:36px;
            }}
            QComboBox:hover {{ border-color:{C['blue2']}; }}
            QComboBox::drop-down {{ border:none; width:28px; }}
            QComboBox QAbstractItemView {{
                background:{C['white']};border:1.5px solid {C['border2']};
                border-radius:8px;selection-background-color:{C['blue_l']};
                selection-color:{C['blue']};font-size:13px;padding:4px;
            }}
        """)
        self._combo.currentIndexChanged.connect(self._on_changed)
        bl.addWidget(self._combo)

        # Açıklama etiketi
        self._desc_lbl = QLabel(_STATE_DESC[0])
        self._desc_lbl.setWordWrap(True)
        self._desc_lbl.setStyleSheet(
            f"color:{C['text3']};font-size:11px;border:none;background:transparent;"
        )
        bl.addWidget(self._desc_lbl)

        bl.addWidget(_sep())

        # ── "Kullanıldı" alanı: işlem türü (opsiyonel) + tip + manuel ad
        self._used_w = QWidget()
        self._used_w.setStyleSheet("background:transparent;")
        uw = QVBoxLayout(self._used_w)
        uw.setContentsMargins(0, 0, 0, 0)
        uw.setSpacing(6)
        lbl_up = QLabel("Son Üretilen Ürün")
        lbl_up.setStyleSheet(
            f"color:{C['text']};font-size:12px;font-weight:700;border:none;background:transparent;"
        )
        uw.addWidget(lbl_up)

        if show_substep:
            self._used_substep = QComboBox()
            self._used_substep.addItems(["DKK", "ATP+STP"])
            self._used_substep.setStyleSheet(_INPUT)
            uw.addWidget(self._used_substep)

        self._used_type = QComboBox()
        for t in self._type_options:
            self._used_type.addItem(t)
        _attach_type_picker(self._used_type, self)
        self._used_type.setStyleSheet(_INPUT)
        uw.addWidget(self._used_type)

        self._used_name = QLineEdit()
        self._used_name.setPlaceholderText("Ürün adı (birden fazla ise virgülle ayır)")
        self._used_name.setStyleSheet(_INPUT)
        uw.addWidget(self._used_name)

        self._used_type.currentTextChanged.connect(self._on_used_type_changed)
        self._on_used_type_changed(self._used_type.currentText())

        bl.addWidget(self._used_w)
        self._used_w.hide()

        # ── "Meşgul" alanı: işlem türü (opsiyonel) + tip + manuel ad + kalan süre
        self._busy_w = QWidget()
        self._busy_w.setStyleSheet("background:transparent;")
        bw = QVBoxLayout(self._busy_w)
        bw.setContentsMargins(0, 0, 0, 0)
        bw.setSpacing(6)
        lbl_bp = QLabel("Üretilen Ürün")
        lbl_bp.setStyleSheet(
            f"color:{C['text']};font-size:12px;font-weight:700;border:none;background:transparent;"
        )
        bw.addWidget(lbl_bp)

        if show_substep:
            self._busy_substep = QComboBox()
            self._busy_substep.addItems(["DKK", "ATP+STP"])
            self._busy_substep.setStyleSheet(_INPUT)
            bw.addWidget(self._busy_substep)

        self._busy_type = QComboBox()
        for t in self._type_options:
            self._busy_type.addItem(t)
        _attach_type_picker(self._busy_type, self)
        self._busy_type.setStyleSheet(_INPUT)
        bw.addWidget(self._busy_type)

        self._busy_name = QLineEdit()
        self._busy_name.setPlaceholderText("Ürün adı (birden fazla ise virgülle ayır)")
        self._busy_name.setStyleSheet(_INPUT)
        bw.addWidget(self._busy_name)

        self._busy_type.currentTextChanged.connect(self._on_busy_type_changed)
        self._on_busy_type_changed(self._busy_type.currentText())

        lbl_bh = QLabel("Kalan Süre")
        lbl_bh.setStyleSheet(
            f"color:{C['text']};font-size:12px;font-weight:700;border:none;background:transparent;"
        )
        bw.addWidget(lbl_bh)
        self._busy_hours = QDoubleSpinBox()
        self._busy_hours.setRange(0.1, 72.0)
        self._busy_hours.setSingleStep(0.5)
        self._busy_hours.setDecimals(1)
        self._busy_hours.setValue(2.0)
        self._busy_hours.setSuffix("  saat")
        self._busy_hours.setStyleSheet(_INPUT)
        bw.addWidget(self._busy_hours)
        # Atama sonrası setup + process kırılımı (Çalıştır sonucu)
        self._setup_info_lbl = QLabel("")
        self._setup_info_lbl.setStyleSheet(
            f"color:{C['amber']};font-size:11px;font-weight:600;"
            "background:transparent;border:none;"
        )
        self._setup_info_lbl.setWordWrap(True)
        self._setup_info_lbl.hide()
        bw.addWidget(self._setup_info_lbl)
        bl.addWidget(self._busy_w)
        self._busy_w.hide()

        bl.addStretch()

        # İlk renk
        self._apply_header_color(0)

    # Durum bazlı renk paleti — simülasyon sayfasındaki gibi pastel
    # (border, bg, text) → light bg + dark text, colored border
    _HEADER_COLORS = {
        0: ("#3B82F6", "#EFF6FF", "#1E40AF", "🔵 İLK KULLANIM SETUP"),
        1: ("#D1D5DB", "#F9FAFB", "#6B7280", "⚪ HAZIR"),
        2: ("#22C55E", "#F0FDF4", "#166534", "🟢 ÜRETİMDE"),
    }

    def _apply_header_color(self, idx: int):
        border, bg, text, status_txt = self._HEADER_COLORS.get(idx, ("#D1D5DB", "#F9FAFB", "#6B7280", ""))
        self._hdr.setStyleSheet(
            f"QWidget{{background:{bg};border:none;border-bottom:2px solid {border};"
            "border-radius:11px 11px 0 0;}}"
        )
        self._hdr_name.setStyleSheet(f"color:{text};background:transparent;border:none;")
        self._hdr_status.setStyleSheet(
            f"color:{text};background:transparent;border:none;font-size:11px;font-weight:700;"
        )
        self._hdr_status.setText(status_txt)

    def _on_changed(self, idx: int):
        self._desc_lbl.setText(_STATE_DESC[idx])
        self._used_w.setVisible(idx == 1)
        self._busy_w.setVisible(idx == 2)
        self._apply_header_color(idx)
        if idx != 2:
            self._setup_info_lbl.hide()

    @staticmethod
    def _combo_set_value(combo, text: str):
        """Combo'da yoksa 'Diğer...'dan ÖNCE ekleyip seçer."""
        if not text:
            combo.setCurrentIndex(-1) if combo.count() == 0 else combo.setCurrentIndex(0)
            return
        idx = combo.findText(text)
        if idx >= 0:
            combo.setCurrentIndex(idx)
        else:
            diger_idx = combo.findText(DIGER_LABEL)
            pos = diger_idx if diger_idx >= 0 else combo.count()
            combo.insertItem(pos, text)
            combo.setCurrentIndex(pos)

    @staticmethod
    def _combo_value(combo) -> str:
        txt = combo.currentText().strip()
        return "" if txt == DIGER_LABEL else txt

    def _on_used_type_changed(self, ptype: str):
        self._used_name.setText(self._type_to_name.get(ptype, ""))

    def _on_busy_type_changed(self, ptype: str):
        self._busy_name.setText(self._type_to_name.get(ptype, ""))

    def _build_pid(self, ptype: str, name_text: str) -> Optional[str]:
        """Tip ve isim alanından canonical pid (ilk isim) üretir.
        Birden fazla isim virgülle ayrılmışsa ilkini canonical alır."""
        ptype = (ptype or "").strip()
        if not ptype:
            return None
        names = [n.strip() for n in (name_text or "").split(",") if n.strip()]
        first_name = names[0] if names else self._type_to_name.get(ptype, "")
        return f"{ptype} / {first_name}" if first_name else ptype

    def reset(self):
        """Makineyi İlk Kullanım durumuna sıfırla, ürün alanlarını temizle."""
        self._combo.setCurrentIndex(0)
        if self._used_type.count() > 0:
            self._used_type.setCurrentIndex(0)
        if self._busy_type.count() > 0:
            self._busy_type.setCurrentIndex(0)
        self._used_name.clear()
        self._busy_name.clear()
        self._busy_hours.setValue(2.0)

    def set_assigned(self, product_type: str, product_name: str,
                     setup_hours: float = 0.0, process_hours: float = 0.0,
                     substep: Optional[str] = None,
                     group_size: int = 0, wait_hours: float = 0.0):
        """Çalıştır sonucunda atanan ürünü göster (Meşgul durumuna geç).
        group_size: bu batch'te kaç adet üretiliyor.
        wait_hours: makinenin müsait olmasını beklemek için geçen süre (>0 ise gösterilir)."""
        # Tipi combo'da seç (yoksa Diğer...'dan önce ekle)
        if product_type:
            idx = self._busy_type.findText(product_type)
            if idx >= 0:
                self._busy_type.setCurrentIndex(idx)
            else:
                diger_idx = self._busy_type.findText(DIGER_LABEL)
                pos = diger_idx if diger_idx >= 0 else self._busy_type.count()
                self._busy_type.insertItem(pos, product_type)
                self._busy_type.setCurrentIndex(pos)
        if product_name is not None:
            self._busy_name.setText(product_name)
        if substep and self._show_substep:
            sub_label = "ATP+STP" if substep.lower() in ("atp_stp", "atp+stp") else "DKK"
            i = self._busy_substep.findText(sub_label)
            if i >= 0:
                self._busy_substep.setCurrentIndex(i)
        total = max(0.1, float(setup_hours) + float(process_hours))
        self._busy_hours.setValue(total)
        # Bilgi etiketi: adet + bekleme + setup + üretim
        parts = []
        if group_size and group_size > 0:
            parts.append(f"📦 {group_size} adet")
        if wait_hours and wait_hours > 0:
            parts.append(f"⏳ Bekleme: {wait_hours:.1f}h")
        if setup_hours > 0:
            parts.append(f"⏱ Setup: {setup_hours:.1f}h")
        parts.append(f"⚙️ Üretim: {process_hours:.1f}h")
        self._setup_info_lbl.setText("  ·  ".join(parts))
        self._setup_info_lbl.show()
        self._combo.setCurrentIndex(2)

    def get_config(self) -> dict:
        idx = self._combo.currentIndex()
        if idx == 0:
            return {"machine": self.machine_name, "last_product": None,
                    "needs_initial_setup": True,  "remaining_hours": 0.0,
                    "substep": None}
        if idx == 1:
            substep_val = (self._used_substep.currentText()
                           if self._show_substep else None)
            return {"machine": self.machine_name,
                    "last_product": self._build_pid(
                        self._used_type.currentText(), self._used_name.text()),
                    "needs_initial_setup": False, "remaining_hours": 0.0,
                    "substep": substep_val}
        substep_val = (self._busy_substep.currentText()
                       if self._show_substep else None)
        return {"machine": self.machine_name,
                "last_product": self._build_pid(
                    self._busy_type.currentText(), self._busy_name.text()),
                "needs_initial_setup": False,
                "remaining_hours": self._busy_hours.value(),
                "substep": substep_val}


# ── JobRow: iş kuyruğu satırı ─────────────────────────────────────────────────
class JobRow(QFrame):
    def __init__(self, substep_labels: list,
                 type_options: list, type_to_name: dict, on_remove, parent=None):
        super().__init__(parent)
        self.setStyleSheet(
            f"JobRow{{background:{C['bg']};border:1.5px solid {C['border']};"
            "border-radius:8px;}}"
        )
        lay = QHBoxLayout(self)
        lay.setContentsMargins(12, 8, 12, 8)
        lay.setSpacing(10)

        self._type_to_name = dict(type_to_name or {})

        # Her zaman işlem türü combo'su gösterilir; tek seçenek varsa o adımın kendi adı default olur.
        self.substep_combo = QComboBox()
        for lb in substep_labels:
            self.substep_combo.addItem(lb)
        self.substep_combo.setFixedWidth(100)
        self.substep_combo.setStyleSheet(_INPUT)
        lay.addWidget(self.substep_combo)

        # Ürün tipi (sadece K11, K12 gibi); 'Diğer...' ile yeni tip eklenebilir
        self.type_combo = QComboBox()
        for t in type_options:
            self.type_combo.addItem(t)
        _attach_type_picker(self.type_combo, self)
        self.type_combo.setFixedWidth(90)
        self.type_combo.setStyleSheet(_INPUT)
        lay.addWidget(self.type_combo)

        # Ürün adı — kullanıcı manuel girer (boş bırakırsa o tipin canonical adı kullanılır)
        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText("Ürün adı (manuel)")
        self.name_edit.setMinimumWidth(140)
        self.name_edit.setStyleSheet(_INPUT)
        lay.addWidget(self.name_edit, stretch=1)

        # Tip değişince ad alanını o tipin canonical adıyla doldur (kullanıcı override edebilir)
        self.type_combo.currentTextChanged.connect(self._on_type_change)
        self._on_type_change(self.type_combo.currentText())

        lay.addWidget(_lbl("Adet:"))
        self.qty_spin = QSpinBox()
        self.qty_spin.setRange(1, 100)
        self.qty_spin.setValue(1)
        self.qty_spin.setFixedWidth(58)
        self.qty_spin.setStyleSheet(_INPUT)
        lay.addWidget(self.qty_spin)

        lay.addWidget(_lbl("Öncelik:"))
        self.prio_spin = QDoubleSpinBox()
        self.prio_spin.setRange(-2.0, 2.0)
        self.prio_spin.setValue(0.5)
        self.prio_spin.setSingleStep(0.05)
        self.prio_spin.setDecimals(3)
        self.prio_spin.setFixedWidth(78)
        self.prio_spin.setStyleSheet(_INPUT)
        lay.addWidget(self.prio_spin)

        del_btn = QPushButton("✕")
        del_btn.setFixedSize(28, 28)
        del_btn.setStyleSheet(_BTN_DEL)
        del_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        del_btn.clicked.connect(on_remove)
        lay.addWidget(del_btn)

    def _on_type_change(self, ptype: str):
        default_name = self._type_to_name.get(ptype, "")
        self.name_edit.setText(default_name)

    def get_data(self) -> dict:
        substep = _SUBSTEP_MAP.get(self.substep_combo.currentText())
        ptype = self.type_combo.currentText().strip()
        pname = self.name_edit.text().strip() or self._type_to_name.get(ptype, "")
        pid = f"{ptype} / {pname}" if pname else ptype
        return {
            "substep":       substep,
            "product_id":    pid,
            "qty":           self.qty_spin.value(),
            "priority":      self.prio_spin.value(),
            "arrival_hours": 0.0,
        }


# ── ArrivalRow: gelmekte olan ürün satırı ─────────────────────────────────────
class ArrivalRow(QFrame):
    """İş kuyruğundaki satırın aynısı + adım seçimi + gelme süresi alanı.
    Kaynak adım kilitli; tek seçenekli ve değiştirilemez."""

    def __init__(self, type_options: list, type_to_name: dict, on_remove,
                 step_options: Optional[List[str]] = None, parent=None):
        super().__init__(parent)
        self.setStyleSheet(
            f"ArrivalRow{{background:{C['bg']};border:1.5px solid {C['border']};"
            "border-radius:8px;}}"
        )
        lay = QHBoxLayout(self)
        lay.setContentsMargins(12, 8, 12, 8)
        lay.setSpacing(10)

        self._type_to_name = dict(type_to_name or {})

        labels = step_options if step_options is not None else _ALL_STEP_LABELS
        self.substep_combo = QComboBox()
        for lb in labels:
            self.substep_combo.addItem(lb)
        self.substep_combo.setFixedWidth(110)
        self.substep_combo.setStyleSheet(_INPUT)
        lay.addWidget(self.substep_combo)

        # Ürün tipi (sadece K11, K12 gibi); 'Diğer...' ile yeni tip eklenebilir
        self.type_combo = QComboBox()
        for t in type_options:
            self.type_combo.addItem(t)
        _attach_type_picker(self.type_combo, self)
        self.type_combo.setFixedWidth(90)
        self.type_combo.setStyleSheet(_INPUT)
        lay.addWidget(self.type_combo)

        # Ürün adı — kullanıcı manuel girer
        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText("Ürün adı (manuel)")
        self.name_edit.setMinimumWidth(140)
        self.name_edit.setStyleSheet(_INPUT)
        lay.addWidget(self.name_edit, stretch=1)

        self.type_combo.currentTextChanged.connect(self._on_type_change)
        self._on_type_change(self.type_combo.currentText())

        lay.addWidget(_lbl("Adet:"))
        self.qty_spin = QSpinBox()
        self.qty_spin.setRange(1, 100)
        self.qty_spin.setValue(1)
        self.qty_spin.setFixedWidth(58)
        self.qty_spin.setStyleSheet(_INPUT)
        lay.addWidget(self.qty_spin)

        lay.addWidget(_lbl("Öncelik:"))
        self.prio_spin = QDoubleSpinBox()
        self.prio_spin.setRange(-2.0, 2.0)
        self.prio_spin.setValue(0.5)
        self.prio_spin.setSingleStep(0.05)
        self.prio_spin.setDecimals(3)
        self.prio_spin.setFixedWidth(78)
        self.prio_spin.setStyleSheet(_INPUT)
        lay.addWidget(self.prio_spin)

        lay.addWidget(_lbl("Bu adıma gelme süresi:"))
        self.arrival_spin = QDoubleSpinBox()
        self.arrival_spin.setRange(0.1, 168.0)
        self.arrival_spin.setValue(1.0)
        self.arrival_spin.setSingleStep(0.5)
        self.arrival_spin.setDecimals(1)
        self.arrival_spin.setSuffix(" saat")
        self.arrival_spin.setFixedWidth(72)
        self.arrival_spin.setStyleSheet(_INPUT)
        lay.addWidget(self.arrival_spin)

        del_btn = QPushButton("✕")
        del_btn.setFixedSize(28, 28)
        del_btn.setStyleSheet(_BTN_DEL)
        del_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        del_btn.clicked.connect(on_remove)
        lay.addWidget(del_btn)

    def set_source_step(self, source_label: str):
        """Kaynak adımını güncelle (JobRow'daki işlem türü değişince çağrılır)."""
        self.substep_combo.clear()
        self.substep_combo.addItem(source_label)

    def _on_type_change(self, ptype: str):
        default_name = self._type_to_name.get(ptype, "")
        self.name_edit.setText(default_name)

    def get_data(self) -> dict:
        substep = _SUBSTEP_MAP.get(self.substep_combo.currentText(), "dkk")
        ptype = self.type_combo.currentText().strip()
        pname = self.name_edit.text().strip() or self._type_to_name.get(ptype, "")
        pid = f"{ptype} / {pname}" if pname else ptype
        return {
            "substep":       substep,
            "product_id":    pid,
            "qty":           self.qty_spin.value(),
            "priority":      self.prio_spin.value(),
            "arrival_hours": self.arrival_spin.value(),
        }


# ── ResultCard ─────────────────────────────────────────────────────────────────
class ResultCard(QFrame):
    def __init__(self, machine, product_type, product_name, step,
                 group_size, setup_h, process_h, parent=None):
        super().__init__(parent)
        step_lbl = step.upper().replace("ATP_STP", "ATP+STP")
        self.setStyleSheet(
            f"ResultCard{{background:{C['green_l']};border:2px solid {C['green_b']};"
            "border-radius:10px;}}"
        )
        lay = QVBoxLayout(self)
        lay.setContentsMargins(14, 12, 14, 12)
        lay.setSpacing(6)

        top = QHBoxLayout()
        ml = QLabel(machine)
        ml.setFont(QFont("Segoe UI", 15, QFont.Weight.Bold))
        ml.setStyleSheet(f"color:{C['blue']};border:none;")
        top.addWidget(ml)
        top.addStretch()
        badge = QLabel(step_lbl)
        badge.setStyleSheet(
            f"color:white;background:{C['blue']};border:none;border-radius:4px;"
            "padding:2px 8px;font-size:11px;font-weight:800;"
        )
        top.addWidget(badge)
        lay.addLayout(top)

        name = product_type if product_name == product_type else f"{product_type} — {product_name}"
        pl = QLabel(name)
        pl.setFont(QFont("Segoe UI", 12))
        pl.setStyleSheet(f"color:{C['text']};border:none;")
        lay.addWidget(pl)

        parts = [f"{group_size} adet"]
        if setup_h > 0:
            parts.append(f"Setup {setup_h:.1f}s")
        parts.append(f"İşlem {process_h:.1f}s")
        dl = QLabel("  ·  ".join(parts))
        dl.setStyleSheet(f"color:{C['text2']};font-size:11px;border:none;")
        lay.addWidget(dl)


# ── IdleCard ───────────────────────────────────────────────────────────────────
class IdleCard(QFrame):
    def __init__(self, machine, reason="Boşta kaldı", parent=None):
        super().__init__(parent)
        self.setStyleSheet(
            f"IdleCard{{background:{C['bg']};border:1.5px solid {C['border']};"
            "border-radius:10px;}}"
        )
        lay = QVBoxLayout(self)
        lay.setContentsMargins(14, 12, 14, 12)
        lay.setSpacing(4)
        ml = QLabel(machine)
        ml.setFont(QFont("Segoe UI", 15, QFont.Weight.Bold))
        ml.setStyleSheet(f"color:{C['text3']};border:none;")
        lay.addWidget(ml)
        rl = QLabel(reason)
        rl.setStyleSheet(f"color:{C['text3']};font-size:12px;border:none;")
        lay.addWidget(rl)
        lay.addStretch()


# ── LogEntry ───────────────────────────────────────────────────────────────────
class LogEntry(QFrame):
    _MAP = [
        (("HOLD", "1H_WAIT", "BEKLENIYOR"), (C["amber"],  C["amber_l"])),
        (("RULE2", "KURAL-2"),              (C["green"],  C["green_l"])),
        (("RULE3", "KURAL-3"),              (C["purple"], C["purple_l"])),
        (("KARAR_DETAY", "KARAR"),          (C["cyan"],   C["cyan_l"])),
    ]

    def __init__(self, log: dict, parent=None):
        super().__init__(parent)
        action  = log.get("action", "")
        details = log.get("details", "")
        ts      = log.get("timestamp", datetime.now())

        lc, bg = C["text3"], C["bg"]
        for keys, colors in self._MAP:
            if any(k in action for k in keys):
                lc, bg = colors
                break

        self.setStyleSheet(
            f"QFrame{{background:{bg};border:1px solid {C['border']};"
            f"border-left:3px solid {lc};border-radius:6px;}}"
        )
        lay = QVBoxLayout(self)
        lay.setContentsMargins(10, 7, 10, 7)
        lay.setSpacing(4)

        top = QHBoxLayout()
        tl = QLabel(ts.strftime("%H:%M:%S"))
        tl.setFont(QFont("Consolas", 9))
        tl.setStyleSheet(f"color:{C['text3']};border:none;background:transparent;")
        tl.setFixedWidth(62)
        top.addWidget(tl)
        al = QLabel(action)
        al.setFont(QFont("Segoe UI", 8, QFont.Weight.Bold))
        al.setStyleSheet(
            f"color:white;background:{lc};border:none;border-radius:3px;padding:1px 6px;"
        )
        al.setFixedHeight(18)
        top.addWidget(al)
        top.addStretch()
        lay.addLayout(top)

        dl = QLabel(details)
        dl.setFont(QFont("Segoe UI", 10))
        dl.setStyleSheet(f"color:{C['text']};border:none;background:transparent;")
        dl.setWordWrap(True)
        lay.addWidget(dl)


# ══════════════════════════════════════════════════════════════════════════════
class StepTesterPage(QWidget):

    # Yeni ürün tip(ler)i girildiğinde main_window'a wizard akışını başlatması için sinyal
    new_product_wizard_requested = pyqtSignal(list)  # list[str] display_names

    def __init__(self, data_manager, parent=None):
        super().__init__(parent)
        self.data_manager = data_manager
        self._selected_step = "dkk_atp"
        self._job_rows: List[JobRow] = []
        self._arrival_rows: List[ArrivalRow] = []
        self._machine_cards: List[MachineConfigCard] = []
        self.setStyleSheet(f"StepTesterPage{{background:{C['bg']};}}")
        self._build_ui()

    # ── UI ─────────────────────────────────────────────────────────────────────
    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # Sayfa başlığı
        hdr_w = QWidget()
        hdr_w.setStyleSheet(
            f"background:{C['white']};border-bottom:1px solid {C['border']};"
        )
        hl = QVBoxLayout(hdr_w)
        hl.setContentsMargins(28, 20, 28, 16)
        hl.setSpacing(4)
        t = QLabel("Adım Test Simülatörü")
        t.setFont(QFont("Segoe UI", 20, QFont.Weight.Bold))
        t.setStyleSheet(f"color:{C['text']};border:none;background:transparent;")
        hl.addWidget(t)
        s = QLabel("Adım seçin  ·  makine durumunu ayarlayın  ·  iş kuyruğunu oluşturun  ·  Çalıştır")
        s.setStyleSheet(f"color:{C['text3']};font-size:13px;border:none;background:transparent;")
        hl.addWidget(s)
        root.addWidget(hdr_w)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet(f"QScrollArea{{border:none;background:{C['bg']};}}")
        body_w = QWidget()
        body_w.setStyleSheet(f"background:{C['bg']};")
        self._body = QVBoxLayout(body_w)
        self._body.setContentsMargins(28, 20, 28, 28)
        self._body.setSpacing(16)
        scroll.setWidget(body_w)
        root.addWidget(scroll)

        self._build_step_row()
        self._build_machines_section()
        self._build_queue_section()
        self._build_run_btn()
        self._build_results_section()
        self._body.addStretch()

    # ── 1. Adım seçici ─────────────────────────────────────────────────────────
    def _build_step_row(self):
        card = _card()
        self._step_row_card = card
        lay = QHBoxLayout(card)
        lay.setContentsMargins(20, 14, 20, 14)
        lay.setSpacing(16)

        lay.addWidget(_lbl("Üretim Adımı:", 12, bold=True, color=C["text"]))

        self._step_btns: Dict[str, QPushButton] = {}
        for key, cfg in STEP_CONFIGS.items():
            btn = QPushButton(cfg["label"])
            btn.setCheckable(True)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setMinimumHeight(34)
            btn.setStyleSheet(self._step_on() if key == self._selected_step else self._step_off())
            btn.clicked.connect(lambda _, k=key: self._on_step_changed(k))
            self._step_btns[key] = btn
            lay.addWidget(btn)

        lay.addStretch()

        # Algoritma seçimi (yalnızca DKK/ATP)
        self._algo_widget = QWidget()
        self._algo_widget.setStyleSheet("background:transparent;")
        al = QHBoxLayout(self._algo_widget)
        al.setContentsMargins(0, 0, 0, 0)
        al.setSpacing(8)
        al.addWidget(_sep_v())
        al.addWidget(_lbl("Algoritma:", bold=True, color=C["text"]))
        self._algo_combo = QComboBox()
        self._algo_combo.addItems(["Sevkiyat Destekli Yaklaşım", "Makina Verimli Dengeli Yaklaşım"])
        self._algo_combo.setCurrentIndex(1)
        self._algo_combo.setStyleSheet(_INPUT)
        self._algo_combo.setMinimumWidth(220)
        al.addWidget(self._algo_combo)
        lay.addWidget(self._algo_widget)

        self._body.addWidget(card)

    # ── 2. Makine durumu ───────────────────────────────────────────────────────
    def _build_machines_section(self):
        self._machines_card = _card()
        ml = QVBoxLayout(self._machines_card)
        ml.setContentsMargins(20, 16, 20, 16)
        ml.setSpacing(12)

        hdr = QHBoxLayout()
        hdr.addWidget(_lbl("Makine Durumu", 13, bold=True, color=C["text"]))
        hdr.addWidget(_lbl("  Her makine için başlangıç durumunu seçin."))
        hdr.addStretch()
        reset_btn = QPushButton("↺  Sıfırla")
        reset_btn.setStyleSheet(f"""QPushButton {{
            background:{C['bg']}; color:{C['text2']};
            border:1.5px solid {C['border2']}; border-radius:6px;
            font-size:12px; font-weight:600; padding:4px 12px;
        }}
        QPushButton:hover {{ background:{C['red_l']}; color:{C['red']}; border-color:{C['red_b']}; }}""")
        reset_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        reset_btn.clicked.connect(self._reset_machines)
        hdr.addWidget(reset_btn)
        ml.addLayout(hdr)
        ml.addWidget(_sep())

        self._machine_cards_row = QHBoxLayout()
        self._machine_cards_row.setSpacing(12)
        self._machine_cards_row.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        ml.addLayout(self._machine_cards_row)

        self._body.addWidget(self._machines_card)
        self._rebuild_machine_cards()

    # ── 3. İş kuyruğu ─────────────────────────────────────────────────────────
    def _build_queue_section(self):
        # Hazır işler
        self._queue_card = _card()
        ql = QVBoxLayout(self._queue_card)
        ql.setContentsMargins(20, 16, 20, 16)
        ql.setSpacing(10)

        hdr = QHBoxLayout()
        hdr.addWidget(_lbl("İş Kuyruğu", 13, bold=True, color=C["text"]))
        hdr.addWidget(_lbl("  Bu adımda bekleyen ürünler."))
        hdr.addStretch()
        add_btn = QPushButton("+ İş Ekle")
        add_btn.setStyleSheet(_BTN_ADD)
        add_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        add_btn.clicked.connect(self._add_job_row)
        hdr.addWidget(add_btn)
        ql.addLayout(hdr)
        ql.addWidget(_sep())

        self._job_rows_container = QVBoxLayout()
        self._job_rows_container.setSpacing(6)
        ql.addLayout(self._job_rows_container)
        self._body.addWidget(self._queue_card)
        self._add_job_row()

        # Gelmekte olan işler
        self._arrival_card = _card()
        al = QVBoxLayout(self._arrival_card)
        al.setContentsMargins(20, 16, 20, 16)
        al.setSpacing(10)

        ahdr = QHBoxLayout()
        ahdr.addWidget(_lbl("Gelmekte Olan Ürünler", 13, bold=True, color=C["text"]))
        ahdr.addWidget(_lbl("  Henüz bu adıma ulaşmamış, önceki adımda işlenmekte olan ürünler."))
        ahdr.addStretch()
        add_arr_btn = QPushButton("+ Ürün Ekle")
        add_arr_btn.setStyleSheet(_BTN_ADD)
        add_arr_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        add_arr_btn.clicked.connect(self._add_arrival_row)
        ahdr.addWidget(add_arr_btn)
        al.addLayout(ahdr)
        al.addWidget(_sep())

        self._arrival_rows_container = QVBoxLayout()
        self._arrival_rows_container.setSpacing(6)
        al.addLayout(self._arrival_rows_container)
        self._body.addWidget(self._arrival_card)

    # ── 4. Çalıştır butonu ─────────────────────────────────────────────────────
    def _build_run_btn(self):
        w = QWidget()
        w.setStyleSheet("background:transparent;")
        r = QHBoxLayout(w)
        r.setContentsMargins(0, 4, 0, 4)
        r.addStretch()
        self._run_btn = QPushButton("▶  Çalıştır")
        self._run_btn.setStyleSheet(_BTN_RUN)
        self._run_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._run_btn.setMinimumHeight(48)
        self._run_btn.setMinimumWidth(200)
        self._run_btn.clicked.connect(self._run_planner)
        r.addWidget(self._run_btn)
        r.addStretch()
        self._body.addWidget(w)

    # ── 5. Sonuçlar ────────────────────────────────────────────────────────────
    def _build_results_section(self):
        self._results_card = _card()
        rl = QVBoxLayout(self._results_card)
        rl.setContentsMargins(20, 16, 20, 16)
        rl.setSpacing(12)

        top = QHBoxLayout()
        top.addWidget(_lbl("Sonuç", 13, bold=True, color=C["text"]))
        top.addStretch()
        self._summary_lbl = QLabel("")
        self._summary_lbl.setStyleSheet(f"color:{C['text2']};font-size:12px;border:none;")
        top.addWidget(self._summary_lbl)
        rl.addLayout(top)
        rl.addWidget(_sep())

        self._result_cards_row = QHBoxLayout()
        self._result_cards_row.setSpacing(10)
        self._result_cards_row.setAlignment(Qt.AlignmentFlag.AlignLeft)
        rl.addLayout(self._result_cards_row)

        self._body.addWidget(self._results_card)
        self._results_card.hide()

        # Karar günlüğü
        self._log_card = _card()
        ll = QVBoxLayout(self._log_card)
        ll.setContentsMargins(20, 16, 20, 16)
        ll.setSpacing(10)

        lhdr = QHBoxLayout()
        lhdr.addWidget(_lbl("Karar Günlüğü", 13, bold=True, color=C["text"]))
        lhdr.addStretch()
        self._log_count = QLabel("")
        self._log_count.setStyleSheet(f"color:{C['text3']};font-size:11px;border:none;")
        lhdr.addWidget(self._log_count)
        ll.addLayout(lhdr)
        ll.addWidget(_sep())

        self._log_scroll = QScrollArea()
        self._log_scroll.setWidgetResizable(True)
        self._log_scroll.setMaximumHeight(340)
        self._log_scroll.setStyleSheet("QScrollArea{border:none;background:transparent;}")
        self._log_inner = QWidget()
        self._log_inner.setStyleSheet("background:transparent;")
        self._log_inner_lay = QVBoxLayout(self._log_inner)
        self._log_inner_lay.setContentsMargins(0, 0, 4, 0)
        self._log_inner_lay.setSpacing(5)
        self._log_inner_lay.addStretch()
        self._log_scroll.setWidget(self._log_inner)
        ll.addWidget(self._log_scroll)

        self._body.addWidget(self._log_card)
        self._log_card.hide()

    # ── Adım değiştirme ────────────────────────────────────────────────────────
    def _on_step_changed(self, key: str):
        self._selected_step = key
        for k, btn in self._step_btns.items():
            btn.setStyleSheet(self._step_on() if k == key else self._step_off())
            btn.setChecked(k == key)
        self._rebuild_machine_cards()
        self._algo_widget.setVisible(key in ("dkk_atp", "rvb"))
        # Assembly/FTP/B/N tek-makine ve insan/basit makine adımları → Makine Durumu kartını gizle
        if hasattr(self, "_machines_card"):
            self._machines_card.setVisible(key not in ("assembly", "ftp", "bn"))
        # Adıma göre "Gelmekte Olan Ürünler" bölümünü güncelle
        upstream = UPSTREAM_STEPS.get(key, _ALL_STEP_LABELS)
        # İlk adımda (Assembly) bu kart hiç gösterilmez
        if hasattr(self, "_arrival_card"):
            self._arrival_card.setVisible(bool(upstream))
        # Eski arrival row'ları temizle (combo seçenekleri değişti)
        for row in self._arrival_rows:
            row.setParent(None)
            row.deleteLater()
        self._arrival_rows.clear()
        # Mevcut iş satırlarını da güncelle (substep combosu ekle/çıkar)
        for row in self._job_rows:
            row.setParent(None)
            row.deleteLater()
        self._job_rows.clear()
        self._add_job_row()
        # Önceki adımın sonuçlarını temizle/gizle — kullanıcı bu adıma ait olmayan
        # eski sonuçları görmesin
        self._clear_results()

    def _clear_results(self):
        """Sonuç ve log panellerini temizleyip gizler."""
        if hasattr(self, "_result_cards_row"):
            while self._result_cards_row.count():
                item = self._result_cards_row.takeAt(0)
                if item.widget(): item.widget().deleteLater()
        if hasattr(self, "_log_inner_lay"):
            while self._log_inner_lay.count():
                item = self._log_inner_lay.takeAt(0)
                if item.widget(): item.widget().deleteLater()
        if hasattr(self, "_summary_lbl"):
            self._summary_lbl.setText("")
        if hasattr(self, "_log_count"):
            self._log_count.setText("")
        if hasattr(self, "_results_card"):
            self._results_card.hide()
        if hasattr(self, "_log_card"):
            self._log_card.hide()

    def _rebuild_machine_cards(self):
        while self._machine_cards_row.count():
            item = self._machine_cards_row.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self._machine_cards.clear()
        type_opts = self._type_options()
        type_names = self._type_to_canonical_name()
        # DKK/ATP+STP modunda her makine için işlem türü combo'su göster
        show_substep = self._selected_step == "dkk_atp"
        for mname in STEP_CONFIGS[self._selected_step]["machines"]:
            card = MachineConfigCard(
                mname,
                type_options=type_opts,
                type_to_name=type_names,
                show_substep=show_substep,
            )
            self._machine_cards.append(card)
            self._machine_cards_row.addWidget(card)
        self._machine_cards_row.addStretch()
        self._algo_widget.setVisible(self._selected_step in ("dkk_atp", "rvb"))

    def _reset_machines(self):
        self._rebuild_machine_cards()
        # Sonuç bölümünü ve log paneli temizle
        if hasattr(self, "_result_cards_row"):
            while self._result_cards_row.count():
                item = self._result_cards_row.takeAt(0)
                if item.widget(): item.widget().deleteLater()
        if hasattr(self, "_log_inner_lay"):
            while self._log_inner_lay.count():
                item = self._log_inner_lay.takeAt(0)
                if item.widget(): item.widget().deleteLater()
        if hasattr(self, "_summary_lbl"):
            self._summary_lbl.setText("")
        if hasattr(self, "_log_count"):
            self._log_count.setText("")
        if hasattr(self, "_results_card"):
            self._results_card.hide()
        if hasattr(self, "_log_card"):
            self._log_card.hide()

    # ── İş satırı ─────────────────────────────────────────────────────────────
    def _product_options(self) -> List[str]:
        try:
            return [p.display_name for p in self.data_manager.state.products]
        except Exception:
            return []

    def _type_options(self) -> List[str]:
        """Tip listesi (her tipten bir kez, ekleme sırasını korur)."""
        seen, result = set(), []
        try:
            for p in self.data_manager.state.products:
                if p.type and p.type not in seen:
                    seen.add(p.type)
                    result.append(p.type)
        except Exception:
            pass
        return result

    def _type_to_canonical_name(self) -> Dict[str, str]:
        """Tip → o tipin ilk ürününün adı (canonical isim)."""
        result: Dict[str, str] = {}
        try:
            for p in self.data_manager.state.products:
                if p.type and p.type not in result:
                    result[p.type] = p.name
        except Exception:
            pass
        return result

    def _add_job_row(self):
        cfg = STEP_CONFIGS[self._selected_step]
        row = JobRow(
            substep_labels=cfg["substep_labels"],
            type_options=self._type_options(),
            type_to_name=self._type_to_canonical_name(),
            on_remove=lambda r=None: self._remove_job_row(row),
        )
        # JobRow'da işlem türü değişince ArrivalRow'lar yeni kaynak adımına güncellenir
        row.substep_combo.currentIndexChanged.connect(lambda _: self._sync_arrival_sources())
        self._job_rows.append(row)
        self._job_rows_container.addWidget(row)

    def _remove_job_row(self, row: JobRow):
        if row in self._job_rows:
            self._job_rows.remove(row)
        row.setParent(None)
        row.deleteLater()

    def _current_arrival_source(self) -> str:
        """Seçili adım için ArrivalRow'da gösterilecek kaynak adımı.
        DKK/ATP+STP'de JobRow'un işlem türü seçimine göre değişir; diğer adımlarda sabit."""
        if self._selected_step == "dkk_atp":
            # JobRow'larda DKK seçiliyse B/N, ATP+STP seçiliyse RVB
            substep_to_source = {"DKK": "B/N", "ATP+STP": "RVB"}
            for r in self._job_rows:
                txt = r.substep_combo.currentText()
                if txt in substep_to_source:
                    return substep_to_source[txt]
            return "B/N"  # default (hiç JobRow yoksa)
        return DEFAULT_UPSTREAM.get(self._selected_step, "")

    def _sync_arrival_sources(self):
        """JobRow işlem türü değişince tüm ArrivalRow'ların kaynak adımını güncelle.
        DKK/ATP+STP modunda kaynak (B/N veya RVB) kullanıcı tarafından satır bazlı
        seçildiği için sync yapılmaz."""
        if self._selected_step == "dkk_atp":
            return
        src = self._current_arrival_source()
        if not src:
            return
        for r in self._arrival_rows:
            r.set_source_step(src)

    def _add_arrival_row(self):
        upstream = UPSTREAM_STEPS.get(self._selected_step, _ALL_STEP_LABELS)
        if not upstream:
            return  # Assembly gibi ilk adımlarda gelmekte olan ürün yok
        # DKK/ATP+STP modunda kullanıcı kaynak adımı (B/N veya RVB) seçebilir
        if self._selected_step == "dkk_atp":
            step_options = ["B/N", "RVB"]
            enabled = True
        else:
            source_label = self._current_arrival_source() or upstream[0]
            step_options = [source_label]
            enabled = False
        row = ArrivalRow(
            type_options=self._type_options(),
            type_to_name=self._type_to_canonical_name(),
            on_remove=lambda r=None: self._remove_arrival_row(row),
            step_options=step_options,
        )
        row.substep_combo.setEnabled(enabled)
        self._arrival_rows.append(row)
        self._arrival_rows_container.addWidget(row)

    def _remove_arrival_row(self, row: ArrivalRow):
        if row in self._arrival_rows:
            self._arrival_rows.remove(row)
        row.setParent(None)
        row.deleteLater()

    # ── Planlayıcı ─────────────────────────────────────────────────────────────
    def _resolve_products(self, raw_data: list) -> tuple:
        """Girilen ürünleri doğrula; aynı tipte isim farklıysa o tipin verilerini inherit et.
        Yeni tip / hatalı format varsa hata mesajı döner.
        Dönüş: (ok, pt_dict, cap_dict, setup_dict, err)"""
        import copy as _copy
        products = self.data_manager.state.products
        type_to_first = {}
        for p in products:
            if p.type not in type_to_first:
                type_to_first[p.type] = p.display_name

        pt = _copy.deepcopy(self.data_manager.state.production_time_data) or {}
        cap = _copy.deepcopy(self.data_manager.state.capacity_data) or {}
        setup = _copy.deepcopy(self.data_manager.state.setup_matrix) or {}

        new_added: List[str] = []  # Bu turda data_manager'a eklenen yeni ürünler

        for d in raw_data:
            pid = d["product_id"].strip()
            if not pid:
                continue
            if "/" not in pid:
                return False, None, None, None, (
                    f"'{pid}' formatı yanlış. Format: 'Tip / İsim' (örn 'K11 / Ürün A')."
                )
            ptype = pid.split("/")[0].strip()
            if pid in pt:
                continue  # Tam eşleşme
            if ptype not in type_to_first:
                # Yeni tip → otomatik kaydet, listeye al; iterasyon devam etsin (diğer yeniler de toplansın)
                pname = pid.split("/", 1)[1].strip() if "/" in pid else pid
                new_p = Product(type=ptype, name=pname, monthly_target=0)
                self.data_manager.add_product(new_p)
                type_to_first[ptype] = pid  # Sonraki ürünler bu tipi tanısın
                new_added.append(pid)
                continue
            # Aynı tipte mevcut bir ürün var → onun verilerini kopyala (in-memory, geçici)
            existing = type_to_first[ptype]
            if existing in pt:
                pt[pid] = _copy.deepcopy(pt[existing])
            if existing in cap:
                cap[pid] = _copy.deepcopy(cap[existing])
            if existing in setup:
                setup[pid] = _copy.deepcopy(setup[existing])
            for k in list(setup.keys()):
                if k != pid and existing in setup[k]:
                    setup[k][pid] = setup[k][existing]

        # Yeni eklenenler varsa wizard tetikle, çalıştırmayı durdur
        if new_added:
            self.new_product_wizard_requested.emit(new_added)
            count = len(new_added)
            urunler = ", ".join(new_added)
            return False, None, None, None, (
                f"{count} yeni ürün otomatik eklendi: {urunler}.\n\n"
                f"Sırayla Üretim Süreleri, Kurulum Matrisi ve Kapasite Tablosu "
                f"sayfalarında bu ürünlerin bilgilerini güncelle, sonra Adım Testi'ne "
                f"dönüp tekrar Çalıştır'a bas."
            )
        return True, pt, cap, setup, ""

    def _run_planner(self):
        if not self._job_rows:
            QMessageBox.warning(self, "Uyarı", "Önce en az bir iş ekleyin.")
            return
        raw_data = [r.get_data() for r in self._job_rows + self._arrival_rows]
        raw_data = [d for d in raw_data if d["product_id"]]
        if not raw_data:
            QMessageBox.warning(self, "Uyarı", "Geçerli ürün ID'si olan en az bir iş ekleyin.")
            return

        # Ürün doğrulama: aynı tipte isim farklıysa inherit, yeni tip varsa hata
        ok, prod_time_raw, cap_raw, setup_dict, err = self._resolve_products(raw_data)
        if not ok:
            QMessageBox.warning(self, "Ürün Hatası", err)
            return

        now = datetime.now().replace(second=0, microsecond=0)
        try:
            all_pids = list(prod_time_raw.keys()) or list({d["product_id"] for d in raw_data})
            setup_mat = SetupMatrix(product_ids=all_pids, matrix=setup_dict)
        except Exception:
            setup_mat = SetupMatrix(product_ids=[], matrix={})

        try:
            step = self._selected_step
            if   step == "dkk_atp":  self._run_dkk_atp(raw_data, now, prod_time_raw, setup_mat, cap_raw)
            elif step == "rvb":      self._run_rvb(raw_data, now, prod_time_raw, setup_mat, cap_raw)
            elif step == "assembly": self._run_assembly(raw_data, now, prod_time_raw, cap_raw)
            elif step == "ftp":      self._run_ftp(raw_data, now, prod_time_raw, setup_mat)
            elif step == "bn":       self._run_bn(raw_data, now, prod_time_raw, setup_mat, cap_raw)
        except Exception as e:
            import traceback; traceback.print_exc()
            QMessageBox.critical(self, "Hata", f"Planlayıcı hatası:\n{e}")

    def _run_dkk_atp(self, raw_data, now, pt_raw, setup_mat, cap_raw):
        # Routing kuralları:
        # - JobRow substep="dkk" → DKK queue
        # - JobRow substep="atp_stp" → ATP+STP queue
        # - ArrivalRow source="B/N" (substep="bn") → DKK queue (B/N → DKK)
        # - ArrivalRow source="RVB" (substep="rvb") → ATP+STP queue (RVB → ATP+STP)
        dkk_data, atp_data = [], []
        for d in raw_data:
            sub = d.get("substep")
            if sub in ("atp_stp", "rvb"):
                atp_data.append(d)
            else:
                dkk_data.append(d)
        for d in dkk_data: d["substep"] = "dkk"
        for d in atp_data: d["substep"] = "atp_stp"
        pool = self._build_pool(["M1","M2","M3","M4"], now)
        prod_times = {"dkk": self._pt(pt_raw,"DKK",raw_data), "atp_stp": self._pt(pt_raw,"ATP+STP",raw_data)}
        capacities = {"dkk": self._cap(cap_raw,"DKK"),        "atp_stp": self._cap(cap_raw,"ATP+STP")}
        logger = _Logger()
        planner = DkkAtpPlannerV2 if self._algo_combo.currentIndex()==1 else DkkAtpPlanner
        # v1 (DkkAtpPlanner) product_index_map kabul eder; v2 (DkkAtpPlannerV2) etmez
        extra_kwargs = {}
        if planner is DkkAtpPlanner:
            extra_kwargs["product_index_map"] = self._build_product_index_map(raw_data)
        entries,_,_ = planner.plan(
            dkk_waiting=self._jobs(dkk_data,"dkk",now),
            atp_waiting=self._jobs(atp_data,"atp_stp",now),
            machine_pool=pool, current_time=now,
            production_times=prod_times, setup_matrix=setup_mat,
            shift_capacities=capacities, shift_number=1, logger=logger,
            **extra_kwargs,
        )
        self._show(entries, logger.logs, ["M1","M2","M3","M4"])

    def _build_product_index_map(self, raw_data):
        """UI'daki iş kuyruğu satırlarının sırasından tie-break için indeks haritası üretir.
        Aynı priority'li ürünler bu haritaya göre sıralanır (küçük indeks önce).
        Ana scheduler ile birebir aynı davranışı sağlar."""
        idx_map = {}
        for i, d in enumerate(raw_data):
            pid = d.get("product_id")
            if pid and pid not in idx_map:
                idx_map[pid] = i
        return idx_map

    def _run_rvb(self, raw_data, now, pt_raw, setup_mat, cap_raw):
        cfg = self._machine_cards[0].get_config() if self._machine_cards else {}
        logger = _Logger()
        # Algoritma 2 seçildiyse RvbPlannerV2; aksi halde mevcut RvbPlanner (v1)
        planner = RvbPlannerV2 if self._algo_combo.currentIndex() == 1 else RvbPlanner
        # v2 product_index_map almıyor — v1 ile uyumluluk için kwargs ile gönder
        extra_kwargs = {}
        if planner is RvbPlanner:
            extra_kwargs["product_index_map"] = self._build_product_index_map(raw_data)
        entries,_,_,_ = planner.plan(
            waiting_jobs=self._jobs(raw_data,"rvb",now), current_time=now,
            machine_available_at=now, last_product_id=cfg.get("last_product"),
            production_times=self._pt(pt_raw,"RVB",raw_data),
            setup_matrix=setup_mat, shift_capacity=self._cap(cap_raw,"RVB"),
            shift_number=1,
            last_work_date=None if cfg.get("needs_initial_setup",True) else now.date(),
            logger=logger,
            **extra_kwargs,
        )
        self._show(entries, logger.logs, ["RVB"])

    def _run_assembly(self, raw_data, now, pt_raw, cap_raw):
        logger = _Logger()
        entries,_,_,_,_ = AssemblyPlanner.plan(
            waiting_jobs=self._jobs(raw_data,"assembly",now), current_time=now,
            machine_available_at=now, shift_capacity=self._cap(cap_raw,"Assembly"),
            production_times=self._pt(pt_raw,"Assembly",raw_data),
            remaining_counts={d["product_id"]:d["qty"] for d in raw_data},
            shift_number=1,
            assembly_state={"remaining_in_chunk":{}, "last_product_id": None},
            logger=logger,
            product_index_map=self._build_product_index_map(raw_data),
        )
        self._show(entries, logger.logs, ["Assembly"])

    def _run_ftp(self, raw_data, now, pt_raw, setup_mat):
        cfg = self._machine_cards[0].get_config() if self._machine_cards else {}
        logger = _Logger()
        entries,_,_,_ = FtpPlanner.plan(
            waiting_jobs=self._jobs(raw_data,"ftp",now), current_time=now,
            machine_available_at=now, last_product_id=cfg.get("last_product"),
            production_times=self._pt(pt_raw,"FTP",raw_data,0.5),
            setup_matrix=setup_mat, shift_number=1,
            ftp_state={"remaining_in_chunk":{}}, logger=logger,
        )
        self._show(entries, logger.logs, ["FTP"])

    def _run_bn(self, raw_data, now, pt_raw, setup_mat, cap_raw):
        cfg = self._machine_cards[0].get_config() if self._machine_cards else {}
        logger = _Logger()
        entries,_,_,_,_ = BnPlanner.plan(
            waiting_jobs=self._jobs(raw_data,"bn",now), current_time=now,
            machine_available_at=now, last_product_id=cfg.get("last_product"),
            production_times=self._pt(pt_raw,"B/N",raw_data,12.0),
            setup_matrix=setup_mat, shift_capacity=self._cap(cap_raw,"B/N"),
            shift_number=1, logger=logger,
            product_index_map=self._build_product_index_map(raw_data),
        )
        self._show(entries, logger.logs, ["B/N"])

    # ── Yardımcılar ────────────────────────────────────────────────────────────
    def _jobs(self, data, step, now):
        """JobRow verilerinden Job nesneleri üretir.
        Aynı tipteki tüm satırlar aynı product_id'yi (canonical) paylaşır; böylece
        mevcut planner gruplama mantığı (product_id bazlı) onları otomatik tek
        batch'e toplar. İlk eklenen ürün adı temsilci olarak kullanılır."""
        # Tip → ilk görülen pid (canonical) eşleştirmesi
        canonical_by_type = {}
        for d in data:
            pid = d["product_id"]
            ptype = pid.split("/", 1)[0].strip() if "/" in pid else pid
            if ptype not in canonical_by_type:
                canonical_by_type[ptype] = pid

        jobs = []
        for d in data:
            pid = d["product_id"]
            ptype = pid.split("/", 1)[0].strip() if "/" in pid else pid
            canonical_pid = canonical_by_type[ptype]
            pname = (canonical_pid.split("/", 1)[1].strip()
                     if "/" in canonical_pid else canonical_pid)
            ready_time = now + timedelta(hours=d.get("arrival_hours", 0.0))
            for i in range(d["qty"]):
                jobs.append(Job(
                    job_id=f"tst_{pid}_{i}_{uuid.uuid4().hex[:4]}",
                    product_id=canonical_pid,
                    product_type=ptype,
                    product_name=pname,
                    priority_score=d["priority"], is_priority_override=False,
                    current_step=step, ready_time=ready_time,
                    completed_steps=[], is_completed=False,
                ))
        return jobs

    def _pt(self, raw, stage, job_data, default=1.0):
        pt = {pid: times.get(stage, default) for pid, times in raw.items()} if raw else {}
        for d in job_data:
            if d["product_id"] not in pt:
                pt[d["product_id"]] = default
        return pt

    def _cap(self, cap_raw, stage, idx=0):
        result = {}
        for pid, stages in cap_raw.items():
            caps = stages.get(stage, [])
            if caps and len(caps) > idx:
                try: result[pid] = max(1, int(caps[idx]))
                except: result[pid] = 1
        return result if result else 1

    def _build_pool(self, names, now):
        pool = SharedMachinePool(machine_names=names, initial_time=now)
        for card in self._machine_cards:
            cfg = card.get_config()
            m = cfg["machine"]
            if cfg["last_product"]:
                pool.last_product_ids[m] = cfg["last_product"]
            if not cfg["needs_initial_setup"]:
                pool.last_work_dates[m] = now.date()
            if cfg["remaining_hours"] > 0:
                pool.machines[m].available_at = now + timedelta(hours=cfg["remaining_hours"])
        return pool

    # ── Sonuç göster ───────────────────────────────────────────────────────────
    def _show(self, entries, logs, all_machines):
        while self._result_cards_row.count():
            item = self._result_cards_row.takeAt(0)
            if item.widget(): item.widget().deleteLater()

        # Makine durumu kartlarını atanan ürün ile güncelle
        # Aynı makineye ait birden çok entry → tipi ortak, isimleri virgülle birleştir
        machine_to_entries: Dict[str, list] = {}
        for e in entries:
            machine_to_entries.setdefault(e.machine_name, []).append(e)
        # Çalıştır anındaki referans saat — bekleme süresini hesaplamak için
        run_now = datetime.now().replace(second=0, microsecond=0)
        for card in self._machine_cards:
            ents = machine_to_entries.get(card.machine_name)
            if not ents:
                continue
            first = ents[0]
            # Tüm entry'lerin product_name'lerini topla, dedupla, sırasını koru
            seen_names = []
            for e in ents:
                nm = (e.product_name or "").strip()
                if nm and nm not in seen_names:
                    seen_names.append(nm)
            joined_names = ", ".join(seen_names)
            substep = first.step_name  # 'dkk' veya 'atp_stp'
            wait_h = max(0.0, (first.start_time - run_now).total_seconds() / 3600.0)
            card.set_assigned(
                product_type=first.product_type,
                product_name=joined_names,
                setup_hours=first.setup_time,
                process_hours=first.process_time,
                substep=substep,
                group_size=first.group_size,
                wait_hours=wait_h,
            )

        assigned = {e.machine_name for e in entries}
        if not entries:
            self._summary_lbl.setText("Hiçbir makineye iş atanamadı")
            self._summary_lbl.setStyleSheet(f"color:{C['amber']};font-size:12px;font-weight:600;border:none;")
        else:
            total = sum(e.group_size for e in entries if e.machine_name in assigned)
            idle  = len(all_machines) - len(assigned)
            self._summary_lbl.setText(
                f"{len(assigned)} makine  ·  {total} iş atandı  ·  {idle} boşta"
            )
            self._summary_lbl.setStyleSheet(
                f"color:{C['green']};font-size:12px;font-weight:600;border:none;"
            )

        seen = set()
        for e in entries:
            if e.machine_name not in seen:
                seen.add(e.machine_name)
                self._result_cards_row.addWidget(
                    ResultCard(e.machine_name, e.product_type, e.product_name,
                               e.step_name, e.group_size, e.setup_time, e.process_time)
                )
        for m in all_machines:
            if m not in assigned:
                busy = any(c.get_config()["machine"]==m and c.get_config()["remaining_hours"]>0
                           for c in self._machine_cards)
                self._result_cards_row.addWidget(IdleCard(m, "Meşgul — bekleniyor" if busy else "Boşta kaldı"))

        while self._log_inner_lay.count():
            item = self._log_inner_lay.takeAt(0)
            if item.widget(): item.widget().deleteLater()
        for log in logs:
            self._log_inner_lay.addWidget(LogEntry(log))
        self._log_inner_lay.addStretch()
        self._log_count.setText(f"{len(logs)} kayıt")

        self._results_card.show()
        self._log_card.show()

    # ── Stil yardımcıları ──────────────────────────────────────────────────────
    @staticmethod
    def _step_on():
        return (f"QPushButton{{background:{C['blue']};color:white;border:none;"
                "border-radius:7px;font-size:12px;font-weight:700;padding:6px 16px;}}")

    @staticmethod
    def _step_off():
        return (f"QPushButton{{background:{C['white']};color:{C['text2']};"
                f"border:1.5px solid {C['border']};border-radius:7px;"
                f"font-size:12px;font-weight:600;padding:6px 16px;}}"
                f"QPushButton:hover{{background:{C['blue_l']};color:{C['blue']};"
                f"border-color:{C['blue_m']};}}")


def _sep_v() -> QFrame:
    f = QFrame()
    f.setFrameShape(QFrame.Shape.VLine)
    f.setFixedWidth(1)
    f.setStyleSheet(f"background:{C['border']}; border:none;")
    return f
