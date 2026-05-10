from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum, auto
import heapq
from typing import List, Dict, Any, Optional

class EventType(Enum):
    MACHINE_FREE = auto()        # Bir makine/istasyonun boşaldığı an
    GROUP_COMPLETE = auto()      # Bir işlem grubunun tamamlandığı an
    SHIFT_CHANGE = auto()        # Yeni vardiyanın başladığı an
    WAIT_TIMEOUT = auto()        # B/N bekleme eşiğinin dolduğu an
    PARTS_READY = auto()         # Bir sonraki adım için yeni parçaların hazır olduğu an

# order=False: dataclass otomatik karşılaştırma üretmesin; __lt__ elle tanımlı
@dataclass(order=False)
class Event:
    time: datetime
    event_type: EventType
    data: Dict[str, Any] = field(default_factory=dict)
    _priority: int = 0  # Aynı zamanda birden fazla event varsa küçük değer önce işlenir

    def __lt__(self, other):
        if not isinstance(other, Event):
            return NotImplemented
        if self.time != other.time:
            return self.time < other.time
        # Zaman eşitse öncelik sayısına göre sırala (SHIFT_CHANGE önce gelsin, priority=-10)
        return self._priority < other._priority

class EventQueue:
    def __init__(self):
        self._queue: List[Event] = []

    def add_event(self, time: datetime, event_type: EventType, data: Dict[str, Any], priority: int = 0):
        event = Event(time=time, event_type=event_type, data=data, _priority=priority)
        heapq.heappush(self._queue, event)

    def pop_next(self) -> Optional[Event]:
        if not self._queue:
            return None
        return heapq.heappop(self._queue)

    def peek_next(self) -> Optional[Event]:
        if not self._queue:
            return None
        return self._queue[0]

    def peek_next_time(self) -> Optional[datetime]:
        next_event = self.peek_next()
        return next_event.time if next_event else None

    def pop_events_at(self, time: datetime) -> List[Event]:
        events = []
        while self._queue and self._queue[0].time == time:
            events.append(heapq.heappop(self._queue))
        return events

    def has_events(self) -> bool:
        return len(self._queue) > 0

    def clear(self):
        self._queue = []

    def __len__(self):
        return len(self._queue)

def add_shift_events(
    queue: EventQueue,
    start_date: datetime,
    end_date: datetime,
    shift_schedule: List[Dict[str, str]],
    weekend_shifts: Optional[Dict[str, List[int]]] = None,
):
    """
    Verilen tarih aralığında her gün için vardiya başlangıç event'leri ekle.
    shift_schedule format: [{"name": "1. Vardiya", "start": "HH:MM", "end": "HH:MM"}, ...]
    weekend_shifts: {"saturday": [0], "sunday": []}  →  Cumartesi sadece V1, Pazar tatil
                    None ise varsayılan kural uygulanır (Cumartesi V1, Pazar tatil).
    """
    from datetime import timedelta, time as dt_time

    # Varsayılan: Cumartesi yalnızca 1. vardiya, Pazar tamamen tatil
    if weekend_shifts is None:
        weekend_shifts = {"saturday": [0], "sunday": []}

    current_date = start_date.date()
    end_date_only = end_date.date()

    while current_date <= end_date_only:
        weekday = current_date.weekday()  # 0=Pazartesi … 5=Cumartesi, 6=Pazar

        if weekday == 6:        # Pazar → genellikle boş liste (tatil)
            allowed = weekend_shifts.get("sunday", [])
        elif weekday == 5:      # Cumartesi → genellikle [0] (sadece 1. vardiya)
            allowed = weekend_shifts.get("saturday", [0])
        else:
            allowed = None      # Hafta içi: tüm vardiyalar çalışır

        for idx, shift in enumerate(shift_schedule):
            if allowed is not None and idx not in allowed:
                continue        # Bu gün bu vardiya çalışmıyor, atla
            try:
                start_str = shift.get("start", "00:00")
                h, m = map(int, start_str.split(":"))
                shift_start_time = datetime.combine(current_date, dt_time(h, m))

                if start_date <= shift_start_time <= end_date:
                    # priority=-10: SHIFT_CHANGE event'i aynı zamandaki diğer event'lerden önce işlenir
                    queue.add_event(
                        time=shift_start_time,
                        event_type=EventType.SHIFT_CHANGE,
                        data={"shift_name": shift.get("name"), "original_data": shift},
                        priority=-10,
                    )
            except (ValueError, AttributeError):
                continue
        current_date += timedelta(days=1)
