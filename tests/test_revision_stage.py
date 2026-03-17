from __future__ import annotations

import json

from revisor.revision_stage import RevisionStage


class _DummyClient:
    def __init__(self, responses: list[str]) -> None:
        self._responses = responses
        self.model = "dummy-model"

    def chat(self, system_prompt: str, user_prompt: str, temperature: float = 0.2) -> str:
        _ = (system_prompt, user_prompt, temperature)
        if not self._responses:
            raise RuntimeError("No more stub responses")
        return self._responses.pop(0)


def test_revision_stage_with_verifier_output() -> None:
    outline = {
        "schema_version": "1.0",
        "total_paragraphs": 6,
        "title_revised_en": "Sharper Energy Outlook",
        "entity_mapping_used": True,
        "parts": [
            {"part_id": 1, "subtitle_en": "Policy Shock Builds", "summary": "前半段。", "paragraph_ids": [1, 2, 3, 4, 5]},
            {"part_id": 2, "subtitle_en": "Risk Gets Repriced", "summary": "后半段。", "paragraph_ids": [6]},
        ],
    }
    chunk_1 = {
        "schema_version": "1.0",
        "part_id": 1,
        "paragraphs_revised_en": ["p1", "p2", "p3", "p4", "p5"],
        "captions_revised_en": ["caption-1", "caption-2"],
    }
    chunk_2 = {
        "schema_version": "1.0",
        "part_id": 2,
        "paragraphs_revised_en": ["p6"],
        "captions_revised_en": [],
    }
    stage = RevisionStage(client=_DummyClient([json.dumps(outline), json.dumps(chunk_1), json.dumps(chunk_2)]))

    source_article = {
        "title": "Source title",
        "body_paragraphs": ["中1", "中2", "中3", "中4", "中5", "中6"],
        "captions": ["图1", "图2"],
    }
    translation = {
        "translated_text": json.dumps(
            {
                "translation": {
                    "title_en": "Translated title",
                    "paragraphs_en": ["e1", "e2", "e3", "e4", "e5", "e6"],
                    "full_text_en": "unused",
                },
                "captions": {"translated_captions": ["c1", "c2"]},
            },
            ensure_ascii=False,
        )
    }
    verifier_output = {
        "summary": {"verified_entities": 2, "unresolved_entities": 1},
        "paragraph_results": [
            {"verified_entities": [{"entity_zh": "甲", "entity_en": "A", "is_verified": True}]},
            {"verified_entities": [{"entity_zh": "乙", "entity_en": "B", "is_verified": False}]},
        ],
    }

    revised = stage.run(source_article, translation, verifier_output)
    assert revised["schema_version"] == "2.0"
    assert revised["revision_meta"]["used_verifier"] is True
    assert revised["revision_meta"]["resolved_entities"] == 2
    assert revised["revision_meta"]["unresolved_entities"] == 1
    assert len(revised["revision"]["paragraphs_revised_en"]) == 6
    assert len(revised["revision"]["subtitles_en"]) == 2
    assert revised["revision"]["captions_revised_en"] == ["caption-1", "caption-2"]


def test_revision_stage_degraded_without_verifier() -> None:
    outline = {
        "schema_version": "1.0",
        "total_paragraphs": 2,
        "title_revised_en": "Degraded title",
        "entity_mapping_used": False,
        "parts": [
            {"part_id": 1, "subtitle_en": "One Block Only", "summary": "摘要。", "paragraph_ids": [1, 2]},
        ],
    }
    chunk = {
        "schema_version": "1.0",
        "part_id": 1,
        "paragraphs_revised_en": ["rev-1", "rev-2"],
        "captions_revised_en": [],
    }
    stage = RevisionStage(client=_DummyClient([json.dumps(outline), json.dumps(chunk)]))

    source_article = {"title": "Source", "body_paragraphs": ["中1", "中2"], "captions": ["图1"]}
    translation = {
        "translated_text": json.dumps(
            {
                "translation": {
                    "title_en": "Translated",
                    "paragraphs_en": ["en1", "en2"],
                    "full_text_en": "unused",
                },
                "captions": {"translated_captions": []},
            },
            ensure_ascii=False,
        )
    }

    revised = stage.run(source_article, translation, verifier_output=None)
    assert revised["revision_meta"]["used_verifier"] is False
    assert revised["revision_meta"]["degraded_reason"] == "verifier_output_missing_or_invalid"
    assert revised["revised_text"]
    assert revised["title_limit"] == 12
    assert revised["caption_limit"] == 25
