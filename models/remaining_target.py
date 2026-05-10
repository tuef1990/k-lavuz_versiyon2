from dataclasses import dataclass, asdict
from typing import Dict, Any

@dataclass
class RemainingTarget:
    product_id: str
    product_type: str
    product_name: str
    monthly_target: int
    period_target: int
    scheduled_count: int
    remaining_count: int

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'RemainingTarget':
        return cls(**data)
