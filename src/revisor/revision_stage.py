from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any

from translator.siliconflow_client import SiliconFlowClient


OUTLINE_PROMPT_FILE = (
    Path(__file__).resolve().parents[1] / "config" / "prompts" / "Revision_Outline_Prompt.md"
)
CHUNK_PROMPT_FILE = (
    Path(__file__).resolve().parents[1] / "config" / "prompts" / "Revision_Chunk_Prompt.md"
)


@dataclass
class RevisionStage:
    client: SiliconFlowClient
    max_title_words: int = 12
    max_caption_words: int = 25
    temperature: float = 0.2

    def run(
        self,
        source_article: dict,
        translation: dict,
        verifier_output: dict[str, Any] | None = None,
    ) -> dict:
        translated_payload = self._parse_translated_payload(translation)
        zh_paragraphs = self._as_string_list(source_article.get("body_paragraphs", []))
        en_paragraphs = translated_payload.get("paragraphs_en", [])
        if not en_paragraphs:
            en_paragraphs = zh_paragraphs
        title_en = translated_payload.get("title_en", "") or str(source_article.get("title", ""))
        captions = translated_payload.get("captions_en", [])
        if not captions:
            captions = self._as_string_list(source_article.get("captions", []))

        entity_meta = self._collect_entity_meta(verifier_output)
        outline = self._build_outline(
            title_en=title_en,
            paragraphs_en=en_paragraphs,
            captions_en=captions,
            entity_meta=entity_meta,
        )
        chunk_results = self._revise_chunks(
            outline=outline,
            paragraphs_zh=zh_paragraphs,
            paragraphs_en=en_paragraphs,
            captions_en=captions,
            entity_meta=entity_meta,
        )

        assembled = self._assemble(
            outline=outline,
            chunk_results=chunk_results,
            fallback_title=title_en,
            fallback_captions=captions,
            entity_meta=entity_meta,
        )
        return {
            "model": self.client.model,
            "schema_version": "2.0",
            "revision": assembled["revision"],
            "revised_text": assembled["revised_text"],
            "revision_meta": assembled["revision_meta"],
            "revision_outline": outline,
            "title_limit": self.max_title_words,
            "caption_limit": self.max_caption_words,
        }

    def _build_outline(
        self,
        title_en: str,
        paragraphs_en: list[str],
        captions_en: list[str],
        entity_meta: dict[str, Any],
    ) -> dict[str, Any]:
        system_prompt = OUTLINE_PROMPT_FILE.read_text(encoding="utf-8")
        payload = {
            "title_en": title_en,
            "paragraphs_en": paragraphs_en,
            "captions_en": captions_en,
            "entity_mapping": entity_meta.get("mappings", []),
            "entity_summary": {
                "resolved_entities": entity_meta.get("resolved_count", 0),
                "unresolved_entities": entity_meta.get("unresolved_count", 0),
                "used_verifier": entity_meta.get("used_verifier", False),
            },
        }
        user_prompt = (
            "Read full translation and return segmented outline. Each part has at most 5 paragraphs."
            " Keep paragraph order unchanged.\n\n"
            f"{json.dumps(payload, ensure_ascii=False, indent=2)}"
        )
        outline = self._chat_json(system_prompt=system_prompt, user_prompt=user_prompt)
        if not self._is_valid_outline(outline, len(paragraphs_en)):
            return self._fallback_outline(
                paragraph_count=len(paragraphs_en),
                fallback_title=title_en,
                use_entity_mapping=bool(entity_meta.get("used_verifier", False)),
            )
        return outline

    def _revise_chunks(
        self,
        outline: dict[str, Any],
        paragraphs_zh: list[str],
        paragraphs_en: list[str],
        captions_en: list[str],
        entity_meta: dict[str, Any],
    ) -> list[dict[str, Any]]:
        system_prompt = CHUNK_PROMPT_FILE.read_text(encoding="utf-8")
        results: list[dict[str, Any]] = []
        parts = outline.get("parts", [])
        if not isinstance(parts, list):
            return results

        for idx, part in enumerate(parts):
            if not isinstance(part, dict):
                continue
            paragraph_ids = self._normalize_paragraph_ids(part.get("paragraph_ids", []), len(paragraphs_en))
            if not paragraph_ids:
                continue
            part_id = int(part.get("part_id", idx + 1))
            part_en = [paragraphs_en[pid - 1] for pid in paragraph_ids]
            part_zh = [paragraphs_zh[pid - 1] if pid - 1 < len(paragraphs_zh) else "" for pid in paragraph_ids]
            payload = {
                "part": {
                    "part_id": part_id,
                    "subtitle_en": str(part.get("subtitle_en", "")).strip(),
                    "summary": str(part.get("summary", "")).strip(),
                    "paragraph_ids": paragraph_ids,
                },
                "outline": outline,
                "entity_mapping": entity_meta.get("mappings", []),
                "translated_paragraphs_en": part_en,
                "source_paragraphs_zh": part_zh,
                # Captions are sent only in the first chunk to avoid duplicate rewrites.
                "captions_for_revision": captions_en if idx == 0 else [],
            }
            user_prompt = (
                "Revise only the current part. Keep paragraph count and order unchanged.\n\n"
                f"{json.dumps(payload, ensure_ascii=False, indent=2)}"
            )
            revised = self._chat_json(system_prompt=system_prompt, user_prompt=user_prompt)
            revised_paragraphs = self._as_string_list(revised.get("paragraphs_revised_en", []))
            if len(revised_paragraphs) != len(part_en):
                revised_paragraphs = part_en
            revised_captions = self._as_string_list(revised.get("captions_revised_en", []))
            results.append(
                {
                    "part_id": part_id,
                    "subtitle_en": str(part.get("subtitle_en", "")).strip(),
                    "paragraph_ids": paragraph_ids,
                    "paragraphs_revised_en": revised_paragraphs,
                    "captions_revised_en": revised_captions,
                }
            )
        return results

    def _assemble(
        self,
        outline: dict[str, Any],
        chunk_results: list[dict[str, Any]],
        fallback_title: str,
        fallback_captions: list[str],
        entity_meta: dict[str, Any],
    ) -> dict[str, Any]:
        chunk_results_sorted = sorted(chunk_results, key=lambda item: int(item.get("part_id", 0)))
        paragraphs_revised_en: list[str] = []
        subtitles_en: list[dict[str, Any]] = []
        captions_revised_en: list[str] = []
        text_blocks: list[str] = []

        for chunk in chunk_results_sorted:
            subtitle = str(chunk.get("subtitle_en", "")).strip()
            paragraph_ids = chunk.get("paragraph_ids", [])
            if subtitle and paragraph_ids:
                subtitles_en.append(
                    {
                        "insert_before_paragraph": int(paragraph_ids[0]),
                        "subtitle": subtitle,
                    }
                )
                text_blocks.append(subtitle)
            for paragraph in self._as_string_list(chunk.get("paragraphs_revised_en", [])):
                paragraphs_revised_en.append(paragraph)
                text_blocks.append(paragraph)
            if not captions_revised_en:
                captions_revised_en = self._as_string_list(chunk.get("captions_revised_en", []))

        if not captions_revised_en:
            captions_revised_en = fallback_captions

        title_revised = str(outline.get("title_revised_en", "")).strip() or fallback_title
        degraded_reason = None
        if not entity_meta.get("used_verifier", False):
            degraded_reason = "verifier_output_missing_or_invalid"
        revision_meta = {
            "used_verifier": bool(entity_meta.get("used_verifier", False)),
            "resolved_entities": int(entity_meta.get("resolved_count", 0)),
            "unresolved_entities": int(entity_meta.get("unresolved_count", 0)),
            "total_parts": len(chunk_results_sorted),
            "degraded_reason": degraded_reason,
        }
        return {
            "revision": {
                "title_revised_en": title_revised,
                "paragraphs_revised_en": paragraphs_revised_en,
                "captions_revised_en": captions_revised_en,
                "subtitles_en": subtitles_en,
            },
            "revised_text": "\n\n".join(text_blocks).strip(),
            "revision_meta": revision_meta,
        }

    @staticmethod
    def _parse_translated_payload(translation: dict) -> dict[str, Any]:
        raw = str(translation.get("translated_text", "")).strip()
        payload: dict[str, Any] = {
            "title_en": "",
            "paragraphs_en": [],
            "captions_en": [],
        }
        if not raw:
            return payload

        parsed = RevisionStage._extract_json_object(raw)
        if parsed and isinstance(parsed, dict):
            translation_block = parsed.get("translation", {})
            captions_block = parsed.get("captions", {})
            if isinstance(translation_block, dict):
                payload["title_en"] = str(translation_block.get("title_en", "")).strip()
                payload["paragraphs_en"] = RevisionStage._as_string_list(
                    translation_block.get("paragraphs_en", [])
                )
            if isinstance(captions_block, dict):
                payload["captions_en"] = RevisionStage._as_string_list(
                    captions_block.get("translated_captions", [])
                )
            if payload["paragraphs_en"]:
                return payload

        payload["paragraphs_en"] = [block.strip() for block in raw.split("\n\n") if block.strip()]
        return payload

    @staticmethod
    def _collect_entity_meta(verifier_output: dict[str, Any] | None) -> dict[str, Any]:
        if not isinstance(verifier_output, dict):
            return {
                "used_verifier": False,
                "resolved_count": 0,
                "unresolved_count": 0,
                "mappings": [],
            }

        summary = verifier_output.get("summary", {})
        paragraph_results = verifier_output.get("paragraph_results", [])
        mappings: list[dict[str, Any]] = []
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
                    mappings.append(
                        {
                            "entity_zh": str(entity.get("entity_zh", "")).strip(),
                            "entity_en": str(entity.get("entity_en", "")).strip(),
                            "type": str(entity.get("type", "other")).strip() or "other",
                            "is_verified": bool(entity.get("is_verified", False)),
                            "verification_status": str(entity.get("verification_status", "")).strip(),
                            "final_recommendation": str(entity.get("final_recommendation", "")).strip(),
                        }
                    )
        return {
            "used_verifier": True,
            "resolved_count": int(summary.get("verified_entities", 0)),
            "unresolved_count": int(summary.get("unresolved_entities", 0)),
            "mappings": mappings,
        }

    @staticmethod
    def _is_valid_outline(outline: dict[str, Any], paragraph_count: int) -> bool:
        if not isinstance(outline, dict):
            return False
        parts = outline.get("parts", [])
        if not isinstance(parts, list) or not parts:
            return False
        covered: list[int] = []
        for part in parts:
            if not isinstance(part, dict):
                return False
            paragraph_ids = part.get("paragraph_ids", [])
            if not isinstance(paragraph_ids, list) or not paragraph_ids:
                return False
            normalized_ids = []
            for pid in paragraph_ids:
                try:
                    value = int(pid)
                except (TypeError, ValueError):
                    return False
                if value <= 0 or value > paragraph_count:
                    return False
                normalized_ids.append(value)
            if len(normalized_ids) > 5:
                return False
            covered.extend(normalized_ids)
        return sorted(covered) == list(range(1, paragraph_count + 1))

    @staticmethod
    def _fallback_outline(
        paragraph_count: int,
        fallback_title: str,
        use_entity_mapping: bool,
    ) -> dict[str, Any]:
        parts: list[dict[str, Any]] = []
        current_id = 1
        part_id = 1
        while current_id <= paragraph_count:
            ids = list(range(current_id, min(current_id + 5, paragraph_count + 1)))
            parts.append(
                {
                    "part_id": part_id,
                    "subtitle_en": f"Section {part_id} Focus",
                    "summary": f"Part {part_id} summary.",
                    "paragraph_ids": ids,
                }
            )
            current_id += 5
            part_id += 1
        return {
            "schema_version": "1.0",
            "total_paragraphs": paragraph_count,
            "title_revised_en": fallback_title,
            "entity_mapping_used": use_entity_mapping,
            "parts": parts,
        }

    def _chat_json(self, system_prompt: str, user_prompt: str) -> dict[str, Any]:
        raw = self.client.chat(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            temperature=self.temperature,
        )
        parsed = self._extract_json_object(raw)
        if parsed is not None:
            return parsed

        retry_prompt = (
            f"{user_prompt}\n\n"
            "Last response was not valid JSON. Return exactly one JSON object matching schema."
        )
        raw_retry = self.client.chat(
            system_prompt=system_prompt,
            user_prompt=retry_prompt,
            temperature=self.temperature,
        )
        return self._extract_json_object(raw_retry) or {}

    @staticmethod
    def _extract_json_object(text: str) -> dict[str, Any] | None:
        content = str(text).strip()
        if not content:
            return None
        try:
            loaded = json.loads(content)
            if isinstance(loaded, dict):
                return loaded
            return None
        except json.JSONDecodeError:
            pass

        decoder = json.JSONDecoder()
        for idx, char in enumerate(content):
            if char != "{":
                continue
            try:
                loaded, _ = decoder.raw_decode(content[idx:])
                if isinstance(loaded, dict):
                    return loaded
            except json.JSONDecodeError:
                continue
        return None

    @staticmethod
    def _normalize_paragraph_ids(paragraph_ids: Any, max_id: int) -> list[int]:
        if not isinstance(paragraph_ids, list):
            return []
        normalized = []
        for value in paragraph_ids:
            try:
                pid = int(value)
            except (TypeError, ValueError):
                continue
            if 1 <= pid <= max_id:
                normalized.append(pid)
        return normalized

    @staticmethod
    def _as_string_list(value: Any) -> list[str]:
        if not isinstance(value, list):
            return []
        return [str(item).strip() for item in value if str(item).strip()]
