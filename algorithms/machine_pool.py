from datetime import datetime, date as dt_date
from typing import List, Dict, Tuple, Optional
from models.machine_state import MachineState

class SharedMachinePool:
    def __init__(self, machine_names: List[str] = ["M1", "M2", "M3", "M4"], initial_time: datetime = datetime.now()):
        self.machines: Dict[str, MachineState] = {}
        for name in machine_names:
            self.machines[name] = MachineState(
                machine_name=name,
                current_job_id=None,
                current_step=None,
                available_at=initial_time,
                last_product_type=None
            )
        # Verimlilik hesabı için her makinenin toplam meşgul süresi (saat)
        self.busy_time: Dict[str, float] = {name: 0.0 for name in machine_names}
        # Setup kararlarında "aynı ürün → setup yok" kontrolü için son ürün
        self.last_product_ids: Dict[str, Optional[str]] = {name: None for name in machine_names}
        # Günlük ilk kullanım setup'ı takibi; None ise makine bugün hiç çalışmadı
        self.last_work_dates: Dict[str, Optional[dt_date]] = {name: None for name in machine_names}

    def get_free_machines(self, at_time: datetime) -> List[MachineState]:
        # available_at <= şimdiki zaman olan makineler boş sayılır
        return [m for m in self.machines.values() if m.available_at <= at_time]

    def get_next_free(self) -> Tuple[MachineState, datetime]:
        # En erken boşalacak makineyi bul (ek üretim planlamasında kullanılır)
        machine = min(self.machines.values(), key=lambda m: m.available_at)
        return machine, machine.available_at

    def get_machines_free_within(self, hours: float, current_time: datetime) -> List[MachineState]:
        import datetime as dt
        deadline = current_time + dt.timedelta(hours=hours)
        return [m for m in self.machines.values() if m.available_at <= deadline]

    def needs_initial_setup(self, machine_name: str) -> bool:
        """Makine bu planlama çalışmasında hiç kullanılmadıysa True döner."""
        # last_work_dates None ise makineye bugün hiç iş atanmamış → 1 saatlik günlük setup gerekir
        return self.last_work_dates.get(machine_name) is None

    def assign(self, machine_name: str, step: str, product_id: str, product_type: str,
               start_time: datetime, end_time: datetime, job_id: str):
        m = self.machines[machine_name]
        m.available_at = end_time       # Makine bu işi bitirene kadar meşgul
        m.last_product_type = product_type
        m.current_step = step
        m.current_job_id = job_id
        self.last_product_ids[machine_name] = product_id  # Sonraki setup kararı için sakla

        duration = (end_time - start_time).total_seconds() / 3600.0
        self.busy_time[machine_name] += duration  # Verimlilik raporu için birikimli süre

        # Günlük çalışma tarihini güncelle (setup gereksinim takibi için)
        self.last_work_dates[machine_name] = start_time.date()

    def get_machine(self, name: str) -> Optional[MachineState]:
        return self.machines.get(name)

    def all_busy(self, at_time: datetime) -> bool:
        return all(m.available_at > at_time for m in self.machines.values())

    def get_utilization(self, total_time_hours: float) -> Dict[str, float]:
        # Makine verimlilik yüzdesi: toplam_meşgul_süre / toplam_simülasyon_süresi
        if total_time_hours <= 0:
            return {name: 0.0 for name in self.machines}
        util = {}
        for name, busy in self.busy_time.items():
            util[name] = min(1.0, busy / total_time_hours) * 100.0
        return util
