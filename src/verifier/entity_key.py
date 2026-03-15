from __future__ import annotations


def normalize_entity_text(value: str) -> str:
    return "".join(str(value).strip().lower().split())


def build_entity_exact_key(entity_zh: str, entity_en: str, entity_type: str) -> str:
    zh = normalize_entity_text(entity_zh)
    en = normalize_entity_text(entity_en)
    kind = normalize_entity_text(entity_type or "other")
    return f"{zh}|{en}|{kind}"

