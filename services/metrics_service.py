from datetime import datetime
from typing import Dict, Any, List, Tuple
import statistics
from models.planning_result import PlanningResult

# Sistemdeki tüm makineler — ortalama verimlilik paydasında kullanılır
ALL_MACHINES = ["Assembly", "FTP", "B/N", "M1", "M2", "M3", "M4", "RVB"]

# Üretim adımlarının sırası — akış süresi hesabında kullanılır
STEP_ORDER = ["assembly", "ftp", "bn", "dkk", "rvb", "atp_stp"]


class MetricsService:
    @staticmethod
    def calculate(result: PlanningResult) -> Dict[str, Any]:
        """
        Çizelgeleme sonucundan performans metriklerini hesaplar.

        Döndürülen metrikler:
          makespan_hours, makespan_display        — Toplam çizelge süresi
          last_part_display                       — Son parçanın bitiş zamanı
          total_setup_hours                       — Toplam setup süresi
          setup_ratio_pct                         — Setup oranı (%)
          total_parts                             — Tamamlanan parça sayısı
          throughput_per_day                      — Günlük verim (parça/gün)
          machine_utilization                     — Makine bazlı verimlilik (%)
          avg_utilization                         — Tüm makineler üzerinden ort. verimlilik (%)
          machine_idle_hours                      — Makine bazlı boş süre (saat)
          bottleneck_machine                      — En yüksek verimli makine adı
          balance_index                           — Makine denge endeksi (std sapma, düşük=iyi)
          avg_flow_time_hours                     — Ort. akış süresi (saat/parça)
          schedule_achievement_pct                — Hedef karşılama oranı (%)
          num_setups                              — Toplam setup işlemi sayısı
          parts_by_product                        — Ürün tipi bazlı tamamlanan parça sayısı
        """
        if not result.schedule:
            return _empty_metrics()

        # ── 1. Zaman sınırları ────────────────────────────────────────────
        start_time = min(e.start_time for e in result.schedule)
        end_time   = max(e.end_time   for e in result.schedule)
        makespan_hours = (end_time - start_time).total_seconds() / 3600.0

        # ── 2. Makespan görüntü metni ─────────────────────────────────────
        days    = int(makespan_hours // 24)
        hours   = int(makespan_hours % 24)
        minutes = int((makespan_hours * 60) % 60)
        if days > 0:
            makespan_display = f"{days} gün {hours} saat {minutes} dk"
        elif hours > 0:
            makespan_display = f"{hours} saat {minutes} dk"
        else:
            makespan_display = f"{minutes} dk"

        last_part_display = end_time.strftime("%d.%m.%Y %H:%M")

        # ── 3. Setup metrikleri ───────────────────────────────────────────
        # Her grupta yalnızca ilk iş setup_time > 0 alır; toplam doğrudur.
        total_setup_hours = sum(e.setup_time for e in result.schedule)
        num_setups = sum(1 for e in result.schedule if e.setup_time > 0)

        # Toplam saf üretim süresi = tüm adımlardaki process_time'ların toplamı
        # (Aynı batch içindeki her job kendi entry'sine sahip; bir batch için
        #  process_time tüm job'larda aynıdır. Job bazlı benzersiz akış süresini
        #  hesaplamak için job_id üzerinden son entry alınır — bkz. akış süresi.)
        # Setup oranı = total_setup / (makespan × makine sayısı)
        total_machine_hours = makespan_hours * len(ALL_MACHINES)
        setup_ratio_pct = (total_setup_hours / total_machine_hours * 100.0
                           if total_machine_hours > 0 else 0.0)

        # ── 4. Tamamlanan parça sayısı ────────────────────────────────────
        total_parts = result.total_parts  # is_completed sayısı — doğru kaynak

        # Ürün tipi bazlı parça sayısı:
        # Her job_id için sadece son adımın entry'si sayılır (her adım ayrı entry üretir).
        last_step_per_job: Dict[str, str] = {}
        for e in result.schedule:
            last_step_per_job[e.job_id] = e.product_type
        parts_by_product: Dict[str, int] = {}
        for ptype in last_step_per_job.values():
            parts_by_product[ptype] = parts_by_product.get(ptype, 0) + 1

        # ── 5. Verimlilik (makine bazlı, doluluk oranı) ───────────────────
        # Her benzersiz tur (batch) için: doluluk = grup_adedi / kapasite
        # Benzersizlik: aynı makine + aynı başlangıç zamanı = aynı tur
        # Her makinenin tüm turlarının ortalama doluluk oranı = o makinenin verimliliği

        # Aynı turu (makine, start_time) çiftiyle temsil et; her turdan bir örnek al
        seen_batches: set = set()
        machine_batch_fills: Dict[str, List[float]] = {}
        machine_idle_hours: Dict[str, float] = {}

        for e in result.schedule:
            batch_key = (e.machine_name, e.start_time)
            if batch_key in seen_batches:
                continue
            seen_batches.add(batch_key)
            cap = max(e.machine_capacity, 1)
            fill = min(e.group_size / cap, 1.0) * 100.0
            machine_batch_fills.setdefault(e.machine_name, []).append(fill)

        machine_utilization: Dict[str, float] = {}
        for machine in ALL_MACHINES:
            fills = machine_batch_fills.get(machine, [])
            if fills:
                machine_utilization[machine] = round(sum(fills) / len(fills), 2)
            else:
                machine_utilization[machine] = 0.0

        # Boşta süre: zaman blokları birleştirilerek hesaplanır (referans için)
        machine_usage_blocks: Dict[str, List[Tuple[datetime, datetime]]] = {}
        for e in result.schedule:
            machine_usage_blocks.setdefault(e.machine_name, []).append(
                (e.start_time, e.end_time)
            )
        for machine in ALL_MACHINES:
            blocks = machine_usage_blocks.get(machine)
            if not blocks:
                machine_idle_hours[machine] = round(makespan_hours, 2)
                continue
            blocks.sort()
            active = 0.0
            cs, ce = blocks[0]
            for ns, ne in blocks[1:]:
                if ns < ce:
                    ce = max(ce, ne)
                else:
                    active += (ce - cs).total_seconds() / 3600.0
                    cs, ce = ns, ne
            active += (ce - cs).total_seconds() / 3600.0
            machine_idle_hours[machine] = round(max(makespan_hours - active, 0.0), 2)

        # Ortalama verimlilik: TÜM makineler üzerinden (kullanılmayanlar %0)
        avg_utilization = (sum(machine_utilization.values()) / len(ALL_MACHINES)
                           if machine_utilization else 0.0)

        # Darboğaz: en yüksek doluluk oranına sahip makine
        bottleneck_machine = (max(machine_utilization, key=machine_utilization.get)
                              if machine_utilization else "-")

        # Denge endeksi: makine verimlilikleri arasındaki standart sapma
        util_values = list(machine_utilization.values())
        balance_index = round(statistics.stdev(util_values), 2) if len(util_values) > 1 else 0.0

        # ── 6. Ortalama akış süresi ───────────────────────────────────────
        # Her job için: akış süresi = son adımın bitiş zamanı − çizelgenin başlangıcı
        # (Tüm işler start_time'dan itibaren sisteme giriyor)
        job_end_times: Dict[str, datetime] = {}
        for e in result.schedule:
            if e.job_id not in job_end_times or e.end_time > job_end_times[e.job_id]:
                job_end_times[e.job_id] = e.end_time

        if job_end_times:
            flow_times = [(t - start_time).total_seconds() / 3600.0
                          for t in job_end_times.values()]
            avg_flow_time_hours = round(sum(flow_times) / len(flow_times), 2)
        else:
            avg_flow_time_hours = 0.0

        # ── 7. Verim (throughput) ─────────────────────────────────────────
        throughput_per_day = (total_parts / (makespan_hours / 24.0)
                              if makespan_hours > 0 else 0.0)

        # ── 8. Hedef karşılama oranı ──────────────────────────────────────
        # Tüm ürünlerin periyot hedeflerinin toplamı vs. çizelgelenen toplam
        total_period_target   = sum(t.period_target   for t in result.remaining_targets)
        total_scheduled_count = sum(t.scheduled_count for t in result.remaining_targets)
        schedule_achievement_pct = (
            total_scheduled_count / total_period_target * 100.0
            if total_period_target > 0 else 0.0
        )

        return {
            # Temel süreler
            "makespan_hours":           round(makespan_hours, 2),
            "makespan_display":         makespan_display,
            "last_part_time":           end_time,
            "last_part_display":        last_part_display,
            # Setup
            "total_setup_hours":        round(total_setup_hours, 2),
            "num_setups":               num_setups,
            "setup_ratio_pct":          round(setup_ratio_pct, 2),
            # Üretim
            "total_parts":              total_parts,
            "throughput_per_day":       round(throughput_per_day, 2),
            "parts_by_product":         parts_by_product,
            "schedule_achievement_pct": round(schedule_achievement_pct, 1),
            # Makine
            "machine_utilization":      machine_utilization,
            "machine_idle_hours":       machine_idle_hours,
            "avg_utilization":          round(avg_utilization, 2),
            "bottleneck_machine":       bottleneck_machine,
            "balance_index":            balance_index,
            # Akış
            "avg_flow_time_hours":      avg_flow_time_hours,
        }


def _empty_metrics() -> Dict[str, Any]:
    return {
        "makespan_hours": 0.0, "makespan_display": "-",
        "last_part_time": datetime.now(), "last_part_display": "-",
        "total_setup_hours": 0.0, "num_setups": 0, "setup_ratio_pct": 0.0,
        "total_parts": 0, "throughput_per_day": 0.0,
        "parts_by_product": {}, "schedule_achievement_pct": 0.0,
        "machine_utilization": {}, "machine_idle_hours": {},
        "avg_utilization": 0.0, "bottleneck_machine": "-",
        "balance_index": 0.0, "avg_flow_time_hours": 0.0,
    }
