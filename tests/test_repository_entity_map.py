from __future__ import annotations

from typing import Any

from storage.repositories import ENTITY_MAP_BLOB_PATH, RunRepository

class _FakeStorage:
    def __init__(self, payload: dict | None = None):
        self.payload = payload or {"schema_version": "1.0", "updated_at": "", "entities": {}}
        self.files: dict[str, Any] = {}
        self._db: dict[str, Any] = {}

    def download_json(self, blob_path: str) -> dict:
        if blob_path == "name_map/entity_map_v1.json":
            return self.payload
        value = self.files.get(blob_path)
        if isinstance(value, dict):
            return value
        value = self._db.get(blob_path)
        if isinstance(value, dict):
            return value
        return {}

    def upload_json(self, blob_path: str, payload: dict) -> str:
        if blob_path == "name_map/entity_map_v1.json":
            self.payload = payload
        self.files[blob_path] = payload
        self._db[blob_path] = payload
        return f"gs://fake/{blob_path}"


def test_find_entity_by_synonym_set_hits_when_zh_en_aliases_match() -> None:
    storage_payload = {
        "schema_version": "1.0",
        "updated_at": "2026-03-19T00:00:00+00:00",
        "entities": {
            "美利堅合眾國|america|location": {
                "entity_zh": "美利堅合眾國",
                "entity_en": "America",
                "type": "location",
                "is_verified": True,
                "verification_status": "verified",
                "sources": [{"url": "https://en.wikipedia.org/wiki/United_States"}],
                "final_recommendation": "ok",
                "zh_aliases": ["美國", "美国", "美利坚合众国"],
                "en_aliases": ["America", "United States", "US", "U.S.", "the US", "the U.S."],
                "updated_at": "2026-03-19T00:00:00+00:00",
                "last_run_id": "run_x",
            }
        },
    }
    repo = RunRepository(storage=_FakeStorage(storage_payload))
    result = repo.find_entity_by_synonym_set(
        {"entity_zh": "美国", "entity_en": "the U.S.", "type": "location"}
    )
    assert isinstance(result, dict)
    assert result["is_verified"] is True
    assert result["verification_status"] == "db_synonym_hit"
    assert result["entity_en"] == "America"


def test_find_entity_by_synonym_set_rejects_when_only_one_side_matches() -> None:
    storage_payload = {
        "schema_version": "1.0",
        "updated_at": "2026-03-19T00:00:00+00:00",
        "entities": {
            "美利堅合眾國|america|location": {
                "entity_zh": "美利堅合眾國",
                "entity_en": "America",
                "type": "location",
                "is_verified": True,
                "verification_status": "verified",
                "sources": [{"url": "https://en.wikipedia.org/wiki/United_States"}],
                "zh_aliases": ["美國", "美国"],
                "en_aliases": ["America", "United States", "US"],
            }
        },
    }
    repo = RunRepository(storage=_FakeStorage(storage_payload))
    result = repo.find_entity_by_synonym_set(
        {"entity_zh": "美国", "entity_en": "Canada", "type": "location"}
    )
    assert result is None


def test_list_verified_entities_filters_invalid_records() -> None:
    storage_payload = {
        "schema_version": "1.0",
        "updated_at": "2026-03-19T00:00:00+00:00",
        "entities": {
            "valid": {
                "entity_zh": "北京",
                "entity_en": "Beijing",
                "type": "location",
                "is_verified": True,
                "verification_status": "verified",
                "sources": [{"url": "https://en.wikipedia.org/wiki/Beijing"}],
                "updated_at": "2026-03-19T00:00:00+00:00",
                "last_run_id": "run_ok",
            },
            "invalid": {
                "entity_zh": "无效",
                "entity_en": "Invalid",
                "type": "other",
                "is_verified": True,
                "verification_status": "verified",
                "sources": [{"url": "not-a-url"}],
                "updated_at": "2026-03-18T00:00:00+00:00",
                "last_run_id": "run_bad",
            },
        },
    }
    repo = RunRepository(storage=_FakeStorage(storage_payload))
    rows = repo.list_verified_entities()
    assert len(rows) == 1
    assert rows[0]["entity_zh"] == "北京"


def test_apply_pending_changes_merges_records_and_marks_reviewed() -> None:
    storage_payload = {
        "schema_version": "1.0",
        "updated_at": "2026-03-19T00:00:00+00:00",
        "entities": {
            "a": {
                "entity_zh": "美国",
                "entity_en": "the US",
                "type": "location",
                "is_verified": True,
                "verification_status": "verified",
                "sources": [{"url": "https://a.example.com"}],
                "zh_aliases": ["美国"],
                "en_aliases": ["the US"],
                "synonym_reviewed_zh": False,
                "synonym_reviewed_en": False,
            },
            "b": {
                "entity_zh": "美利堅合眾國",
                "entity_en": "America",
                "type": "location",
                "is_verified": True,
                "verification_status": "verified",
                "sources": [{"url": "https://b.example.com"}],
                "zh_aliases": ["美利堅合眾國", "美國"],
                "en_aliases": ["America", "United States"],
                "synonym_reviewed_zh": True,
                "synonym_reviewed_en": True,
            },
        },
    }
    fake = _FakeStorage(storage_payload)
    fake.files["name_map/review/pending_changes.json"] = {
        "schema_version": "1.0",
        "updated_at": "",
        "items": [
            {
                "id": "1",
                "action": "merge_records",
                "status": "pending",
                "target_selector": {"key": "b"},
                "source_selector": {"key": "a"},
            }
        ],
    }
    repo = RunRepository(storage=fake)
    result = repo.apply_pending_changes(run_id="run_apply")
    assert result["applied"] == 1
    assert result["skipped"] == 0
    merged = repo.load_entity_map()["entities"]["b"]
    assert "美国" in merged["zh_aliases"]
    assert "the US" in merged["en_aliases"]
    assert "a" not in repo.load_entity_map()["entities"]


def test_apply_pending_changes_updates_and_deletes_records() -> None:
    storage_payload = {
        "schema_version": "1.0",
        "updated_at": "2026-03-19T00:00:00+00:00",
        "entities": {
            "x": {
                "entity_zh": "北京",
                "entity_en": "Beijing",
                "type": "location",
                "is_verified": True,
                "verification_status": "verified",
                "sources": [{"url": "https://en.wikipedia.org/wiki/Beijing"}],
                "zh_aliases": ["北京"],
                "en_aliases": ["Beijing"],
            },
            "y": {
                "entity_zh": "旧词",
                "entity_en": "Old Term",
                "type": "other",
                "is_verified": True,
                "verification_status": "verified",
                "sources": [{"url": "https://example.com/old"}],
                "zh_aliases": ["旧词"],
                "en_aliases": ["Old Term"],
            },
        },
    }
    fake = _FakeStorage(storage_payload)
    fake.files["name_map/review/pending_changes.json"] = {
        "schema_version": "1.0",
        "updated_at": "",
        "items": [
            {
                "id": "update-1",
                "action": "update_record",
                "status": "pending",
                "selector": {"key": "x"},
                "record": {
                    "entity_zh": "北京市",
                    "entity_en": "Beijing",
                    "type": "location",
                    "zh_aliases": ["北京", "北京市"],
                    "en_aliases": ["Beijing"],
                    "sources": [{"url": "https://en.wikipedia.org/wiki/Beijing"}],
                },
            },
            {
                "id": "delete-1",
                "action": "delete_record",
                "status": "pending",
                "selector": {"key": "y"},
            },
        ],
    }
    repo = RunRepository(storage=fake)
    result = repo.apply_pending_changes(run_id="run_apply_2")
    assert result["applied"] == 2
    entities = repo.load_entity_map()["entities"]
    assert "y" not in entities
    updated = entities.get("x")
    if not isinstance(updated, dict):
        updated = next(iter(entities.values()))
    assert updated["entity_zh"] == "北京市"
    assert "北京市" in updated["zh_aliases"]
def test_upsert_single_verified_entity_requires_valid_url() -> None:
    repo = RunRepository(storage=_FakeStorage())  # type: ignore[arg-type]
    stats = repo.upsert_single_verified_entity(
        run_id="run_001",
        entity={
            "entity_zh": "约翰威克",
            "entity_en": "John Wick",
            "type": "person",
            "is_verified": True,
            "sources": [{"url": "not-a-url", "site": "", "evidence_note": ""}],
            "final_recommendation": "Use John Wick",
        },
    )
    assert stats["upserted"] == 0


def test_upsert_single_verified_entity_persists_record() -> None:
    storage = _FakeStorage()
    repo = RunRepository(storage=storage)  # type: ignore[arg-type]
    stats = repo.upsert_single_verified_entity(
        run_id="run_002",
        entity={
            "entity_zh": "约翰威克",
            "entity_en": "John Wick",
            "type": "person",
            "is_verified": True,
            "sources": [
                {
                    "url": "https://en.wikipedia.org/wiki/John_Wick_(character)",
                    "site": "Wikipedia",
                    "evidence_note": "Character page",
                }
            ],
            "final_recommendation": "Use John Wick",
        },
    )
    assert stats["upserted"] == 1
    payload = storage.download_json(ENTITY_MAP_BLOB_PATH)
    assert isinstance(payload, dict)
    assert payload.get("entities")
