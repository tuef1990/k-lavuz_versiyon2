from datetime import datetime, timedelta
from typing import List, Dict, Tuple, Optional, Union, Any
from models.job import Job
from models.schedule_entry import ScheduleEntry
from models.setup_matrix import SetupMatrix
from algorithms.base import NEXT_STEP

class BnPlanner:
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
        wait_start_time: Optional[datetime] = None,
        wait_threshold_hours: float = 1.5,
        shift_end_time: Optional[datetime] = None,
        next_shift_start_time: Optional[datetime] = None,
        logger: Optional[Any] = None,
        product_index_map: Optional[Dict[str, int]] = None,
    ) -> Tuple[List[ScheduleEntry], List[Job], datetime, Optional[str], Optional[datetime]]:
        
        if machine_available_at > current_time:
            return [], [], machine_available_at, last_product_id, None

        # Şu anki zaman aktif vardiya dışındaysa batch başlatma
        if shift_end_time is not None and shift_end_time <= current_time:
            wait_target = next_shift_start_time if next_shift_start_time else shift_end_time
            return [], [], wait_target, last_product_id, None

        ready_jobs = [j for j in waiting_jobs if j.ready_time <= current_time]
        if not ready_jobs:
            return [], [], machine_available_at, last_product_id, None

        # 1. İşleri grupla:
        # 1) group_id varsa kullan
        # 2) yoksa product_id (canonical_pid) → aynı tipten Excel ürünleri tek batch
        # 3) son fallback: product_name
        def _gkey(job):
            if getattr(job, "group_id", None):
                return job.group_id
            if getattr(job, "product_id", None):
                return job.product_id
            return job.product_name

        groups_by_name = {}
        for job in ready_jobs:
            key = _gkey(job)
            if key not in groups_by_name:
                groups_by_name[key] = []
            groups_by_name[key].append(job)

        group_priorities = []
        for name, jobs in groups_by_name.items():
            max_prio = max(j.priority_score for j in jobs)
            jobs.sort(key=lambda x: x.priority_score, reverse=True)
            group_priorities.append((max_prio, name, jobs))

        # 2. En yüksek öncelikli grubu belirle
        # Tie-break (Assembly ile aynı mantık):
        #   1) priority desc
        #   2) son işlenen ürün varsa → devam ettir (setup yok)
        #   3) Ürün Bilgileri tablosundaki indeks (küçük önce)
        idx_map = product_index_map or {}
        def _group_sort_key(group_tuple):
            max_prio, _key, jobs = group_tuple
            primary_pid = jobs[0].product_id
            return (
                -max_prio,
                0 if last_product_id is not None and primary_pid == last_product_id else 1,
                idx_map.get(primary_pid, 999),
            )

        group_priorities.sort(key=_group_sort_key)
        best_prio, best_name, best_jobs = group_priorities[0]

        primary_job = best_jobs[0]
        current_capacity = shift_capacity.get(primary_job.product_id, 1) if isinstance(shift_capacity, dict) else (shift_capacity if shift_capacity > 0 else 1)
        current_capacity = int(current_capacity)

        # 3. Bekleme Kontrolü: Kapasite dolmadıysa ve yakında aynı üründen daha fazla parça
        # gelecekse bekle; B/N uzun sürdüğünden boş çalıştırmak verimsizdir
        if len(best_jobs) < current_capacity:
            future_jobs = [
                j for j in waiting_jobs
                if _gkey(j) == best_name
                and current_time < j.ready_time <= current_time + timedelta(hours=wait_threshold_hours)
            ]

            if future_jobs:
                if logger:
                    logger.add_log(
                        current_time, "B/N_KARAR_DETAY",
                        f"[B/N] {best_name} bekleniyor. "
                        f"Mevcut: {len(best_jobs)}/{current_capacity} parça (%{len(best_jobs)/current_capacity*100:.0f}). "
                        f"{wait_threshold_hours:.1f} saat içinde {len(future_jobs)} parça daha gelecek, "
                        f"kapasite dolsun diye bekleniyor.",
                        "B/N"
                    )
                return [], [], machine_available_at, last_product_id, None

        # 4. İşleme Al: Kapasite doluysa veya 1 saat içinde beklenen parça yoksa
        take_count = min(current_capacity, len(best_jobs))
        selected_jobs = best_jobs[:take_count]

        if logger:
            fill = len(selected_jobs) / current_capacity * 100 if current_capacity > 0 else 0
            future_check = [
                j for j in waiting_jobs
                if _gkey(j) == best_name
                and current_time < j.ready_time <= current_time + timedelta(hours=wait_threshold_hours)
            ]
            no_future_note = (
                f" {wait_threshold_hours:.1f} saat içinde gelecek parça yok, mevcut dolulukla işleme alındı."
                if not future_check and len(best_jobs) < current_capacity
                else ""
            )
            logger.add_log(
                current_time, "B/N_KARAR_DETAY",
                f"[B/N] {best_name} işleme alındı. "
                f"Doluluk: {len(selected_jobs)}/{current_capacity} = %{fill:.0f}. "
                f"Kuyrukta {len(ready_jobs)} hazır iş vardı.{no_future_note}",
                "B/N"
            )

        setup_time = 0.0 # B/N'de setup kaldırılmıştı
        actual_start = current_time

        process_time = max(job.remaining_work_hours if job.remaining_work_hours > 0 else production_times.get(job.product_id, 0.0) for job in selected_jobs)
        end_time = actual_start + timedelta(hours=process_time)

        # B/N işlemi 12+ saat sürer, doğası gereği birden fazla vardiyayı kapsar;
        # Assembly/FTP'deki gibi vardiya sonu erteleme yapılmaz

        entries = []
        updated_jobs = []
        for job in selected_jobs:
            entry = ScheduleEntry(
                job_id=job.job_id,
                product_type=job.product_type,
                product_name=job.product_name, # Yeni alan
                step_name="bn",
                machine_name="B/N",
                start_time=actual_start,
                end_time=end_time,
                setup_time=0.0,
                process_time=process_time,
                group_size=len(selected_jobs),
                shift_number=shift_number,
                priority_level=job.priority_score,
                is_priority_override=job.is_priority_override,
                machine_capacity=current_capacity
            )
            entries.append(entry)
            
            job.ready_time = end_time
            job.current_step = NEXT_STEP.get("bn", "dkk")
            job.completed_steps.append("bn")
            updated_jobs.append(job)

        # Seçilen ilk ürünün id'sini last_product_id olarak dönüyoruz
        scheduled_pid = selected_jobs[0].product_id if selected_jobs else last_product_id

        return entries, updated_jobs, end_time, scheduled_pid, None
