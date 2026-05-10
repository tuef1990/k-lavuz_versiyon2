from dataclasses import dataclass, field, asdict
from typing import List, Dict, Any

@dataclass
class Product:
    type: str
    name: str
    monthly_target: int
    
    @property
    def display_name(self) -> str:
        return f"{self.type} / {self.name}"

@dataclass
class AppState:
    products: List[Product] = field(default_factory=list)
    # Kapasite verileri: {ürün_görünen_adı: {istasyon_adı: [değer1, değer2, ...]}}
    capacity_data: Dict[str, Dict[str, List[Any]]] = field(default_factory=dict)
    # Üretim süresi verileri: {ürün_görünen_adı: {istasyon_adı: değer}}
    production_time_data: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    # Kurulum matrisi: {kaynak_ürün_adı: {hedef_ürün_adı: değer}}
    setup_matrix: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    # Vardiya verileri: {istasyon_adı: [{"name": "1. Vardiya", "start": "HH:MM", "end": "HH:MM"}]}
    shift_data: Dict[str, List[Dict[str, str]]] = field(default_factory=dict)
    # Gecikme / taşıma verileri: {product_type: {"week": int, "deficit": int, "produced": int, "target": int, "monthly_consumed": int}}
    carryover_data: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    # Hafta sonu vardiya kuralları: hangi vardiya indeksleri (0-tabanlı) çalışıyor
    # Örn: {"saturday": [0], "sunday": []} → Cumartesi sadece V1, Pazar tatil
    weekend_shifts: Dict[str, List[int]] = field(default_factory=lambda: {"saturday": [0], "sunday": []})
    # Üretilen miktar: {ürün_görünen_adı: adet}
    # Hem Ürün Bilgileri hem Çizelgeleme sayfası bu sözlüğü ortak okur/yazar.
    produced_amounts: Dict[str, int] = field(default_factory=dict)

STAGES = ["Assembly", "FTP", "B/N", "DKK", "RVB", "ATP+STP"]
VARDIA_INFO = {
    "Assembly": "3 vardiya çalışıyor",
    "FTP": "3 vardiya çalışıyor",
    "B/N": "3 vardiya çalışıyor",
    "DKK": "3 vardiya çalışıyor- 4 paralel makine",
    "RVB": "3 vardiya çalışıyor",
    "ATP+STP": "3 vardiya çalışıyor- 4 paralel makine"
}
