from datetime import datetime, timedelta
from typing import List, Dict, Tuple, Optional, Any
from models.job import Job
from models.schedule_entry import ScheduleEntry
from models.setup_matrix import SetupMatrix
from algorithms.base import NEXT_STEP

class FtpPlanner:
    @staticmethod
    def plan(
        waiting_jobs: List[Job],
        current_time: datetime,
        machine_available_at: datetime,
        last_product_id: Optional[str],
        production_times: Dict[str, float],
        setup_matrix: SetupMatrix,
        shift_number: int,
        ftp_state: Dict[str, Any],
        shift_end_time: Optional[datetime] = None,
        next_shift_start_time: Optional[datetime] = None,
        logger: Optional[Any] = None,
    ) -> Tuple[List[ScheduleEntry], List[Job], datetime, Optional[str]]:

        # Makine henüz boşalmadıysa: müsait olduğu zamanı wait_target olarak döndür.
        # Eğer müsait olma zamanı vardiya bitiminden sonraysa: doğrudan sonraki çalışan
        # vardiyaya işaret et — vardiya içinde başlamış uzun bir batch'in taşması serbest,
        # ama bittikten sonra yeni iş açılmaz.
        if machine_available_at > current_time:
            wait_target = machine_available_at
            if shift_end_time is not None and machine_available_at >= shift_end_time:
                wait_target = next_shift_start_time if next_shift_start_time else machine_available_at
            return [], [], wait_target, last_product_id

        # Şu anki zaman aktif vardiya dışındaysa batch başlatma
        if shift_end_time is not None and shift_end_time <= current_time:
            wait_target = next_shift_start_time if next_shift_start_time else shift_end_time
            return [], [], wait_target, last_product_id

        ready_jobs = [j for j in waiting_jobs if j.ready_time <= current_time]
        if not ready_jobs:
            return [], [], machine_available_at, last_product_id

        # FTP: kapasite=1, FIFO mantığı — Assembly hangi sırayla ürettiyse o sırayla işle.
        # ready_time = Assembly batch bitiş zamanı; erken biten önce.
        # Tie-break sırası:
        #   1) ready_time (erken hazır olan önce)
        #   2) priority_score (yüksek önce)
        #   3) excel_order (Excel'den gelenler için satır sırası — aa, bb, kl gibi
        #      farklı isimlerde deterministik düzen sağlar; 0 = Excel değil, sıfırlar
        #      önce gelir)
        #   4) job_id (final fallback, deterministik)
        ready_jobs.sort(key=lambda j: (
            j.ready_time, -j.priority_score, j.excel_order or 0, j.job_id
        ))
        job = ready_jobs[0]
        selected_jobs = [job]

        if logger:
            logger.add_log(
                current_time, "FTP_KARAR_DETAY",
                f"Seçilen: {job.product_type} | FIFO sırasıyla (Assembly bitiş: {job.ready_time}, "
                f"priority {job.priority_score:.2f}).",
                "FTP",
            )
        setup_time = 0.0

        actual_start = max(current_time, machine_available_at)

        # Savunmacı: actual_start vardiya bitiminden sonrasıysa yeni iş açma.
        # (Üst kontrollerle yakalanmalı; emniyet için.)
        if shift_end_time is not None and actual_start >= shift_end_time:
            wait_target = next_shift_start_time if next_shift_start_time else actual_start
            return [], [], wait_target, last_product_id

        process_time = job.remaining_work_hours if job.remaining_work_hours > 0 else production_times.get(job.product_id, 0.0)
        end_time = actual_start + timedelta(hours=process_time)

        entry = ScheduleEntry(
            job_id=job.job_id,
            product_type=job.product_type,
            product_name=job.product_name,
            step_name="ftp",
            machine_name="FTP",
            start_time=actual_start,
            end_time=end_time,
            setup_time=setup_time,
            process_time=process_time,
            group_size=1,
            shift_number=shift_number,
            priority_level=job.priority_score,
            is_priority_override=job.is_priority_override,
            machine_capacity=1
        )

        job.ready_time = end_time
        job.current_step = NEXT_STEP.get("ftp", "bn")
        job.completed_steps.append("ftp")

        return [entry], [job], end_time, job.product_id
