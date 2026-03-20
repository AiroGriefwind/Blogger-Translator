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
    / "Verifier_Synonym_Review_Prompt.md"
)


@dataclass
class SynonymReviewStage:
    client: SiliconFlowClient
    temperature: float = 0.0

    def run(
        self,
        *,
        language_mode: str,
        category: str,
        new_items: list[dict[str, Any]],
        reviewed_items_batch: list[dict[str, Any]],
        known_synonym_groups: list[dict[str, Any]],
    ) -> dict[str, Any]:
        system_prompt = PROMPT_FILE.read_text(encoding="utf-8")
        payload = {
            "language_mode": language_mode,
            "category": category,
            "new_items": new_items,
            "reviewed_items_batch": reviewed_items_batch,
            "known_synonym_groups": known_synonym_groups,
        }
        content = self.client.chat(
            system_prompt=system_prompt,
            user_prompt=json.dumps(payload, ensure_ascii=False, indent=2),
            temperature=self.temperature,
        )
        parsed = _parse_json_object(content)
        matches = parsed.get("matches", [])
        if not isinstance(matches, list):
            matches = []
        cleaned_matches: list[dict[str, Any]] = []
        for item in matches:
            if not isinstance(item, dict):
                continue
            cleaned_matches.append(
                {
                    "new_id": str(item.get("new_id", "")).strip(),
                    "reviewed_id": str(item.get("reviewed_id", "")).strip(),
                    "is_synonym": bool(item.get("is_synonym", False)),
                    "confidence": str(item.get("confidence", "low")).strip() or "low",
                    "reason": str(item.get("reason", "")).strip(),
                }
            )
        return {
            "schema_version": str(parsed.get("schema_version", "1.0")),
            "language_mode": str(parsed.get("language_mode", language_mode)).strip(),
            "category": str(parsed.get("category", category)).strip(),
            "matches": cleaned_matches,
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

