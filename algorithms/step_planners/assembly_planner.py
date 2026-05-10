from datetime import datetime, timedelta
from typing import List, Dict, Tuple, Optional, Union, Any
from models.job import Job
from models.schedule_entry import ScheduleEntry
from algorithms.base import NEXT_STEP

class AssemblyPlanner:
    @staticmethod
    def plan(
        waiting_jobs: List[Job],
        current_time: datetime,
        machine_available_at: datetime,
        shift_capacity: Union[int, Dict[str, int]],
        production_times: Dict[str, float],
        remaining_counts: Dict[str, int],
        shift_number: int,
        assembly_state: Dict[str, Any],
        shift_end_time: Optional[datetime] = None,
        next_shift_start_time: Optional[datetime] = None,
        ftp_last_product_id: Optional[str] = None,
        setup_matrix: Optional['SetupMatrix'] = None,
        logger: Optional[Any] = None,
        pause_aware_segments_fn: Optional[Any] = None,
        product_index_map: Optional[Dict[str, int]] = None
    ) -> Tuple[List[ScheduleEntry], List[Job], Dict[str, int], datetime, Optional[str]]:
        new_remaining_counts = remaining_counts.copy()

        if machine_available_at > current_time:
            return [], [], new_remaining_counts, machine_available_at, None

        # Şu anki zaman aktif vardiya dışındaysa (örn. cumartesi V2/V3) batch başlatma
        if shift_end_time is not None and shift_end_time <= current_time:
            wait_target = next_shift_start_time if next_shift_start_time else shift_end_time
            return [], [], new_remaining_counts, wait_target, None

        ready_jobs = [j for j in waiting_jobs if j.ready_time <= current_time]
        if not ready_jobs:
            return [], [], new_remaining_counts, machine_available_at, None

        # remaining_in_chunk: kampanya ortasında vardiyanın dolup taşmasını önler;
        # bir sonraki vardiya aynı kampanyadan kaldığı yerden devam eder
        if "remaining_in_chunk" not in assembly_state:
            assembly_state["remaining_in_chunk"] = {}

        # 1. İşi gruplama anahtarına göre grupla:
        # 1) group_id varsa kullan (Excel'de virgülle ayrılan birden fazla isim aynı group_id paylaşır)
        # 2) yoksa product_id (canonical_pid) → aynı tipten Excel ürünleri otomatik tek batch
        # 3) en sonunda product_name'e fallback
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

        all_chunks = []

        # 2. Her grubun içindeki işleri önceliğe göre sırala ve dinamik paketlere böl
        for name, jobs in groups_by_name.items():
            jobs.sort(key=lambda x: x.priority_score, reverse=True)

            first_chunk_size = assembly_state["remaining_in_chunk"].get(name, 8)
            is_carryover = False
            if first_chunk_size < 8 and first_chunk_size > 0:
                # Önceki vardiyadan yarım kalan kampanya paketi var; tamamlanana kadar önceliklendir
                is_carryover = True
            else:
                first_chunk_size = 8

            # İlk paketi oluştur
            if jobs:
                first_chunk = jobs[:first_chunk_size]
                chunk_priority = first_chunk[0].priority_score
                all_chunks.append((is_carryover, chunk_priority, name, first_chunk))

            # Geri kalanları standart 8'erli paketler olarak ekle
            for i in range(first_chunk_size, len(jobs), 8):
                chunk = jobs[i:i+8]
                chunk_priority = chunk[0].priority_score
                all_chunks.append((False, chunk_priority, name, chunk))

        # 3. Sıralama:
        #    1) Priority desc (yüksek öncelikli önce)
        #    2) Tie-break: makinenin son işlediği ürün → devam ettir (downstream setup tasarrufu)
        #    3) Tie-break: ürün bilgileri tablosundaki sıra (küçük indeks önce)
        last_pid = assembly_state.get("last_product_id")
        idx_map = product_index_map or {}
        all_chunks.sort(key=lambda x: (
            -x[1],
            0 if last_pid is not None and x[3][0].product_id == last_pid else 1,
            idx_map.get(x[3][0].product_id, 999),
        ))

        # Makine kapasitesini seçilen ilk ürün grubuna göre belirle
        primary_is_carryover = all_chunks[0][0]
        primary_job = all_chunks[0][3][0]
        current_capacity = shift_capacity.get(primary_job.product_id, 1) if isinstance(shift_capacity, dict) else (shift_capacity if shift_capacity > 0 else 1)
        current_capacity = int(current_capacity)

        selected_jobs = []
        remaining_capacity = current_capacity
        temporary_state_updates = {}

        # 4. Makine kapasitesi dolana kadar SADECE birincil ürünün paketlerinden al
        # (Karışık batch yerine tek ürün — recalc her batch sonrası priority'ye göre seçim yapacak)
        primary_name = all_chunks[0][2]
        for _, chunk_priority, name, chunk in all_chunks:
            if remaining_capacity <= 0:
                break
            if name != primary_name:
                break  # Başka ürüne geçme; bu batch tek ürün olacak

            take_count = min(len(chunk), remaining_capacity)

            if take_count > 0:
                selected_jobs.extend(chunk[:take_count])
                remaining_capacity -= take_count

                left_in_chunk = len(chunk) - take_count
                if left_in_chunk > 0:
                    temporary_state_updates[name] = left_in_chunk
                else:
                    temporary_state_updates[name] = 8
                
        if not selected_jobs:
            return [], [], new_remaining_counts, machine_available_at, None

        entries = []
        updated_jobs = []

        # Seçilen tüm ürünler o turla (batch) aynı anda işlenecek
        process_time = max((job.remaining_work_hours if job.remaining_work_hours > 0 else production_times.get(job.product_id, 0.0) for job in selected_jobs), default=0.0)

        actual_start = current_time
        # Assembly insan işi: vardiya bitince batch durur, sonraki vardiyada devam eder.
        # pause_aware_segments_fn ile çalışma aralıklarını segmentlere böl.
        if pause_aware_segments_fn is not None:
            segments = pause_aware_segments_fn(actual_start, process_time)
            if not segments:
                segments = [(actual_start, actual_start + timedelta(hours=process_time))]
        else:
            segments = [(actual_start, actual_start + timedelta(hours=process_time))]
        end_time = segments[-1][1]
        setup_time = 0.0 # Her zaman sıfır

        if logger:
            primary_job = selected_jobs[0]
            is_excel = "||Excel" in primary_job.job_id
            origin_info = " (Excel)" if is_excel else ""
            cap_used = shift_capacity.get(primary_job.product_id, 1) if isinstance(shift_capacity, dict) else shift_capacity
            fill = len(selected_jobs) / cap_used * 100 if cap_used > 0 else 0
            carryover_note = " (Yarım kalan paketten devam)" if primary_is_carryover else ""
            logger.add_log(
                current_time, "ASSEMBLY_KARAR_DETAY",
                f"[Assembly] {primary_job.product_type}{origin_info} işleme alındı{carryover_note}. "
                f"Öncelik: {primary_job.priority_score:.2f}. "
                f"Seçilen: {len(selected_jobs)} parça / {len(ready_jobs)} aday. "
                f"Makine doluluk: {len(selected_jobs)}/{cap_used} = %{fill:.0f}.",
                "Assembly"
            )
            
        # VARDİYA BAŞARIYLA ONAYLANDI: Kalan paket hesabını hafızaya (state) kalıcı olarak kaydet
        for name, val in temporary_state_updates.items():
            assembly_state["remaining_in_chunk"][name] = val
        
        for job in selected_jobs:
            # Her segment için ayrı entry yaz; pause aralıkları Gantt'ta boşluk olarak görünür.
            for seg_idx, (seg_start, seg_end) in enumerate(segments):
                seg_process = (seg_end - seg_start).total_seconds() / 3600.0
                entry = ScheduleEntry(
                    job_id=job.job_id,
                    product_type=job.product_type,
                    product_name=job.product_name,
                    step_name="assembly",
                    machine_name="Assembly",
                    start_time=seg_start,
                    end_time=seg_end,
                    setup_time=setup_time if seg_idx == 0 else 0.0,
                    process_time=seg_process,
                    group_size=len(selected_jobs),
                    shift_number=shift_number,
                    priority_level=job.priority_score,
                    is_priority_override=job.is_priority_override,
                    machine_capacity=current_capacity
                )
                entries.append(entry)

            job.ready_time = end_time
            job.current_step = NEXT_STEP.get("assembly", "ftp")
            job.completed_steps.append("assembly")
            updated_jobs.append(job)

            if job.product_type in new_remaining_counts:
                new_remaining_counts[job.product_type] -= 1

        scheduled_pid = selected_jobs[0].product_id if selected_jobs else None
        # Tie-breaker için makinenin son işlediği ürünü kaydet
        if scheduled_pid is not None:
            assembly_state["last_product_id"] = scheduled_pid

        return entries, updated_jobs, new_remaining_counts, end_time, scheduled_pid
