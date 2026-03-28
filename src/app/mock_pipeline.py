from __future__ import annotations

from datetime import datetime
from pathlib import Path
import json
import uuid
from zoneinfo import ZoneInfo

from formatter.byline_resolver import (
    fallback_short_title,
    needs_title_shorten,
    resolve_bylines,
    safe_docx_name,
)
from formatter.docx_formatter import DocxFormatter


def new_mock_run_id(source_title: str = "") -> str:
    ts = datetime.now(tz=ZoneInfo("Asia/Hong_Kong")).strftime("%Y%m%d%H%M%S")
    prefix = _title_prefix(source_title)
    return f"{prefix}_{ts}_{uuid.uuid4().hex[:8]}"


def _title_prefix(source_title: str, limit: int = 6) -> str:
    cleaned = "".join(ch for ch in str(source_title).strip() if ch not in '<>:"/\\|?*')
    cleaned = "".join(ch for ch in cleaned if ch.isalnum() or ("\u4e00" <= ch <= "\u9fff"))
    if cleaned.lower().startswith("mock"):
        cleaned = cleaned[4:]
    if not cleaned:
        return "untitl"
    return cleaned[:limit]


def build_mock_scraped(url: str) -> dict:
    return {
        "url": url,
        "title": "Mock：制裁魔術師特朗普：一手點燃油價大火，一手放出俄油滅火",
        "published_at": "2026-03-15T09:00:40+08:00",
        "author": "雙標研究所",
        "body_paragraphs": [
            "能源市场情绪被政策信号快速放大，油价短时间剧烈波动。",
            "分析人士指出，供应端预期与地缘风险叠加，造成价格上行压力。",
            "与此同时，释放库存与替代来源消息，又在盘中形成回落力量。",
        ],
        "captions": [
            "图一：国际油价在消息发布后急涨急跌。",
            "图二：市场参与者重新评估供需平衡。",
        ],
        "raw_html": "<html><body><!-- mock html --></body></html>",
        "scrape_meta": {
            "paragraph_count": 3,
            "caption_count": 2,
            "used_ldjson_fallback": False,
            "mocked": True,
        },
    }


def build_mock_translated(article: dict) -> dict:
    title = article.get("title", "")
    body = article.get("body_paragraphs", [])
    return {
        "source_url": article.get("url", ""),
        "model": "mock-deepseek-r1",
        "translated_text": (
            f"Title: {title}\n\n"
            "The market reacted sharply to policy signals and supply-side expectations.\n"
            f"Key points:\n- {'; '.join(body)}\n\n"
            "Captions translated in concise English."
        ),
    }


def build_mock_revised(article: dict, translation: dict) -> dict:
    mock_title_en = "Trump the Sanctions Magician: Igniting Oil Prices, Then Cooling Them with Russian Crude"
    paragraphs = [
        "Energy prices whipsawed as conflicting policy signals hit the market.",
        "Traders quickly repriced risk after fresh supply narratives emerged.",
    ]
    return {
        "model": "mock-deepseek-r1",
        "schema_version": "2.0",
        "revision": {
            "title_revised_en": mock_title_en,
            "paragraphs_revised_en": paragraphs,
            "captions_revised_en": article.get("captions", []),
            "subtitles_en": [{"insert_before_paragraph": 1, "subtitle": "Market Shock And Repricing"}],
        },
        "revision_meta": {
            "used_verifier": True,
            "resolved_entities": 1,
            "unresolved_entities": 1,
            "total_parts": 1,
            "degraded_reason": None,
        },
        "revision_outline": {
            "schema_version": "1.0",
            "total_paragraphs": 2,
            "title_revised_en": mock_title_en,
            "entity_mapping_used": True,
            "parts": [
                {
                    "part_id": 1,
                    "subtitle_en": "Market Shock And Repricing",
                    "summary": "市场波动与风险重估。",
                    "paragraph_ids": [1, 2],
                }
            ],
        },
        "revised_text": "\n\n".join(
            ["Market Shock And Repricing", *paragraphs]
        ),
        "title_limit": 12,
        "caption_limit": 25,
        "mock_note": "长度控制逻辑当前为占位输出。",
    }


def build_mock_name_questions() -> list[str]:
    return [
        "Question: What is the English/Traditional Chinese translation of 特朗普, who is this person/company in context?",
        "Question: What is the English/Traditional Chinese translation of 俄油, who is this person/company in context?",
    ]


def build_mock_verifier_output() -> dict:
    return {
        "schema_version": "1.0",
        "summary": {
            "paragraph_count": 2,
            "total_entities": 2,
            "verified_entities": 1,
            "unresolved_entities": 1,
        },
        "alignment_notes": [{"type": "count_match", "message": "mock alignment is one-to-one"}],
        "paragraph_pairs": [
            {
                "paragraph_id": 1,
                "zh": "能源市场情绪被政策信号快速放大，油价短时间剧烈波动。",
                "en": "Policy signals amplified market sentiment and caused sharp short-term oil price swings.",
            },
            {
                "paragraph_id": 2,
                "zh": "分析人士指出，供应端预期与地缘风险叠加，造成价格上行压力。",
                "en": "Analysts said supply expectations and geopolitical risks combined to push prices upward.",
            },
        ],
        "paragraph_results": [
            {
                "paragraph_id": 1,
                "zh": "能源市场情绪被政策信号快速放大，油价短时间剧烈波动。",
                "en": "Policy signals amplified market sentiment and caused sharp short-term oil price swings.",
                "extracted_entities": [
                    {
                        "entity_zh": "俄油",
                        "entity_en": "Russian oil",
                        "type": "source",
                    }
                ],
                "verified_entities": [
                    {
                        "entity_zh": "俄油",
                        "entity_en": "Russian oil",
                        "type": "source",
                        "is_verified": True,
                        "verification_status": "verified",
                        "sources": [
                            {
                                "url": "https://en.wikipedia.org/wiki/Petroleum_industry_in_Russia",
                                "site": "Wikipedia",
                                "evidence_note": "Page describes Russia petroleum industry naming in English.",
                            }
                        ],
                        "final_recommendation": "Use 'Russian oil' in this context.",
                        "uncertainty_reason": "",
                        "next_search_queries": [],
                    }
                ],
            },
            {
                "paragraph_id": 2,
                "zh": "分析人士指出，供应端预期与地缘风险叠加，造成价格上行压力。",
                "en": "Analysts said supply expectations and geopolitical risks combined to push prices upward.",
                "extracted_entities": [
                    {
                        "entity_zh": "分析人士",
                        "entity_en": "analysts",
                        "type": "other",
                    }
                ],
                "verified_entities": [
                    {
                        "entity_zh": "分析人士",
                        "entity_en": "analysts",
                        "type": "other",
                        "is_verified": False,
                        "verification_status": "unverified",
                        "sources": [],
                        "final_recommendation": "Keep generic wording; no specific named entity mapping required.",
                        "uncertainty_reason": "Generic noun phrase, not a concrete named entity.",
                        "next_search_queries": ["energy market analyst term definition"],
                    }
                ],
            },
        ],
        "compat_name_questions": [
            "[p1] 俄油 / Russian oil -> verified",
            "[p2] 分析人士 / analysts -> unverified",
        ],
    }


def build_mock_docx(
    output_dir: str | Path,
    run_id: str,
    article: dict,
    revised: dict,
    translated: dict | None = None,
) -> Path:
    translated = translated if isinstance(translated, dict) else {}
    translated_title_en = ""
    translated_text = str(translated.get("translated_text", "")).strip()
    if translated_text:
        try:
            payload = json.loads(translated_text)
        except json.JSONDecodeError:
            payload = {}
        translation = payload.get("translation", {}) if isinstance(payload, dict) else {}
        if isinstance(translation, dict):
            translated_title_en = str(translation.get("title_en", "")).strip()

    formatter = DocxFormatter()
    revision_block = revised.get("revision", {})
    if not isinstance(revision_block, dict):
        revision_block = {}
    revised_paragraphs = [
        str(item).strip()
        for item in revision_block.get("paragraphs_revised_en", [])
        if str(item).strip()
    ]
    source_paragraphs = [str(item).strip() for item in article.get("body_paragraphs", []) if str(item).strip()]
    body_blocks: list[str] = []
    for idx, paragraph_en in enumerate(revised_paragraphs, start=1):
        paragraph_zh = source_paragraphs[idx - 1] if idx - 1 < len(source_paragraphs) else ""
        body_blocks.append(paragraph_en)
        if paragraph_zh:
            body_blocks.append(paragraph_zh)
        body_blocks.append("")
    if not body_blocks:
        fallback = str(revised.get("revised_text", "")).strip()
        body_blocks = [fallback] if fallback else []
    else:
        while body_blocks and not body_blocks[-1].strip():
            body_blocks.pop()
    byline = resolve_bylines(
        scraped_author=str(article.get("author", "")),
        scraped_title=str(article.get("title", "")),
    )

    title_en = str(revision_block.get("title_revised_en", "")).strip() or article.get("title", "")
    if needs_title_shorten(title_en, max_words=10):
        title_en = fallback_short_title(title_en, max_words=10)
    filename = safe_docx_name(title=title_en or translated_title_en, fallback=run_id)
    output_file = Path(output_dir) / filename

    formatter.build(
        output_path=output_file,
        title_en=title_en,
        header_byline_en=byline.get("header_line_en", ""),
        body_blocks=body_blocks,
        ending_author_en=byline.get("ending_author_en", ""),
        ending_column_en=byline.get("ending_column_en", ""),
        captions_blocks=revision_block.get("captions_revised_en", []) or article.get("captions", []),
    )
    return output_file

