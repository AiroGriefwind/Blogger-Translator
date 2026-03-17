from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path

from dotenv import load_dotenv


BASE_DIR = Path(__file__).resolve().parents[2]
load_dotenv(BASE_DIR / ".env")


class SettingsError(RuntimeError):
    pass


@dataclass(frozen=True)
class Settings:
    app_env: str
    siliconflow_api_key: str
    siliconflow_base_url: str
    siliconflow_model: str
    siliconflow_temperature: float
    siliconflow_timeout_seconds: int
    siliconflow_max_retries: int
    translator_chunk_enabled: bool
    translator_chunk_max_paragraphs: int
    firebase_storage_bucket: str
    google_application_credentials: str

    @classmethod
    def load(cls, require_storage: bool = True) -> "Settings":
        siliconflow_base_url = (
            os.getenv("SILICONFLOW_BASE_URL", "")
            or os.getenv("LLM_BASE_URL", "")
            or os.getenv("MAYNOR_BASE_URL", "")
            or "https://api.siliconflow.cn/v1"
        )
        if "maynor1024.live" in siliconflow_base_url:
            siliconflow_api_key = os.getenv("MAYNOR_API_KEY", "") or os.getenv(
                "SILICONFLOW_API_KEY", ""
            ) or os.getenv("LLM_API_KEY", "")
        else:
            siliconflow_api_key = os.getenv("SILICONFLOW_API_KEY", "") or os.getenv(
                "LLM_API_KEY", ""
            ) or os.getenv("MAYNOR_API_KEY", "")
        siliconflow_model = os.getenv("SILICONFLOW_MODEL", "") or os.getenv(
            "LLM_MODEL", ""
        ) or os.getenv("MAYNOR_MODEL", "deepseek-r1")
        siliconflow_temperature = cls._read_float(
            "SILICONFLOW_TEMPERATURE",
            fallback_key="LLM_TEMPERATURE",
            default=0.2,
        )
        siliconflow_timeout_seconds = cls._read_int(
            "SILICONFLOW_TIMEOUT_SECONDS",
            fallback_key="LLM_TIMEOUT_SECONDS",
            default=120,
            min_value=1,
        )
        siliconflow_max_retries = cls._read_int(
            "SILICONFLOW_MAX_RETRIES",
            fallback_key="LLM_MAX_RETRIES",
            default=2,
            min_value=0,
        )
        translator_chunk_enabled = cls._read_bool(
            "TRANSLATOR_CHUNK_ENABLED",
            default=True,
        )
        translator_chunk_max_paragraphs = cls._read_int(
            "TRANSLATOR_CHUNK_MAX_PARAGRAPHS",
            fallback_key="",
            default=5,
            min_value=1,
        )
        payload = cls(
            app_env=os.getenv("APP_ENV", "dev"),
            siliconflow_api_key=siliconflow_api_key,
            siliconflow_base_url=siliconflow_base_url,
            siliconflow_model=siliconflow_model,
            siliconflow_temperature=siliconflow_temperature,
            siliconflow_timeout_seconds=siliconflow_timeout_seconds,
            siliconflow_max_retries=siliconflow_max_retries,
            translator_chunk_enabled=translator_chunk_enabled,
            translator_chunk_max_paragraphs=translator_chunk_max_paragraphs,
            firebase_storage_bucket=os.getenv("FIREBASE_STORAGE_BUCKET", ""),
            google_application_credentials=os.getenv(
                "GOOGLE_APPLICATION_CREDENTIALS", ""
            ),
        )
        payload.validate(require_storage=require_storage)
        return payload

    def validate(self, require_storage: bool = True) -> None:
        missing = []
        if not self.siliconflow_api_key:
            missing.append("SILICONFLOW_API_KEY (or LLM_API_KEY / MAYNOR_API_KEY)")
        if require_storage:
            if not self.firebase_storage_bucket:
                missing.append("FIREBASE_STORAGE_BUCKET")
            if not self.google_application_credentials:
                missing.append("GOOGLE_APPLICATION_CREDENTIALS")
        if missing:
            names = ", ".join(missing)
            raise SettingsError(f"缺少必要环境变量: {names}")

    @staticmethod
    def _read_int(
        primary_key: str,
        fallback_key: str,
        default: int,
        min_value: int | None = None,
    ) -> int:
        raw = os.getenv(primary_key, "")
        if not raw and fallback_key:
            raw = os.getenv(fallback_key, "")
        if not raw:
            return default
        try:
            value = int(raw)
        except ValueError as exc:
            raise SettingsError(f"{primary_key}/{fallback_key} 必须是整数") from exc
        if min_value is not None and value < min_value:
            raise SettingsError(
                f"{primary_key}/{fallback_key} 必须大于等于 {min_value}"
            )
        return value

    @staticmethod
    def _read_float(primary_key: str, fallback_key: str, default: float) -> float:
        raw = os.getenv(primary_key, "") or os.getenv(fallback_key, "")
        if not raw:
            return default
        try:
            return float(raw)
        except ValueError as exc:
            raise SettingsError(f"{primary_key}/{fallback_key} 必须是数字") from exc

    @staticmethod
    def _read_bool(primary_key: str, default: bool) -> bool:
        raw = os.getenv(primary_key, "").strip().lower()
        if not raw:
            return default
        if raw in {"1", "true", "yes", "on"}:
            return True
        if raw in {"0", "false", "no", "off"}:
            return False
        raise SettingsError(f"{primary_key} 必须是布尔值(true/false)")

