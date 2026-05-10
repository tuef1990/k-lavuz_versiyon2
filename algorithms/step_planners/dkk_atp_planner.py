"""
DKK + ATP+STP Planner — Doluluk-Tabanlı Çoklu Makine Atama + Günlük Setup
"""

from datetime import datetime, timedelta
from typing import List, Dict, Tuple, Optional, Union, Any
from models.job import Job
from models.schedule_entry import ScheduleEntry
from models.setup_matrix import SetupMatrix
from models.machine_state import MachineState
from algorithms.base import NEXT_STEP, DAILY_INITIAL_SETUP_HOURS
from algorithms.machine_pool import SharedMachinePool
from algorithms.utils.group_builder import GroupBuilder
from algorithms.step_planners.dkk_atp_planner_v2 import DkkAtpPlannerV2


class DkkAtpPlanner:
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
        product_index_map: Optional[Dict[str, int]] = None,
    ) -> Tuple[List[ScheduleEntry], List[Job], List[Job]]:
        entries = []
        updated_dkk = []
        updated_atp = []
        assigned_job_ids = set()

        # Şu anki zaman aktif vardiya dışındaysa batch başlatma
        if shift_end_time is not None and shift_end_time <= current_time:
            return [], [], []

        free_machines = machine_pool.get_free_machines(current_time)
        # Tüm makineler meşgul → fallback: en uygun meşgul makineye gelecek-startlı atama
        if not free_machines:
            busy_machines = [
                m for m in machine_pool.machines.values()
                if m.available_at > current_time
            ]
            # Vardiya sonundan SONRA boşalacak makinelere yeni iş açma — sonraki vardiyaya
            # kadar bekle. Mevcut batch'in taşması serbest, ama yeni atama yapılmaz.
            if shift_end_time is not None:
                busy_machines = [m for m in busy_machines if m.available_at < shift_end_time]
            if busy_machines and (dkk_waiting or atp_waiting):
                return DkkAtpPlannerV2._fallback_busy_assign(
                    dkk_waiting=dkk_waiting, atp_waiting=atp_waiting,
                    busy_machines=busy_machines, machine_pool=machine_pool,
                    current_time=current_time, production_times=production_times,
                    setup_matrix=setup_matrix, shift_capacities=shift_capacities,
                    shift_number=shift_number, logger=logger,
                    shift_end_time=shift_end_time,
                )
            return [], [], []

        # Makine sıralaması DİNAMİK: her atama sonrası kalan makineler yeniden
        # değerlendirilir, çünkü atanan iş kuyruktan çıkar ve diğer makinelerin
        # uygunluğu değişir.
        # Öncelik:
        #   0) Bekleyen ready işin tipiyle aynı geçmişi olan makine (setup=0)
        #   1) Geçmişsiz makine (setup=0 + 2h initial)
        #   2) Farklı geçmişe sahip makine (setup gerekir)

        def _machine_priority(m, ready_pids):
            last_pid = machine_pool.last_product_ids.get(m.machine_name)
            if last_pid is None:
                return 1
            if last_pid in ready_pids:
                return 0
            return 2

        remaining_machines = list(free_machines)

        while remaining_machines:
            # Kalan ready işlerin product_id'lerini her seferinde yeniden hesapla
            current_ready_pids = {
                j.product_id for j in (dkk_waiting + atp_waiting)
                if j.ready_time <= current_time and j.job_id not in assigned_job_ids
            }

            if not current_ready_pids:
                # Hazır iş kalmadı, kalan makineler boş gider
                break

            # Sırala ve en uygun olanı al
            remaining_machines.sort(key=lambda m: _machine_priority(m, current_ready_pids))
            machine = remaining_machines.pop(0)
            # Preferred machine (Excel'de tanımlı): o iş yalnızca o makineye gidebilir
            # None ise herhangi bir makineye atanabilir; başka makineye tanımlıysa buraya gelmez
            remaining_dkk_ready = [
                j for j in dkk_waiting
                if j.ready_time <= current_time
                and j.job_id not in assigned_job_ids
                and (getattr(j, 'preferred_machine', None) is None
                     or j.preferred_machine == machine.machine_name)
            ]
            remaining_atp_ready = [
                j for j in atp_waiting
                if j.ready_time <= current_time
                and j.job_id not in assigned_job_ids
                and (getattr(j, 'preferred_machine', None) is None
                     or j.preferred_machine == machine.machine_name)
            ]

            # Preferred job'ları listenin başına taşı (önceliklendir)
            def _sort_preferred(jobs):
                return sorted(jobs, key=lambda j: 0 if getattr(j, 'preferred_machine', None) == machine.machine_name else 1)

            remaining_dkk_ready = _sort_preferred(remaining_dkk_ready)
            remaining_atp_ready = _sort_preferred(remaining_atp_ready)

            if not remaining_dkk_ready and not remaining_atp_ready:
                continue

            # Gelecek parça doluluk hesabı için hazır olmayan işler de gerekli (GroupBuilder kullanır)
            machine_dkk_pool = [
                j for j in dkk_waiting
                if j.job_id not in assigned_job_ids
                and (getattr(j, 'preferred_machine', None) is None
                     or j.preferred_machine == machine.machine_name)
            ]
            machine_atp_pool = [
                j for j in atp_waiting
                if j.job_id not in assigned_job_ids
                and (getattr(j, 'preferred_machine', None) is None
                     or j.preferred_machine == machine.machine_name)
            ]

            target_step, ready_jobs, full_queue = _select_target_queue(
                remaining_dkk_ready, remaining_atp_ready,
                machine_dkk_pool, machine_atp_pool, assigned_job_ids
            )

            if not ready_jobs:
                continue

            last_pid = machine_pool.last_product_ids.get(machine.machine_name)
            step_capacity = shift_capacities.get(target_step, 1)

            filtered_full_queue = [
                j for j in full_queue if j.job_id not in assigned_job_ids
            ]

            group_res = GroupBuilder.build_group(
                waiting_jobs=ready_jobs,
                full_queue=filtered_full_queue,
                capacity=step_capacity,
                last_product_id=last_pid,
                setup_matrix=setup_matrix,
                current_time=current_time,
                product_index_map=product_index_map,
            )

            if group_res.should_wait:
                continue
            if not group_res.selected_jobs:
                continue

            # Bu makine planlama döneminde ilk kez kullanılıyorsa 1 saatlik günlük setup ekle
            daily_setup = 0.0
            if machine_pool.needs_initial_setup(machine.machine_name):
                daily_setup = DAILY_INITIAL_SETUP_HOURS

            total_setup = daily_setup + group_res.setup_time

            # Excel'den gelen "devam eden" iş bu makinede çalışıyordu; kesintisiz devam eder, setup sıfır.
            # İki kriter:
            #   1) preferred_machine bu makineye eşit (Excel'de M1/M2/.. olarak belirtilmiş)
            #   2) Excel job'u + remaining_work_hours > 0 (kısmi tamamlanmış, devam ediyor)
            def _is_continuing(j):
                if getattr(j, 'preferred_machine', None) == machine.machine_name:
                    return True
                if "||Excel" in (j.job_id or "") and getattr(j, 'remaining_work_hours', 0) > 0:
                    return True
                return False

            if any(_is_continuing(j) for j in group_res.selected_jobs):
                # Devam eden iş — hiçbir setup yok (initial dahil)
                total_setup = 0.0
                daily_setup = 0.0
                group_res.setup_time = 0.0

            start_with_setup = max(current_time, machine.available_at)

            # Bu makine için start vardiya bitiminden sonraysa atama yapma — sonraki
            # vardiyaya kadar boş bırak.
            if shift_end_time is not None and start_with_setup >= shift_end_time:
                continue

            actual_start = start_with_setup + timedelta(hours=total_setup)

            # İşlem süresi
            step_times = production_times.get(target_step, {})
            process_time = 0.0
            for job in group_res.selected_jobs:
                t = job.remaining_work_hours if job.remaining_work_hours > 0 else step_times.get(job.product_id, 0.0)
                if t > process_time:
                    process_time = t
            if process_time <= 0:
                process_time = 0.1

            end_time = actual_start + timedelta(hours=process_time)

            # DKK/ATP işlemleri 18-21 saat sürer; B/N gibi vardiya sonu kontrolü yapılmaz

            first_job = group_res.selected_jobs[0]
            machine_pool.assign(
                machine_name=machine.machine_name,
                step=target_step,
                product_id=group_res.selected_product_id,
                product_type=group_res.product_type,
                start_time=start_with_setup,
                end_time=end_time,
                job_id=first_job.job_id
            )

            if logger:
                pref = getattr(first_job, 'preferred_machine', None)
                is_excel = "||Excel" in first_job.job_id
                origin_info = " (Excel'den Gelen)" if is_excel else ""

                excel_reason = ""
                if pref == machine.machine_name:
                    excel_reason = f" | Excel'de {machine.machine_name} makinesi öncelikli tanımlı."

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
                    f"{target_step.upper()}_KARAR_DETAY",
                    f"[{machine.machine_name}] {first_job.product_type}{origin_info} → "
                    f"{group_res.reason_detail}{excel_reason}{setup_detail}",
                    target_step.upper()
                )

            batch_cap = (step_capacity.get(first_job.product_id, 1)
                         if isinstance(step_capacity, dict) else int(step_capacity or 1))
            for job in group_res.selected_jobs:
                is_first = job == first_job
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
                    group_size=len(group_res.selected_jobs),
                    shift_number=shift_number,
                    priority_level=job.priority_score,
                    is_priority_override=job.is_priority_override,
                    machine_capacity=batch_cap,
                    initial_setup_time=daily_setup if is_first else 0.0,
                    transition_setup_time=group_res.setup_time if is_first else 0.0,
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

        # Post-loop fallback: makineler boş ama hazır iş yoksa (sadece gelecek var)
        # en uygun makineye gelecek-startlı atama yap
        if not entries and (dkk_waiting or atp_waiting):
            fallback_machines = list(machine_pool.machines.values())
            # Vardiya sonundan sonra boşalacak makinelere atama yapma
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

        return entries, updated_dkk, updated_atp


def _select_target_queue(ready_dkk, ready_atp, full_dkk, full_atp, assigned_ids):
    """Makineye DKK mi yoksa ATP+STP kuyruğu mu atanacağına karar verir.
    ATP önceliği DKK'dan 0.1'den fazla yüksekse ATP kazanır; aksi halde DKK önceliklidir."""
    max_dkk_prio = max((j.priority_score for j in ready_dkk), default=-1.0)
    max_atp_prio = max((j.priority_score for j in ready_atp), default=-1.0)

    if max_atp_prio > max_dkk_prio + 0.1 or not ready_dkk:
        if ready_atp:
            filtered = [j for j in full_atp if j.job_id not in assigned_ids]
            return "atp_stp", ready_atp, filtered

    if ready_dkk:
        filtered = [j for j in full_dkk if j.job_id not in assigned_ids]
        return "dkk", ready_dkk, filtered

    if ready_atp:
        filtered = [j for j in full_atp if j.job_id not in assigned_ids]
        return "atp_stp", ready_atp, filtered

    return "dkk", [], []
