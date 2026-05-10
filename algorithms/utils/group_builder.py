"""
Doluluk-Tabanlı Akıllı Grup Seçici (Smart Group Selector)

Bu modül, üretim hattındaki DKK, ATP+STP ve RVB adımları için
çok katmanlı karar ağacı tabanlı grup seçimi yapar.

Karar ağacı şeması:
  4.1   → Makinenin geçmişi var mı?
  4.1-B → İlk atama (geçmiş yok)
  4.1.1 → Önceki ürün eşleştirmesi (geçmiş var)
  4.1.1.1 → Farklı tip gelecek parça değerlendirmesi
"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import List, Dict, Optional, Tuple, Union
from models.job import Job
from models.setup_matrix import SetupMatrix
from algorithms.base import DAILY_INITIAL_SETUP_HOURS


@dataclass
class GroupResult:
    """Grup seçim sonucunu taşıyan veri yapısı."""
    selected_jobs: List[Job]
    product_type: str
    selected_product_id: str
    setup_required: bool
    setup_time: float
    reason: str
    should_wait: bool = False  # True ise bu turda hiçbir iş atanmaz (bekleme kararı)
    reason_detail: str = ""    # İnsan tarafından okunabilir Türkçe karar açıklaması


def _calculate_fill_rate(job_count: int, capacity: int) -> float:
    """Doluluk oranı hesapla: 0.0 – 1.0"""
    if capacity <= 0:
        return 0.0
    return min(job_count, capacity) / capacity


def _get_setup_time(setup_matrix: SetupMatrix, from_pid: Optional[str], to_pid: str) -> float:
    """Matris'ten setup süresini güvenli şekilde oku."""
    if from_pid is None:
        return 0.0
    try:
        return float(setup_matrix.matrix.get(from_pid, {}).get(to_pid, 0.0))
    except (AttributeError, KeyError, TypeError, ValueError):
        return 0.0


def _is_same_type(setup_matrix: SetupMatrix, pid_a: Optional[str], pid_b: str) -> bool:
    """İki ürün arasında setup süresi 0 mı? (aynı tip kabul edilir)"""
    return _get_setup_time(setup_matrix, pid_a, pid_b) == 0.0


def _get_capacity_for_product(capacity: Union[int, Dict[str, int]], product_id: str) -> int:
    """Ürün bazlı kapasiteyi al."""
    if isinstance(capacity, dict):
        cap = capacity.get(product_id, 1)
        return max(1, int(cap))
    return max(1, int(capacity))


def _group_by_product(jobs: List[Job]) -> Dict[str, List[Job]]:
    """Job'ları product_id bazlı grupla, her grup önceliğe göre sıralı."""
    groups: Dict[str, List[Job]] = {}
    for job in jobs:
        if job.product_id not in groups:
            groups[job.product_id] = []
        groups[job.product_id].append(job)
    for pid in groups:
        groups[pid].sort(key=lambda j: j.priority_score, reverse=True)
    return groups


def _get_highest_priority_group(
    groups: Dict[str, List[Job]],
    last_product_id: Optional[str] = None,
    product_index_map: Optional[Dict[str, int]] = None,
) -> Tuple[str, List[Job], float]:
    """En yüksek max öncelikli grubu döner: (product_id, jobs, max_priority)
    Tie-break (Assembly ile aynı):
      1) priority desc
      2) son işlenen ürün → devam ettir (setup yok)
      3) Ürün Bilgileri tablosundaki indeks (küçük önce)
    """
    idx_map = product_index_map or {}
    candidates = []
    for pid, jobs in groups.items():
        max_p = max(j.priority_score for j in jobs)
        candidates.append((pid, jobs, max_p))
    if not candidates:
        return None, [], -float('inf')
    # Sıralama: priority desc, last_product_id eşleşen önce, indeks küçük önce
    candidates.sort(key=lambda c: (
        -c[2],
        0 if last_product_id is not None and c[0] == last_product_id else 1,
        idx_map.get(c[0], 999),
    ))
    best_pid, best_jobs, best_prio = candidates[0]
    return best_pid, best_jobs, best_prio


def _select_jobs(jobs: List[Job], capacity: int) -> List[Job]:
    """Önceliğe göre sıralı job listesinden kapasite kadar al."""
    sorted_jobs = sorted(jobs, key=lambda j: j.priority_score, reverse=True)
    return sorted_jobs[:capacity]


def _find_future_jobs(
    full_queue: List[Job],
    current_time: datetime,
    hours: float,
    product_id: Optional[str] = None,
    product_type: Optional[str] = None
) -> List[Job]:
    """Belirtilen süre içinde gelecek parçaları bul."""
    if hours <= 0:
        return []
    deadline = current_time + timedelta(hours=hours)
    result = []
    for j in full_queue:
        if not (current_time < j.ready_time <= deadline):
            continue
        if product_id and j.product_id != product_id:
            continue
        if product_type and j.product_type != product_type:
            continue
        result.append(j)
    return result


def _find_future_highest_priority(
    full_queue: List[Job],
    current_time: datetime,
    hours: float
) -> Optional[Job]:
    """Belirtilen süre içinde gelecek en yüksek öncelikli parçayı bul."""
    if hours <= 0:
        return None
    deadline = current_time + timedelta(hours=hours)
    future = [j for j in full_queue if current_time < j.ready_time <= deadline]
    if not future:
        return None
    return max(future, key=lambda j: j.priority_score)


class GroupBuilder:
    """
    Doluluk-tabanlı çok katmanlı karar ağacı ile grup seçimi yapar.

    Hem tek makine (RVB) hem çoklu eşlenik makine (DKK, ATP+STP) adımlarında
    aynı karar ağacını kullanır.
    """

    @staticmethod
    def build_group(
        waiting_jobs: List[Job],
        full_queue: List[Job],
        capacity: Union[int, Dict[str, int]],
        last_product_id: Optional[str],
        setup_matrix: SetupMatrix,
        current_time: datetime,
        product_index_map: Optional[Dict[str, int]] = None,
    ) -> GroupResult:
        """
        Ana giriş noktası — Adım 4.1 karar ağacını başlatır.

        Args:
            waiting_jobs: ready_time <= current_time olan hazır işler
            full_queue: Gelecek parçaları kontrol etmek için TÜM kuyruk
            capacity: Ürün bazlı makine kapasitesi (dict veya int)
            last_product_id: Makinenin son işlediği ürün product_id'si (None = ilk kullanım)
            setup_matrix: Ürünler-arası geçiş süre matrisi
            current_time: Şu anki simülasyon zamanı

        Returns:
            GroupResult: Seçilen işler, setup bilgisi, bekleme kararı
        """
        empty = GroupResult([], "", "", False, 0.0, "no_waiting_jobs", should_wait=False)

        if not waiting_jobs:
            return empty

        # Hazır job'ları product_id bazlı grupla
        groups = _group_by_product(waiting_jobs)
        if not groups:
            return empty

        # En yüksek öncelikli grubu bul → "baştaki_f"
        # Tie-break: priority desc → last_product devam → tablo indeksi
        bastaki_pid, bastaki_jobs, bastaki_max_prio = _get_highest_priority_group(
            groups,
            last_product_id=last_product_id,
            product_index_map=product_index_map,
        )
        bastaki_type = bastaki_jobs[0].product_type

        # ── ADIM 4.1: Makinenin geçmişi var mı? ──
        if last_product_id is None:
            # Geçmiş yok → ADIM 4.1-B (İlk Atama)
            return GroupBuilder._step_4_1_B(
                bastaki_pid, bastaki_jobs, bastaki_max_prio, bastaki_type,
                groups, full_queue, capacity, setup_matrix, current_time
            )
        else:
            # Geçmiş var → ADIM 4.1.1 (Önceki Ürün Eşleştirmesi)
            return GroupBuilder._step_4_1_1(
                bastaki_pid, bastaki_jobs, bastaki_max_prio, bastaki_type,
                groups, full_queue, capacity, last_product_id, setup_matrix, current_time
            )

    # ════════════════════════════════════════════════════════════════
    # ADIM 4.1-B — İlk Atama (Makine Geçmişi Yok)
    # ════════════════════════════════════════════════════════════════
    @staticmethod
    def _step_4_1_B(
        bastaki_pid: str, bastaki_jobs: List[Job], bastaki_max_prio: float,
        bastaki_type: str, groups: Dict[str, List[Job]],
        full_queue: List[Job], capacity: Union[int, Dict[str, int]],
        setup_matrix: SetupMatrix, current_time: datetime
    ) -> GroupResult:
        """İlk atama: Makine daha önce hiç parça işlememiş."""

        cap = _get_capacity_for_product(capacity, bastaki_pid)

        # İlk atamada setup_time = 0 (from=None) — ama makine yeni açılıyor,
        # günlük 1 saatlik initial setup uygulanacak. Bu pencere içinde
        # gelecek parçaları kontrol et.
        initial_setup_window = DAILY_INITIAL_SETUP_HOURS

        # Setup süresi boyunca gelecek en yüksek öncelikli parça
        gelecek_en_acil = _find_future_highest_priority(full_queue, current_time, initial_setup_window)

        # 5. Gelecek yoksa → hemen işleme al
        if gelecek_en_acil is None:
            selected = _select_jobs(bastaki_jobs, cap)
            fill = _calculate_fill_rate(len(selected), cap)
            return GroupResult(
                selected_jobs=selected,
                product_type=bastaki_type,
                selected_product_id=bastaki_pid,
                setup_required=True,
                setup_time=0.0,
                reason="initial_no_future",
                reason_detail=(
                    f"{bastaki_pid} işleme alındı. "
                    f"İlk atama — makine geçmişi yok. "
                    f"{initial_setup_window:.1f} saatlik pencerede gelecek parça bulunamadı. "
                    f"Doluluk: {len(selected)}/{cap} = %{fill*100:.0f}."
                )
            )

        # 6. Gelecek, baştaki ile aynı product_type VE current_step
        if (gelecek_en_acil.product_type == bastaki_type and
                gelecek_en_acil.product_id == bastaki_pid):
            # Bekle ve birlikte maksimum dolulukla işleme al
            future_same = _find_future_jobs(full_queue, current_time, initial_setup_window,
                                           product_id=bastaki_pid)
            all_candidates = bastaki_jobs + future_same
            seen_ids = set()
            unique_candidates = []
            for j in all_candidates:
                if j.job_id not in seen_ids:
                    seen_ids.add(j.job_id)
                    unique_candidates.append(j)

            selected = _select_jobs(unique_candidates, cap)
            should_wait = len(selected) > len(bastaki_jobs)
            has_future = any(j.ready_time > current_time for j in selected)
            fill = _calculate_fill_rate(len(selected), cap)
            wait_str = "Bekleniyor (gelecek parça dahil edildi)." if (should_wait and has_future) else "Hemen işleme alındı."
            return GroupResult(
                selected_jobs=selected,
                product_type=bastaki_type,
                selected_product_id=bastaki_pid,
                setup_required=True,
                setup_time=0.0,
                reason="initial_wait_same_type",
                should_wait=should_wait and has_future,
                reason_detail=(
                    f"{bastaki_pid} seçildi. "
                    f"{initial_setup_window:.1f} saat içinde aynı ürün gelecek "
                    f"({len(future_same)} parça). {wait_str} "
                    f"Doluluk: {len(selected)}/{cap} = %{fill*100:.0f}."
                )
            )

        # 7. Gelecek farklı (product_type VEYA current_step farklı) → "gelecek_farklı"
        gelecek_farklı = gelecek_en_acil
        gelecek_farklı_pid = gelecek_farklı.product_id
        gelecek_farklı_prio = gelecek_farklı.priority_score
        fark = gelecek_farklı_prio - bastaki_max_prio

        D1 = _calculate_fill_rate(len(bastaki_jobs), cap)
        future_same_for_bastaki = _find_future_jobs(
            full_queue, current_time, initial_setup_window, product_id=bastaki_pid)
        D2_count = len(bastaki_jobs) + len(future_same_for_bastaki)
        D2 = _calculate_fill_rate(D2_count, cap)
        gelecek_farklı_cap = _get_capacity_for_product(capacity, gelecek_farklı_pid)
        mevcut_gelecek_eslesenler = groups.get(gelecek_farklı_pid, [])
        D3_count = len(mevcut_gelecek_eslesenler) + 1
        D3 = _calculate_fill_rate(D3_count, gelecek_farklı_cap)

        # 7a. |fark| <= 0.1 → üç doluluk karşılaştır
        if abs(fark) <= 0.1:
            best_d = max(D1, D2, D3)
            if best_d == D3 and D3 > D1:
                selected = _select_jobs(mevcut_gelecek_eslesenler, gelecek_farklı_cap)
                setup_t = _get_setup_time(setup_matrix, bastaki_pid, gelecek_farklı_pid)
                return GroupResult(
                    selected_jobs=selected if selected else bastaki_jobs[:cap],
                    product_type=gelecek_farklı.product_type,
                    selected_product_id=gelecek_farklı_pid,
                    setup_required=True,
                    setup_time=setup_t,
                    reason="initial_gelecek_farklı_higher_fill",
                    should_wait=True,
                    reason_detail=(
                        f"{gelecek_farklı_pid} için bekleniyor. "
                        f"Öncelik farkı {fark:+.2f} (eşit sayılır, ≤0.1). "
                        f"Doluluk karşılaştırması — "
                        f"D1 (mevcut {bastaki_pid}): %{D1*100:.0f}, "
                        f"D2 (bekleyerek {bastaki_pid}): %{D2*100:.0f}, "
                        f"D3 (gelecek {gelecek_farklı_pid}): %{D3*100:.0f}. "
                        f"D3 en yüksek."
                    )
                )
            elif best_d == D2 and D2 > D1:
                selected = _select_jobs(bastaki_jobs, cap)
                return GroupResult(
                    selected_jobs=selected,
                    product_type=bastaki_type,
                    selected_product_id=bastaki_pid,
                    setup_required=True,
                    setup_time=0.0,
                    reason="initial_wait_same_better_fill",
                    should_wait=True,
                    reason_detail=(
                        f"{bastaki_pid} için bekleniyor. "
                        f"Öncelik farkı {fark:+.2f} (eşit sayılır, ≤0.1). "
                        f"Doluluk karşılaştırması — "
                        f"D1 (mevcut): %{D1*100:.0f}, "
                        f"D2 (bekleyerek): %{D2*100:.0f}, "
                        f"D3 (gelecek farklı): %{D3*100:.0f}. "
                        f"D2 en yüksek, bekleyerek daha iyi doluluk sağlanacak."
                    )
                )
            else:
                selected = _select_jobs(bastaki_jobs, cap)
                return GroupResult(
                    selected_jobs=selected,
                    product_type=bastaki_type,
                    selected_product_id=bastaki_pid,
                    setup_required=True,
                    setup_time=0.0,
                    reason="initial_current_best_fill",
                    reason_detail=(
                        f"{bastaki_pid} hemen işleme alındı. "
                        f"Öncelik farkı {fark:+.2f} (eşit sayılır, ≤0.1). "
                        f"Doluluk karşılaştırması — "
                        f"D1 (mevcut): %{D1*100:.0f}, "
                        f"D2 (bekleyerek): %{D2*100:.0f}, "
                        f"D3 (gelecek farklı): %{D3*100:.0f}. "
                        f"D1 en yüksek veya hepsi eşit."
                    )
                )

        # 7b. fark > 0.1 → gelecek_farklı çok daha acil
        if fark > 0.1:
            selected = _select_jobs(mevcut_gelecek_eslesenler, gelecek_farklı_cap)
            setup_t = _get_setup_time(setup_matrix, bastaki_pid, gelecek_farklı_pid)
            return GroupResult(
                selected_jobs=selected if selected else bastaki_jobs[:cap],
                product_type=gelecek_farklı.product_type,
                selected_product_id=gelecek_farklı_pid,
                setup_required=True,
                setup_time=setup_t,
                reason="initial_gelecek_much_higher_prio",
                should_wait=True,
                reason_detail=(
                    f"{gelecek_farklı_pid} için bekleniyor. "
                    f"Gelecek ürünün önceliği çok daha yüksek "
                    f"(fark {fark:+.2f} > 0.1). "
                    f"Mevcut {bastaki_pid} beklemeye alındı."
                )
            )

        # 7c. fark < -0.1 → baştaki_f çok daha acil
        if D2 > D1:
            selected = _select_jobs(bastaki_jobs, cap)
            return GroupResult(
                selected_jobs=selected,
                product_type=bastaki_type,
                selected_product_id=bastaki_pid,
                setup_required=True,
                setup_time=0.0,
                reason="initial_wait_same_better_fill_acil",
                should_wait=True,
                reason_detail=(
                    f"{bastaki_pid} için bekleniyor. "
                    f"Öncelik çok yüksek (fark {fark:+.2f} < -0.1). "
                    f"Bekleyerek doluluk artacak: "
                    f"D1 (mevcut): %{D1*100:.0f} → D2 (bekleyerek): %{D2*100:.0f}."
                )
            )
        else:
            selected = _select_jobs(bastaki_jobs, cap)
            fill = _calculate_fill_rate(len(selected), cap)
            return GroupResult(
                selected_jobs=selected,
                product_type=bastaki_type,
                selected_product_id=bastaki_pid,
                setup_required=True,
                setup_time=0.0,
                reason="initial_current_acil_go",
                reason_detail=(
                    f"{bastaki_pid} hemen işleme alındı. "
                    f"Öncelik çok yüksek (fark {fark:+.2f} < -0.1). "
                    f"Beklemek doluluk artırmıyor: "
                    f"D1 (mevcut): %{D1*100:.0f}, D2 (bekleyerek): %{D2*100:.0f}."
                )
            )

    # ════════════════════════════════════════════════════════════════
    # ADIM 4.1.1 — Önceki Ürün Eşleştirmesi (Makine Geçmişi Var)
    # ════════════════════════════════════════════════════════════════
    @staticmethod
    def _step_4_1_1(
        bastaki_pid: str, bastaki_jobs: List[Job], bastaki_max_prio: float,
        bastaki_type: str, groups: Dict[str, List[Job]],
        full_queue: List[Job], capacity: Union[int, Dict[str, int]],
        last_product_id: str, setup_matrix: SetupMatrix, current_time: datetime
    ) -> GroupResult:
        """Makinenin geçmişi var — önceki ürün ile eşleştirme dene."""

        cap = _get_capacity_for_product(capacity, bastaki_pid)

        # Önceki ürün ile baştaki_f arasındaki setup süresi
        setup_to_bastaki = _get_setup_time(setup_matrix, last_product_id, bastaki_pid)

        # ── Uyuşma kontrolü: setup == 0 ise "aynı tip" ──
        if setup_to_bastaki == 0.0:
            # Setup ortadan kalktı → doluluk kontrolüne geç
            doluluk = _calculate_fill_rate(len(bastaki_jobs), cap)

            # %60 veya üzeri → hemen işleme al
            if doluluk >= 0.60:
                selected = _select_jobs(bastaki_jobs, cap)
                return GroupResult(
                    selected_jobs=selected,
                    product_type=bastaki_type,
                    selected_product_id=bastaki_pid,
                    setup_required=False,
                    setup_time=0.0,
                    reason="same_type_high_fill",
                    reason_detail=(
                        f"{bastaki_pid} hemen işleme alındı. "
                        f"Önceki ürün ({last_product_id}) ile aynı tip — setup yok. "
                        f"Doluluk %{doluluk*100:.0f} ≥ %60, beklemeye gerek yok."
                    )
                )

            # Doluluk < %60 → 1 saat gelecek kontrolü
            return GroupBuilder._check_1h_future(
                bastaki_pid, bastaki_jobs, bastaki_max_prio, bastaki_type,
                groups, full_queue, capacity, last_product_id, setup_matrix,
                current_time, cap
            )
        else:
            # Uyuşmuyor (setup > 0) → 4.1-B mantığı uygulanır (setup süresi var)
            return GroupBuilder._step_4_1_B_with_setup(
                bastaki_pid, bastaki_jobs, bastaki_max_prio, bastaki_type,
                groups, full_queue, capacity, last_product_id, setup_matrix,
                current_time, setup_to_bastaki
            )

    @staticmethod
    def _step_4_1_B_with_setup(
        bastaki_pid: str, bastaki_jobs: List[Job], bastaki_max_prio: float,
        bastaki_type: str, groups: Dict[str, List[Job]],
        full_queue: List[Job], capacity: Union[int, Dict[str, int]],
        last_product_id: str, setup_matrix: SetupMatrix,
        current_time: datetime, setup_time: float
    ) -> GroupResult:
        """Makine geçmişi var ama farklı tip → setup gerekli, setup süresi boyunca geleceğe bak."""

        cap = _get_capacity_for_product(capacity, bastaki_pid)

        # Setup süresi boyunca gelecek en yüksek öncelikli parça
        gelecek_en_acil = _find_future_highest_priority(full_queue, current_time, setup_time)

        if gelecek_en_acil is None:
            selected = _select_jobs(bastaki_jobs, cap)
            fill = _calculate_fill_rate(len(selected), cap)
            return GroupResult(
                selected_jobs=selected,
                product_type=bastaki_type,
                selected_product_id=bastaki_pid,
                setup_required=True,
                setup_time=setup_time,
                reason="setup_no_future",
                reason_detail=(
                    f"{bastaki_pid} işleme alındı. "
                    f"Önceki ürün {last_product_id} farklı tip — "
                    f"{setup_time:.1f} saatlik setup gerekli. "
                    f"Setup süresi içinde gelecek parça yok. "
                    f"Doluluk: %{fill*100:.0f}."
                )
            )

        # Gelecek baştaki ile aynı product_id
        if gelecek_en_acil.product_id == bastaki_pid:
            future_same = _find_future_jobs(full_queue, current_time, setup_time,
                                           product_id=bastaki_pid)
            all_candidates = bastaki_jobs + future_same
            seen_ids = set()
            unique = [j for j in all_candidates if j.job_id not in seen_ids and not seen_ids.add(j.job_id)]
            selected = _select_jobs(unique, cap)
            has_future = any(j.ready_time > current_time for j in selected)
            fill = _calculate_fill_rate(len(selected), cap)
            wait_str = "Bekleniyor." if has_future else "Birlikte alındı."
            return GroupResult(
                selected_jobs=selected,
                product_type=bastaki_type,
                selected_product_id=bastaki_pid,
                setup_required=True,
                setup_time=setup_time,
                reason="setup_wait_same",
                should_wait=has_future,
                reason_detail=(
                    f"{bastaki_pid} seçildi. "
                    f"Setup süresi ({setup_time:.1f} saat) içinde aynı ürün gelecek "
                    f"({len(future_same)} parça). {wait_str} "
                    f"Doluluk: {len(selected)}/{cap} = %{fill*100:.0f}."
                )
            )

        # Gelecek farklı
        gelecek_farklı = gelecek_en_acil
        gelecek_farklı_pid = gelecek_farklı.product_id
        fark = gelecek_farklı.priority_score - bastaki_max_prio

        gelecek_farklı_cap = _get_capacity_for_product(capacity, gelecek_farklı_pid)

        D1 = _calculate_fill_rate(len(bastaki_jobs), cap)
        future_same = _find_future_jobs(full_queue, current_time, setup_time, product_id=bastaki_pid)
        D2 = _calculate_fill_rate(len(bastaki_jobs) + len(future_same), cap)
        mevcut_eslesenler = groups.get(gelecek_farklı_pid, [])
        D3 = _calculate_fill_rate(len(mevcut_eslesenler) + 1, gelecek_farklı_cap)

        if abs(fark) <= 0.1:
            best = max(D1, D2, D3)
            if best == D3 and D3 > D1:
                setup_t = _get_setup_time(setup_matrix, last_product_id, gelecek_farklı_pid)
                selected = _select_jobs(mevcut_eslesenler, gelecek_farklı_cap) or _select_jobs(bastaki_jobs, cap)
                return GroupResult(
                    selected_jobs=selected,
                    product_type=gelecek_farklı.product_type,
                    selected_product_id=gelecek_farklı_pid,
                    setup_required=True,
                    setup_time=setup_t,
                    reason="setup_gelecek_farklı_better_fill",
                    should_wait=True,
                    reason_detail=(
                        f"{gelecek_farklı_pid} için bekleniyor. "
                        f"Öncelik farkı {fark:+.2f} (eşit sayılır, ≤0.1). "
                        f"Doluluk — D1 ({bastaki_pid} mevcut): %{D1*100:.0f}, "
                        f"D2 ({bastaki_pid} bekleyerek): %{D2*100:.0f}, "
                        f"D3 ({gelecek_farklı_pid}): %{D3*100:.0f}. "
                        f"D3 en yüksek."
                    )
                )
            elif best == D2 and D2 > D1:
                selected = _select_jobs(bastaki_jobs, cap)
                return GroupResult(
                    selected_jobs=selected,
                    product_type=bastaki_type,
                    selected_product_id=bastaki_pid,
                    setup_required=True,
                    setup_time=setup_time,
                    reason="setup_wait_same_better",
                    should_wait=True,
                    reason_detail=(
                        f"{bastaki_pid} için bekleniyor. "
                        f"Öncelik farkı {fark:+.2f} (eşit sayılır, ≤0.1). "
                        f"Doluluk — D1 (mevcut): %{D1*100:.0f}, "
                        f"D2 (bekleyerek): %{D2*100:.0f}, "
                        f"D3 (gelecek farklı): %{D3*100:.0f}. "
                        f"D2 en yüksek, bekleyerek daha iyi doluluk sağlanacak."
                    )
                )
            else:
                selected = _select_jobs(bastaki_jobs, cap)
                return GroupResult(
                    selected_jobs=selected,
                    product_type=bastaki_type,
                    selected_product_id=bastaki_pid,
                    setup_required=True,
                    setup_time=setup_time,
                    reason="setup_current_best",
                    reason_detail=(
                        f"{bastaki_pid} hemen işleme alındı. "
                        f"Öncelik farkı {fark:+.2f} (eşit sayılır, ≤0.1). "
                        f"Doluluk — D1 (mevcut): %{D1*100:.0f}, "
                        f"D2 (bekleyerek): %{D2*100:.0f}, "
                        f"D3 (gelecek farklı): %{D3*100:.0f}. "
                        f"D1 en yüksek veya hepsi eşit."
                    )
                )

        if fark > 0.1:
            setup_t = _get_setup_time(setup_matrix, last_product_id, gelecek_farklı_pid)
            selected = _select_jobs(mevcut_eslesenler, gelecek_farklı_cap) or _select_jobs(bastaki_jobs, cap)
            return GroupResult(
                selected_jobs=selected,
                product_type=gelecek_farklı.product_type,
                selected_product_id=gelecek_farklı_pid,
                setup_required=True,
                setup_time=setup_t,
                reason="setup_gelecek_much_higher",
                should_wait=True,
                reason_detail=(
                    f"{gelecek_farklı_pid} için bekleniyor. "
                    f"Gelecek ürünün önceliği çok daha yüksek "
                    f"(fark {fark:+.2f} > 0.1)."
                )
            )

        # fark < -0.1
        if D2 > D1:
            selected = _select_jobs(bastaki_jobs, cap)
            return GroupResult(
                selected_jobs=selected,
                product_type=bastaki_type,
                selected_product_id=bastaki_pid,
                setup_required=True,
                setup_time=setup_time,
                reason="setup_wait_acil_better",
                should_wait=True,
                reason_detail=(
                    f"{bastaki_pid} için bekleniyor. "
                    f"Öncelik çok yüksek (fark {fark:+.2f} < -0.1). "
                    f"Bekleyerek doluluk artacak: "
                    f"D1 (mevcut): %{D1*100:.0f} → D2 (bekleyerek): %{D2*100:.0f}."
                )
            )
        selected = _select_jobs(bastaki_jobs, cap)
        fill = _calculate_fill_rate(len(selected), cap)
        return GroupResult(
            selected_jobs=selected,
            product_type=bastaki_type,
            selected_product_id=bastaki_pid,
            setup_required=True,
            setup_time=setup_time,
            reason="setup_acil_go",
            reason_detail=(
                f"{bastaki_pid} hemen işleme alındı. "
                f"Öncelik çok yüksek (fark {fark:+.2f} < -0.1). "
                f"Beklemek doluluk artırmıyor: "
                f"D1 (mevcut): %{D1*100:.0f}, D2 (bekleyerek): %{D2*100:.0f}."
            )
        )

    # ════════════════════════════════════════════════════════════════
    # 1 Saatlik Gelecek Kontrolü (Adım 4.1.1 alt dalı)
    # ════════════════════════════════════════════════════════════════
    @staticmethod
    def _check_1h_future(
        bastaki_pid: str, bastaki_jobs: List[Job], bastaki_max_prio: float,
        bastaki_type: str, groups: Dict[str, List[Job]],
        full_queue: List[Job], capacity: Union[int, Dict[str, int]],
        last_product_id: str, setup_matrix: SetupMatrix,
        current_time: datetime, cap: int
    ) -> GroupResult:
        """Doluluk < %60 durumunda 1 saat içinde gelecek parçaları kontrol et."""

        WAIT_HOURS = 1.0

        doluluk_mevcut = _calculate_fill_rate(len(bastaki_jobs), cap)

        # 1 saat içinde gelecek en yüksek öncelikli parça
        gelecek_1h_en_acil = _find_future_highest_priority(full_queue, current_time, WAIT_HOURS)

        # A. Hiç gelecek parça yoksa → mevcut dolulukla hemen işle
        if gelecek_1h_en_acil is None:
            selected = _select_jobs(bastaki_jobs, cap)
            return GroupResult(
                selected_jobs=selected,
                product_type=bastaki_type,
                selected_product_id=bastaki_pid,
                setup_required=False,
                setup_time=0.0,
                reason="no_future_1h_go",
                reason_detail=(
                    f"{bastaki_pid} hemen işleme alındı. "
                    f"Doluluk %{doluluk_mevcut*100:.0f} < %60 ancak "
                    f"1 saat içinde gelecek hiç parça yok."
                )
            )

        gelecek_pid = gelecek_1h_en_acil.product_id
        gelecek_type = gelecek_1h_en_acil.product_type
        gelecek_prio = gelecek_1h_en_acil.priority_score

        # B. Gelecek = aynı product_type VE aynı product_id (aynı tip+adım)
        if gelecek_pid == bastaki_pid:
            future_same = _find_future_jobs(full_queue, current_time, WAIT_HOURS,
                                           product_id=bastaki_pid)
            all_candidates = bastaki_jobs + future_same
            seen_ids = set()
            unique = [j for j in all_candidates if j.job_id not in seen_ids and not seen_ids.add(j.job_id)]
            selected = _select_jobs(unique, cap)
            has_future = any(j.ready_time > current_time for j in selected)
            fill = _calculate_fill_rate(len(selected), cap)
            wait_str = "Bekleniyor." if has_future else "Birlikte işleme alındı."
            return GroupResult(
                selected_jobs=selected,
                product_type=bastaki_type,
                selected_product_id=bastaki_pid,
                setup_required=False,
                setup_time=0.0,
                reason="1h_same_type_wait",
                should_wait=has_future,
                reason_detail=(
                    f"{bastaki_pid} seçildi. "
                    f"Doluluk %{doluluk_mevcut*100:.0f} < %60, "
                    f"1 saat içinde aynı ürün gelecek ({len(future_same)} parça). "
                    f"{wait_str} Beklenen doluluk: {len(selected)}/{cap} = %{fill*100:.0f}."
                )
            )

        # C. Gelecek = aynı product_type ama farklı product_id (aynı tip, farklı adım) → "gelecek_farklı"
        if gelecek_type == bastaki_type and gelecek_pid != bastaki_pid:
            fark = gelecek_prio - bastaki_max_prio

            D1 = _calculate_fill_rate(len(bastaki_jobs), cap)
            future_same_step = _find_future_jobs(full_queue, current_time, WAIT_HOURS,
                                                product_id=bastaki_pid)
            D2 = _calculate_fill_rate(len(bastaki_jobs) + len(future_same_step), cap)
            gelecek_farklı_cap = _get_capacity_for_product(capacity, gelecek_pid)
            mevcut_eslesenler = groups.get(gelecek_pid, [])
            D3 = _calculate_fill_rate(len(mevcut_eslesenler) + 1, gelecek_farklı_cap)

            # C1. |fark| <= 0.1
            if abs(fark) <= 0.1:
                best = max(D1, D2, D3)
                if best == D3 and D3 > D1:
                    selected = _select_jobs(mevcut_eslesenler, gelecek_farklı_cap) or _select_jobs(bastaki_jobs, cap)
                    return GroupResult(
                        selected_jobs=selected,
                        product_type=gelecek_type,
                        selected_product_id=gelecek_pid,
                        setup_required=False,
                        setup_time=0.0,
                        reason="1h_gelecek_farklı_fill",
                        should_wait=True,
                        reason_detail=(
                            f"{gelecek_pid} için bekleniyor. "
                            f"Aynı tip, farklı ürün. Öncelik farkı {fark:+.2f} (≤0.1). "
                            f"Doluluk — D1 ({bastaki_pid}): %{D1*100:.0f}, "
                            f"D2 (bekleyerek {bastaki_pid}): %{D2*100:.0f}, "
                            f"D3 ({gelecek_pid}): %{D3*100:.0f}. D3 en yüksek."
                        )
                    )
                elif best == D2 and D2 > D1:
                    selected = _select_jobs(bastaki_jobs, cap)
                    return GroupResult(
                        selected_jobs=selected,
                        product_type=bastaki_type,
                        selected_product_id=bastaki_pid,
                        setup_required=False,
                        setup_time=0.0,
                        reason="1h_wait_same_better",
                        should_wait=True,
                        reason_detail=(
                            f"{bastaki_pid} için bekleniyor. "
                            f"Aynı tip, farklı ürün. Öncelik farkı {fark:+.2f} (≤0.1). "
                            f"Doluluk — D1 (mevcut): %{D1*100:.0f}, "
                            f"D2 (bekleyerek): %{D2*100:.0f}, "
                            f"D3 (gelecek farklı): %{D3*100:.0f}. "
                            f"D2 en yüksek, bekleyerek daha iyi doluluk."
                        )
                    )
                else:
                    selected = _select_jobs(bastaki_jobs, cap)
                    return GroupResult(
                        selected_jobs=selected,
                        product_type=bastaki_type,
                        selected_product_id=bastaki_pid,
                        setup_required=False,
                        setup_time=0.0,
                        reason="1h_current_best",
                        reason_detail=(
                            f"{bastaki_pid} hemen işleme alındı. "
                            f"Aynı tip, farklı ürün. Öncelik farkı {fark:+.2f} (≤0.1). "
                            f"Doluluk — D1 (mevcut): %{D1*100:.0f}, "
                            f"D2 (bekleyerek): %{D2*100:.0f}, "
                            f"D3 (gelecek farklı): %{D3*100:.0f}. D1 en yüksek."
                        )
                    )

            # C2. baştaki >> gelecek (fark < -0.1)
            if fark < -0.1:
                D1 = _calculate_fill_rate(len(bastaki_jobs), cap)
                future_same = _find_future_jobs(full_queue, current_time, WAIT_HOURS,
                                               product_id=bastaki_pid)
                D2 = _calculate_fill_rate(len(bastaki_jobs) + len(future_same), cap)
                if D2 > D1:
                    selected = _select_jobs(bastaki_jobs, cap)
                    return GroupResult(
                        selected_jobs=selected,
                        product_type=bastaki_type,
                        selected_product_id=bastaki_pid,
                        setup_required=False,
                        setup_time=0.0,
                        reason="1h_acil_wait_better",
                        should_wait=True,
                        reason_detail=(
                            f"{bastaki_pid} için bekleniyor. "
                            f"Öncelik çok yüksek (fark {fark:+.2f} < -0.1). "
                            f"Bekleyerek doluluk artacak: "
                            f"D1: %{D1*100:.0f} → D2: %{D2*100:.0f}."
                        )
                    )
                selected = _select_jobs(bastaki_jobs, cap)
                return GroupResult(
                    selected_jobs=selected,
                    product_type=bastaki_type,
                    selected_product_id=bastaki_pid,
                    setup_required=False,
                    setup_time=0.0,
                    reason="1h_acil_go",
                    reason_detail=(
                        f"{bastaki_pid} hemen işleme alındı. "
                        f"Öncelik çok yüksek (fark {fark:+.2f} < -0.1). "
                        f"Beklemek doluluk artırmıyor: D1=%{D1*100:.0f}, D2=%{D2*100:.0f}."
                    )
                )

            # C3. gelecek >> baştaki (fark > 0.1)
            selected = _select_jobs(mevcut_eslesenler, gelecek_farklı_cap) or _select_jobs(bastaki_jobs, cap)
            return GroupResult(
                selected_jobs=selected,
                product_type=gelecek_type,
                selected_product_id=gelecek_pid,
                setup_required=False,
                setup_time=0.0,
                reason="1h_gelecek_much_higher",
                should_wait=True,
                reason_detail=(
                    f"{gelecek_pid} için bekleniyor. "
                    f"Aynı tip, farklı ürün. Gelecek ürünün önceliği çok daha yüksek "
                    f"(fark {fark:+.2f} > 0.1)."
                )
            )

        # D. Gelecek tamamen farklı product_type → "farklı_tip" → ADIM 4.1.1.1
        return GroupBuilder._step_4_1_1_1(
            bastaki_pid, bastaki_jobs, bastaki_max_prio, bastaki_type,
            gelecek_1h_en_acil, groups, full_queue, capacity,
            last_product_id, setup_matrix, current_time, cap
        )

    # ════════════════════════════════════════════════════════════════
    # ADIM 4.1.1.1 — Farklı Tip Gelecek Parça Değerlendirmesi
    # ════════════════════════════════════════════════════════════════
    @staticmethod
    def _step_4_1_1_1(
        bastaki_pid: str, bastaki_jobs: List[Job], bastaki_max_prio: float,
        bastaki_type: str, farklı_tip_job: Job,
        groups: Dict[str, List[Job]], full_queue: List[Job],
        capacity: Union[int, Dict[str, int]],
        last_product_id: str, setup_matrix: SetupMatrix,
        current_time: datetime, cap: int
    ) -> GroupResult:
        """Farklı tip gelecek parça: setup süresi boyunca tekrar geleceğe bak."""

        farklı_tip_pid = farklı_tip_job.product_id
        farklı_tip_setup = _get_setup_time(setup_matrix, bastaki_pid, farklı_tip_pid)
        if farklı_tip_setup <= 0:
            farklı_tip_setup = 0.5  # Minimum bekleme penceresi

        # Setup süresi boyunca gelecek en yüksek öncelikli parçayı kontrol et
        gelecek_setup_en_acil = _find_future_highest_priority(
            full_queue, current_time, farklı_tip_setup)

        # A. Setup süresinde gelecek, baştaki ile aynı product_type
        if (gelecek_setup_en_acil and
                gelecek_setup_en_acil.product_type == bastaki_type):
            # 4.1.1 doluluk kontrol mantığını uygula (setup kalkar, bekleme olmuş olur)
            return GroupBuilder._check_1h_future(
                bastaki_pid, bastaki_jobs, bastaki_max_prio, bastaki_type,
                groups, full_queue, capacity, last_product_id, setup_matrix,
                current_time, cap
            )

        # B. Hâlâ farklı tip → "farklı_tip_tekrar"
        if gelecek_setup_en_acil:
            farklı_tekrar = gelecek_setup_en_acil
            farklı_tekrar_pid = farklı_tekrar.product_id
            fark = farklı_tekrar.priority_score - bastaki_max_prio

            farklı_tekrar_cap = _get_capacity_for_product(capacity, farklı_tekrar_pid)

            # B1. farklı_tip_tekrar çok daha acil (fark > 0.1)
            if fark > 0.1:
                mevcut_eslesenler = groups.get(farklı_tekrar_pid, [])
                selected = _select_jobs(mevcut_eslesenler, farklı_tekrar_cap)
                if not selected:
                    selected = _select_jobs(bastaki_jobs, cap)
                    return GroupResult(
                        selected_jobs=selected,
                        product_type=bastaki_type,
                        selected_product_id=bastaki_pid,
                        setup_required=False,
                        setup_time=0.0,
                        reason="4111_farklı_tekrar_acil_no_match",
                        reason_detail=(
                            f"{bastaki_pid} hemen işleme alındı. "
                            f"Çok acil farklı tip ({farklı_tekrar_pid}) var "
                            f"(fark {fark:+.2f} > 0.1) ama kuyrukta o tipten parça yok."
                        )
                    )
                setup_t = _get_setup_time(setup_matrix, last_product_id, farklı_tekrar_pid)
                return GroupResult(
                    selected_jobs=selected,
                    product_type=farklı_tekrar.product_type,
                    selected_product_id=farklı_tekrar_pid,
                    setup_required=True,
                    setup_time=setup_t,
                    reason="4111_farklı_tekrar_acil",
                    reason_detail=(
                        f"{farklı_tekrar_pid} için bekleniyor. "
                        f"Setup süresi içinde yine farklı tip gelecek. "
                        f"Öncelik çok daha yüksek (fark {fark:+.2f} > 0.1)."
                    )
                )

            # B2. Yakın öncelik (|fark| <= 0.1)
            if abs(fark) <= 0.1:
                D1 = _calculate_fill_rate(len(bastaki_jobs), cap)
                future_same = _find_future_jobs(
                    full_queue, current_time, farklı_tip_setup, product_id=bastaki_pid)
                D2 = _calculate_fill_rate(len(bastaki_jobs) + len(future_same), cap)
                mevcut_eslesenler = groups.get(farklı_tekrar_pid, [])
                # +1: B/N'den gelecek olan farklı_tekrar parça da hesaba dahil
                # (diğer iki D3 hesabıyla tutarlı: _step_4_1_B ve _check_1h_future)
                D3 = _calculate_fill_rate(len(mevcut_eslesenler) + 1, farklı_tekrar_cap)

                best = max(D1, D2, D3)
                if best == D3 and D3 > D1:
                    setup_t = _get_setup_time(setup_matrix, last_product_id, farklı_tekrar_pid)
                    selected = _select_jobs(mevcut_eslesenler, farklı_tekrar_cap) or _select_jobs(bastaki_jobs, cap)
                    return GroupResult(
                        selected_jobs=selected,
                        product_type=farklı_tekrar.product_type,
                        selected_product_id=farklı_tekrar_pid,
                        setup_required=True,
                        setup_time=setup_t,
                        reason="4111_farklı_tekrar_better_fill",
                        should_wait=True,
                        reason_detail=(
                            f"{farklı_tekrar_pid} seçildi. "
                            f"Öncelik farkı {fark:+.2f} (≤0.1). "
                            f"Doluluk — D1 ({bastaki_pid}): %{D1*100:.0f}, "
                            f"D2 (bekleyerek {bastaki_pid}): %{D2*100:.0f}, "
                            f"D3 ({farklı_tekrar_pid}): %{D3*100:.0f}. D3 en yüksek."
                        )
                    )
                elif best == D2 and D2 > D1:
                    selected = _select_jobs(bastaki_jobs, cap)
                    return GroupResult(
                        selected_jobs=selected,
                        product_type=bastaki_type,
                        selected_product_id=bastaki_pid,
                        setup_required=False,
                        setup_time=0.0,
                        reason="4111_wait_same_better",
                        should_wait=True,
                        reason_detail=(
                            f"{bastaki_pid} için bekleniyor. "
                            f"Öncelik farkı {fark:+.2f} (≤0.1). "
                            f"Bekleyerek doluluk artacak: "
                            f"D1: %{D1*100:.0f} → D2: %{D2*100:.0f}."
                        )
                    )
                else:
                    selected = _select_jobs(bastaki_jobs, cap)
                    return GroupResult(
                        selected_jobs=selected,
                        product_type=bastaki_type,
                        selected_product_id=bastaki_pid,
                        setup_required=False,
                        setup_time=0.0,
                        reason="4111_current_best",
                        reason_detail=(
                            f"{bastaki_pid} hemen işleme alındı. "
                            f"Öncelik farkı {fark:+.2f} (≤0.1). "
                            f"Doluluk — D1: %{D1*100:.0f}, D2: %{D2*100:.0f}, "
                            f"D3: %{D3*100:.0f}. D1 en yüksek."
                        )
                    )

            # B3. baştaki çok daha acil (fark < -0.1)
            D1 = _calculate_fill_rate(len(bastaki_jobs), cap)
            # gelecek_farklı = farklı_tekrar (4.1.1.1 penceresinde gözüken EN GÜNCEL gelecek parça)
            gelecek_farklı_in_groups = groups.get(farklı_tekrar_pid, [])
            gelecek_farklı_cap = _get_capacity_for_product(capacity, farklı_tekrar_pid)
            D2 = _calculate_fill_rate(len(gelecek_farklı_in_groups) + 1, gelecek_farklı_cap)
            if D2 > D1:
                setup_t = _get_setup_time(setup_matrix, last_product_id, farklı_tekrar_pid)
                selected = _select_jobs(gelecek_farklı_in_groups, gelecek_farklı_cap) or _select_jobs(bastaki_jobs, cap)
                return GroupResult(
                    selected_jobs=selected,
                    product_type=farklı_tekrar.product_type,
                    selected_product_id=farklı_tekrar_pid,
                    setup_required=True,
                    setup_time=setup_t,
                    reason="4111_gelecek_farklı_better_fill",
                    should_wait=True,
                    reason_detail=(
                        f"{farklı_tekrar_pid} seçildi. "
                        f"Öncelik çok düşük (fark {fark:+.2f} < -0.1) ama "
                        f"doluluk daha yüksek: D2 ({farklı_tekrar_pid}): %{D2*100:.0f} "
                        f"> D1 ({bastaki_pid}): %{D1*100:.0f}."
                    )
                )
            selected = _select_jobs(bastaki_jobs, cap)
            return GroupResult(
                selected_jobs=selected,
                product_type=bastaki_type,
                selected_product_id=bastaki_pid,
                setup_required=False,
                setup_time=0.0,
                reason="4111_acil_go",
                reason_detail=(
                    f"{bastaki_pid} hemen işleme alındı. "
                    f"Öncelik çok yüksek (fark {fark:+.2f} < -0.1). "
                    f"Mevcut doluluk en iyi: D1=%{D1*100:.0f} ≥ D2=%{D2*100:.0f}."
                )
            )

        # Gelecek yoksa → mevcut dolulukla hemen işle
        selected = _select_jobs(bastaki_jobs, cap)
        fill = _calculate_fill_rate(len(selected), cap)
        return GroupResult(
            selected_jobs=selected,
            product_type=bastaki_type,
            selected_product_id=bastaki_pid,
            setup_required=False,
            setup_time=0.0,
            reason="4111_no_future_go",
            reason_detail=(
                f"{bastaki_pid} hemen işleme alındı. "
                f"Setup süresi ({farklı_tip_setup:.1f} saat) içinde de parça gelmeyecek. "
                f"Doluluk: %{fill*100:.0f}."
            )
        )
