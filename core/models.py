"""
Domain models and Data Transfer Objects (DTOs) for twitch-auto-clipper.
Defines contracts across the 4 decoupled modules.
"""
from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


@dataclass
class ChatMessage:
    """Evento normalizado de mensagem recebida no chat."""
    author: str
    text: str
    timestamp: datetime = field(default_factory=_utcnow)
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    emotes: List[str] = field(default_factory=list)
    bits: int = 0
    is_subscriber: bool = False
    is_moderator: bool = False

    def to_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        data["timestamp"] = self.timestamp.isoformat()
        return data


@dataclass
class HypeScoreBreakdown:
    """Detalhamento da pontuação calculada para fins de auditoria/log."""
    messages_per_sec: float = 0.0
    keyword_matches: int = 0
    emotes_count: int = 0
    bits_donated: int = 0
    total_score: float = 0.0


@dataclass
class HypeEvent:
    """Evento disparado quando um pico de hype é detectado."""
    score: float
    reason: str
    streamer_channel: str
    suggested_duration: float = 30.0
    pre_roll_seconds: float = 15.0
    timestamp: datetime = field(default_factory=_utcnow)
    event_id: str = field(default_factory=lambda: f"hype_{uuid.uuid4().hex[:8]}")
    event_name: str = "Clipe Detectado"
    breakdown: Optional[HypeScoreBreakdown] = None
    json_path: Optional[str] = None
    spike_multiplier: float = 0.0
    recent_messages_count: int = 0

    def to_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        data["timestamp"] = self.timestamp.isoformat()
        return data


@dataclass
class ClipMetadata:
    """Metadados do vídeo gerado após corte e formatação."""
    clip_id: str
    file_path: str
    title: str
    description: str
    tags: List[str]
    duration: float
    resolution: Tuple[int, int] = (1080, 1920)
    created_at: datetime = field(default_factory=_utcnow)
    hype_score: float = 0.0

    def file_exists(self) -> bool:
        return Path(self.file_path).is_file()

    def to_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        data["created_at"] = self.created_at.isoformat()
        return data


@dataclass
class UploadResult:
    """Resultado da publicação em uma rede social específica."""
    platform: str
    success: bool
    post_id: Optional[str] = None
    post_url: Optional[str] = None
    error_message: Optional[str] = None
    published_at: datetime = field(default_factory=_utcnow)

    def to_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        data["published_at"] = self.published_at.isoformat()
        return data
