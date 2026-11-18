"""
Configurable rules and weights for hype scoring.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List


@dataclass
class HypeRuleConfig:
    """Parâmetros e pesos para o cálculo do score de hype."""
    window_seconds: int = 10
    threshold_mps: float = 3.5
    min_score: float = 8.0
    cooldown_seconds: int = 30
    keywords: List[str] = field(default_factory=lambda: [
        "POG", "POGGERS", "LUL", "KEKW", "CLIP", "OMG", "WTF", "GG", "NICE", "INSANE", "JOGOU", "MUITO"
    ])

    # Pesos de ponderação
    weight_mps: float = 2.0
    weight_keyword: float = 1.5
    weight_emote: float = 0.5
    weight_bits: float = 0.01  # 100 bits = +1 ponto
    weight_sub: float = 0.8    # Bônus para mensagens de inscritos
