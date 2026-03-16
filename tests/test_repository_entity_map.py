from __future__ import annotations

from typing import Any

from storage.repositories import ENTITY_MAP_BLOB_PATH, RunRepository


class _FakeStorage:
    def __init__(self) -> None:
        self._db: dict[str, Any] = {}

    def upload_json(self, blob_path: str, payload: dict[str, Any]) -> str:
        self._db[blob_path] = payload
        return f"gs://fake/{blob_path}"

    def download_json(self, blob_path: str) -> dict[str, Any] | None:
        value = self._db.get(blob_path)
        if isinstance(value, dict):
            return value
        return None


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

