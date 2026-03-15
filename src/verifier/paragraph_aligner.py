from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from translator.siliconflow_client import SiliconFlowClient


PROMPT_FILE = (
    Path(__file__).resolve().parents[1]
    / "config"
    / "prompts"
    / "Verifier_Interleave_Paragraphs_Prompt.md"
)


@dataclass
class ParagraphAligner:
    client: SiliconFlowClient
    temperature: float = 0.0

    def run(
        self,
        original_zh_paragraphs: list[str],
        translated_en_paragraphs: list[str],
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        system_prompt = PROMPT_FILE.read_text(encoding="utf-8")
        payload = {
            "original_zh_paragraphs": original_zh_paragraphs,
            "translated_en_paragraphs": translated_en_paragraphs,
            "metadata": metadata or {},
        }
        content = self.client.chat(
            system_prompt=system_prompt,
            user_prompt=json.dumps(payload, ensure_ascii=False, indent=2),
            temperature=self.temperature,
        )
        parsed = _parse_json_object(content)
        paragraph_pairs = parsed.get("paragraph_pairs", [])
        alignment_notes = parsed.get("alignment_notes", [])
        if not isinstance(paragraph_pairs, list):
            raise ValueError("Verifier_Interleave_Paragraphs_Prompt 输出缺少 paragraph_pairs 数组")
        if not isinstance(alignment_notes, list):
            raise ValueError("Verifier_Interleave_Paragraphs_Prompt 输出缺少 alignment_notes 数组")
        return {
            "schema_version": str(parsed.get("schema_version", "1.0")),
            "paragraph_pairs": paragraph_pairs,
            "alignment_notes": alignment_notes,
        }


def _parse_json_object(content: str) -> dict[str, Any]:
    cleaned = content.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.strip("`").replace("json", "", 1).strip()
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start != -1 and end != -1 and end > start:
        cleaned = cleaned[start : end + 1]
    data = json.loads(cleaned)
    if not isinstance(data, dict):
        raise ValueError("LLM 返回不是 JSON object")
    return data
