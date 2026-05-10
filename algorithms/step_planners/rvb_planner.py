"""
RVB Planner — Doluluk-Tabanlı Tek Makine Atama + Günlük Setup
"""

from datetime import datetime, timedelta, date as dt_date
from typing import List, Dict, Tuple, Optional, Union, Any
from models.job import Job
from models.schedule_entry import ScheduleEntry
from models.setup_matrix import SetupMatrix
from algorithms.base import NEXT_STEP, DAILY_INITIAL_SETUP_HOURS
from algorithms.utils.group_builder import GroupBuilder


class RvbPlanner:
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
        # Şu anki zaman aktif vardiya dışındaysa batch başlatma
        if shift_end_time is not None and shift_end_time <= current_time:
            wait_target = next_shift_start_time if next_shift_start_time else shift_end_time
            return [], [], wait_target, last_product_id

        # Makine bu vardiya bitmeden önce boşalmıyorsa: yeni iş açma. Vardiya içinde başlamış
        # uzun batch'in mesai dışına taşması serbest, ama o iş bittikten sonra bir sonraki
        # çalışan vardiyaya kadar başka iş atanmaz.
        if shift_end_time is not None and machine_available_at >= shift_end_time:
            wait_target = next_shift_start_time if next_shift_start_time else machine_available_at
            return [], [], wait_target, last_product_id

        # Hiç iş yoksa atama yapılamaz (ne hazır ne de gelecek)
        if not waiting_jobs:
            return [], [], machine_available_at, last_product_id

        # Aday havuzu: hazır olanlar varsa onları kullan, yoksa gelecekteki en yakın işler
        # Makine doluyken erken çıkış kaldırıldı — atama geleceğe yansıtılır
        ready_jobs = [j for j in waiting_jobs if j.ready_time <= current_time]
        if not ready_jobs:
            ready_jobs = sorted(waiting_jobs, key=lambda j: (j.ready_time, -j.priority_score))

        group_res = GroupBuilder.build_group(
            waiting_jobs=ready_jobs,
            full_queue=waiting_jobs,
            capacity=shift_capacity,
            last_product_id=last_product_id,
            setup_matrix=setup_matrix,
            current_time=current_time,
            product_index_map=product_index_map,
        )

        if group_res.should_wait:
            return [], [], machine_available_at, last_product_id

        if not group_res.selected_jobs:
            return [], [], machine_available_at, last_product_id

        # İlk kullanım setup'ı: RVB o planlama döneminde ilk kez devreye giriyorsa 1 saat eklenir
        # (last_work_date None ise o güne kadar hiç çalışmamış)
        daily_setup = 0.0
        if last_work_date is None:
            daily_setup = DAILY_INITIAL_SETUP_HOURS

        total_setup = daily_setup + group_res.setup_time

        # Excel'den gelen "devam eden iş": makine zaten bu ürünü işliyordu, setup saymak hatalı olur.
        # İki kriter:
        #   1) preferred_machine == "RVB" (Excel'de açıkça belirtilmiş)
        #   2) remaining_work_hours > 0 (Excel job'u RVB adımında kısmi tamamlanmış)
        def _is_continuing(j):
            if getattr(j, 'preferred_machine', None) == "RVB":
                return True
            if "||Excel" in (j.job_id or "") and getattr(j, 'remaining_work_hours', 0) > 0:
                return True
            return False

        if any(_is_continuing(j) for j in group_res.selected_jobs):
            # Devam eden iş — hiçbir setup yok (initial dahil)
            total_setup = 0.0
            daily_setup = 0.0
            group_res.setup_time = 0.0

        if logger:
            if total_setup <= 0:
                setup_detail = " | Setup yok."
            elif daily_setup > 0 and group_res.setup_time > 0:
                setup_detail = (
                    f" | İlk kullanım setup: {daily_setup:.1f} saat"
                    f" + Ürünler arası geçiş: {group_res.setup_time:.1f} saat"
                    f" = Toplam {total_setup:.1f} saat."
                )
            elif daily_setup > 0:
                setup_detail = f" | İlk kullanım setup: {daily_setup:.1f} saat."
            else:
                setup_detail = f" | Ürünler arası geçiş setup: {group_res.setup_time:.1f} saat."
            logger.add_log(
                current_time,
                "RVB_KARAR_DETAY",
                f"[RVB] {group_res.selected_jobs[0].product_type} → "
                f"{group_res.reason_detail}{setup_detail}",
                "RVB"
            )

        # Başlangıç: max(şimdi, makine müsait, seçili işlerin en geç ready_time'ı)
        # Makine doluysa veya işler henüz gelmediyse bu max gelecek bir zamanı verir
        latest_ready = max((j.ready_time for j in group_res.selected_jobs), default=current_time)
        start_with_setup = max(current_time, machine_available_at, latest_ready)

        # start_with_setup vardiya bitiminin sonrasına düşüyorsa (örn. parça vardiya
        # bitiminden sonra geliyor): yeni iş açma, sonraki çalışan vardiyaya kadar bekle.
        if shift_end_time is not None and start_with_setup >= shift_end_time:
            wait_target = next_shift_start_time if next_shift_start_time else start_with_setup
            return [], [], wait_target, last_product_id

        actual_start = start_with_setup + timedelta(hours=total_setup)

        process_time = 0.0
        for job in group_res.selected_jobs:
            t = job.remaining_work_hours if job.remaining_work_hours > 0 else production_times.get(job.product_id, 0.0)
            if t > process_time:
                process_time = t
        if process_time <= 0:
            process_time = 0.1

        end_time = actual_start + timedelta(hours=process_time)

        entries = []
        updated_jobs = []
        first_job = group_res.selected_jobs[0]

        rvb_cap = (shift_capacity.get(first_job.product_id, 1)
                   if isinstance(shift_capacity, dict) else int(shift_capacity or 1))
        for job in group_res.selected_jobs:
            is_first = job == first_job
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
                group_size=len(group_res.selected_jobs),
                shift_number=shift_number,
                priority_level=job.priority_score,
                is_priority_override=job.is_priority_override,
                machine_capacity=rvb_cap,
                initial_setup_time=daily_setup if is_first else 0.0,
                transition_setup_time=group_res.setup_time if is_first else 0.0,
            )
            entries.append(entry)

            job.ready_time = end_time
            job.current_step = NEXT_STEP.get("rvb", "atp_stp")
            job.completed_steps.append("rvb")
            updated_jobs.append(job)

        return entries, updated_jobs, end_time, group_res.selected_product_id
