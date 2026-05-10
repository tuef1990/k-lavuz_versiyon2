"""
DKK + ATP+STP Planner V2 — Senaryo Bazlı Çoklu Makine Atama

Kural-1 (Hold): En yüksek öncelikli ürün zaten bir makinede işleniyorsa
  ve kalan süre ≤ boş makinelerin min setup süresiyse → o ürün bekletilir.

Kural-2 (Geçmişi olan boş makine): En yoğun kuyruğa göre aynı tür ürün
  atanır. Doluluk < %60 ise 1 saat beklenir.

Kural-3 (Geçmişsiz boş makine): Hold edilmeyen en yüksek öncelikli iş atanır.
"""

from datetime import datetime, timedelta
from typing import List, Dict, Tuple, Optional, Union, Any, Set
from models.job import Job
from models.schedule_entry import ScheduleEntry
from models.setup_matrix import SetupMatrix
from algorithms.base import NEXT_STEP, DAILY_INITIAL_SETUP_HOURS
from algorithms.machine_pool import SharedMachinePool


def _setup(setup_matrix: SetupMatrix, from_pid: Optional[str], to_pid: str) -> float:
    if from_pid is None:
        return 0.0
    try:
        return float(setup_matrix.matrix.get(from_pid, {}).get(to_pid, 0.0))
    except Exception:
        return 0.0


def _cap(capacity: Union[int, Dict[str, int]], product_id: str) -> int:
    if isinstance(capacity, dict):
        return max(1, int(capacity.get(product_id, 1)))
    return max(1, int(capacity or 1))


class DkkAtpPlannerV2:
    @staticmethod
    def plan(
        dkk_waiting: List[Job],
        atp_waiting: List[Job],
        machine_pool: SharedMachinePool,
        current_time: datetime,
        production_times: Dict[str, Dict[str, float]],
        setup_matrix: SetupMatrix,
        shift_capacities: Dict[str, Union[int, Dict[str, int]]],
        shift_number: int,
        shift_end_time: Optional[datetime] = None,
        next_shift_start_time: Optional[datetime] = None,
        logger: Optional[Any] = None,
    ) -> Tuple[List[ScheduleEntry], List[Job], List[Job]]:

        entries: List[ScheduleEntry] = []
        updated_dkk: List[Job] = []
        updated_atp: List[Job] = []
        assigned_job_ids: Set[str] = set()

        # Şu anki zaman aktif vardiya dışındaysa batch başlatma
        if shift_end_time is not None and shift_end_time <= current_time:
            return [], [], []

        free_machines = machine_pool.get_free_machines(current_time)

        # Meşgul makineler: Kural-1 (Hold) ve fallback (tüm makineler dolu) için kullanılır.
        # Vardiya sonundan SONRA boşalacak makinelere yeni iş açılmaması için filtrelenir —
        # mevcut batch'in mesai dışına taşması serbest, ama yeni atama yapılmaz.
        busy_machines = [
            m for m in machine_pool.machines.values()
            if m.available_at > current_time
            and (shift_end_time is None or m.available_at < shift_end_time)
        ]

        all_ready_dkk = [j for j in dkk_waiting if j.ready_time <= current_time]
        all_ready_atp = [j for j in atp_waiting if j.ready_time <= current_time]
        all_ready = (
            [(j, "dkk") for j in all_ready_dkk] +
            [(j, "atp_stp") for j in all_ready_atp]
        )

        # Hiç iş yoksa — ne hazır ne gelecek — atama yapılamaz
        any_jobs = bool(dkk_waiting) or bool(atp_waiting)
        if not any_jobs:
            return [], [], []

        # Tüm makineler meşgul → fallback: en uygun meşgul makineye gelecek-startlı atama
        if not free_machines and busy_machines:
            return DkkAtpPlannerV2._fallback_busy_assign(
                dkk_waiting=dkk_waiting, atp_waiting=atp_waiting,
                busy_machines=busy_machines, machine_pool=machine_pool,
                current_time=current_time, production_times=production_times,
                setup_matrix=setup_matrix, shift_capacities=shift_capacities,
                shift_number=shift_number, logger=logger,
                shift_end_time=shift_end_time,
            )

        if not free_machines:
            return [], [], []
        if not all_ready:
            # Hazır iş yok ama gelecek iş var, makine boş — fallback yine atayabilir
            if busy_machines or any_jobs:
                fallback_machines = list(machine_pool.machines.values())
                if shift_end_time is not None:
                    fallback_machines = [m for m in fallback_machines if m.available_at < shift_end_time]
                if fallback_machines:
                    return DkkAtpPlannerV2._fallback_busy_assign(
                        dkk_waiting=dkk_waiting, atp_waiting=atp_waiting,
                        busy_machines=fallback_machines,
                        machine_pool=machine_pool,
                        current_time=current_time, production_times=production_times,
                        setup_matrix=setup_matrix, shift_capacities=shift_capacities,
                        shift_number=shift_number, logger=logger,
                        shift_end_time=shift_end_time,
                    )
            return [], [], []

        # ════════════════════════════════════════════════════════════════
        # KURAL-1: En yüksek öncelikli ürünü gerekirse beklet
        # ════════════════════════════════════════════════════════════════
        held_pids: Set[str] = set()

        top_job, _ = max(all_ready, key=lambda x: x[0].priority_score)
        top_pid = top_job.product_id

        # Top_pid'i işleyen TÜM meşgul makinelerin remaining_h'larını topla,
        # MIN olanı al (en erken biten). Sadece ilk match'i değil hepsini gör.
        matching_busy = [
            bm for bm in busy_machines
            if machine_pool.last_product_ids.get(bm.machine_name) == top_pid
        ]
        if matching_busy:
            min_busy_remaining = min(
                (bm.available_at - current_time).total_seconds() / 3600.0
                for bm in matching_busy
            )

            # Boş makinelerin herhangi biri için minimum setup maliyeti
            min_free_setup = float("inf")
            for fm in free_machines:
                fm_last = machine_pool.last_product_ids.get(fm.machine_name)
                fm_daily = DAILY_INITIAL_SETUP_HOURS if machine_pool.needs_initial_setup(fm.machine_name) else 0.0
                fm_trans = _setup(setup_matrix, fm_last, top_pid)
                total = fm_daily + fm_trans
                if total < min_free_setup:
                    min_free_setup = total

            if min_free_setup == float("inf"):
                min_free_setup = 0.0

            # Min kalan süre ≤ en ucuz setup → bekle
            if min_busy_remaining <= min_free_setup:
                held_pids.add(top_pid)
                if logger:
                    logger.add_log(
                        current_time, "DKK_ATP_HOLD",
                        f"[KURAL-1] {top_pid} bekletiliyor: {len(matching_busy)} meşgul makine içinde min "
                        f"{min_busy_remaining:.1f}h içinde bitecek, min boş-makine setup "
                        f"{min_free_setup:.1f}h ≥ kalan süre.",
                        "DKK_ATP",
                    )

        # ════════════════════════════════════════════════════════════════
        # Geçmişi olan makineler önce işlenir: aynı-tip işleri kapar, geçmişsiz makineler
        # kalan işleri alır; bu sıra Kural-2'nin Kural-3'e müdahalesini önler
        # ════════════════════════════════════════════════════════════════
        free_with_hist = [m for m in free_machines if not machine_pool.needs_initial_setup(m.machine_name)]
        free_no_hist = [m for m in free_machines if machine_pool.needs_initial_setup(m.machine_name)]
        ordered_free = free_with_hist + free_no_hist

        for machine in ordered_free:
            has_history = not machine_pool.needs_initial_setup(machine.machine_name)
            last_pid = machine_pool.last_product_ids.get(machine.machine_name)

            # ── Preferred-machine filtresi ──
            def _ok(j: Job) -> bool:
                pm = getattr(j, "preferred_machine", None)
                return pm is None or pm == machine.machine_name

            ready_dkk = [j for j in dkk_waiting if j.ready_time <= current_time and j.job_id not in assigned_job_ids and _ok(j)]
            ready_atp = [j for j in atp_waiting if j.ready_time <= current_time and j.job_id not in assigned_job_ids and _ok(j)]
            full_dkk  = [j for j in dkk_waiting if j.job_id not in assigned_job_ids and _ok(j)]
            full_atp  = [j for j in atp_waiting if j.job_id not in assigned_job_ids and _ok(j)]

            if not ready_dkk and not ready_atp:
                continue

            # Excel'den gelen "bu makineye atanmış" işler listenin başına geçer
            ready_dkk.sort(key=lambda j: 0 if getattr(j, "preferred_machine", None) == machine.machine_name else 1)
            ready_atp.sort(key=lambda j: 0 if getattr(j, "preferred_machine", None) == machine.machine_name else 1)

            target_step: str = "dkk"
            selected_jobs: List[Job] = []
            transition_setup: float = 0.0

            # ════════════════════════════════════════════════════════════
            # KURAL-2: Geçmişi olan boş makine
            # ════════════════════════════════════════════════════════════
            if has_history and last_pid is not None:
                # Adım 1: Daha yoğun kuyruğu seç
                if len(ready_dkk) >= len(ready_atp):
                    target_step = "dkk"
                    cand_ready = ready_dkk
                    cand_full  = full_dkk
                else:
                    target_step = "atp_stp"
                    cand_ready = ready_atp
                    cand_full  = full_atp

                # Adım 2: Aynı türde işler (setup = 0).
                # KURAL-1 ile bekletilen ürünleri DAHİL ETME — boş makineye atanırsa
                # KURAL-1 ihlal edilir (meşgul makinenin yakında bitmesini bekliyorduk).
                same_type = [
                    j for j in cand_ready
                    if _setup(setup_matrix, last_pid, j.product_id) == 0.0
                    and j.product_id not in held_pids
                ]

                if same_type:
                    # En yüksek öncelikli ürün grubunu seç
                    best_same = max(same_type, key=lambda j: j.priority_score)
                    best_pid  = best_same.product_id
                    machine_cap = _cap(shift_capacities.get(target_step, 1), best_pid)

                    # Aynı ürünün tümü (hazır + 1h içinde gelecek olanlar) batch'e alınır;
                    # start_time gelecek ürünün ready_time'ına göre kayar
                    deadline_1h = current_time + timedelta(hours=1.0)
                    pid_group = [
                        j for j in cand_full
                        if j.product_id == best_pid
                        and (j.ready_time <= current_time or j.ready_time <= deadline_1h)
                        and j.product_id not in held_pids
                        and _setup(setup_matrix, last_pid, j.product_id) == 0.0
                    ]
                    selected_jobs    = sorted(pid_group, key=lambda j: j.priority_score, reverse=True)[:machine_cap]
                    transition_setup = 0.0
                    fill = min(len(selected_jobs), machine_cap) / machine_cap if machine_cap > 0 else 0

                    if logger:
                        future_count = sum(1 for j in selected_jobs if j.ready_time > current_time)
                        future_note = f" (gelecek {future_count} dahil)" if future_count > 0 else ""
                        logger.add_log(
                            current_time, "DKK_ATP_RULE2",
                            f"[KURAL-2][{machine.machine_name}] {best_pid}: aynı tür ürün seçildi "
                            f"({target_step.upper()} yoğun). Doluluk %{fill*100:.0f}. "
                            f"{len(selected_jobs)} parça{future_note}.",
                            "DKK_ATP",
                        )

                else:
                    # Aynı türde iş yok → Kural-3 mantığına düş (en yüksek öncelikli + geçiş setup'ı)
                    all_m = [(j, "dkk") for j in ready_dkk] + [(j, "atp_stp") for j in ready_atp]
                    not_held = [(j, s) for j, s in all_m if j.product_id not in held_pids]
                    candidates = not_held if not_held else all_m
                    if not candidates:
                        continue
                    best_j, best_s = max(candidates, key=lambda x: x[0].priority_score)
                    target_step = best_s
                    target_pid  = best_j.product_id
                    deadline_1h = current_time + timedelta(hours=1.0)
                    cand_full2 = full_dkk if best_s == "dkk" else full_atp
                    pool = [
                        j for j in cand_full2
                        if j.product_id == target_pid
                        and (j.ready_time <= current_time or j.ready_time <= deadline_1h)
                    ]
                    mc  = _cap(shift_capacities.get(target_step, 1), target_pid)
                    selected_jobs    = sorted(pool, key=lambda j: j.priority_score, reverse=True)[:mc]
                    transition_setup = _setup(setup_matrix, last_pid, target_pid)

            # ════════════════════════════════════════════════════════════
            # KURAL-3: Geçmişsiz boş makine
            # ════════════════════════════════════════════════════════════
            else:
                all_m = [(j, "dkk") for j in ready_dkk] + [(j, "atp_stp") for j in ready_atp]
                not_held = [(j, s) for j, s in all_m if j.product_id not in held_pids]
                candidates = not_held if not_held else all_m  # deadlock önlemi
                if not candidates:
                    continue
                best_j, best_s = max(candidates, key=lambda x: x[0].priority_score)
                target_step = best_s
                target_pid  = best_j.product_id
                # 1h içinde gelecek aynı ürünleri de batch'e dahil et (start_time kayar)
                deadline_1h = current_time + timedelta(hours=1.0)
                cand_full3 = full_dkk if best_s == "dkk" else full_atp
                pool = [
                    j for j in cand_full3
                    if j.product_id == target_pid
                    and (j.ready_time <= current_time or j.ready_time <= deadline_1h)
                ]
                mc  = _cap(shift_capacities.get(target_step, 1), target_pid)
                selected_jobs    = sorted(pool, key=lambda j: j.priority_score, reverse=True)[:mc]
                transition_setup = 0.0  # geçmiş yok, geçiş setup'ı yok

                if logger:
                    future_count = sum(1 for j in selected_jobs if j.ready_time > current_time)
                    future_note = f" (gelecek {future_count} dahil)" if future_count > 0 else ""
                    logger.add_log(
                        current_time, "DKK_ATP_RULE3",
                        f"[KURAL-3][{machine.machine_name}] {target_pid}: en yüksek öncelikli, "
                        f"{len(selected_jobs)} parça{future_note}.",
                        "DKK_ATP",
                    )

            if not selected_jobs:
                continue

            # İlk kullanım setup'ı + ürünler arası geçiş setup'ı
            daily_setup = DAILY_INITIAL_SETUP_HOURS if machine_pool.needs_initial_setup(machine.machine_name) else 0.0
            total_setup = daily_setup + transition_setup

            # Excel'den gelen devam eden iş: bu makinede zaten çalışıyordu, setup geçerli değil
            if any(getattr(j, "preferred_machine", None) == machine.machine_name for j in selected_jobs):
                total_setup = 0.0

            # Batch'e dahil olan future işlerin ready_time'ını da hesaba kat
            latest_ready = max((j.ready_time for j in selected_jobs), default=current_time)
            start_with_setup = max(current_time, machine.available_at, latest_ready)

            # start vardiya bitiminden sonraysa atama yapma — sonraki vardiyaya kadar boş.
            if shift_end_time is not None and start_with_setup >= shift_end_time:
                continue

            actual_start     = start_with_setup + timedelta(hours=total_setup)

            # Batch içindeki en uzun işlem süresi tüm grubun bitiş zamanını belirler
            step_times   = production_times.get(target_step, {})
            process_time = 0.0
            for job in selected_jobs:
                t = job.remaining_work_hours if job.remaining_work_hours > 0 else step_times.get(job.product_id, 0.0)
                if t > process_time:
                    process_time = t
            if process_time <= 0:
                process_time = 0.1

            end_time = actual_start + timedelta(hours=process_time)

            first_job = selected_jobs[0]
            machine_pool.assign(
                machine_name=machine.machine_name,
                step=target_step,
                product_id=first_job.product_id,
                product_type=first_job.product_type,
                start_time=start_with_setup,
                end_time=end_time,
                job_id=first_job.job_id,
            )

            if logger:
                rule_tag  = "KURAL-2" if (has_history and last_pid is not None) else "KURAL-3"
                held_str  = f" | Bekletilen: {held_pids}" if held_pids else ""
                pref_info = ""
                if any(getattr(j, "preferred_machine", None) == machine.machine_name for j in selected_jobs):
                    pref_info = f" | Excel'de {machine.machine_name} öncelikli."
                setup_detail = ""
                if total_setup <= 0:
                    setup_detail = " | Setup yok."
                elif daily_setup > 0 and transition_setup > 0:
                    setup_detail = (f" | Günlük setup: {daily_setup:.1f}h"
                                    f" + Geçiş: {transition_setup:.1f}h"
                                    f" = {total_setup:.1f}h.")
                elif daily_setup > 0:
                    setup_detail = f" | Günlük setup: {daily_setup:.1f}h."
                else:
                    setup_detail = f" | Geçiş setup: {transition_setup:.1f}h."

                logger.add_log(
                    current_time,
                    f"{target_step.upper()}_KARAR_DETAY",
                    f"[{machine.machine_name}][{rule_tag}] {first_job.product_type}"
                    f"{pref_info}{setup_detail}{held_str}",
                    target_step.upper(),
                )

            step_cap  = shift_capacities.get(target_step, 1)
            batch_cap = (step_cap.get(first_job.product_id, 1)
                         if isinstance(step_cap, dict) else int(step_cap or 1))

            for job in selected_jobs:
                is_first = job is first_job
                entry = ScheduleEntry(
                    job_id=job.job_id,
                    product_type=job.product_type,
                    product_name=job.product_name,
                    step_name=target_step,
                    machine_name=machine.machine_name,
                    start_time=start_with_setup,
                    end_time=end_time,
                    setup_time=total_setup if is_first else 0.0,
                    process_time=process_time,
                    group_size=len(selected_jobs),
                    shift_number=shift_number,
                    priority_level=job.priority_score,
                    is_priority_override=job.is_priority_override,
                    machine_capacity=batch_cap,
                    initial_setup_time=daily_setup if is_first else 0.0,
                    transition_setup_time=transition_setup if is_first else 0.0,
                )
                entries.append(entry)

                job.ready_time = end_time
                if target_step == "dkk":
                    job.current_step = NEXT_STEP.get("dkk", "rvb")
                    job.completed_steps.append("dkk")
                    updated_dkk.append(job)
                else:
                    job.current_step = None
                    job.is_completed = True
                    job.completed_steps.append("atp_stp")
                    updated_atp.append(job)

                assigned_job_ids.add(job.job_id)

        return entries, updated_dkk, updated_atp

    @staticmethod
    def _fallback_busy_assign(
        dkk_waiting: List[Job], atp_waiting: List[Job],
        busy_machines: List[Any], machine_pool: SharedMachinePool,
        current_time: datetime, production_times: Dict[str, Dict[str, float]],
        setup_matrix: SetupMatrix,
        shift_capacities: Dict[str, Union[int, Dict[str, int]]],
        shift_number: int, logger: Optional[Any] = None,
        shift_end_time: Optional[datetime] = None,
    ) -> Tuple[List[ScheduleEntry], List[Job], List[Job]]:
        """Hiç boş makine yokken (veya tüm hazır işler boş kalmışken) en yüksek
        öncelikli işi en uygun meşgul makineye gelecek-startlı atar.

        Best-fit metriği: bekleme süresi + setup. Aynı tipi işleyen makinede setup 0
        olduğundan tercih edilir."""
        entries: List[ScheduleEntry] = []
        updated_dkk: List[Job] = []
        updated_atp: List[Job] = []

        all_jobs = (
            [(j, "dkk") for j in dkk_waiting] +
            [(j, "atp_stp") for j in atp_waiting]
        )
        if not all_jobs or not busy_machines:
            return [], [], []

        # En yüksek öncelikli iş (gelecekteki ürünler de dahil)
        top_job, top_step = max(all_jobs, key=lambda x: x[0].priority_score)
        top_pid = top_job.product_id

        # Best machine: min(wait + setup)
        best_machine = None
        best_total_setup = 0.0
        best_daily = 0.0
        best_trans = 0.0
        best_cost = float("inf")
        for m in busy_machines:
            wait = max(0.0, (m.available_at - current_time).total_seconds() / 3600.0)
            last_pid = machine_pool.last_product_ids.get(m.machine_name)
            daily = DAILY_INITIAL_SETUP_HOURS if machine_pool.needs_initial_setup(m.machine_name) else 0.0
            trans = _setup(setup_matrix, last_pid, top_pid)
            cost = wait + daily + trans
            if cost < best_cost:
                best_cost = cost
                best_machine = m
                best_daily = daily
                best_trans = trans
                best_total_setup = daily + trans

        if best_machine is None:
            return [], [], []

        # Aynı tipte ve hazır olan işleri kapasiteye kadar al
        same_pid_pool = [
            j for j in (dkk_waiting if top_step == "dkk" else atp_waiting)
            if j.product_id == top_pid
        ]
        machine_cap = _cap(shift_capacities.get(top_step, 1), top_pid)
        selected = sorted(same_pid_pool, key=lambda j: j.priority_score, reverse=True)[:machine_cap]
        if not selected:
            return [], [], []

        # start_with_setup = max(şimdi, makine müsait, seçili işlerin en geç ready_time'ı)
        latest_ready = max((j.ready_time for j in selected), default=current_time)
        start_with_setup = max(current_time, best_machine.available_at, latest_ready)

        # Vardiya bitiminden sonra başlayacaksa fallback iptal — sonraki vardiyaya kalsın.
        if shift_end_time is not None and start_with_setup >= shift_end_time:
            return [], [], []

        actual_start = start_with_setup + timedelta(hours=best_total_setup)

        step_times = production_times.get(top_step, {})
        process_time = 0.0
        for j in selected:
            t = j.remaining_work_hours if j.remaining_work_hours > 0 else step_times.get(j.product_id, 0.0)
            if t > process_time:
                process_time = t
        if process_time <= 0:
            process_time = 0.1

        end_time = actual_start + timedelta(hours=process_time)
        first_job = selected[0]
        wait_h = max(0.0, (start_with_setup - current_time).total_seconds() / 3600.0)

        machine_pool.assign(
            machine_name=best_machine.machine_name,
            step=top_step,
            product_id=first_job.product_id,
            product_type=first_job.product_type,
            start_time=start_with_setup,
            end_time=end_time,
            job_id=first_job.job_id,
        )

        if logger:
            last_pid = machine_pool.last_product_ids.get(best_machine.machine_name)
            logger.add_log(
                current_time, f"{top_step.upper()}_KARAR_DETAY",
                f"[{best_machine.machine_name}][FALLBACK] Tüm makineler dolu — "
                f"{first_job.product_type} en uygun makineye atandı. "
                f"Bekleme: {wait_h:.1f}h"
                + (f" | Geçiş: {last_pid}→{top_pid} setup {best_trans:.1f}h" if best_trans > 0 else "")
                + (f" | Günlük setup: {best_daily:.1f}h" if best_daily > 0 else "")
                + ".",
                top_step.upper(),
            )

        step_cap = shift_capacities.get(top_step, 1)
        batch_cap = (step_cap.get(first_job.product_id, 1)
                     if isinstance(step_cap, dict) else int(step_cap or 1))

        for job in selected:
            is_first = job is first_job
            entry = ScheduleEntry(
                job_id=job.job_id,
                product_type=job.product_type,
                product_name=job.product_name,
                step_name=top_step,
                machine_name=best_machine.machine_name,
                start_time=start_with_setup,
                end_time=end_time,
                setup_time=best_total_setup if is_first else 0.0,
                process_time=process_time,
                group_size=len(selected),
                shift_number=shift_number,
                priority_level=job.priority_score,
                is_priority_override=job.is_priority_override,
                machine_capacity=batch_cap,
                initial_setup_time=best_daily if is_first else 0.0,
                transition_setup_time=best_trans if is_first else 0.0,
            )
            entries.append(entry)

            job.ready_time = end_time
            if top_step == "dkk":
                job.current_step = NEXT_STEP.get("dkk", "rvb")
                job.completed_steps.append("dkk")
                updated_dkk.append(job)
            else:
                job.current_step = None
                job.is_completed = True
                job.completed_steps.append("atp_stp")
                updated_atp.append(job)

        return entries, updated_dkk, updated_atp
