from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from translator.siliconflow_client import SiliconFlowClient
from verifier.entity_extractor import EntityExtractor
from verifier.entity_verifier import EntityVerifier
from verifier.paragraph_aligner import ParagraphAligner


@dataclass
class VerifyStage:
    client: SiliconFlowClient
    temperature: float = 0.0

    def run(self, scraped: dict, translated: dict) -> dict[str, Any]:
        zh_paragraphs = self._as_string_list(scraped.get("body_paragraphs", []))
        en_paragraphs = self._extract_translated_paragraphs(translated)

        aligner = ParagraphAligner(self.client, temperature=self.temperature)
        extractor = EntityExtractor(self.client, temperature=self.temperature)
        verifier = EntityVerifier(self.client, temperature=self.temperature)

        aligned = aligner.run(
            original_zh_paragraphs=zh_paragraphs,
            translated_en_paragraphs=en_paragraphs,
            metadata={
                "title": scraped.get("title", ""),
                "author": scraped.get("author", ""),
                "published_at": scraped.get("published_at", ""),
                "source_url": scraped.get("url", ""),
            },
        )

        paragraph_results: list[dict[str, Any]] = []
        total_entities = 0
        verified_entities = 0
        unresolved_entities = 0

        for pair in aligned.get("paragraph_pairs", []):
            paragraph_id = int(pair.get("paragraph_id", 0))
            if paragraph_id <= 0:
                continue
            zh = str(pair.get("zh", ""))
            en = str(pair.get("en", ""))

            extracted = extractor.run(paragraph_id=paragraph_id, zh=zh, en=en)
            extracted_entities = extracted.get("entities", [])
            verified_items: list[dict[str, Any]] = []

            for entity in extracted_entities:
                if not isinstance(entity, dict):
                    continue
                verified = verifier.run(
                    paragraph_id=paragraph_id,
                    paragraph_zh=zh,
                    paragraph_en=en,
                    entity=entity,
                ).get("entity", {})
                if not isinstance(verified, dict):
                    continue
                verified_items.append(verified)
                total_entities += 1
                if verified.get("is_verified", False):
                    verified_entities += 1
                else:
                    unresolved_entities += 1

            paragraph_results.append(
                {
                    "paragraph_id": paragraph_id,
                    "zh": zh,
                    "en": en,
                    "extracted_entities": extracted_entities,
                    "verified_entities": verified_items,
                }
            )

        return {
            "schema_version": "1.0",
            "summary": {
                "paragraph_count": len(paragraph_results),
                "total_entities": total_entities,
                "verified_entities": verified_entities,
                "unresolved_entities": unresolved_entities,
            },
            "alignment_notes": aligned.get("alignment_notes", []),
            "paragraph_pairs": aligned.get("paragraph_pairs", []),
            "paragraph_results": paragraph_results,
        }

    @staticmethod
    def _as_string_list(value: Any) -> list[str]:
        if not isinstance(value, list):
            return []
        return [str(item) for item in value]

    def _extract_translated_paragraphs(self, translated: dict) -> list[str]:
        raw = str(translated.get("translated_text", "")).strip()
        if not raw:
            return []

        try:
            data = json.loads(raw)
            if isinstance(data, dict):
                blocks = data.get("translation", {}).get("paragraphs_en", [])
                if isinstance(blocks, list):
                    parsed = [str(item).strip() for item in blocks if str(item).strip()]
                    if parsed:
                        return parsed
        except json.JSONDecodeError:
            pass

        # 联调兜底：若未返回 JSON，按空行切段。
        paragraphs = [chunk.strip() for chunk in raw.split("\n\n") if chunk.strip()]
        return paragraphs
