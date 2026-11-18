"""Hype Detector module."""
from .base import BaseHypeDetector
from .rules import HypeRuleConfig
from .detector import SlidingWindowHypeDetector
from .moving_average_detector import MovingAverageHypeDetector

__all__ = [
    "BaseHypeDetector",
    "HypeRuleConfig",
    "SlidingWindowHypeDetector",
    "MovingAverageHypeDetector",
]
