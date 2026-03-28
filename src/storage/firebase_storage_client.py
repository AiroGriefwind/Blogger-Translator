from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from google.cloud import storage


class FirebaseStorageClient:
    def __init__(self, bucket_name: str):
        self.client = storage.Client()
        self.bucket = self.client.bucket(bucket_name)

    def upload_json(self, blob_path: str, payload: dict[str, Any]) -> str:
        blob = self.bucket.blob(blob_path)
        blob.upload_from_string(
            json.dumps(payload, ensure_ascii=False, indent=2),
            content_type="application/json",
        )
        return f"gs://{self.bucket.name}/{blob_path}"

    def download_json(self, blob_path: str) -> dict[str, Any] | None:
        blob = self.bucket.blob(blob_path)
        if not blob.exists():
            return None
        data = blob.download_as_text(encoding="utf-8")
        loaded = json.loads(data)
        if not isinstance(loaded, dict):
            raise ValueError(f"JSON blob 不是对象: {blob_path}")
        return loaded

    def upload_text(self, blob_path: str, text: str) -> str:
        blob = self.bucket.blob(blob_path)
        blob.upload_from_string(text, content_type="text/plain; charset=utf-8")
        return f"gs://{self.bucket.name}/{blob_path}"

    def upload_file(self, blob_path: str, local_file: str | Path) -> str:
        blob = self.bucket.blob(blob_path)
        blob.upload_from_filename(str(local_file))
        return f"gs://{self.bucket.name}/{blob_path}"

    def list_blobs(self, prefix: str) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for blob in self.client.list_blobs(self.bucket, prefix=prefix):
            rows.append(
                {
                    "path": str(blob.name),
                    "updated_at": blob.updated.isoformat() if blob.updated else "",
                    "size": int(blob.size or 0),
                }
            )
        return rows

