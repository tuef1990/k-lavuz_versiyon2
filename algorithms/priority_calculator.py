from datetime import datetime, timedelta
from typing import List, Dict, Set, Tuple, Optional
from models.job import Job

# Job.current_step (lowercase) ↔ production_time_data anahtarları (STAGES, başharf büyük)
_STEP_TO_STAGE = {
    "assembly": "Assembly",
    "ftp": "FTP",
    "bn": "B/N",
    "dkk": "DKK",
    "rvb": "RVB",
    "atp_stp": "ATP+STP",
}
_STEP_ORDER = ["assembly", "ftp", "bn", "dkk", "rvb", "atp_stp"]


def _job_total_time(job: Job, production_time_data: Dict[str, Dict[str, float]],
                    type_total_time: Dict[str, float]) -> float:
    """
    Excel job (remaining_work_hours > 0) için:
        kalan_saat + mevcut_adımdan_sonraki_adımların_toplam_süresi
    Normal job için:
        ürünün tüm adımlarının toplam süresi
    """
    if job.remaining_work_hours > 0 and job.current_step in _STEP_TO_STAGE:
        try:
            cur_idx = _STEP_ORDER.index(job.current_step)
        except ValueError:
            return type_total_time.get(job.product_id, 0.0)
        steps = production_time_data.get(job.product_id, {})
        future_total = sum(
            steps.get(_STEP_TO_STAGE[s], 0.0) for s in _STEP_ORDER[cur_idx + 1:]
        )
        return job.remaining_work_hours + future_total
    return type_total_time.get(job.product_id, 0.0)


class PriorityCalculator:
    @staticmethod
    def calculate_raw_priorities(
        jobs: List[Job],
        production_time_data: Dict[str, Dict[str, float]],
        start_date: datetime,
        end_date: datetime,
        remaining_counts: Dict[str, int],
        week_number: int = 0
    ) -> Dict[str, float]:
        """
        Öncelik = (kalan_saat/24) / (bitiş_tarihi - başlangıç)
                  * NORMALIZE(kalan_sevkiyat / (4 - hafta_no))

        NORMALIZE(x) = (x - min) / (max - min)
        """

        # Payda: çizelgelemenin bitiş tarihine kaç gün kaldığı (en az 1 gün)
        day_diff = float(max((end_date.date() - start_date.date()).days, 1))

        # Her ürünün tüm üretim adımlarındaki toplam süresi (saat)
        time_map = {p: sum(t.values()) for p, t in production_time_data.items()}

        # Kalan sevkiyat / (4 - hafta_no): haftanın ilerlemesiyle paydayı küçültür → öncelik artar
        # cnt < 0 ise (haftalık hedefi aşıp gelecek hafta işine geçildi) 0'a clamp et
        denom = max(1, 4 - week_number)
        ship_per_product: Dict[str, float] = {
            ptype: max(0, cnt) / denom
            for ptype, cnt in remaining_counts.items()
        }

        # Min-max normalizasyon: farklı ölçeklerdeki kalan adetleri [0,1] aralığına çeker
        active_types = {ptype: val for ptype, val in ship_per_product.items() if val > 0}
        if active_types:
            min_val = min(active_types.values())
            max_val = max(active_types.values())
        else:
            min_val = max_val = 0.0

        def normalize(val: float) -> float:
            if max_val == min_val:
                return 0.0
            return (val - min_val) / (max_val - min_val)

        # Gelecek hafta işleri için ayrı normalizasyon: bu haftakilerin önüne geçmesin
        future_jobs = [j for j in jobs if "||Gelecek Hafta" in j.job_id and not j.is_completed]
        future_types = {j.product_type: ship_per_product.get(j.product_type, 0.0) for j in future_jobs}
        f_min = min(future_types.values()) if future_types else 0.0
        f_max = max(future_types.values()) if future_types else 0.0

        def normalize_future(val: float) -> float:
            if f_max == f_min:
                return 0.0
            return (val - f_min) / (f_max - f_min)

        raw_priorities: Dict[str, float] = {}

        for job in jobs:
            if job.is_completed:
                raw_priorities[job.job_id] = 0.0
                continue

            # Ek üretim işleri her zaman en düşük öncelikte (normal işler bitmeden başlamasın)
            if "||Ek Üretim" in job.job_id:
                raw_priorities[job.job_id] = -1.000
                continue

            ship_val = ship_per_product.get(job.product_type, 0.0)

            # Gelecek hafta işleri: bu haftakilerin (öncelik > 0) altında, ama sıfırın hemen altında
            if "||Gelecek Hafta" in job.job_id:
                norm = normalize_future(ship_val)
                raw_priorities[job.job_id] = -0.001 - (1.0 - norm) * 0.999
                continue

            # Kalan sevkiyatı olmayan ürün → düşük öncelik (-0.001), tamamlanmış sayılmaz
            if ship_val == 0:
                raw_priorities[job.job_id] = -0.001
            else:
                # Excel job ise mevcut adımın kalan saati + sonraki adımlar; normal ise tüm toplam
                total_time = _job_total_time(job, production_time_data, time_map)
                base = (total_time / 24.0) / day_diff
                norm = normalize(ship_val)
                raw_priorities[job.job_id] = base * norm

        return raw_priorities

    @staticmethod
    def apply_overrides(
        priorities: Dict[str, float],
        overrides: Optional[Dict[str, float]]
    ) -> Tuple[Dict[str, float], Set[str]]:
        updated = priorities.copy()
        overridden_ids: Set[str] = set()
        if overrides:
            for jid, val in overrides.items():
                if jid in updated:
                    updated[jid] = val
                    overridden_ids.add(jid)
        return updated, overridden_ids

    @classmethod
    def calculate_all(
        cls,
        jobs: List[Job],
        production_time_data: Dict[str, Dict[str, float]],
        start_date: datetime,
        end_date: datetime,
        remaining_counts: Dict[str, int],
        overrides: Optional[Dict[str, float]] = None,
        week_number: int = 0
    ) -> Tuple[Dict[str, float], Set[str]]:
        raw = cls.calculate_raw_priorities(
            jobs, production_time_data, start_date, end_date, remaining_counts, week_number
        )
        return cls.apply_overrides(raw, overrides)
