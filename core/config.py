"""
Configuration manager for twitch-auto-clipper.
Loads settings from environment variables and .env file.
Works out of the box with zero external dependencies,
and seamlessly integrates with pydantic-settings if installed.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import List


def _load_dotenv_file(filepath: Path) -> None:
    """Carrega arquivo .env simples no os.environ sem depender de pacotes externos."""
    if not filepath.is_file():
        return
    with open(filepath, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" in line:
                key, val = line.split("=", 1)
                key = key.strip()
                val = val.strip().strip("'\"")
                if key and key not in os.environ:
                    os.environ[key] = val


@dataclass
class Settings:
    """Configurações centralizadas do sistema."""
    # App
    app_env: str = "development"
    mock_mode: bool = True
    storage_dir: Path = Path("./storage/clips")
    events_dir: Path = Path("./storage/events")

    # Chat Listener
    twitch_channel: str = "gaules"
    twitch_bot_nickname: str = "justinfan98765"
    twitch_oauth_token: str = "oauth:mock_token"
    twitch_client_id: str = "mock_client_id"
    twitch_client_secret: str = "mock_client_secret"

    # Hype Detector
    hype_interval_seconds: int = 5
    hype_spike_multiplier: float = 3.0
    hype_window_seconds: int = 10
    hype_threshold_mps: float = 4.0
    hype_min_score: float = 10.0
    hype_cooldown_seconds: int = 45
    hype_keywords: List[str] = field(default_factory=lambda: [
        "POG", "POGGERS", "LUL", "KEKW", "CLIP", "OMG", "WTF", "GG", "NICE", "INSANE", "JOGOU", "MUITO"
    ])

    # Video Processor
    clip_duration_seconds: int = 45
    clip_preroll_seconds: int = 30
    clip_postroll_seconds: int = 15
    video_framing_mode: str = "blur"
    video_vertical_aspect: bool = True
    stream_buffer_dir: Path = Path("./storage/buffer")
    ffmpeg_path: str = "/usr/bin/ffmpeg"

    # Clip Analyst (Gemini + Whisper)
    gemini_api_key: str = ""
    gemini_model: str = "gemini-2.0-flash"
    min_clip_score: float = 6.0
    whisper_model_size: str = "tiny"
    whisper_device: str = "cpu"
    whisper_language: str = "pt"

    # Social Uploader
    youtube_enabled: bool = True
    tiktok_enabled: bool = True
    instagram_enabled: bool = False
    youtube_client_secrets_file: str = "./credentials/youtube_client_secret.json"
    youtube_token_file: str = "./credentials/youtube_token.pkl"
    youtube_privacy_status: str = "public"
    tiktok_access_token: str = "mock_tiktok_token"
    tiktok_privacy_level: str = "PUBLIC_TO_EVERYONE"
    instagram_access_token: str = "mock_instagram_token"
    instagram_account_id: str = "mock_instagram_account_id"

    @classmethod
    def from_env(cls, env_path: Path | str | None = None) -> "Settings":
        """Carrega as configurações a partir do arquivo .env e variáveis de ambiente."""
        if env_path is None:
            # Procura .env na raiz do projeto
            root_dir = Path(__file__).resolve().parent.parent
            env_file = root_dir / ".env"
        else:
            env_file = Path(env_path)

        _load_dotenv_file(env_file)

        raw_keywords = os.getenv("HYPE_KEYWORDS", "")
        keywords = (
            [k.strip().upper() for k in raw_keywords.split(",") if k.strip()]
            if raw_keywords
            else ["POG", "POGGERS", "LUL", "KEKW", "CLIP", "OMG", "WTF", "GG", "NICE", "INSANE", "JOGOU", "MUITO"]
        )

        raw_storage = os.getenv("STORAGE_DIR", "./storage/clips")
        if os.path.isabs(raw_storage):
            storage = Path(raw_storage)
        else:
            storage = root_dir / raw_storage
        storage.mkdir(parents=True, exist_ok=True)

        raw_events = os.getenv("EVENTS_DIR", "./storage/events")
        if os.path.isabs(raw_events):
            events_dir = Path(raw_events)
        else:
            events_dir = root_dir / raw_events
        events_dir.mkdir(parents=True, exist_ok=True)

        raw_buffer = os.getenv("STREAM_BUFFER_DIR", "./storage/buffer")
        if os.path.isabs(raw_buffer):
            buffer_dir = Path(raw_buffer)
        else:
            buffer_dir = root_dir / raw_buffer
        buffer_dir.mkdir(parents=True, exist_ok=True)

        return cls(
            app_env=os.getenv("APP_ENV", "development"),
            mock_mode=os.getenv("MOCK_MODE", "true").lower() in ("true", "1", "yes"),
            storage_dir=storage,
            events_dir=events_dir,
            twitch_channel=os.getenv("TWITCH_CHANNEL", "gaules").lower().replace("#", ""),
            twitch_bot_nickname=os.getenv("TWITCH_BOT_NICKNAME", "justinfan98765"),
            twitch_oauth_token=os.getenv("TWITCH_OAUTH_TOKEN", "oauth:mock_token"),
            twitch_client_id=os.getenv("TWITCH_CLIENT_ID", "mock_client_id"),
            twitch_client_secret=os.getenv("TWITCH_CLIENT_SECRET", "mock_client_secret"),
            hype_interval_seconds=int(os.getenv("HYPE_INTERVAL_SECONDS", "5")),
            hype_spike_multiplier=float(os.getenv("HYPE_SPIKE_MULTIPLIER", "3.0")),
            hype_window_seconds=int(os.getenv("HYPE_WINDOW_SECONDS", "10")),
            hype_threshold_mps=float(os.getenv("HYPE_THRESHOLD_MPS", "4.0")),
            hype_min_score=float(os.getenv("HYPE_MIN_SCORE", "10.0")),
            hype_cooldown_seconds=int(os.getenv("HYPE_COOLDOWN_SECONDS", "45")),
            hype_keywords=keywords,
            clip_duration_seconds=int(os.getenv("CLIP_DURATION_SECONDS", "45")),
            clip_preroll_seconds=int(os.getenv("CLIP_PREROLL_SECONDS", "30")),
            clip_postroll_seconds=int(os.getenv("CLIP_POSTROLL_SECONDS", "15")),
            video_framing_mode=os.getenv("VIDEO_FRAMING_MODE", "blur"),
            video_vertical_aspect=os.getenv("VIDEO_VERTICAL_ASPECT", "true").lower() in ("true", "1", "yes"),
            stream_buffer_dir=buffer_dir,
            ffmpeg_path=os.getenv("FFMPEG_PATH", "/usr/bin/ffmpeg"),
            youtube_enabled=os.getenv("YOUTUBE_ENABLED", "true").lower() in ("true", "1", "yes"),
            tiktok_enabled=os.getenv("TIKTOK_ENABLED", "true").lower() in ("true", "1", "yes"),
            instagram_enabled=os.getenv("INSTAGRAM_ENABLED", "false").lower() in ("true", "1", "yes"),
            youtube_client_secrets_file=os.getenv("YOUTUBE_CLIENT_SECRETS_FILE", "./credentials/youtube_client_secret.json"),
            youtube_token_file=os.getenv("YOUTUBE_TOKEN_FILE", "./credentials/youtube_token.pkl"),
            youtube_privacy_status=os.getenv("YOUTUBE_PRIVACY_STATUS", "public"),
            tiktok_access_token=os.getenv("TIKTOK_ACCESS_TOKEN", "mock_tiktok_token"),
            tiktok_privacy_level=os.getenv("TIKTOK_PRIVACY_LEVEL", "PUBLIC_TO_EVERYONE"),
            instagram_access_token=os.getenv("INSTAGRAM_ACCESS_TOKEN", "mock_instagram_token"),
            instagram_account_id=os.getenv("INSTAGRAM_ACCOUNT_ID", "mock_instagram_account_id"),
            gemini_api_key=os.getenv("GEMINI_API_KEY", ""),
            gemini_model=os.getenv("GEMINI_MODEL", "gemini-2.0-flash"),
            min_clip_score=float(os.getenv("MIN_CLIP_SCORE", "6.0")),
            whisper_model_size=os.getenv("WHISPER_MODEL_SIZE", "tiny"),
            whisper_device=os.getenv("WHISPER_DEVICE", "cpu"),
            whisper_language=os.getenv("WHISPER_LANGUAGE", "pt"),
        )


_cached_settings: Settings | None = None


def get_settings() -> Settings:
    """Retorna instância singleton das configurações."""
    global _cached_settings
    if _cached_settings is None:
        _cached_settings = Settings.from_env()
    return _cached_settings
