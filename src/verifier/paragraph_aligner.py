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
        try:
            parsed = _parse_json_object(content)
        except Exception:
            parsed = self._repair_and_parse_json(content)
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

    def _repair_and_parse_json(self, broken_content: str) -> dict[str, Any]:
        repair_system_prompt = (
            "You are a strict JSON repair tool. Return exactly one valid JSON object only."
        )
        repair_user_prompt = (
            "Fix the following invalid JSON output. Keep original meaning and fields when possible.\n\n"
            f"{broken_content}"
        )
        repaired = self.client.chat(
            system_prompt=repair_system_prompt,
            user_prompt=repair_user_prompt,
            temperature=0.0,
        )
        return _parse_json_object(repaired)


def _parse_json_object(content: str) -> dict[str, Any]:
    cleaned = content.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.strip("`").replace("json", "", 1).strip()
    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError:
        start = cleaned.find("{")
        end = cleaned.rfind("}")
        if start == -1 or end == -1 or end <= start:
            raise
        cleaned = cleaned[start : end + 1]
        try:
            data = json.loads(cleaned)
        except json.JSONDecodeError:
            decoder = json.JSONDecoder()
            for idx, char in enumerate(cleaned):
                if char != "{":
                    continue
                try:
                    data, _ = decoder.raw_decode(cleaned[idx:])
                    break
                except json.JSONDecodeError:
                    continue
            else:
                raise
    if not isinstance(data, dict):
        raise ValueError("LLM 返回不是 JSON object")
    return data
