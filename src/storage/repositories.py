from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from storage.firebase_storage_client import FirebaseStorageClient


def _utc_now() -> str:
    return datetime.now(tz=timezone.utc).isoformat()


@dataclass
class RunRepository:
    storage: FirebaseStorageClient

    def save_raw_article(self, run_id: str, article: dict) -> str:
        article["saved_at"] = _utc_now()
        return self.storage.upload_json(f"runs/{run_id}/raw/article.json", article)

    def save_translation(self, run_id: str, translated: dict) -> str:
        translated["saved_at"] = _utc_now()
        return self.storage.upload_json(f"runs/{run_id}/translated/translated.json", translated)

    def save_revision(self, run_id: str, revised: dict) -> str:
        revised["saved_at"] = _utc_now()
        return self.storage.upload_json(f"runs/{run_id}/revised/revised.json", revised)

    def save_name_map(self, month_key: str, payload: dict) -> str:
        payload["saved_at"] = _utc_now()
        return self.storage.upload_json(f"name_map/{month_key}/name_map.json", payload)

    def save_log(self, run_id: str, name: str, payload: dict) -> str:
        return self.storage.upload_json(f"runs/{run_id}/logs/{name}.json", payload)

    def save_output_docx(self, run_id: str, local_docx_path: str) -> str:
        return self.storage.upload_file(f"runs/{run_id}/output/final.docx", local_docx_path)

