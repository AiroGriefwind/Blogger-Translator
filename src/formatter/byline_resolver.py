from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path


MAPPING_FILE = Path(__file__).resolve().parents[1] / "config" / "author_column_mappings.json"


def resolve_bylines(scraped_author: str, scraped_title: str = "") -> dict[str, str]:
    raw = _normalize_space(scraped_author)
    title = _normalize_space(scraped_title)
    source_text = f"{raw} {title}".strip()
    columns, authors = _load_mapping()

    # Strict mapping-only: never trust translated author/column from LLM.
    column_en = _find_en_by_alias(columns, source_text)
    author_en = _find_en_by_alias(authors, source_text)

    header_line = ""
    if column_en and author_en:
        header_line = f"{column_en} (By {author_en})"
    elif column_en:
        header_line = column_en
    else:
        header_line = author_en

    return {
        "header_line_en": header_line.strip(),
        "ending_author_en": author_en.strip(),
        "ending_column_en": column_en.strip(),
    }


def safe_docx_name(title: str, fallback: str) -> str:
    raw = _normalize_space(title)
    if not raw:
        raw = fallback
    sanitized = re.sub(r'[<>:"/\\|?*]', "_", raw).strip(" .")
    sanitized = re.sub(r"\s+", " ", sanitized).strip()
    if not sanitized:
        sanitized = fallback
    return f"{sanitized[:120]}.docx"


def needs_title_shorten(title: str, max_words: int = 10) -> bool:
    text = _normalize_space(title)
    if not text:
        return False
    words = [part for part in text.split(" ") if part]
    if len(words) > max_words:
        return True
    cjk_chars = re.findall(r"[\u4e00-\u9fff]", text)
    return len(cjk_chars) > max_words


def fallback_short_title(title: str, max_words: int = 10) -> str:
    text = _normalize_space(title)
    if not text:
        return ""
    words = [part for part in text.split(" ") if part]
    if len(words) > max_words:
        return " ".join(words[:max_words]).strip(" -:;,.!?")
    return text


def _normalize_space(text: str) -> str:
    return " ".join(str(text).strip().split())


@lru_cache(maxsize=1)
def _load_mapping() -> tuple[list[dict], list[dict]]:
    payload = json.loads(MAPPING_FILE.read_text(encoding="utf-8"))
    columns = payload.get("columns", [])
    authors = payload.get("authors", [])
    if not isinstance(columns, list):
        columns = []
    if not isinstance(authors, list):
        authors = []
    return (
        [item for item in columns if isinstance(item, dict)],
        [item for item in authors if isinstance(item, dict)],
    )


def _find_en_by_alias(items: list[dict], text: str) -> str:
    source = _normalize_space(text)
    if not source:
        return ""
    for item in items:
        en = _normalize_space(str(item.get("en", "")))
        aliases = item.get("aliases", [])
        if not en or not isinstance(aliases, list):
            continue
        for alias in aliases:
            token = _normalize_space(str(alias))
            if token and token in source:
                return en
    return ""
