from dataclasses import dataclass, asdict
from datetime import datetime
from typing import Optional, Dict, Any

@dataclass
class MachineState:
    machine_name: str
    current_job_id: Optional[str]
    current_step: Optional[str]
    available_at: datetime
    last_product_type: Optional[str]

    def to_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        data['available_at'] = self.available_at.isoformat()
        return data

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'MachineState':
        data['available_at'] = datetime.fromisoformat(data['available_at'])
        return cls(**data)
