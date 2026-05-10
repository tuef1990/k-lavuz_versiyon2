"""
Optimal Yaklaşım — MIP (Mixed Integer Programming) bazlı flow-shop scheduler.

Karar değişkenleri:
  - C[j][k]      : Job j'nin step k'da bitiş zamanı (saat cinsinden, start_date'ten itibaren)
  - x[j][k][m]   : Job j step k'da makine m'ye atanmış mı (0/1)
  - y[j][j'][k][m]: Job j, step k makine m'de j'nden ÖNCE mi (0/1)
  - C_max        : Makespan (minimize edilen)

Hedef: minimize C_max (tüm joblar bitince geçen toplam süre)

Kısıtlar:
  - Her job her step'te tek bir makineye atanır
  - Adımlar arası ardışıklık (job step k'yı bitirmeden step k+1 başlayamaz)
  - Aynı makinede iki job aynı anda çalışamaz; geçişte setup süresi eklenir
  - Earliest start (start_date offseti)
  - Step kapasitesi (paralel makineler)

ÖNEMLİ: MIP NP-zor; ürün sayısı arttıkça hızla şişer. Maksimum 10 ürün ile sınırlı.
Üzerinde olursa hata döner; PriorityScheduler kullanılması önerilir.
"""

from datetime import datetime, timedelta
from typing import List, Dict, Optional, Any
import itertools

from .base import (
    PlanningAlgorithm, PROCESS_STEPS_ORDER, DAILY_INITIAL_SETUP_HOURS,
    DAILY_SETUP_STEPS,
)
from core.models import AppState
from models.planning_result import PlanningResult
from models.schedule_entry import ScheduleEntry
from models.remaining_target import RemainingTarget


# Adım adı → state.shift_data anahtarı eşlemesi (kapasite/vardıya tablolarındaki isimler)
_STEP_TO_STAGE = {
    "assembly": "Assembly",
    "ftp": "FTP",
    "bn": "B/N",
    "dkk": "DKK",
    "rvb": "RVB",
    "atp_stp": "ATP+STP",
}

# Her step için makine isimleri
def _machine_names_for_step(step: str) -> List[str]:
    if step == "assembly":
        return ["Assembly"]
    if step == "ftp":
        return ["FTP"]
    if step == "bn":
        return ["B/N"]
    if step == "rvb":
        return ["RVB"]
    if step in ("dkk", "atp_stp"):
        return ["M1", "M2", "M3", "M4"]
    return [step.upper()]


MAX_PRODUCTS = 5  # MIP ölçek limiti


class MathematicalScheduler(PlanningAlgorithm):
    """MIP tabanlı flow-shop scheduler — makespan minimize."""

    def solve(
        self,
        project_data: AppState,
        start_date: datetime,
        end_date: datetime,
        period: str,
        priority_overrides: Optional[Dict[str, float]] = None,
        excel_products: Optional[List] = None,
        week_number: int = 0,
        produced_amounts: Optional[Dict[str, int]] = None,
        excel_only: bool = False,
        extra_production_list: Optional[List[Dict[str, Any]]] = None,
    ) -> PlanningResult:

        try:
            from mip import Model, MINIMIZE, BINARY, CONTINUOUS, xsum, minimize, OptimizationStatus
        except ImportError:
            raise RuntimeError(
                "Optimal Yaklaşım için 'mip' kütüphanesi gerekli. "
                "Kurulum: pip install mip"
            )

        # ────────────────────────────────────────────────────────────
        # 1. Veri hazırlama: tabloları MIP indeks setlerine çevir
        # ────────────────────────────────────────────────────────────
        produced = produced_amounts or {}
        products = [
            p for p in project_data.products
            if max(0, p.monthly_target - produced.get(p.display_name, 0)) > 0
        ]

        if not products:
            return self._empty_result(start_date, period)

        if len(products) >= MAX_PRODUCTS:
            raise RuntimeError(
                f"Optimal Yaklaşım maksimum {MAX_PRODUCTS} üründe çalışabilir "
                f"(şu an {len(products)} ürün var). Lütfen Sevkiyat Destekli "
                f"Yaklaşım veya Makina Verimli Dengeli Yaklaşım seçin."
            )

        N = len(products)
        steps = list(PROCESS_STEPS_ORDER)
        S = len(steps)

        # Her step için makineler
        machines_per_step: Dict[str, List[str]] = {
            step: _machine_names_for_step(step) for step in steps
        }
        # Step başına makine sayısı
        M_k = {k: len(machines_per_step[step]) for k, step in enumerate(steps)}

        # Process time: p[j][k][m] saat (job j, step k, makine m)
        # Batch süresi olarak alıyoruz: piece_time × ceil(qty/cap) — toplu işlenen tek "iş"
        prod_times = project_data.production_time_data or {}
        capacities = project_data.capacity_data or {}

        def _piece_time(pid: str, step: str) -> float:
            stage_key = _STEP_TO_STAGE[step]
            return float(prod_times.get(pid, {}).get(stage_key, 0.0) or 0.0)

        def _capacity(pid: str, step: str) -> int:
            stage_key = _STEP_TO_STAGE[step]
            vals = capacities.get(pid, {}).get(stage_key, [])
            if not vals:
                return 1
            try:
                return max(1, int(vals[0]))
            except Exception:
                return 1

        # Each Product = 1 batch; batch süresi = piece_time × ceil(qty/cap)
        # DKK/RVB/ATP+STP için ek olarak günlük 2h initial setup (DAILY_INITIAL_SETUP_HOURS)
        import math as _math
        p = {}  # p[(j, k)] = float (saat) — process time (initial setup HARİÇ)
        initial_setup = {}  # initial_setup[(j, k)] = float (saat) — sadece DKK/RVB/ATP+STP'de
        for j, prod in enumerate(products):
            qty = max(0, prod.monthly_target - produced.get(prod.display_name, 0))
            for k, step in enumerate(steps):
                pt = _piece_time(prod.display_name, step)
                cap = _capacity(prod.display_name, step)
                batches = _math.ceil(qty / cap) if qty > 0 else 0
                p[(j, k)] = pt * batches
                # Daily initial setup yalnızca belirli adımlarda
                initial_setup[(j, k)] = (
                    DAILY_INITIAL_SETUP_HOURS if step in DAILY_SETUP_STEPS else 0.0
                )

        # Setup matrix → setup[j_from][j_to] saat (yalnızca farklı tipler için)
        setup_mtx = project_data.setup_matrix or {}

        def _setup(j_from: int, j_to: int) -> float:
            if j_from == j_to:
                return 0.0
            from_pid = products[j_from].display_name
            to_pid = products[j_to].display_name
            try:
                return float(setup_mtx.get(from_pid, {}).get(to_pid, 0.0) or 0.0)
            except Exception:
                return 0.0

        # Earliest start: hepsi 0 (start_date'ten itibaren)
        s_j = {j: 0.0 for j in range(N)}

        # bigM
        total_horizon = sum(p[(j, k)] for j in range(N) for k in range(S))
        max_setup = max(
            (_setup(a, b) for a in range(N) for b in range(N) if a != b),
            default=0.0,
        )
        bigM = total_horizon + max_setup * N + 24.0

        # ────────────────────────────────────────────────────────────
        # 2. MIP modelini kur
        # ────────────────────────────────────────────────────────────
        mdl = Model(sense=MINIMIZE, solver_name="CBC")
        mdl.verbose = 0

        # C[j][k] : completion time
        C = [[mdl.add_var(name=f"C_{j}_{k}", var_type=CONTINUOUS, lb=0.0)
              for k in range(S)] for j in range(N)]

        # x[j][k][m] : assignment binary
        x = [[[mdl.add_var(name=f"x_{j}_{k}_{m}", var_type=BINARY)
               for m in range(M_k[k])] for k in range(S)] for j in range(N)]

        # y[j1][j2][k][m] : j1 precedes j2 on machine m at step k (1=yes, 0=no)
        y = [[[[mdl.add_var(name=f"y_{j1}_{j2}_{k}_{m}", var_type=BINARY)
                if j1 != j2 else None
                for m in range(M_k[k])] for k in range(S)]
              for j2 in range(N)] for j1 in range(N)]

        C_max = mdl.add_var(name="C_max", var_type=CONTINUOUS, lb=0.0)

        # Hedef
        mdl.objective = minimize(C_max)

        # Kısıt 1: Her job her step için bir makineye atanır
        for j in range(N):
            for k in range(S):
                mdl += xsum(x[j][k][m] for m in range(M_k[k])) == 1

        # Kısıt 2: İlk step bitiş zamanı = earliest_start + initial_setup + process_time
        for j in range(N):
            mdl += C[j][0] >= s_j[j] + initial_setup[(j, 0)] + p[(j, 0)]

        # Kısıt 3: Adımlar arası ardışıklık + her adımda initial setup ekleniyor
        # C[j][k] >= C[j][k-1] + initial_setup[j][k] + p[j][k]
        for j in range(N):
            for k in range(1, S):
                mdl += C[j][k] >= C[j][k - 1] + initial_setup[(j, k)] + p[(j, k)]

        # Kısıt 4: Sıralama — aynı makinede iki iş çakışmaz, geçişte setup_matrix süresi eklenir
        # j1 önce j2: C[j2][k] >= C[j1][k] + p[j2][k] + setup(j1->j2) + initial_setup[j2][k] - bigM*(3 - y - x1 - x2)
        for k in range(S):
            for m in range(M_k[k]):
                for j1 in range(N):
                    for j2 in range(N):
                        if j1 == j2:
                            continue
                        st = _setup(j1, j2)
                        # j1 önce j2 sonra
                        mdl += (
                            C[j2][k] >= C[j1][k] + p[(j2, k)] + st + initial_setup[(j2, k)]
                            - bigM * (3 - y[j1][j2][k][m] - x[j1][k][m] - x[j2][k][m])
                        )
                        # y simetrisi: ya j1 önce ya j2 önce (eğer ikisi de aynı makinedeyse)
                        # x[j1][k][m] + x[j2][k][m] - 1 <= y[j1][j2][k][m] + y[j2][j1][k][m]
                        if j1 < j2:
                            mdl += (
                                y[j1][j2][k][m] + y[j2][j1][k][m]
                                >= x[j1][k][m] + x[j2][k][m] - 1
                            )
                            mdl += y[j1][j2][k][m] + y[j2][j1][k][m] <= 1

        # Kısıt 5: Makespan
        for j in range(N):
            mdl += C_max >= C[j][S - 1]

        # ────────────────────────────────────────────────────────────
        # 3. Çöz
        # ────────────────────────────────────────────────────────────
        mdl.max_seconds = 120  # 2 dakika sınır
        status = mdl.optimize()

        if status not in (OptimizationStatus.OPTIMAL, OptimizationStatus.FEASIBLE):
            raise RuntimeError(
                f"MIP çözücü sonuç bulamadı (status={status}). "
                f"Daha az ürün ile deneyin veya farklı algoritma kullanın."
            )

        # ────────────────────────────────────────────────────────────
        # 4. Shift-aware takvim çeviricisi
        #    MIP'in hesapladığı "uninterrupted hours" değerlerini gerçek
        #    takvim tarihlerine çeviriyoruz: shift_data ve weekend_shifts
        #    kuralları kullanılıyor.
        # ────────────────────────────────────────────────────────────
        shift_data = project_data.shift_data or {}
        weekend_shifts = project_data.weekend_shifts or {"saturday": [0], "sunday": []}

        def _allowed_shift_indices(weekday: int, step_shifts: List[Dict]) -> List[int]:
            if weekday == 5:  # cumartesi
                return [i for i in weekend_shifts.get("saturday", [0]) if 0 <= i < len(step_shifts)]
            if weekday == 6:  # pazar
                return [i for i in weekend_shifts.get("sunday", []) if 0 <= i < len(step_shifts)]
            return list(range(len(step_shifts)))

        def _shift_hours(s: Dict[str, str]) -> float:
            try:
                sh, sm = map(int, s["start"].split(":"))
                eh, em = map(int, s["end"].split(":"))
                start_dec = sh + sm / 60.0
                end_dec = eh + em / 60.0
                if end_dec > start_dec:
                    return end_dec - start_dec
                return 24.0 - start_dec + end_dec
            except Exception:
                return 0.0

        def _hours_to_calendar(work_hours: float, step: str) -> datetime:
            """`start_date`'ten itibaren `work_hours` kadar çalışma süresi
            biriktiğinde takvimin hangi tarih/saatine denk geldiğini döner.
            Vardıya saatleri ve hafta sonu kuralları dikkate alınır.
            """
            stage_key = _STEP_TO_STAGE.get(step, step)
            step_shifts = shift_data.get(stage_key, [])
            if not step_shifts:
                # Vardıya bilgisi yoksa 24/7 say
                return start_date + timedelta(hours=work_hours)

            remaining = work_hours
            cur_date = start_date.date()
            cur_dt = start_date

            # Her vardıyanın başlangıç datetime'ını üret ve içine work_hours dağıt
            from datetime import datetime as _dt
            while remaining > 0:
                weekday = cur_date.weekday()
                allowed = _allowed_shift_indices(weekday, step_shifts)
                for idx in allowed:
                    s = step_shifts[idx]
                    sh, sm = map(int, s["start"].split(":"))
                    shift_start = _dt(cur_date.year, cur_date.month, cur_date.day, sh, sm)
                    sh_hours = _shift_hours(s)
                    # Vardıya start_date'ten önceyse atla
                    if shift_start + timedelta(hours=sh_hours) <= cur_dt:
                        continue
                    effective_start = max(shift_start, cur_dt)
                    remaining_in_shift = sh_hours - (
                        (effective_start - shift_start).total_seconds() / 3600.0
                    )
                    if remaining <= remaining_in_shift:
                        return effective_start + timedelta(hours=remaining)
                    remaining -= remaining_in_shift
                    cur_dt = shift_start + timedelta(hours=sh_hours)
                cur_date = cur_date + timedelta(days=1)
                # Yeni güne geçtiğimizde cur_dt'yi gün başına düşür (bir sonraki vardıya başlangıcı zaten hesaplanır)
                if cur_dt < _dt(cur_date.year, cur_date.month, cur_date.day):
                    cur_dt = _dt(cur_date.year, cur_date.month, cur_date.day)
            return cur_dt

        # ────────────────────────────────────────────────────────────
        # 5. Çözümü ScheduleEntry listesine çevir (shift-aware)
        # ────────────────────────────────────────────────────────────
        schedule: List[ScheduleEntry] = []
        for j in range(N):
            prod = products[j]
            for k, step in enumerate(steps):
                # Hangi makineye atandı?
                assigned_m = None
                for m_idx in range(M_k[k]):
                    if x[j][k][m_idx].x is not None and x[j][k][m_idx].x >= 0.5:
                        assigned_m = m_idx
                        break
                if assigned_m is None:
                    continue

                end_h = float(C[j][k].x or 0.0)
                proc_h = p[(j, k)]
                init_setup_h = initial_setup[(j, k)]
                start_h = max(0.0, end_h - proc_h - init_setup_h)

                start_dt = _hours_to_calendar(start_h, step)
                end_dt = _hours_to_calendar(end_h, step)

                machine_name = machines_per_step[step][assigned_m]

                qty = max(0, prod.monthly_target - produced.get(prod.display_name, 0))
                cap = _capacity(prod.display_name, step)

                # Sıralamadan kaynaklanan setup süresi (bir önceki ürünle geçiş)
                # MIP zaten dahil etti; entry'de görünür hale getir
                trans_setup = 0.0
                # j'den önce hangisi geldi? y matrisini tara
                for j_prev in range(N):
                    if j_prev == j:
                        continue
                    yv = y[j_prev][j][k][assigned_m]
                    if yv is not None and yv.x is not None and yv.x >= 0.5:
                        trans_setup = _setup(j_prev, j)
                        break

                schedule.append(ScheduleEntry(
                    job_id=f"MIP-{j}-{k}",
                    product_type=prod.type,
                    product_name=prod.name,
                    step_name=step,
                    machine_name=machine_name,
                    start_time=start_dt,
                    end_time=end_dt,
                    setup_time=init_setup_h + trans_setup,
                    process_time=proc_h,
                    group_size=qty,
                    shift_number=1,
                    priority_level=0.0,
                    is_priority_override=False,
                    machine_capacity=cap,
                    initial_setup_time=init_setup_h,
                    transition_setup_time=trans_setup,
                ))

        # Sonuçları paketle
        makespan_hours = float(C_max.x or 0.0)
        # Shift-aware son tamamlanma tarihi: en son entry'nin end_time'ı
        last_completion = max(
            (e.end_time for e in schedule), default=start_date
        )
        total_setup_time = sum(e.setup_time for e in schedule)

        # Makine kullanım oranları
        machine_busy: Dict[str, float] = {}
        for entry in schedule:
            machine_busy[entry.machine_name] = (
                machine_busy.get(entry.machine_name, 0.0) + entry.process_time
            )
        utilization = {
            name: (busy / makespan_hours if makespan_hours > 0 else 0.0)
            for name, busy in machine_busy.items()
        }

        # Kalan hedefler (MIP tüm hedefi tamamladığını varsayıyoruz)
        remaining_targets: List[RemainingTarget] = []
        for prod in products:
            qty = max(0, prod.monthly_target - produced.get(prod.display_name, 0))
            remaining_targets.append(RemainingTarget(
                product_id=prod.display_name,
                product_type=prod.type,
                product_name=prod.name,
                monthly_target=prod.monthly_target,
                period_target=qty,
                scheduled_count=qty,
                remaining_count=0,
            ))

        return PlanningResult(
            schedule=schedule,
            makespan=makespan_hours,
            last_part_completion=last_completion,
            machine_utilization=utilization,
            algorithm_used="Optimal Yaklaşım",
            period=period,
            remaining_targets=remaining_targets,
            total_setup_time=total_setup_time,
            total_parts=sum(t.scheduled_count for t in remaining_targets),
            audit_log=[
                f"MIP çözüm durumu: {status}",
                f"Optimum makespan (uninterrupted): {makespan_hours:.2f} saat",
                f"Shift-aware son tamamlanma: {last_completion}",
                f"Toplam setup: {total_setup_time:.2f} saat",
                f"Toplam ürün: {N}",
            ],
            raw_audit_logs=[],
            priority_history={},
        )

    @staticmethod
    def _empty_result(start_date: datetime, period: str) -> PlanningResult:
        return PlanningResult(
            schedule=[],
            makespan=0.0,
            last_part_completion=start_date,
            machine_utilization={},
            algorithm_used="Optimal Yaklaşım",
            period=period,
            remaining_targets=[],
            total_setup_time=0.0,
            total_parts=0,
            audit_log=["Plan için ürün yok."],
            raw_audit_logs=[],
            priority_history={},
        )
