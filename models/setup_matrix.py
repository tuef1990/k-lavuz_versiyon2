from dataclasses import dataclass
from typing import Dict

@dataclass
class SetupMatrix:
    product_ids: list[str]
    matrix: Dict[str, Dict[str, float]]
