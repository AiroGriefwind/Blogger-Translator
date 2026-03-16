from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlparse

from storage.firebase_storage_client import FirebaseStorageClient
from verifier.entity_key import build_entity_exact_key


def _utc_now() -> str:
    return datetime.now(tz=timezone.utc).isoformat()


ENTITY_MAP_BLOB_PATH = "name_map/entity_map_v1.json"


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

    def load_entity_map(self) -> dict[str, Any]:
        data = self.storage.download_json(ENTITY_MAP_BLOB_PATH)
        if not isinstance(data, dict):
            return self._empty_entity_map()
        entities = data.get("entities", {})
        if not isinstance(entities, dict):
            data["entities"] = {}
        if not data.get("schema_version"):
            data["schema_version"] = "1.0"
        return data

    def find_entity_exact(self, entity: dict[str, Any]) -> dict[str, Any] | None:
        key = build_entity_exact_key(
            str(entity.get("entity_zh", "")),
            str(entity.get("entity_en", "")),
            str(entity.get("type", "other")),
        )
        data = self.load_entity_map()
        entities = data.get("entities", {})
        if not isinstance(entities, dict):
            return None
        record = entities.get(key)
        if not isinstance(record, dict):
            return None
        if not bool(record.get("is_verified", False)):
            return None
        sources = record.get("sources", [])
        if not isinstance(sources, list):
            return None
        valid_sources = [item for item in sources if self._is_valid_source(item)]
        if not valid_sources:
            return None
        return {
            "entity_zh": str(record.get("entity_zh", "")).strip(),
            "entity_en": str(record.get("entity_en", "")).strip(),
            "type": str(record.get("type", "other")).strip() or "other",
            "is_verified": True,
            "verification_status": "db_exact_hit",
            "sources": valid_sources,
            "final_recommendation": str(record.get("final_recommendation", "")).strip(),
            "uncertainty_reason": "",
            "next_search_queries": [],
        }

    def upsert_verified_entities(self, run_id: str, verifier_output: dict[str, Any]) -> dict[str, int]:
        data = self.load_entity_map()
        entities = data.setdefault("entities", {})
        if not isinstance(entities, dict):
            entities = {}
            data["entities"] = entities

        scanned = 0
        upserted = 0
        paragraph_results = verifier_output.get("paragraph_results", [])
        if isinstance(paragraph_results, list):
            for paragraph in paragraph_results:
                if not isinstance(paragraph, dict):
                    continue
                verified_entities = paragraph.get("verified_entities", [])
                if not isinstance(verified_entities, list):
                    continue
                for entity in verified_entities:
                    if not isinstance(entity, dict):
                        continue
                    scanned += 1
                    if not bool(entity.get("is_verified", False)):
                        continue
                    sources = entity.get("sources", [])
                    if not isinstance(sources, list):
                        continue
                    valid_sources = [item for item in sources if self._is_valid_source(item)]
                    if not valid_sources:
                        continue
                    key = build_entity_exact_key(
                        str(entity.get("entity_zh", "")),
                        str(entity.get("entity_en", "")),
                        str(entity.get("type", "other")),
                    )
                    entities[key] = {
                        "entity_zh": str(entity.get("entity_zh", "")).strip(),
                        "entity_en": str(entity.get("entity_en", "")).strip(),
                        "type": str(entity.get("type", "other")).strip() or "other",
                        "is_verified": True,
                        "verification_status": "verified",
                        "sources": valid_sources,
                        "final_recommendation": str(entity.get("final_recommendation", "")).strip(),
                        "updated_at": _utc_now(),
                        "last_run_id": run_id,
                    }
                    upserted += 1

        data["schema_version"] = "1.0"
        data["updated_at"] = _utc_now()
        self.storage.upload_json(ENTITY_MAP_BLOB_PATH, data)
        return {"scanned": scanned, "upserted": upserted, "entries": len(entities)}

    def save_log(self, run_id: str, name: str, payload: dict) -> str:
        return self.storage.upload_json(f"runs/{run_id}/logs/{name}.json", payload)

    def save_run_log(self, date_key: str, run_id: str, payload: dict[str, Any]) -> str:
        payload["saved_at"] = _utc_now()
        return self.storage.upload_json(f"logs/{date_key}/{run_id}.json", payload)

    def save_output_docx(self, run_id: str, local_docx_path: str) -> str:
        return self.storage.upload_file(f"runs/{run_id}/output/final.docx", local_docx_path)

    @staticmethod
    def _empty_entity_map() -> dict[str, Any]:
        return {
            "schema_version": "1.0",
            "updated_at": "",
            "entities": {},
        }

    @staticmethod
    def _is_valid_source(source: Any) -> bool:
        if not isinstance(source, dict):
            return False
        url = str(source.get("url", "")).strip()
        site = str(source.get("site", "")).strip()
        note = str(source.get("evidence_note", "")).strip()
        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            return False
        source["url"] = url
        source["site"] = site
        source["evidence_note"] = note
        return True

