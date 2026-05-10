import uuid
from datetime import datetime, timedelta, time as dt_time
from typing import List, Dict, Any, Optional, Set, Tuple
import math

from core.models import AppState, STAGES, VARDIA_INFO
from models.job import Job
from models.schedule_entry import ScheduleEntry
from models.planning_result import PlanningResult
from models.remaining_target import RemainingTarget
from models.setup_matrix import SetupMatrix

from .base import PlanningAlgorithm, PROCESS_STEPS_ORDER, NEXT_STEP
from .priority_calculator import PriorityCalculator
from .utils.event_queue import EventQueue, EventType, Event, add_shift_events
from .utils.audit_logger import PlanningAuditLogger
from .machine_pool import SharedMachinePool
from .step_planners.assembly_planner import AssemblyPlanner
from .step_planners.ftp_planner import FtpPlanner
from .step_planners.bn_planner import BnPlanner
from .step_planners.rvb_planner import RvbPlanner
from .step_planners.dkk_atp_planner import DkkAtpPlanner

class PriorityBasedScheduler(PlanningAlgorithm):
    def solve(
        self,
        project_data: AppState,
        start_date: datetime,
        end_date: datetime,
        period: str,
        priority_overrides: Dict[str, float] | None = None,
        excel_products: Optional[List] = None,
        week_number: int = 0,
        carryover_data: Optional[Dict] = None,
        produced_amounts: Optional[Dict[str, int]] = None,
        excel_only: bool = False,
        extra_production_list: Optional[List[Dict[str, Any]]] = None
    ) -> PlanningResult:
        logger = PlanningAuditLogger()
        logger.add_log(time=start_date, action="BAŞLANGIÇ", details=f"Planlama {start_date} tarihinde başladı. Periyot: {period}", step="BASLANGIC")
        
        # 1. HEDEF HESAPLA ve JOB'LARI OLUŞTUR
        # Her ürün için periyot hedefini hesapla; her hedef adedi bir Job nesnesine karşılık gelir
        all_jobs: List[Job] = []
        product_targets: Dict[str, int] = {}
        remaining_counts: Dict[str, int] = {}  # product_type -> sevkiyat için kalan adet

        effective_carryover = carryover_data or project_data.carryover_data

        _produced = produced_amounts or {}

        def _build_normal_jobs(product, all_jobs, product_targets, remaining_counts):
            """Aylık/haftalık hedef bazında Job'ları oluşturur ve listeye ekler."""
            produced_so_far = _produced.get(product.display_name, 0)
            full_remaining = max(0, product.monthly_target - produced_so_far)

            # Ay 4 hafta kabul edilir; week_number ay içindeki şu anki hafta (0..3).
            # Kalan üretim (4 - week_number) haftaya eşit bölünür.
            weeks_left = max(1, 4 - week_number)

            if period == "weekly":
                target = math.ceil(full_remaining / weeks_left) if full_remaining > 0 else 0
            elif period == "custom":
                target = math.ceil(full_remaining / weeks_left) if full_remaining > 0 else 0
            else:  # monthly
                if produced_so_far > 0:
                    target = full_remaining
                else:
                    target = self.calculate_period_target(product.monthly_target, period, start_date, end_date)

            # remaining_counts:
            # - Aylık modda: aylık hedefin tamamı (hafta no sabit 0)
            # - Haftalık/custom: bu haftanın hedefi (ceil(full_remaining/weeks_left))
            remaining_counts[product.type] = remaining_counts.get(product.type, 0) + target
            product_targets[product.display_name] = product_targets.get(product.display_name, 0) + target

            week_distribution = []
            if period == "monthly":
                chunk_size = math.ceil(target / 4)
                rem = target
                for w in range(4):
                    take = min(chunk_size, rem)
                    rem -= take
                    week_distribution.append((take, week_number + w, ""))
            else:
                week_distribution.append((target, week_number, "||Bu Hafta"))

                # Gelecek haftaya kalan üretimi week_number+1..3 arasına eşit dağıt
                rem = full_remaining - target
                pull_week = week_number + 1
                last_week = 3
                while rem > 0 and pull_week <= last_week:
                    weeks_remaining_for_dist = last_week - pull_week + 1
                    take = math.ceil(rem / weeks_remaining_for_dist)
                    take = min(take, rem)
                    week_distribution.append((take, pull_week, "||Gelecek Hafta"))
                    rem -= take
                    pull_week += 1

            for count, t_week, job_tag in week_distribution:
                for _ in range(count):
                    job = Job(
                        job_id=f"{uuid.uuid4()}{job_tag}",
                        product_id=product.display_name,
                        product_type=product.type,
                        product_name=product.name,
                        priority_score=0.0,
                        is_priority_override=False,
                        current_step="assembly",
                        ready_time=start_date,
                        completed_steps=[],
                        is_completed=False,
                        target_week=t_week
                    )
                    all_jobs.append(job)

        if excel_products:
            # === EXCEL + NORMAL MODU: ikisi birlikte çizelgelenir ===
            # 1a) Excel satırlarından Job'ları oluştur
            for ep in excel_products:
                target = ep.quantity
                product_targets[ep.display_name] = product_targets.get(ep.display_name, 0) + target
                remaining_counts[ep.product_type] = remaining_counts.get(ep.product_type, 0) + target

                job_ready_time = start_date
                if ep.earliest_start_date and ep.earliest_start_date > start_date:
                    job_ready_time = ep.earliest_start_date

                # Hafta numarası hesaplama: başlangıç tarihi varsa haftaya çevir
                if ep.earliest_start_date and ep.earliest_start_date > start_date:
                    delta_days = (ep.earliest_start_date - start_date).days
                    ep_target_week = week_number + max(0, delta_days // 7)
                else:
                    ep_target_week = week_number

                _date_tag = (
                    f"::{ep.earliest_start_date.strftime('%d.%m.%Y')}"
                    if ep.earliest_start_date and ep.earliest_start_date > start_date
                    else ""
                )
                # Canonical pid: aynı tipten birden fazla isim varsa hepsi tek tablo satırını kullanır
                _canonical_pid = getattr(ep, "canonical_pid", None) or ep.display_name
                for idx in range(target):
                    job = Job(
                        job_id=str(uuid.uuid4()) + f"||Excel{_date_tag}",
                        product_id=_canonical_pid,
                        product_type=ep.product_type,
                        product_name=ep.product_name,
                        priority_score=0.0,
                        is_priority_override=False,
                        current_step=ep.current_step if idx == 0 else "assembly",
                        ready_time=job_ready_time,
                        completed_steps=ep.completed_steps.copy() if idx == 0 else [],
                        is_completed=False,
                        remaining_work_hours=ep.remaining_work_hours if idx == 0 else 0.0,
                        target_week=ep_target_week,
                        preferred_machine=ep.preferred_machine if idx == 0 else None,
                        group_id=getattr(ep, "group_id", None)
                    )
                    all_jobs.append(job)
                
                logger.add_log(time=job_ready_time, action="EXCEL_JOB", details=f"{ep.product_type} için {target} adet iş oluşturuldu. İlk parça hazır olma zamanı: {job_ready_time}", step="EXCEL_IMPORT")

            # 1b) Tablodaki ürünleri ekle (excel_only modda atlanır)
            if not excel_only:
                for product in project_data.products:
                    _build_normal_jobs(product, all_jobs, product_targets, remaining_counts)
        else:
            # === NORMAL MOD ===
            for product in project_data.products:
                _build_normal_jobs(product, all_jobs, product_targets, remaining_counts)

        # 2. ÖNCELİK HESAPLA
        initial_remaining = remaining_counts.copy()
        priorities, overridden_ids = PriorityCalculator.calculate_all(
            all_jobs, project_data.production_time_data, start_date, end_date,
            initial_remaining, priority_overrides, week_number=week_number
        )
        for job in all_jobs:
            job.priority_score = priorities.get(job.job_id, 0.5)
            job.initial_priority_score = job.priority_score
            job.is_priority_override = job.job_id in overridden_ids

        # Priority snapshot mekanizması (slider zamanına göre lookup için)
        priority_history: Dict[str, List[tuple]] = {}

        def _job_tag(jid: str) -> str:
            if "||Ek Üretim" in jid: return "Ek Üretim"
            if "||Gelecek Hafta" in jid: return "Gelecek Hafta"
            if "||Excel" in jid: return "Excel"
            if "||Bu Hafta" in jid: return "Bu Hafta"
            return ""

        def _snapshot_priorities(snap_time):
            t_iso = snap_time.isoformat()
            seen = set()
            for j in all_jobs:
                key = f"{j.product_type}||{_job_tag(j.job_id)}"
                if key in seen:
                    continue
                seen.add(key)
                priority_history.setdefault(key, []).append((t_iso, j.priority_score))

        _snapshot_priorities(start_date)


        # 3. KUYRUKLARI VE DURUMLARI BAŞLAT
        queues = {step: [] for step in PROCESS_STEPS_ORDER}

        # Excel ürün başlama tarihleri: {product_type: earliest_start_date}
        # Normal jobların ready_time'ını güncellemek için kullanılır.
        excel_earliest_dates: Dict[str, datetime] = {}
        if excel_products:
            for ep in excel_products:
                if ep.earliest_start_date and ep.earliest_start_date > start_date:
                    existing = excel_earliest_dates.get(ep.product_type)
                    if existing is None or ep.earliest_start_date < existing:
                        excel_earliest_dates[ep.product_type] = ep.earliest_start_date

        # Normal jobların ready_time'ını Excel tarihine göre güncelle
        # (Excel jobları zaten job_ready_time ile doğru atandı)
        if excel_earliest_dates:
            for job in all_jobs:
                if (
                    "||Excel" not in job.job_id
                    and "||Gelecek Hafta" not in job.job_id
                    and job.product_type in excel_earliest_dates
                    and job.ready_time <= start_date  # henüz ertelenmemiş
                ):
                    job.ready_time = excel_earliest_dates[job.product_type]

        # Tüm jobları kuyruğa ekle — planlayıcı ready_time ile filtreler
        if excel_products:
            for job in all_jobs:
                target_step = job.current_step if job.current_step in queues else "assembly"
                queues[target_step].append(job)
        else:
            queues["assembly"] = all_jobs.copy()

        # Gelecek hafta işleri target_week'e göre bucket'lara ayrılır; her hafta sırayla release edilir
        _future_jobs: List[Job] = [j for j in queues["assembly"] if "||Gelecek Hafta" in j.job_id]
        queues["assembly"] = [j for j in queues["assembly"] if "||Gelecek Hafta" not in j.job_id]
        from collections import defaultdict as _dd
        _future_by_week: Dict[int, List[Job]] = _dd(list)
        for _j in _future_jobs:
            _future_by_week[_j.target_week].append(_j)
        pending_future_buckets: List[Tuple[int, List[Job]]] = sorted(
            _future_by_week.items(), key=lambda kv: kv[0]
        )

        # Kullanıcı tanımlı ek üretim listesi varsa joblarını üret + kuyruğa ekle
        _user_extra_list = extra_production_list or []
        if _user_extra_list:
            extra_jobs_buf: List[Job] = []
            for _idx, _item in enumerate(_user_extra_list):
                _ptype = (_item.get("product_type") or "").strip()
                _pname_raw = (_item.get("product_name") or _item.get("product_id") or "").strip()
                _qty = int(_item.get("qty") or 0)
                if not _pname_raw or _qty <= 0:
                    continue
                _product = next((p for p in project_data.products if p.display_name == _pname_raw), None)
                if _product is not None:
                    _final_id = _product.display_name
                    _final_type = _product.type
                    _final_name = f"{_product.name} [Ek #{_idx+1}]"
                else:
                    if not _ptype:
                        continue
                    _final_id = _pname_raw
                    _final_type = _ptype
                    _final_name = f"{_pname_raw} [Ek #{_idx+1}]"
                _prio = -1.0 - _idx * 0.001
                for _ in range(_qty):
                    extra_jobs_buf.append(Job(
                        job_id=f"{uuid.uuid4()}||Ek Üretim",
                        product_id=_final_id,
                        product_type=_final_type,
                        product_name=_final_name,
                        priority_score=_prio,
                        is_priority_override=True,
                        current_step="assembly",
                        ready_time=start_date,
                        completed_steps=[],
                        is_completed=False,
                        target_week=9999,
                        initial_priority_score=_prio,
                    ))
            all_jobs.extend(extra_jobs_buf)
            # Ek üretim joblarını ayrı bekletme listesine al — sadece TÜM aylık hedef bittiğinde release.
            pending_extra_jobs: List[Job] = list(extra_jobs_buf)
            logger.add_log(time=start_date, action="EK_ÜRETİM_LİSTESİ_YÜKLENDİ",
                           details=f"Kullanıcı listesinden {len(extra_jobs_buf)} ek üretim job'u oluşturuldu (aylık hedef sonrası release).",
                           step="ASSEMBLY")
        else:
            pending_extra_jobs: List[Job] = []
        
        machine_pool = SharedMachinePool(initial_time=start_date)
        assembly_state = {"available_at": start_date, "current_campaign_product": None, "campaign_count": 0, "last_product_id": None}
        ftp_state = {"available_at": start_date, "last_product_id": None}
        bn_state = {"available_at": start_date, "last_product_id": None, "wait_start": None}
        rvb_state = {"available_at": start_date, "last_product_id": None, "last_work_date": None}

        event_queue = EventQueue()
        event_queue.add_event(start_date, EventType.PARTS_READY, {"step": "assembly"})

        if excel_products:
            for step_name in PROCESS_STEPS_ORDER:
                if queues[step_name]:
                    event_queue.add_event(start_date, EventType.PARTS_READY, {"step": step_name})

            # earliest_start_date olan ürünler için simülasyonun tam tarihte tepki vermesini garantile
            seen_early_dates: set = set()
            for ep in excel_products:
                if ep.earliest_start_date and ep.earliest_start_date > start_date:
                    if ep.earliest_start_date not in seen_early_dates:
                        seen_early_dates.add(ep.earliest_start_date)
                        # Assembly ve ürünün mevcut adımı için event ekle
                        event_queue.add_event(ep.earliest_start_date, EventType.PARTS_READY, {"step": "assembly"})
                        if ep.current_step != "assembly" and ep.current_step in PROCESS_STEPS_ORDER:
                            event_queue.add_event(ep.earliest_start_date, EventType.PARTS_READY, {"step": ep.current_step})

        shift_schedule = project_data.shift_data.get("Assembly", [])
        weekend_shifts = getattr(project_data, "weekend_shifts", {"saturday": [0], "sunday": []})
        add_shift_events(event_queue, start_date, end_date, shift_schedule, weekend_shifts)

        all_entries: List[ScheduleEntry] = []
        current_time = start_date
        prod_times = project_data.production_time_data
        
        product_ids = [p.display_name for p in project_data.products]
        if excel_products:
            excel_product_ids = [ep.display_name for ep in excel_products]
            product_ids = list(set(product_ids + excel_product_ids))
        
        setup_matrix_obj = SetupMatrix(
            product_ids=product_ids,
            matrix=project_data.setup_matrix
        )

        # Aynı öncelikli ürünler arasındaki tie-break için tablo sırası
        product_index_map: Dict[str, int] = {
            p.display_name: i for i, p in enumerate(project_data.products)
        }
        if excel_products:
            for i, ep in enumerate(excel_products, start=len(product_index_map)):
                if ep.display_name not in product_index_map:
                    product_index_map[ep.display_name] = i

        expected_ftp_product_id = None
        
        _remaining_overrides: Dict[str, tuple] = {}
        if excel_products:
            for job in all_jobs:
                if job.remaining_work_hours > 0:
                    _remaining_overrides[job.job_id] = (job.current_step, job.remaining_work_hours)

        # Hafta bazlı öncelik yenileme referansları:
        current_sim_week = week_number
        last_calc_date = start_date

        # --- EK ÜRETİM YARDIMCI FONKSİYONLARI ---
        def _select_ek_uretim_product():
            """Aylık hedeften en çok geride olan ürünü ek üretim için seçer."""
            best_product = None
            best_score = -float('inf')
            for p in project_data.products:
                if p.monthly_target <= 0:
                    continue
                produced = _produced.get(p.display_name, 0)
                completed_now = sum(
                    1 for j in all_jobs
                    if j.product_id == p.display_name
                    and "||Ek Üretim" not in j.job_id
                    and j.is_completed
                )
                remaining = max(0, p.monthly_target - produced - completed_now)
                # Önce kalan miktar, eşitlikte aylık hedef büyük olan kazanır
                score = remaining * 1000 + p.monthly_target
                if score > best_score:
                    best_score = score
                    best_product = p
            return best_product

        def _create_ek_uretim_batch(product, batch_time, batch_size=8):
            """Ek üretim için bir batch iş oluşturur (öncelik: -1.000)."""
            return [
                Job(
                    job_id=f"{uuid.uuid4()}||Ek Üretim",
                    product_id=product.display_name,
                    product_type=product.type,
                    product_name=f"{product.name} [Ek Üretim]",
                    priority_score=-1.000,
                    is_priority_override=True,
                    current_step="assembly",
                    ready_time=batch_time,
                    completed_steps=[],
                    is_completed=False,
                    target_week=9999,
                    initial_priority_score=-1.000
                )
                for _ in range(batch_size)
            ]

        # 4. ANA DÖNGÜ
        max_iterations = 50000
        iteration_count = 0
        
        while not all(job.is_completed for job in all_jobs) and event_queue.has_events():
            iteration_count += 1
            if iteration_count > max_iterations:
                raise RuntimeError(f"Simülasyon sonsuz döngüye girdi veya çok uzun sürdü ({iteration_count} adım). Lütfen verileri kontrol edin.")
            
            event = event_queue.pop_next()
            current_time = event.time
            
            if current_time > end_date:
                break

            # Her 7 günde bir öncelikleri yenile: haftanın ilerlemesiyle kalan/denom değişir
            # Aylık modda hafta sabit kalır — bu blok atlanır
            if period != "monthly" and (current_time - last_calc_date).days >= 7:
                current_sim_week += 1
                last_calc_date = current_time
                # remaining_counts'ı yeni haftanın hedefine resetle
                weeks_left = max(1, 4 - current_sim_week)
                new_remaining = {}
                for j in all_jobs:
                    if not j.is_completed and "||Ek Üretim" not in j.job_id:
                        new_remaining[j.product_type] = new_remaining.get(j.product_type, 0) + 1
                for ptype in remaining_counts:
                    full_rem_now = new_remaining.get(ptype, 0)
                    remaining_counts[ptype] = math.ceil(full_rem_now / weeks_left) if full_rem_now > 0 else 0

                new_priorities, _ = PriorityCalculator.calculate_all(
                    all_jobs, project_data.production_time_data, start_date, end_date,
                    remaining_counts, priority_overrides, week_number=current_sim_week
                )
                for job in all_jobs:
                    if not job.is_completed:
                        job.priority_score = new_priorities.get(job.job_id, job.priority_score)
                _snapshot_priorities(current_time)

            current_shift_idx = self._determine_current_shift(current_time, project_data)
            shift_num = current_shift_idx + 1

            def sync_queues(q_dict):
                for step_name in PROCESS_STEPS_ORDER:
                    for job_item in q_dict[step_name][:]:
                        if job_item.current_step != step_name:
                            q_dict[step_name].remove(job_item)
                            if job_item.current_step in q_dict:
                                q_dict[job_item.current_step].append(job_item)
            
            def _clear_remaining_overrides(processed_jobs: List[Job]):
                for pj in processed_jobs:
                    if pj.job_id in _remaining_overrides:
                        del _remaining_overrides[pj.job_id]
                        pj.remaining_work_hours = 0.0

            sync_queues(queues) # İlk senkronizasyon

            # Gelecek hafta işlerini hafta hafta release et — bir hafta bitmeden sonraki gelmez
            assembly_ready = [j for j in queues["assembly"] if j.ready_time <= current_time]
            if pending_future_buckets and not assembly_ready:
                _next_week, _bucket_jobs = pending_future_buckets.pop(0)
                queues["assembly"].extend(_bucket_jobs)
                logger.add_log(
                    time=current_time, action="YENİ_HAFTA_BAŞLADI",
                    details=f"Önceki haftanın Assembly işleri bitti, Hafta {_next_week} işleri kuyruğa alındı. Toplam {len(_bucket_jobs)} iş.",
                    step="QUEUE_UPDATE"
                )
                event_queue.add_event(current_time, EventType.PARTS_READY, {"step": "assembly"})

            # Ek üretim release: TÜM hafta bucket'ları tükendiğinde
            if pending_extra_jobs and not pending_future_buckets and not assembly_ready:
                released_extra = len(pending_extra_jobs)
                queues["assembly"].extend(pending_extra_jobs)
                pending_extra_jobs.clear()
                logger.add_log(
                    time=current_time, action="EK_ÜRETİM_BAŞLADI",
                    details=f"Aylık hedef tamamlandı, ek üretim listesi devreye alındı. Toplam {released_extra} iş.",
                    step="QUEUE_UPDATE"
                )
                event_queue.add_event(current_time, EventType.PARTS_READY, {"step": "assembly"})

            # NOT: Otomatik ek üretim mantığı kaldırıldı. Ek üretim sadece kullanıcı
            # planlama sayfasında "Ek üretim ekle" işaretleyip liste girdiğinde
            # `extra_production_list` parametresi üzerinden eklenir (yukarıda).

            # --- ASSEMBLY ---
            as_cap = self._get_shift_capacity("Assembly", shift_num, project_data)
            as_times = self._build_effective_times(
                prod_times, "Assembly", "assembly", queues["assembly"], _remaining_overrides)

            shift_end, next_shift_start = self._get_shift_boundaries(current_time, project_data, "Assembly")

            e, j, rc, a_avail, sched_pid = AssemblyPlanner.plan(
                queues["assembly"], current_time, assembly_state["available_at"],
                as_cap, as_times, remaining_counts, shift_num, assembly_state,
                shift_end_time=shift_end, next_shift_start_time=next_shift_start,
                ftp_last_product_id=expected_ftp_product_id, setup_matrix=setup_matrix_obj,
                logger=logger,
                pause_aware_segments_fn=lambda s, d: self._compute_pause_aware_segments(s, d, project_data, "Assembly"),
                product_index_map=product_index_map
            )
            all_entries.extend(e)
            remaining_counts = rc
            assembly_state["available_at"] = a_avail
            if sched_pid: expected_ftp_product_id = sched_pid
            if e:
                _clear_remaining_overrides(j)
                logger.add_log(time=current_time, action="ASSEMBLY_KARAR", details=f"{len(j)} adet parça planlandı. Makine {a_avail} kadar meşgul.", step="ASSEMBLY")
                # Assembly her çalışmasında remaining_counts değişir → öncelikleri hemen güncelle
                new_priorities, _ = PriorityCalculator.calculate_all(
                    all_jobs, project_data.production_time_data, start_date, end_date,
                    remaining_counts, priority_overrides, week_number=current_sim_week
                )
                for job in all_jobs:
                    if not job.is_completed:
                        job.priority_score = new_priorities.get(job.job_id, job.priority_score)
                _snapshot_priorities(a_avail)
                event_queue.add_event(a_avail, EventType.MACHINE_FREE, {"machine": "Assembly"})
                for job in j:
                    event_queue.add_event(job.ready_time, EventType.PARTS_READY, {"job_id": job.job_id, "step": "ftp"})
                sync_queues(queues)

            # --- FTP ---
            ftp_shift_end, ftp_next_start = self._get_shift_boundaries(current_time, project_data, "FTP")
            _ftp_non_work = ftp_shift_end is not None and ftp_shift_end <= current_time
            if _ftp_non_work:
                if ftp_next_start:
                    ftp_state["available_at"] = max(ftp_state["available_at"], ftp_next_start)
            else:
                ftp_times = self._build_effective_times(
                    prod_times, "FTP", "ftp", queues["ftp"], _remaining_overrides)
                e, j, f_avail, f_pid = FtpPlanner.plan(
                    queues["ftp"], current_time, ftp_state["available_at"],
                    ftp_state["last_product_id"], ftp_times, setup_matrix_obj, shift_num, ftp_state,
                    shift_end_time=ftp_shift_end, next_shift_start_time=ftp_next_start,
                    logger=logger)
                all_entries.extend(e)
                ftp_state["available_at"] = f_avail
                ftp_state["last_product_id"] = f_pid
                if e:
                    _clear_remaining_overrides(j)
                    logger.add_log(time=current_time, action="FTP_KARAR", details=f"{j[0].product_type} planlandı. Makine {f_avail} kadar meşgul.", step="FTP")
                    event_queue.add_event(f_avail, EventType.MACHINE_FREE, {"machine": "FTP"})
                    for job in j:
                        event_queue.add_event(job.ready_time, EventType.PARTS_READY, {"job_id": job.job_id, "step": "bn"})
                    sync_queues(queues)

            # --- B/N ---
            bn_shift_end, bn_next_start = self._get_shift_boundaries(current_time, project_data, "B/N")
            _bn_non_work = bn_shift_end is not None and bn_shift_end <= current_time
            if _bn_non_work:
                if bn_next_start:
                    bn_state["available_at"] = max(bn_state["available_at"], bn_next_start)
            else:
                bn_cap = self._get_shift_capacity("B/N", shift_num, project_data)
                bn_times = self._build_effective_times(
                    prod_times, "B/N", "bn", queues["bn"], _remaining_overrides)
                e, j, b_avail, b_pid, b_wait = BnPlanner.plan(
                    queues["bn"], current_time, bn_state["available_at"],
                    bn_state["last_product_id"], bn_times, setup_matrix_obj, bn_cap, shift_num,
                    bn_state["wait_start"],
                    shift_end_time=bn_shift_end, next_shift_start_time=bn_next_start,
                    logger=logger,
                    product_index_map=product_index_map)
                all_entries.extend(e)
                bn_state["available_at"] = b_avail
                bn_state["last_product_id"] = b_pid
                bn_state["wait_start"] = b_wait
                if e:
                    _clear_remaining_overrides(j)
                    logger.add_log(time=current_time, action="B/N_KARAR", details=f"{len(j)} adet parça planlandı. Makine {b_avail} kadar meşgul.", step="B/N")
                    event_queue.add_event(b_avail, EventType.MACHINE_FREE, {"machine": "B/N"})
                    for job in j:
                        event_queue.add_event(job.ready_time, EventType.PARTS_READY, {"job_id": job.job_id, "step": "dkk"})
                    sync_queues(queues)
                elif b_wait:
                    event_queue.add_event(current_time + timedelta(hours=2), EventType.WAIT_TIMEOUT, {"step": "bn"})

            # --- DKK + ATP+STP ---
            dkk_shift_end, dkk_next_start = self._get_shift_boundaries(current_time, project_data, "DKK")
            _dkk_non_work = dkk_shift_end is not None and dkk_shift_end <= current_time
            if _dkk_non_work:
                pass  # machine_pool kendi available_at'ını korur; sonraki çalışma saatinde devam eder
            else:
                dkk_eff_times = self._build_effective_times(prod_times, "DKK", "dkk", queues["dkk"], _remaining_overrides)
                atp_eff_times = self._build_effective_times(prod_times, "ATP+STP", "atp_stp", queues["atp_stp"], _remaining_overrides)
                shared_times = {"dkk": dkk_eff_times, "atp_stp": atp_eff_times}
                shared_caps = {
                    "dkk": self._get_shift_capacity("DKK", shift_num, project_data),
                    "atp_stp": self._get_shift_capacity("ATP+STP", shift_num, project_data)
                }
                e, j_dkk, j_atp = DkkAtpPlanner.plan(queues["dkk"], queues["atp_stp"], machine_pool, current_time,
                                                   shared_times, setup_matrix_obj, shared_caps, shift_num,
                                                   shift_end_time=dkk_shift_end, next_shift_start_time=dkk_next_start,
                                                   logger=logger,
                                                   product_index_map=product_index_map)
                all_entries.extend(e)
                if e:
                    _clear_remaining_overrides(j_dkk)
                    _clear_remaining_overrides(j_atp)
                    logger.add_log(time=current_time, action="DKK_ATP_KARAR", details=f"{len(e)} adet makine görevi atandı.", step="DKK_ATP")
                    for entry in e:
                        event_queue.add_event(entry.end_time, EventType.MACHINE_FREE, {"machine": entry.machine_name})
                    for job in j_dkk:
                        event_queue.add_event(job.ready_time, EventType.PARTS_READY, {"job_id": job.job_id, "step": "rvb"})
                    for job in j_atp:
                        event_queue.add_event(job.ready_time, EventType.PARTS_READY, {"job_id": job.job_id, "step": "COMPLETED"})
                    sync_queues(queues)

            # --- RVB ---
            rvb_shift_end, rvb_next_start = self._get_shift_boundaries(current_time, project_data, "RVB")
            _rvb_non_work = rvb_shift_end is not None and rvb_shift_end <= current_time
            if _rvb_non_work:
                if rvb_next_start:
                    rvb_state["available_at"] = max(rvb_state["available_at"], rvb_next_start)
            else:
                rvb_cap = self._get_shift_capacity("RVB", shift_num, project_data)
                rvb_times = self._build_effective_times(prod_times, "RVB", "rvb", queues["rvb"], _remaining_overrides)
                e, j, r_avail, r_pid = RvbPlanner.plan(
                    queues["rvb"], current_time, rvb_state["available_at"],
                    rvb_state["last_product_id"], rvb_times, setup_matrix_obj, rvb_cap, shift_num,
                    last_work_date=rvb_state.get("last_work_date"),
                    shift_end_time=rvb_shift_end, next_shift_start_time=rvb_next_start,
                    logger=logger,
                    product_index_map=product_index_map)
                all_entries.extend(e)
                rvb_state["available_at"] = r_avail
                rvb_state["last_product_id"] = r_pid
                if e:
                    rvb_state["last_work_date"] = current_time.date()
                    _clear_remaining_overrides(j)
                    logger.add_log(time=current_time, action="RVB_KARAR", details=f"{len(j)} adet parça planlandı.", step="RVB")
                    event_queue.add_event(r_avail, EventType.MACHINE_FREE, {"machine": "RVB"})
                    for job in j:
                        event_queue.add_event(job.ready_time, EventType.PARTS_READY, {"job_id": job.job_id, "step": "atp_stp"})
                    sync_queues(queues)

        # 5. SONUÇLAR
        total_time_hours = (current_time - start_date).total_seconds() / 3600.0 if current_time > start_date else 1.0
        rem_targets = []

        if excel_products:
            # 5a) Excel'den gelen ürünler (devam eden işler)
            for ep in excel_products:
                completed_count = sum(
                    1 for j in all_jobs
                    if j.product_type == ep.product_type
                    and "||Excel" in j.job_id
                    and j.is_completed
                )
                # Assembly dışındaki devam eden ürünler için kullanıcının girdiği hedefi kullan
                ep_period_target = (
                    ep.period_target
                    if ep.current_step != "assembly" and ep.period_target is not None
                    else ep.quantity
                )
                rem_targets.append(RemainingTarget(
                    product_id=ep.display_name + " [Excel]",
                    product_type=ep.product_type,
                    product_name=ep.product_name,
                    monthly_target=ep.quantity,
                    period_target=ep_period_target,
                    scheduled_count=completed_count,
                    remaining_count=ep_period_target - completed_count
                ))
            # 5b) Tablodaki normal hedefler
            for p in project_data.products:
                produced_so_far = _produced.get(p.display_name, 0)
                full_remaining = max(0, p.monthly_target - produced_so_far)
                period_target = math.ceil(full_remaining / 4) if full_remaining > 0 else 0
                completed_count = sum(
                    1 for j in all_jobs
                    if j.product_id == p.display_name
                    and "||Excel" not in j.job_id
                    and "||Ek Üretim" not in j.job_id
                    and j.is_completed
                )
                rem_targets.append(RemainingTarget(
                    product_id=p.display_name,
                    product_type=p.type,
                    product_name=p.name,
                    monthly_target=p.monthly_target,
                    period_target=period_target,
                    scheduled_count=completed_count,
                    remaining_count=period_target - completed_count
                ))
        else:
            for p in project_data.products:
                produced_so_far = _produced.get(p.display_name, 0)
                full_remaining = max(0, p.monthly_target - produced_so_far)
                period_target = math.ceil(full_remaining / 4) if full_remaining > 0 else 0
                completed_count = sum(
                    1 for j in all_jobs
                    if j.product_id == p.display_name
                    and "||Ek Üretim" not in j.job_id
                    and j.is_completed
                )
                rem_targets.append(RemainingTarget(
                    product_id=p.display_name, product_type=p.type, product_name=p.name,
                    monthly_target=p.monthly_target, period_target=period_target, scheduled_count=completed_count,
                    remaining_count=period_target - completed_count
                ))

        # Karar analiz raporu için özet verisi hazırla
        summary_data_to_log = {"products": []}
        for rt in rem_targets:
            # Excel'den mi normal mi olduğunu product_id'den ayırt et
            is_excel = "[Excel]" in rt.product_id
            summary_data_to_log["products"].append({
                "type": rt.product_type,
                "name": rt.product_name,
                "target": rt.period_target,
                "excel_count": rt.scheduled_count if is_excel else 0, # Basit eşleştirme
                "scheduled": rt.scheduled_count,
                "remaining": rt.remaining_count
            })

        # Karar analiz raporunu oluştur ve kaydet
        audit_report = logger.generate_report_md({
            "period": period,
            "total_parts": len([j for j in all_jobs if j.is_completed]),
            "total_setup_time": sum(e.setup_time for e in all_entries)
        })
        with open("algorithm_decision_log.md", "w", encoding="utf-8") as f:
            f.write(audit_report)
        
        # Excel raporunu da oluştur (Özet verisi ile birlikte)
        logger.generate_report_xlsx("algorithm_decision_log.xlsx", summary_data=summary_data_to_log)

        return PlanningResult(
            schedule=all_entries, makespan=total_time_hours, last_part_completion=current_time,
            machine_utilization=machine_pool.get_utilization(total_time_hours),
            algorithm_used="PriorityBasedScheduler (Excel)" if excel_products else "PriorityBasedScheduler",
            period=period, remaining_targets=rem_targets,
            total_setup_time=sum(e.setup_time for e in all_entries),
            total_parts=len([j for j in all_jobs if j.is_completed]),
            audit_log=[f"[{l['timestamp']}] {l['step']}: {l['action']} - {l['details']}" for l in logger.logs],
            raw_audit_logs=logger.logs,
            priority_history=priority_history
        )

    def _get_shift_capacity(self, step_name: str, shift_num: int, project_data: AppState) -> Dict[str, int]:
        # capacity_data[ürün_adı][adım_adı] = [V1_adet, V2_adet, V3_adet]
        cap_dict = {}
        for prod_name, steps in project_data.capacity_data.items():
            caps = steps.get(step_name, [])
            if 0 < shift_num <= len(caps):
                try: cap_dict[prod_name] = int(caps[shift_num - 1])
                except: cap_dict[prod_name] = 0
            else: cap_dict[prod_name] = 0
        return cap_dict

    def _determine_current_shift(self, current_time: datetime, project_data: AppState) -> int:
        # Şu anki saat hangi vardiya aralığına düşüyor? (0-tabanlı indeks döner)
        shifts = project_data.shift_data.get("Assembly", [])
        weekend_shifts = getattr(project_data, "weekend_shifts", {"saturday": [0], "sunday": []})
        current_t = current_time.time()
        weekday = current_time.weekday()
        if weekday == 6:
            today_allowed = weekend_shifts.get("sunday", [])
        elif weekday == 5:
            today_allowed = weekend_shifts.get("saturday", [0])
        else:
            today_allowed = list(range(len(shifts)))
        from datetime import time as dt_time
        for idx, s in enumerate(shifts):
            if idx not in today_allowed:
                continue
            try:
                start_h, start_m = map(int, s["start"].split(":"))
                end_h, end_m = map(int, s["end"].split(":"))
                start_dt = dt_time(start_h, start_m)
                end_dt = dt_time(end_h, end_m)
                if start_dt <= current_t < end_dt: return idx
                if start_dt > end_dt:
                    if current_t >= start_dt or current_t < end_dt: return idx
            except: continue
        return 0

    def _is_non_working_time(
        self, current_time: datetime, step_name: str, project_data: AppState
    ) -> tuple:
        """
        Verilen an ilgili istasyon için çalışma saati dışındaysa (True, sonraki_vardiya_başlangıcı),
        çalışma saatindeyse (False, None) döndürür.
        """
        shift_end, next_start = self._get_shift_boundaries(current_time, project_data, step_name)
        # shift_end == current_time ise aktif vardiya yok (tatil veya vardiya arası)
        if shift_end is not None and shift_end <= current_time:
            return True, next_start
        return False, None

    def _compute_pause_aware_segments(
        self, start: datetime, duration_hours: float,
        project_data: AppState, step_name: str = "Assembly"
    ) -> List[Tuple[datetime, datetime]]:
        """Batch'i vardiya kesintilerine göre segmentlere böl (Assembly pause/resume).
        [(seg_start, seg_end), ...] — bitişik segmentler birleştirilir."""
        from datetime import timedelta
        segments: List[Tuple[datetime, datetime]] = []
        cur = start
        remaining = float(duration_hours)
        for _ in range(50):
            if remaining <= 0:
                break
            shift_end, next_start = self._get_shift_boundaries(cur, project_data, step_name)
            if shift_end is None or shift_end <= cur:
                if next_start is None or next_start <= cur:
                    segments.append((cur, cur + timedelta(hours=remaining)))
                    break
                cur = next_start
                continue
            available = (shift_end - cur).total_seconds() / 3600.0
            if available >= remaining:
                segments.append((cur, cur + timedelta(hours=remaining)))
                break
            segments.append((cur, shift_end))
            remaining -= available
            if next_start is None or next_start <= shift_end:
                segments.append((shift_end, shift_end + timedelta(hours=remaining)))
                break
            cur = next_start
        # Bitişik segmentleri birleştir (V1→V2 gibi pause olmayan geçişler)
        merged: List[Tuple[datetime, datetime]] = []
        for seg in segments:
            if merged and merged[-1][1] == seg[0]:
                merged[-1] = (merged[-1][0], seg[1])
            else:
                merged.append(seg)
        return merged

    def _find_next_working_shift_start(
        self,
        from_time: datetime,
        parsed_shifts: list,
        weekend_shifts: dict,
    ) -> Optional[datetime]:
        """
        from_time'dan sonraki ilk çalışan vardiyanın başlangıç zamanını döndürür.
        Hafta sonu kurallarını (weekend_shifts) dikkate alır.
        """
        from datetime import timedelta

        check_date = from_time.date()
        for _ in range(8):  # en fazla 7 gün ileri bak
            weekday = check_date.weekday()
            if weekday == 6:
                allowed = weekend_shifts.get("sunday", [])
            elif weekday == 5:
                allowed = weekend_shifts.get("saturday", [0])
            else:
                allowed = list(range(len(parsed_shifts)))

            for i, s in enumerate(parsed_shifts):
                if i not in allowed:
                    continue
                shift_dt = datetime.combine(check_date, s["start"])
                if shift_dt >= from_time:
                    return shift_dt

            check_date += timedelta(days=1)

        return None

    def _get_shift_boundaries(self, current_time: datetime, project_data: AppState, step_name: str="Assembly") -> Tuple[Optional[datetime], Optional[datetime]]:
        # (vardiya_sonu, sonraki_vardiya_başlangıcı) döner; aktif vardiya yoksa (şu_an, sonraki_başlangıç)
        shifts = project_data.shift_data.get(step_name, [])
        weekend_shifts = getattr(project_data, "weekend_shifts", {"saturday": [0], "sunday": []})

        if not shifts:
            return None, None

        from datetime import time as dt_time, timedelta

        parsed_shifts = []
        for s in shifts:
            try:
                h, m = map(int, s["start"].split(':'))
                st = dt_time(h, m)
                h, m = map(int, s["end"].split(':'))
                et = dt_time(h, m)
                parsed_shifts.append({"start": st, "end": et})
            except:
                pass

        if not parsed_shifts:
            return None, None

        current_t = current_time.time()
        current_date = current_time.date()

        def _allowed_for(wd: int) -> list:
            if wd == 6: return weekend_shifts.get("sunday", [])
            if wd == 5: return weekend_shifts.get("saturday", [0])
            return list(range(len(parsed_shifts)))

        today_allowed = _allowed_for(current_date.weekday())
        yesterday_allowed = _allowed_for((current_date - timedelta(days=1)).weekday())

        for idx, s in enumerate(parsed_shifts):
            start_t = s["start"]
            end_t = s["end"]
            is_cross_midnight = start_t > end_t

            in_shift = False
            end_date_val = current_date

            if not is_cross_midnight:
                if idx in today_allowed and start_t <= current_t < end_t:
                    in_shift = True
            else:
                # V3 gibi gece yarısını geçen vardıya (örn. 23:00→07:00)
                if current_t >= start_t and idx in today_allowed:
                    # Başlangıç-gün dilimi: bu vardıya bugün başlamış
                    in_shift = True
                    end_date_val = current_date + timedelta(days=1)
                elif current_t < end_t and idx in yesterday_allowed:
                    # Bitiş-gün dilimi: dün başlayan vardıya hala sürüyor
                    in_shift = True

            if in_shift:
                shift_end_dt = datetime.combine(end_date_val, end_t)
                next_shift_start_dt = self._find_next_working_shift_start(
                    shift_end_dt, parsed_shifts, weekend_shifts
                )
                return shift_end_dt, next_shift_start_dt

        # Aktif vardiya yok — sonraki çalışan vardiyanın başlangıcını bul
        next_start = self._find_next_working_shift_start(current_time, parsed_shifts, weekend_shifts)
        return current_time, next_start

    def _build_effective_times(self, prod_times, stage_name, step_name, queue_jobs, remaining_overrides) -> Dict[str, float]:
        return {pid: t.get(stage_name, 0.0) for pid, t in prod_times.items()}
