from __future__ import annotations

import re
from typing import Any


def build_entity_groups(paragraph_results: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    groups = {"llm": [], "db_exact_hit": [], "runtime_cache_hit": []}
    for paragraph in paragraph_results:
        if not isinstance(paragraph, dict):
            continue
        paragraph_id = paragraph.get("paragraph_id", "")
        zh = str(paragraph.get("zh", ""))
        en = str(paragraph.get("en", ""))
        verified_entities = paragraph.get("verified_entities", [])
        if not isinstance(verified_entities, list):
            continue
        for entity_index, entity in enumerate(verified_entities):
            if not isinstance(entity, dict):
                continue
            row = {
                "paragraph_id": paragraph_id,
                "paragraph_zh": zh,
                "paragraph_en": en,
                "entity_index": entity_index,
                "entity": entity,
            }
            status = str(entity.get("verification_status", "")).strip()
            if status == "db_exact_hit":
                groups["db_exact_hit"].append(row)
            elif status == "runtime_cache_hit":
                groups["runtime_cache_hit"].append(row)
            else:
                groups["llm"].append(row)
    return groups


def build_entity_search_terms(entity_en: str, entity_type: str) -> list[str]:
    terms: list[str] = []
    cleaned = " ".join(str(entity_en).split()).strip()
    if cleaned:
        terms.append(cleaned)

    if str(entity_type).strip().lower() == "person" and cleaned:
        parts = [part.strip() for part in cleaned.split(" ") if part.strip()]
        if len(parts) >= 2:
            # 人名补充简称候选，覆盖 John Wick -> John / Wick 的常见写法。
            terms.extend([parts[0], parts[-1]])
        if len(parts) >= 3:
            terms.append(" ".join(parts[:-1]))
            terms.append(" ".join(parts[1:]))

    seen: set[str] = set()
    unique_terms: list[str] = []
    for term in terms:
        lowered = term.lower()
        if lowered in seen:
            continue
        seen.add(lowered)
        unique_terms.append(term)
    return unique_terms


def _find_term_matches(text: str, term: str) -> list[dict[str, Any]]:
    if not text or not term:
        return []
    pattern = re.compile(rf"(?<!\w){re.escape(term)}(?!\w)", flags=re.IGNORECASE)
    results: list[dict[str, Any]] = []
    for match in pattern.finditer(text):
        start, end = match.span()
        context_start = max(0, start - 24)
        context_end = min(len(text), end + 24)
        results.append(
            {
                "term": term,
                "start": start,
                "end": end,
                "matched_text": text[start:end],
                "context": text[context_start:context_end],
            }
        )
    return results


def build_replacement_candidates(
    translated_text: str,
    paragraph_results: list[dict[str, Any]],
    search_terms: list[str],
) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    for term in search_terms:
        for match in _find_term_matches(translated_text, term):
            candidates.append(
                {
                    "scope": "translated_text",
                    "scope_label": "Translator 输出全文",
                    "paragraph_id": None,
                    **match,
                }
            )

    for paragraph in paragraph_results:
        if not isinstance(paragraph, dict):
            continue
        text = str(paragraph.get("en", ""))
        paragraph_id = paragraph.get("paragraph_id")
        for term in search_terms:
            for match in _find_term_matches(text, term):
                candidates.append(
                    {
                        "scope": "paragraph_en",
                        "scope_label": f"核验段落译文 p{paragraph_id}",
                        "paragraph_id": paragraph_id,
                        **match,
                    }
                )
    return candidates

