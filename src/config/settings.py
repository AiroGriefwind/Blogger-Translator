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
    firebase_storage_bucket: str
    google_application_credentials: str

    @classmethod
    def load(cls) -> "Settings":
        payload = cls(
            app_env=os.getenv("APP_ENV", "dev"),
            siliconflow_api_key=os.getenv("SILICONFLOW_API_KEY", ""),
            siliconflow_base_url=os.getenv(
                "SILICONFLOW_BASE_URL", "https://api.siliconflow.cn/v1"
            ),
            siliconflow_model=os.getenv("SILICONFLOW_MODEL", "deepseek-r1"),
            firebase_storage_bucket=os.getenv("FIREBASE_STORAGE_BUCKET", ""),
            google_application_credentials=os.getenv(
                "GOOGLE_APPLICATION_CREDENTIALS", ""
            ),
        )
        payload.validate()
        return payload

    def validate(self) -> None:
        missing = []
        if not self.siliconflow_api_key:
            missing.append("SILICONFLOW_API_KEY")
        if not self.firebase_storage_bucket:
            missing.append("FIREBASE_STORAGE_BUCKET")
        if not self.google_application_credentials:
            missing.append("GOOGLE_APPLICATION_CREDENTIALS")
        if missing:
            names = ", ".join(missing)
            raise SettingsError(f"缺少必要环境变量: {names}")

