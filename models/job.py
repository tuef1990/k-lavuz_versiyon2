from dataclasses import dataclass, field, asdict
from datetime import datetime
from typing import List, Dict, Any, Optional

@dataclass
class Job:
    job_id: str
    product_id: str
    product_type: str
    product_name: str
    priority_score: float
    is_priority_override: bool
    current_step: str
    ready_time: datetime
    completed_steps: List[str]
    is_completed: bool
    remaining_work_hours: float = 0.0  # Excel'den  gelen kalan  işçilik süresi (saat)
    target_week: int = 0  # 0: İlk Hafta, 1: İkinci Hafta vb.
    preferred_machine: Optional[str] = None  # Excel'den gelen tercih edilen makine (M1-M4)
    initial_priority_score: float = 0.0  # Simülasyon başlangıcındaki öncelik (display için sabit)
    # Excel'de tek satırda birden fazla isim girildiğinde aynı group_id'yi paylaşırlar.
    # Planner'lar batch oluştururken aynı group_id'li işleri tek grup gibi işler.
    group_id: Optional[str] = None
    # Excel satır sırası — aynı tip/öncelik/ready_time'lı işler bu sıraya göre
    # işlenir (FTP, B/N, RVB, DKK/ATP planner tie-break'i). 0 = bilinmiyor.
    excel_order: int = 0

    @property
    def display_label(self) -> str:
        return f"{self.product_type} / {self.product_name} #{self.job_id[:4]}"

    def to_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        data['ready_time'] = self.ready_time.isoformat()
        return data

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'Job':
        data['ready_time'] = datetime.fromisoformat(data['ready_time'])
        data.setdefault('preferred_machine', None)
        data.setdefault('group_id', None)
        data.setdefault('excel_order', 0)
        return cls(**data)
