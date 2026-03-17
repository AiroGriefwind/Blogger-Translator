from __future__ import annotations

import json

from translator.translate_stage import TranslateStage


class _DummyClient:
    def __init__(self, responses: list[str]) -> None:
        self._responses = responses
        self.model = "dummy-model"
        self.calls = 0

    def chat(self, system_prompt: str, user_prompt: str, temperature: float = 0.2) -> str:
        _ = (system_prompt, user_prompt, temperature)
        self.calls += 1
        if not self._responses:
            raise RuntimeError("No more stub responses")
        return self._responses.pop(0)


def test_chunk_paragraphs_size_limit() -> None:
    paragraphs = [f"p{i}" for i in range(1, 13)]
    chunks = TranslateStage._chunk_paragraphs(paragraphs, 5)
    assert [len(chunk) for chunk in chunks] == [5, 5, 2]
    assert chunks[0][0] == "p1"
    assert chunks[-1][-1] == "p12"


def test_translate_stage_chunk_assemble_output_contract() -> None:
    chunk_1 = json.dumps(
        {
            "schema_version": "1.1",
            "thought": {"summary": "chunk1"},
            "translation": {
                "chunk_id": 1,
                "total_chunks": 2,
                "title_en": "English Title",
                "published_at": "2026-03-17",
                "author_en": "Author Name",
                "paragraphs_en": ["en1", "en2", "en3", "en4", "en5"],
            },
            "captions": {"translated_captions": ["cap1", "cap2"]},
        },
        ensure_ascii=False,
    )
    chunk_2 = json.dumps(
        {
            "schema_version": "1.1",
            "thought": {"summary": "chunk2"},
            "translation": {
                "chunk_id": 2,
                "total_chunks": 2,
                "title_en": "",
                "published_at": "",
                "author_en": "",
                "paragraphs_en": ["en6"],
            },
            "captions": {"translated_captions": []},
        },
        ensure_ascii=False,
    )
    stage = TranslateStage(client=_DummyClient([chunk_1, chunk_2]), chunk_max_paragraphs=5)
    article = {
        "url": "https://example.com/a",
        "title": "原文标题",
        "published_at": "2026-03-17",
        "author": "作者",
        "body_paragraphs": ["段1", "段2", "段3", "段4", "段5", "段6"],
        "captions": ["图1", "图2"],
    }

    result = stage.run(article)
    parsed = json.loads(result["translated_text"])

    assert result["source_url"] == "https://example.com/a"
    assert parsed["schema_version"] == "1.1"
    assert parsed["translation"]["title_en"] == "English Title"
    assert parsed["translation"]["author_en"] == "Author Name"
    assert parsed["translation"]["paragraphs_en"] == ["en1", "en2", "en3", "en4", "en5", "en6"]
    assert parsed["captions"]["translated_captions"] == ["cap1", "cap2"]
    assert result["chunk_metrics"]["total_chunks"] == 2
    assert result["chunk_metrics"]["total_retries"] == 0


def test_translate_stage_chunk_retry_when_truncated() -> None:
    chunk_1 = json.dumps(
        {
            "translation": {
                "paragraphs_en": ["en1", "en2", "en3", "en4", "en5"],
                "title_en": "T",
                "published_at": "P",
                "author_en": "A",
            },
            "captions": {"translated_captions": ["c1"]},
        },
        ensure_ascii=False,
    )
    chunk_2_truncated = json.dumps(
        {
            "translation": {
                "paragraphs_en": [],
                "title_en": "",
                "published_at": "",
                "author_en": "",
            },
            "captions": {"translated_captions": []},
        },
        ensure_ascii=False,
    )
    chunk_2_retry = json.dumps(
        {
            "translation": {
                "paragraphs_en": ["en6"],
                "title_en": "",
                "published_at": "",
                "author_en": "",
            },
            "captions": {"translated_captions": []},
        },
        ensure_ascii=False,
    )

    client = _DummyClient([chunk_1, chunk_2_truncated, chunk_2_retry])
    stage = TranslateStage(client=client, chunk_max_paragraphs=5, chunk_parse_retries=2)
    article = {
        "url": "https://example.com/a",
        "body_paragraphs": ["段1", "段2", "段3", "段4", "段5", "段6"],
        "captions": ["图1"],
    }

    progress_events: list[dict] = []
    result = stage.run(article, on_progress=lambda payload: progress_events.append(payload))
    parsed = json.loads(result["translated_text"])
    assert client.calls == 3
    assert parsed["translation"]["paragraphs_en"][-1] == "en6"
    assert result["chunk_metrics"]["total_retries"] == 1
    assert len(result["chunk_events"]) == 2
    assert any(str(evt.get("event")) == "chunk_retry" for evt in progress_events)
