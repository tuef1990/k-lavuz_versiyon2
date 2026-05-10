"""
RVB Planner V2 — DkkAtpPlannerV2 ile aynı KURAL-2 / KURAL-3 mantığı, tek makine.

Tek makine olduğu için KURAL-1 (Hold — bir başka meşgul makinenin yakında bitmesini
bekleme) uygulanmaz; doğrudan KURAL-2 (geçmişi olan makine: aynı türde iş ara,
doluluk %60'tan azsa 1 saat bekle) veya KURAL-3 (geçmişsiz makine: en yüksek
öncelikli işi al) çalışır.
"""

from datetime import datetime, timedelta, date as dt_date
from typing import List, Dict, Tuple, Optional, Union, Any
from models.job import Job
from models.schedule_entry import ScheduleEntry
from models.setup_matrix import SetupMatrix
from algorithms.base import NEXT_STEP, DAILY_INITIAL_SETUP_HOURS


def _setup(setup_matrix: Optional[SetupMatrix], from_pid: Optional[str], to_pid: str) -> float:
    if from_pid is None or setup_matrix is None:
        return 0.0
    try:
        return float(setup_matrix.matrix.get(from_pid, {}).get(to_pid, 0.0))
    except Exception:
        return 0.0


def _cap(capacity: Union[int, Dict[str, int]], product_id: str) -> int:
    if isinstance(capacity, dict):
        return max(1, int(capacity.get(product_id, 1)))
    return max(1, int(capacity or 1))


class RvbPlannerV2:
    @staticmethod
    def plan(
        waiting_jobs: List[Job],
        current_time: datetime,
        machine_available_at: datetime,
        last_product_id: Optional[str],
        production_times: Dict[str, float],
        setup_matrix: SetupMatrix,
        shift_capacity: Union[int, Dict[str, int]],
        shift_number: int,
        last_work_date: Optional[dt_date] = None,
        shift_end_time: Optional[datetime] = None,
        next_shift_start_time: Optional[datetime] = None,
        logger: Optional[Any] = None,
        product_index_map: Optional[Dict[str, int]] = None,
    ) -> Tuple[List[ScheduleEntry], List[Job], datetime, Optional[str]]:

        # Aktif vardiya dışındaysa atama yapma
        if shift_end_time is not None and shift_end_time <= current_time:
            wait_target = next_shift_start_time if next_shift_start_time else shift_end_time
            return [], [], wait_target, last_product_id

        # Makine bu vardiya bitmeden önce boşalmıyorsa: yeni iş açma. Vardiya içinde başlamış
        # uzun batch'in mesai dışına taşması serbest, ama o iş bittikten sonra bir sonraki
        # çalışan vardiyaya kadar başka iş atanmaz.
        if shift_end_time is not None and machine_available_at >= shift_end_time:
            wait_target = next_shift_start_time if next_shift_start_time else machine_available_at
            return [], [], wait_target, last_product_id

        # Makine meşgulse atamayı geleceğe yansıt — sadece job'ları kuyrukta yoksa boş dön
        # NOT: ready_jobs filtresi kaldırıldı; gelecekteki ürünler de aday havuzuna girer.
        # Bu sayede tüm parçalar bekliyor olsa bile en yüksek öncelikliye atama yapılır.
        if not waiting_jobs:
            return [], [], machine_available_at, last_product_id

        # Aday havuzu: hazır olanlar varsa onları kullan, yoksa gelecekteki en yakın ürün
        ready_jobs = [j for j in waiting_jobs if j.ready_time <= current_time]
        if not ready_jobs:
            ready_jobs = sorted(waiting_jobs, key=lambda j: (j.ready_time, -j.priority_score))

        has_history = last_product_id is not None and last_work_date is not None
        target_pid: Optional[str] = None
        selected_jobs: List[Job] = []
        transition_setup: float = 0.0

        deadline_1h = current_time + timedelta(hours=1.0)

        # ════════════════════════════════════════════════════════════════
        # KURAL-2: Geçmişi olan makine — aynı türde iş ara
        # ════════════════════════════════════════════════════════════════
        if has_history:
            same_type = [
                j for j in ready_jobs
                if _setup(setup_matrix, last_product_id, j.product_id) == 0.0
            ]
            if same_type:
                best_same = max(same_type, key=lambda j: j.priority_score)
                best_pid = best_same.product_id
                machine_cap = _cap(shift_capacity, best_pid)
                # Aynı ürünün tümü (hazır + 1h içinde gelecek olanlar) batch'e alınır
                pid_group = [
                    j for j in waiting_jobs
                    if j.product_id == best_pid
                    and (j.ready_time <= current_time or j.ready_time <= deadline_1h)
                    and _setup(setup_matrix, last_product_id, j.product_id) == 0.0
                ]
                target_pid = best_pid
                selected_jobs = sorted(pid_group, key=lambda j: j.priority_score, reverse=True)[:machine_cap]
                transition_setup = 0.0
                fill = min(len(selected_jobs), machine_cap) / machine_cap if machine_cap > 0 else 0.0

                if logger:
                    future_count = sum(1 for j in selected_jobs if j.ready_time > current_time)
                    future_note = f" (gelecek {future_count} dahil)" if future_count > 0 else ""
                    logger.add_log(
                        current_time, "RVB_RULE2",
                        f"[KURAL-2][RVB] {best_pid}: aynı tür ürün seçildi. "
                        f"Doluluk %{fill*100:.0f}. {len(selected_jobs)} parça{future_note}.",
                        "RVB",
                    )

            else:
                # Aynı türde yok → en yüksek öncelikliyi al + 1h içindeki future'ı da dahil et
                best_j = max(ready_jobs, key=lambda j: j.priority_score)
                target_pid = best_j.product_id
                pool = [
                    j for j in waiting_jobs
                    if j.product_id == target_pid
                    and (j.ready_time <= current_time or j.ready_time <= deadline_1h)
                ]
                machine_cap = _cap(shift_capacity, target_pid)
                selected_jobs = sorted(pool, key=lambda j: j.priority_score, reverse=True)[:machine_cap]
                transition_setup = _setup(setup_matrix, last_product_id, target_pid)

                if logger:
                    logger.add_log(
                        current_time, "RVB_RULE2",
                        f"[KURAL-2][RVB] Aynı türde iş yok → en yüksek öncelikli {target_pid}. "
                        f"Geçiş setup: {transition_setup:.1f}h. {len(selected_jobs)} parça.",
                        "RVB",
                    )

        # ════════════════════════════════════════════════════════════════
        # KURAL-3: Geçmişsiz makine — en yüksek öncelikliyi al + future dahil
        # ════════════════════════════════════════════════════════════════
        else:
            best_j = max(ready_jobs, key=lambda j: j.priority_score)
            target_pid = best_j.product_id
            pool = [
                j for j in waiting_jobs
                if j.product_id == target_pid
                and (j.ready_time <= current_time or j.ready_time <= deadline_1h)
            ]
            machine_cap = _cap(shift_capacity, target_pid)
            selected_jobs = sorted(pool, key=lambda j: j.priority_score, reverse=True)[:machine_cap]
            transition_setup = 0.0  # geçmiş yok

            if logger:
                future_count = sum(1 for j in selected_jobs if j.ready_time > current_time)
                future_note = f" (gelecek {future_count} dahil)" if future_count > 0 else ""
                logger.add_log(
                    current_time, "RVB_RULE3",
                    f"[KURAL-3][RVB] Geçmiş yok → en yüksek öncelikli {target_pid}. "
                    f"{len(selected_jobs)} parça{future_note}.",
                    "RVB",
                )

        if not selected_jobs:
            return [], [], machine_available_at, last_product_id

        # Setup hesaplaması
        daily_setup = DAILY_INITIAL_SETUP_HOURS if last_work_date is None else 0.0
        total_setup = daily_setup + transition_setup

        # Excel'den gelen devam eden iş: setup yok
        def _is_continuing(j):
            if getattr(j, 'preferred_machine', None) == "RVB":
                return True
            if "||Excel" in (j.job_id or "") and getattr(j, 'remaining_work_hours', 0) > 0:
                return True
            return False

        if any(_is_continuing(j) for j in selected_jobs):
            total_setup = 0.0
            daily_setup = 0.0
            transition_setup = 0.0

        # Başlangıç: max(şimdi, makine müsait, seçili işlerin en geç ready_time'ı)
        # Makine doluysa veya işler henüz gelmediyse bu max gelecek bir zamanı verir
        # → entry'nin start_time'ı geleceğe yansır, bekleme süresi UI'da görünür
        latest_ready = max((j.ready_time for j in selected_jobs), default=current_time)
        start_with_setup = max(current_time, machine_available_at, latest_ready)

        # start_with_setup vardiya bitiminin sonrasına düşüyorsa: yeni iş açma,
        # sonraki çalışan vardiyaya kadar bekle.
        if shift_end_time is not None and start_with_setup >= shift_end_time:
            wait_target = next_shift_start_time if next_shift_start_time else start_with_setup
            return [], [], wait_target, target_pid

        actual_start = start_with_setup + timedelta(hours=total_setup)

        process_time = 0.0
        for job in selected_jobs:
            t = job.remaining_work_hours if job.remaining_work_hours > 0 else production_times.get(job.product_id, 0.0)
            if t > process_time:
                process_time = t
        if process_time <= 0:
            process_time = 0.1

        end_time = actual_start + timedelta(hours=process_time)

        entries: List[ScheduleEntry] = []
        updated_jobs: List[Job] = []
        first_job = selected_jobs[0]

        rvb_cap = _cap(shift_capacity, first_job.product_id)
        for job in selected_jobs:
            is_first = job is first_job
            entry = ScheduleEntry(
                job_id=job.job_id,
                product_type=job.product_type,
                product_name=job.product_name,
                step_name="rvb",
                machine_name="RVB",
                start_time=start_with_setup,
                end_time=end_time,
                setup_time=total_setup if is_first else 0.0,
                process_time=process_time,
                group_size=len(selected_jobs),
                shift_number=shift_number,
                priority_level=job.priority_score,
                is_priority_override=job.is_priority_override,
                machine_capacity=rvb_cap,
                initial_setup_time=daily_setup if is_first else 0.0,
                transition_setup_time=transition_setup if is_first else 0.0,
            )
            entries.append(entry)

            job.ready_time = end_time
            job.current_step = NEXT_STEP.get("rvb", "atp_stp")
            job.completed_steps.append("rvb")
            updated_jobs.append(job)

        return entries, updated_jobs, end_time, target_pid
