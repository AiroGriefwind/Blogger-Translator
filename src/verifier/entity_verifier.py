from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from translator.siliconflow_client import SiliconFlowClient


PROMPT_FILE = (
    Path(__file__).resolve().parents[1]
    / "config"
    / "prompts"
    / "Verifier_Entity_Verify_Prompt.md"
)


@dataclass
class EntityVerifier:
    client: SiliconFlowClient
    temperature: float = 0.0

    def run(
        self,
        paragraph_id: int,
        paragraph_zh: str,
        paragraph_en: str,
        entity: dict[str, Any],
    ) -> dict[str, Any]:
        system_prompt = PROMPT_FILE.read_text(encoding="utf-8")
        payload = {
            "paragraph_id": paragraph_id,
            "paragraph_zh": paragraph_zh,
            "paragraph_en": paragraph_en,
            "entity_zh": str(entity.get("entity_zh", "")),
            "entity_en": str(entity.get("entity_en", "")),
            "entity_type": str(entity.get("type", "other")),
            "candidate_sources": entity.get("candidate_sources", []),
        }
        content = self.client.chat(
            system_prompt=system_prompt,
            user_prompt=json.dumps(payload, ensure_ascii=False, indent=2),
            temperature=self.temperature,
        )
        parsed = _parse_json_object(content)
        item = parsed.get("entity", {}) if isinstance(parsed.get("entity", {}), dict) else {}
        normalized = self._normalize_result(
            paragraph_id=int(parsed.get("paragraph_id", paragraph_id)),
            entity=item,
        )
        return {
            "schema_version": str(parsed.get("schema_version", "1.0")),
            "paragraph_id": normalized["paragraph_id"],
            "entity": normalized["entity"],
        }

    def _normalize_result(self, paragraph_id: int, entity: dict[str, Any]) -> dict[str, Any]:
        sources = entity.get("sources", [])
        if not isinstance(sources, list):
            sources = []
        valid_sources = []
        for source in sources:
            if not isinstance(source, dict):
                continue
            url = str(source.get("url", "")).strip()
            if _is_valid_http_url(url):
                valid_sources.append(
                    {
                        "url": url,
                        "site": str(source.get("site", "")).strip(),
                        "evidence_note": str(source.get("evidence_note", "")).strip(),
                    }
                )

        is_verified = bool(entity.get("is_verified", False))
        verification_status = str(entity.get("verification_status", "unverified")).strip() or "unverified"
        uncertainty_reason = str(entity.get("uncertainty_reason", "")).strip()
        next_queries = entity.get("next_search_queries", [])
        if not isinstance(next_queries, list):
            next_queries = []
        next_queries = [str(item).strip() for item in next_queries if str(item).strip()]

        # 严格门禁：没有有效 URL 就不能标为 verified。
        if is_verified and not valid_sources:
            is_verified = False
            verification_status = "unverified"
            if not uncertainty_reason:
                uncertainty_reason = "模型未返回有效可点击 URL，已按门禁降级为未确认。"
            if not next_queries:
                next_queries = [f"{entity.get('entity_zh', '')} {entity.get('entity_en', '')} Wikipedia"]

        return {
            "paragraph_id": paragraph_id,
            "entity": {
                "entity_zh": str(entity.get("entity_zh", "")).strip(),
                "entity_en": str(entity.get("entity_en", "")).strip(),
                "type": str(entity.get("type", "other")).strip() or "other",
                "is_verified": is_verified,
                "verification_status": verification_status,
                "sources": valid_sources,
                "final_recommendation": str(entity.get("final_recommendation", "")).strip(),
                "uncertainty_reason": uncertainty_reason,
                "next_search_queries": next_queries,
            },
        }


def _is_valid_http_url(value: str) -> bool:
    parsed = urlparse(value)
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


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
