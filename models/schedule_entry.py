from dataclasses import dataclass, asdict
from datetime import datetime
from typing import Dict, Any

@dataclass
class ScheduleEntry:
    job_id: str
    product_type: str
    product_name: str # Düzeltildi: varsayılan değer kaldırıldı
    step_name: str
    machine_name: str
    start_time: datetime
    end_time: datetime
    setup_time: float
    process_time: float
    group_size: int
    shift_number: int
    priority_level: float
    is_priority_override: bool
    machine_capacity: int = 1
    initial_setup_time: float = 0.0     # İlk kullanım setup (planlamada ilk kez çalışma)
    transition_setup_time: float = 0.0  # Ürünler arası geçiş setup (setup matrix'ten)

    def to_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        data['start_time'] = self.start_time.isoformat()
        data['end_time'] = self.end_time.isoformat()
        return data

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'ScheduleEntry':
        data['start_time'] = datetime.fromisoformat(data['start_time'])
        data['end_time'] = datetime.fromisoformat(data['end_time'])
        data.setdefault('machine_capacity', 1)
        data.setdefault('initial_setup_time', 0.0)
        data.setdefault('transition_setup_time', 0.0)
        return cls(**data)
