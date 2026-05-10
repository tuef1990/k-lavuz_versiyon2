from dataclasses import dataclass, asdict, field
from datetime import datetime
from typing import List, Dict, Any
from .schedule_entry import ScheduleEntry
from .remaining_target import RemainingTarget

@dataclass
class PlanningResult:
    schedule: List[ScheduleEntry]
    makespan: float
    last_part_completion: datetime
    machine_utilization: Dict[str, float]
    algorithm_used: str
    period: str
    remaining_targets: List[RemainingTarget]
    total_setup_time: float
    total_parts: int
    audit_log: List[str] = field(default_factory=list)
    raw_audit_logs: List[Dict] = field(default_factory=list)
    # Her recalc anında ürün tipi başına alınan priority snapshot'ları
    # {product_type: [(timestamp, score), ...]} — slider zamanına göre lookup için
    priority_history: Dict[str, List[Any]] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        data['schedule'] = [entry.to_dict() for entry in self.schedule]
        data['remaining_targets'] = [target.to_dict() for target in self.remaining_targets]
        data['last_part_completion'] = self.last_part_completion.isoformat()
        data['audit_log'] = self.audit_log
        return data

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'PlanningResult':
        data['schedule'] = [ScheduleEntry.from_dict(entry) for entry in data['schedule']]
        data['remaining_targets'] = [RemainingTarget.from_dict(t) for t in data['remaining_targets']]
        data['last_part_completion'] = datetime.fromisoformat(data['last_part_completion'])
        data.setdefault('audit_log', [])
        data.setdefault('priority_history', {})
        return cls(**data)
