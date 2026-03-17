from __future__ import annotations

from datetime import datetime
from pathlib import Path
import uuid

from formatter.docx_formatter import DocxFormatter


def new_mock_run_id() -> str:
    ts = datetime.utcnow().strftime("%Y%m%d%H%M%S")
    return f"mock_{ts}_{uuid.uuid4().hex[:8]}"


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
    paragraphs = [
        "Energy prices whipsawed as conflicting policy signals hit the market.",
        "Traders quickly repriced risk after fresh supply narratives emerged.",
    ]
    return {
        "model": "mock-deepseek-r1",
        "schema_version": "2.0",
        "revision": {
            "title_revised_en": article.get("title", ""),
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
            "title_revised_en": article.get("title", ""),
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


def build_mock_docx(output_dir: str | Path, run_id: str, article: dict, revised: dict) -> Path:
    output_file = Path(output_dir) / f"{run_id}.docx"
    formatter = DocxFormatter()
    formatter.build(
        output_path=output_file,
        title_en=article.get("title", ""),
        author_en=article.get("author", ""),
        body_blocks=[revised.get("revised_text", "")],
        ending_author_zh=article.get("author", ""),
        captions_blocks=article.get("captions", []),
    )
    return output_file

