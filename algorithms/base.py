from abc import ABC, abstractmethod
from datetime import datetime
from typing import List, Optional
import math
from core.models import AppState
from models.planning_result import PlanningResult

# --- Sabitler ---

# Üretim hattındaki adımların sırası (Assembly'den ATP+STP'ye)
PROCESS_STEPS_ORDER = ['assembly', 'ftp', 'bn', 'dkk', 'rvb', 'atp_stp']

# Her adımdan sonra iş hangi adıma geçer (None = süreç tamamlandı)
NEXT_STEP = {
    'assembly': 'ftp',
    'ftp': 'bn',
    'bn': 'dkk',
    'dkk': 'rvb',
    'rvb': 'atp_stp',
    'atp_stp': None
}

# Assembly setup gerektirmez (tek istasyon, sabit hat)
SETUP_EXEMPT_STEPS = {'assembly'}
# DKK ve ATP+STP M1-M4 makinelerini paylaşır
PARALLEL_MACHINE_STEPS = {'dkk', 'atp_stp'}
SHARED_MACHINES = ['M1', 'M2', 'M3', 'M4']
# FTP tek seferde yalnızca 1 parça işler
SINGLE_PART_STEPS = {'ftp'}
# B/N kapasite dolmayı bekler; GroupBuilder benzeri mantık burada uygulanır
WAIT_PREFERRED_STEPS = {'bn'}
DAILY_INITIAL_SETUP_HOURS = 2.0  # Makine o gün ilk kez çalışıyorsa eklenen setup (saat)
# Günlük setup yalnızca bu adımlarda takip edilir (Assembly ve FTP'de gerek yok)
DAILY_SETUP_STEPS = {'dkk', 'rvb', 'atp_stp'}

STEP_MACHINE_NAMES = {
    'assembly': 'İstasyon',
    'ftp': 'FTP',
    'bn': 'B/N',
    'rvb': 'RVB',
}

class PlanningAlgorithm(ABC):
    @abstractmethod
    def solve(
        self,
        project_data: AppState,
        start_date: datetime,
        end_date: datetime,
        period: str,
        priority_overrides: dict[str, float] | None = None,
        excel_products: Optional[List] = None
    ) -> PlanningResult:
        pass

    @staticmethod
    def calculate_period_target(monthly_target: int, period: str, start_date: datetime = None, end_date: datetime = None) -> int:
        if period == 'monthly':
            return monthly_target
        elif period == 'weekly':
            return math.ceil(monthly_target / 4)
        elif period == 'custom' and start_date and end_date:
            days = (end_date.date() - start_date.date()).days
            if days <= 0: days = 1
            # Kullanıcının örneği üzerinden: 60 aylık hedef, 5 günlük periyot -> 10 adet.
            # 60 * (5/30) = 10.
            return math.ceil(monthly_target * days / 30)
        
        # Default or error case
        if period == 'custom': return math.ceil(monthly_target / 4) # Fallback
        raise ValueError(f'Geçersiz periyot: {period}')

