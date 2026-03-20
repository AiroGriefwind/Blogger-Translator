from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlparse
import re

from storage.firebase_storage_client import FirebaseStorageClient
from verifier.entity_key import build_entity_exact_key


def _utc_now() -> str:
    return datetime.now(tz=timezone.utc).isoformat()


ENTITY_MAP_BLOB_PATH = "name_map/entity_map_v1.json"
REVIEW_STATE_BLOB_PATH = "name_map/review/review_state.json"
REVIEW_RESULTS_BLOB_PATH = "name_map/review/review_results.json"
PENDING_CHANGES_BLOB_PATH = "name_map/review/pending_changes.json"
DATABASE_AUDIT_LOG_DIR = "name_map/review/audit_logs"


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
        return self._format_db_hit(record, valid_sources, status="db_exact_hit")

    def find_entity_by_synonym_set(self, entity: dict[str, Any]) -> dict[str, Any] | None:
        exact = self.find_entity_exact(entity)
        if exact:
            return exact

        query_type = self._normalize_alias_token(str(entity.get("type", "other")))
        query_zh = self._normalize_alias_token(str(entity.get("entity_zh", "")))
        query_en = self._normalize_alias_token(str(entity.get("entity_en", "")), is_english=True)
        if not query_type or (not query_zh and not query_en):
            return None

        data = self.load_entity_map()
        entities = data.get("entities", {})
        if not isinstance(entities, dict):
            return None

        for record in entities.values():
            if not isinstance(record, dict):
                continue
            normalized = self._normalize_entity_record(record)
            if self._normalize_alias_token(normalized["type"]) != query_type:
                continue
            if not normalized["is_verified"]:
                continue
            valid_sources = [item for item in normalized["sources"] if self._is_valid_source(item)]
            if not valid_sources:
                continue
            zh_aliases = self._alias_token_set(
                normalized["zh_aliases"], fallback=normalized["entity_zh"], is_english=False
            )
            en_aliases = self._alias_token_set(
                normalized["en_aliases"], fallback=normalized["entity_en"], is_english=True
            )
            if query_zh and query_zh not in zh_aliases:
                continue
            if query_en and query_en not in en_aliases:
                continue
            return self._format_db_hit(normalized, valid_sources, status="db_synonym_hit")
        return None

    def list_verified_entities(self) -> list[dict[str, Any]]:
        data = self.load_entity_map()
        entities = data.get("entities", {})
        if not isinstance(entities, dict):
            return []
        rows: list[dict[str, Any]] = []
        for key, record in entities.items():
            if not isinstance(record, dict):
                continue
            normalized = self._normalize_entity_record(record)
            if not normalized["is_verified"]:
                continue
            valid_sources = [item for item in normalized["sources"] if self._is_valid_source(item)]
            if not valid_sources:
                continue
            rows.append(
                {
                    "key": str(key),
                    "entity_zh": normalized["entity_zh"],
                    "entity_en": normalized["entity_en"],
                    "type": normalized["type"],
                    "verification_status": normalized["verification_status"],
                    "sources": valid_sources,
                    "final_recommendation": normalized["final_recommendation"],
                    "updated_at": normalized["updated_at"],
                    "last_run_id": normalized["last_run_id"],
                    "created_at": normalized["created_at"],
                    "zh_aliases": normalized["zh_aliases"],
                    "en_aliases": normalized["en_aliases"],
                    "synonym_reviewed_zh": normalized["synonym_reviewed_zh"],
                    "synonym_reviewed_en": normalized["synonym_reviewed_en"],
                }
            )
        rows.sort(key=lambda item: item.get("updated_at", ""), reverse=True)
        return rows

    def load_review_state(self) -> dict[str, Any]:
        data = self.storage.download_json(REVIEW_STATE_BLOB_PATH)
        if not isinstance(data, dict):
            return {
                "schema_version": "1.0",
                "updated_at": "",
                "language_mode": "zh",
                "category": "",
                "new_batch_size": 20,
                "reviewed_batch_size": 50,
                "active": {},
                "history": [],
            }
        data.setdefault("schema_version", "1.0")
        data.setdefault("updated_at", "")
        data.setdefault("language_mode", "zh")
        data.setdefault("category", "")
        data.setdefault("new_batch_size", 20)
        data.setdefault("reviewed_batch_size", 50)
        data.setdefault("active", {})
        data.setdefault("history", [])
        return data

    def save_review_state(self, payload: dict[str, Any]) -> str:
        payload["schema_version"] = "1.0"
        payload["updated_at"] = _utc_now()
        return self.storage.upload_json(REVIEW_STATE_BLOB_PATH, payload)

    def load_review_results(self) -> dict[str, Any]:
        data = self.storage.download_json(REVIEW_RESULTS_BLOB_PATH)
        if not isinstance(data, dict):
            return {"schema_version": "1.0", "updated_at": "", "results": []}
        data.setdefault("schema_version", "1.0")
        data.setdefault("updated_at", "")
        if not isinstance(data.get("results", []), list):
            data["results"] = []
        return data

    def save_review_results(self, payload: dict[str, Any]) -> str:
        payload["schema_version"] = "1.0"
        payload["updated_at"] = _utc_now()
        return self.storage.upload_json(REVIEW_RESULTS_BLOB_PATH, payload)

    def load_pending_changes(self) -> dict[str, Any]:
        data = self.storage.download_json(PENDING_CHANGES_BLOB_PATH)
        if not isinstance(data, dict):
            return {"schema_version": "1.0", "updated_at": "", "items": []}
        data.setdefault("schema_version", "1.0")
        data.setdefault("updated_at", "")
        if not isinstance(data.get("items", []), list):
            data["items"] = []
        return data

    def save_pending_changes(self, payload: dict[str, Any]) -> str:
        payload["schema_version"] = "1.0"
        payload["updated_at"] = _utc_now()
        return self.storage.upload_json(PENDING_CHANGES_BLOB_PATH, payload)

    def list_all_entities(self) -> list[dict[str, Any]]:
        data = self.load_entity_map()
        entities = data.get("entities", {})
        if not isinstance(entities, dict):
            return []
        rows: list[dict[str, Any]] = []
        for key, raw_record in entities.items():
            if not isinstance(raw_record, dict):
                continue
            record = self._normalize_entity_record(raw_record)
            rows.append(
                {
                    "key": str(key),
                    **record,
                }
            )
        rows.sort(key=lambda item: item.get("updated_at", ""), reverse=True)
        return rows

    def apply_pending_changes(self, run_id: str) -> dict[str, Any]:
        pending = self.load_pending_changes()
        items = pending.get("items", [])
        if not isinstance(items, list):
            items = []
        data = self.load_entity_map()
        entities = data.setdefault("entities", {})
        if not isinstance(entities, dict):
            entities = {}
            data["entities"] = entities

        applied = 0
        skipped = 0
        for item in items:
            if not isinstance(item, dict):
                skipped += 1
                continue
            if str(item.get("status", "pending")).strip() != "pending":
                continue
            action = str(item.get("action", "")).strip()
            if action == "upsert_record":
                record = item.get("record", {})
                if not isinstance(record, dict):
                    skipped += 1
                    continue
                normalized = self._normalize_entity_record(record)
                key = build_entity_exact_key(
                    normalized["entity_zh"],
                    normalized["entity_en"],
                    normalized["type"],
                )
                normalized["last_run_id"] = run_id
                normalized["updated_at"] = _utc_now()
                entities[key] = normalized
                item["status"] = "applied"
                applied += 1
                continue
            if action == "mark_reviewed":
                selector = item.get("selector", {})
                if not isinstance(selector, dict):
                    skipped += 1
                    continue
                record = self._find_record_by_selector(entities, selector)
                if not record:
                    skipped += 1
                    continue
                language_mode = str(item.get("language_mode", "zh")).strip().lower()
                field = "synonym_reviewed_zh" if language_mode == "zh" else "synonym_reviewed_en"
                record[field] = True
                record["updated_at"] = _utc_now()
                record["last_run_id"] = run_id
                item["status"] = "applied"
                applied += 1
                continue
            if action == "merge_records":
                target_selector = item.get("target_selector", {})
                source_selector = item.get("source_selector", {})
                if not isinstance(target_selector, dict) or not isinstance(source_selector, dict):
                    skipped += 1
                    continue
                target_key = self._find_record_key_by_selector(entities, target_selector)
                source_key = self._find_record_key_by_selector(entities, source_selector)
                if not target_key or not source_key:
                    skipped += 1
                    continue
                target = entities.get(target_key)
                source = entities.get(source_key)
                if not isinstance(target, dict) or not isinstance(source, dict):
                    skipped += 1
                    continue
                self._merge_record_fields(target, source)
                target["updated_at"] = _utc_now()
                target["last_run_id"] = run_id
                if source_key != target_key:
                    entities.pop(source_key, None)
                item["status"] = "applied"
                applied += 1
                continue
            if action == "update_record":
                selector = item.get("selector", {})
                record_payload = item.get("record", {})
                if not isinstance(selector, dict) or not isinstance(record_payload, dict):
                    skipped += 1
                    continue
                old_key = self._find_record_key_by_selector(entities, selector)
                if not old_key:
                    skipped += 1
                    continue
                existing = entities.get(old_key)
                if not isinstance(existing, dict):
                    skipped += 1
                    continue
                normalized = self._normalize_entity_record({**existing, **record_payload})
                normalized["updated_at"] = _utc_now()
                normalized["last_run_id"] = run_id
                new_key = build_entity_exact_key(
                    normalized["entity_zh"],
                    normalized["entity_en"],
                    normalized["type"],
                )
                if new_key != old_key:
                    entities.pop(old_key, None)
                entities[new_key] = normalized
                item["status"] = "applied"
                applied += 1
                continue
            if action == "delete_record":
                selector = item.get("selector", {})
                if not isinstance(selector, dict):
                    skipped += 1
                    continue
                target_key = self._find_record_key_by_selector(entities, selector)
                if not target_key:
                    skipped += 1
                    continue
                entities.pop(target_key, None)
                item["status"] = "applied"
                applied += 1
                continue
            skipped += 1

        data["schema_version"] = "1.0"
        data["updated_at"] = _utc_now()
        self.storage.upload_json(ENTITY_MAP_BLOB_PATH, data)
        self.save_pending_changes(pending)
        audit_path = self._write_database_audit_log(run_id=run_id, pending=pending, applied=applied, skipped=skipped)
        return {"applied": applied, "skipped": skipped, "audit_log_path": audit_path}

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
                    previous = entities.get(key, {})
                    if not isinstance(previous, dict):
                        previous = {}
                    merged = self._normalize_entity_record(
                        {
                            **previous,
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
                    )
                    entities[key] = merged
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

    @staticmethod
    def _format_db_hit(
        record: dict[str, Any], valid_sources: list[dict[str, Any]], status: str
    ) -> dict[str, Any]:
        normalized = RunRepository._normalize_entity_record(record)
        return {
            "entity_zh": normalized["entity_zh"],
            "entity_en": normalized["entity_en"],
            "type": normalized["type"],
            "is_verified": True,
            "verification_status": status,
            "sources": valid_sources,
            "final_recommendation": normalized["final_recommendation"],
            "uncertainty_reason": "",
            "next_search_queries": [],
        }

    @staticmethod
    def _normalize_loose(value: str) -> str:
        text = str(value).strip().lower()
        if not text:
            return ""
        return re.sub(r"[\s\-_/\\|,;:(){}\[\]<>\"'`。，“”‘’！？、]+", "", text)

    @staticmethod
    def _normalize_alias_token(value: str, is_english: bool = False) -> str:
        raw = RunRepository._normalize_loose(value)
        if not raw:
            return ""
        if is_english and raw.startswith("the"):
            trimmed = raw[3:]
            if trimmed:
                return trimmed
        return raw

    @classmethod
    def _expand_aliases(cls, value: str, is_english: bool = False) -> set[str]:
        raw = str(value).strip()
        if not raw:
            return set()
        parts = re.split(r"[\/|,;；，\n]+", raw)
        aliases: set[str] = set()
        for part in parts:
            normalized = cls._normalize_alias_token(part, is_english=is_english)
            if normalized:
                aliases.add(normalized)
        merged = cls._normalize_alias_token(raw, is_english=is_english)
        if merged:
            aliases.add(merged)
        return aliases

    @classmethod
    def _alias_token_set(cls, values: list[str], fallback: str, is_english: bool) -> set[str]:
        tokens: set[str] = set()
        for value in values:
            if not isinstance(value, str):
                continue
            token = cls._normalize_alias_token(value, is_english=is_english)
            if token:
                tokens.add(token)
        if not tokens:
            tokens = cls._expand_aliases(fallback, is_english=is_english)
        return tokens

    @classmethod
    def _normalize_entity_record(cls, record: dict[str, Any]) -> dict[str, Any]:
        entity_zh = str(record.get("entity_zh", "")).strip()
        entity_en = str(record.get("entity_en", "")).strip()
        entity_type = str(record.get("type", "other")).strip() or "other"
        zh_aliases_raw = record.get("zh_aliases", [])
        en_aliases_raw = record.get("en_aliases", [])
        if not isinstance(zh_aliases_raw, list):
            zh_aliases_raw = []
        if not isinstance(en_aliases_raw, list):
            en_aliases_raw = []
        zh_aliases = sorted(
            {
                item.strip()
                for item in [entity_zh, *[str(v) for v in zh_aliases_raw]]
                if str(item).strip()
            }
        )
        en_aliases = sorted(
            {
                item.strip()
                for item in [entity_en, *[str(v) for v in en_aliases_raw]]
                if str(item).strip()
            }
        )
        sources = record.get("sources", [])
        if not isinstance(sources, list):
            sources = []
        normalized_sources = [item for item in sources if cls._is_valid_source(item)]
        return {
            "entity_zh": entity_zh,
            "entity_en": entity_en,
            "type": entity_type,
            "is_verified": bool(record.get("is_verified", False)),
            "verification_status": str(record.get("verification_status", "verified")).strip() or "verified",
            "sources": normalized_sources,
            "final_recommendation": str(record.get("final_recommendation", "")).strip(),
            "updated_at": str(record.get("updated_at", "")).strip(),
            "created_at": str(record.get("created_at", "")).strip() or str(record.get("updated_at", "")).strip(),
            "last_run_id": str(record.get("last_run_id", "")).strip(),
            "zh_aliases": zh_aliases,
            "en_aliases": en_aliases,
            "synonym_reviewed_zh": bool(record.get("synonym_reviewed_zh", False)),
            "synonym_reviewed_en": bool(record.get("synonym_reviewed_en", False)),
        }

    @classmethod
    def _find_record_by_selector(
        cls, entities: dict[str, Any], selector: dict[str, Any]
    ) -> dict[str, Any] | None:
        key = cls._find_record_key_by_selector(entities, selector)
        if not key:
            return None
        target = entities.get(key)
        if isinstance(target, dict):
            return target
        return None

    @classmethod
    def _find_record_key_by_selector(
        cls, entities: dict[str, Any], selector: dict[str, Any]
    ) -> str | None:
        key = str(selector.get("key", "")).strip()
        if key and isinstance(entities.get(key), dict):
            return key
        selector_zh = cls._normalize_alias_token(str(selector.get("entity_zh", "")))
        selector_en = cls._normalize_alias_token(str(selector.get("entity_en", "")), is_english=True)
        selector_type = cls._normalize_alias_token(str(selector.get("type", "other")))
        for entity_key, record in entities.items():
            if not isinstance(record, dict):
                continue
            normalized = cls._normalize_entity_record(record)
            if selector_type and cls._normalize_alias_token(normalized["type"]) != selector_type:
                continue
            zh_tokens = cls._alias_token_set(normalized["zh_aliases"], normalized["entity_zh"], is_english=False)
            en_tokens = cls._alias_token_set(normalized["en_aliases"], normalized["entity_en"], is_english=True)
            if selector_zh and selector_zh not in zh_tokens:
                continue
            if selector_en and selector_en not in en_tokens:
                continue
            return str(entity_key)
        return None

    @classmethod
    def _merge_record_fields(cls, target: dict[str, Any], source: dict[str, Any]) -> None:
        target_normalized = cls._normalize_entity_record(target)
        source_normalized = cls._normalize_entity_record(source)
        target["zh_aliases"] = sorted(
            {
                *target_normalized["zh_aliases"],
                *source_normalized["zh_aliases"],
            }
        )
        target["en_aliases"] = sorted(
            {
                *target_normalized["en_aliases"],
                *source_normalized["en_aliases"],
            }
        )
        existing_urls = {
            str(item.get("url", "")).strip()
            for item in target_normalized["sources"]
            if isinstance(item, dict)
        }
        merged_sources = list(target_normalized["sources"])
        for source_item in source_normalized["sources"]:
            if not isinstance(source_item, dict):
                continue
            source_url = str(source_item.get("url", "")).strip()
            if source_url and source_url not in existing_urls:
                merged_sources.append(source_item)
                existing_urls.add(source_url)
        target["sources"] = merged_sources
        target["synonym_reviewed_zh"] = bool(
            target_normalized["synonym_reviewed_zh"] or source_normalized["synonym_reviewed_zh"]
        )
        target["synonym_reviewed_en"] = bool(
            target_normalized["synonym_reviewed_en"] or source_normalized["synonym_reviewed_en"]
        )
        if not str(target.get("final_recommendation", "")).strip() and source_normalized[
            "final_recommendation"
        ]:
            target["final_recommendation"] = source_normalized["final_recommendation"]

    def _write_database_audit_log(
        self,
        run_id: str,
        pending: dict[str, Any],
        applied: int,
        skipped: int,
    ) -> str:
        date_key = datetime.now(tz=timezone.utc).strftime("%Y%m%d")
        stamp = datetime.now(tz=timezone.utc).strftime("%H%M%S")
        payload = {
            "schema_version": "1.0",
            "run_id": run_id,
            "saved_at": _utc_now(),
            "applied": applied,
            "skipped": skipped,
            "pending_snapshot": pending,
        }
        blob_path = f"{DATABASE_AUDIT_LOG_DIR}/{date_key}_database_prune_{stamp}.json"
        self.storage.upload_json(blob_path, payload)
        bucket_name = getattr(getattr(self.storage, "bucket", None), "name", "")
        if bucket_name:
            return f"gs://{bucket_name}/{blob_path}"
        return blob_path

