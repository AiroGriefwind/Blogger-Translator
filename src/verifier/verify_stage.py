from __future__ import annotations

import json
from copy import deepcopy
from dataclasses import dataclass
from typing import Any
from typing import Callable

from translator.siliconflow_client import SiliconFlowClient
from verifier.entity_extractor import EntityExtractor
from verifier.entity_key import build_entity_exact_key
from verifier.entity_verifier import EntityVerifier
from verifier.paragraph_aligner import ParagraphAligner


@dataclass
class VerifyStage:
    client: SiliconFlowClient
    temperature: float = 0.0

    def run(
        self,
        scraped: dict,
        translated: dict,
        on_progress: Callable[[dict[str, Any]], None] | None = None,
        lookup_exact: Callable[[dict[str, Any]], dict[str, Any] | None] | None = None,
    ) -> dict[str, Any]:
        zh_paragraphs = self._as_string_list(scraped.get("body_paragraphs", []))
        en_paragraphs = self._extract_translated_paragraphs(translated)

        aligner = ParagraphAligner(self.client, temperature=self.temperature)
        extractor = EntityExtractor(self.client, temperature=self.temperature)
        verifier = EntityVerifier(self.client, temperature=self.temperature)

        try:
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
        except Exception as err:
            aligned = self._fallback_alignment(
                zh_paragraphs=zh_paragraphs,
                en_paragraphs=en_paragraphs,
                err=err,
            )

        aligned_pairs = [
            pair
            for pair in aligned.get("paragraph_pairs", [])
            if int(pair.get("paragraph_id", 0)) > 0
        ]
        total_paragraphs = len(aligned_pairs)
        if on_progress:
            on_progress(
                {
                    "event": "start",
                    "done_paragraphs": 0,
                    "total_paragraphs": total_paragraphs,
                    "percent": 0.0,
                    "message": f"核验启动，共 {total_paragraphs} 段待处理",
                }
            )

        paragraph_results: list[dict[str, Any]] = []
        total_entities = 0
        verified_entities = 0
        unresolved_entities = 0
        aligner_fallbacks = 0
        extractor_failures = 0
        verifier_failures = 0
        degradation_notes: list[str] = []
        done_paragraphs = 0
        run_cache: dict[str, dict[str, Any]] = {}
        alignment_notes = aligned.get("alignment_notes", [])
        if isinstance(alignment_notes, list):
            for note in alignment_notes:
                if isinstance(note, dict) and str(note.get("type", "")).strip() == "fallback":
                    aligner_fallbacks += 1
                    degradation_notes.append(str(note.get("message", "")).strip())
                    if on_progress:
                        on_progress(
                            {
                                "event": "align_failed",
                                "done_paragraphs": 0,
                                "total_paragraphs": total_paragraphs,
                                "percent": 0.0,
                                "message": f"段落对齐失败，已降级按段号一一对齐：{note.get('message', '')}",
                            }
                        )

        for pair in aligned_pairs:
            paragraph_id = int(pair.get("paragraph_id", 0))
            zh = str(pair.get("zh", ""))
            en = str(pair.get("en", ""))

            try:
                extracted = extractor.run(paragraph_id=paragraph_id, zh=zh, en=en)
                extracted_entities = extracted.get("entities", [])
            except Exception as err:
                extracted_entities = []
                extractor_failures += 1
                degradation_notes.append(f"extract_failed:p{paragraph_id}:{err}")
                if on_progress:
                    on_progress(
                        {
                            "event": "extract_failed",
                            "done_paragraphs": done_paragraphs,
                            "total_paragraphs": total_paragraphs,
                            "paragraph_id": paragraph_id,
                            "percent": (
                                done_paragraphs / total_paragraphs * 100.0 if total_paragraphs else 100.0
                            ),
                            "message": (
                                f"段落ID={paragraph_id} 实体抽取失败，已降级为空实体列表：{err}"
                            ),
                        }
                    )
            verified_items: list[dict[str, Any]] = []

            for entity in extracted_entities:
                if not isinstance(entity, dict):
                    continue
                exact_key = build_entity_exact_key(
                    str(entity.get("entity_zh", "")),
                    str(entity.get("entity_en", "")),
                    str(entity.get("type", "other")),
                )
                verified: dict[str, Any] = {}
                if exact_key in run_cache:
                    verified = deepcopy(run_cache[exact_key])
                    verified["verification_status"] = "runtime_cache_hit"
                    if on_progress:
                        on_progress(
                            {
                                "event": "entity_cached_hit",
                                "done_paragraphs": done_paragraphs,
                                "total_paragraphs": total_paragraphs,
                                "paragraph_id": paragraph_id,
                                "percent": (
                                    done_paragraphs / total_paragraphs * 100.0
                                    if total_paragraphs
                                    else 100.0
                                ),
                                "message": (
                                    f"段落ID={paragraph_id} 命中运行内缓存，跳过 LLM："
                                    f"{verified.get('entity_zh', '')} / {verified.get('entity_en', '')}"
                                ),
                            }
                        )
                else:
                    if lookup_exact:
                        db_match = lookup_exact(entity)
                        if isinstance(db_match, dict):
                            verified = deepcopy(db_match)
                            if not str(verified.get("verification_status", "")).strip():
                                verified["verification_status"] = "db_exact_hit"
                            if on_progress:
                                on_progress(
                                    {
                                        "event": "entity_db_hit",
                                        "done_paragraphs": done_paragraphs,
                                        "total_paragraphs": total_paragraphs,
                                        "paragraph_id": paragraph_id,
                                        "percent": (
                                            done_paragraphs / total_paragraphs * 100.0
                                            if total_paragraphs
                                            else 100.0
                                        ),
                                        "message": (
                                            f"段落ID={paragraph_id} 命中线上映射，跳过 LLM："
                                            f"{verified.get('entity_zh', '')} / {verified.get('entity_en', '')}"
                                        ),
                                    }
                                )
                    if not verified:
                        try:
                            verified = verifier.run(
                                paragraph_id=paragraph_id,
                                paragraph_zh=zh,
                                paragraph_en=en,
                                entity=entity,
                            ).get("entity", {})
                        except Exception as err:
                            verifier_failures += 1
                            degradation_notes.append(f"verify_failed:p{paragraph_id}:{err}")
                            verified = self._fallback_unverified_entity(entity, err)
                            if on_progress:
                                on_progress(
                                    {
                                        "event": "verify_failed",
                                        "done_paragraphs": done_paragraphs,
                                        "total_paragraphs": total_paragraphs,
                                        "paragraph_id": paragraph_id,
                                        "percent": (
                                            done_paragraphs / total_paragraphs * 100.0
                                            if total_paragraphs
                                            else 100.0
                                        ),
                                        "message": (
                                            "实体核验 JSON 解析失败，已降级 unverified："
                                            f"{verified.get('entity_zh', '')} / {verified.get('entity_en', '')}"
                                        ),
                                    }
                                )
                    if isinstance(verified, dict) and verified:
                        run_cache[exact_key] = deepcopy(verified)

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
            done_paragraphs += 1
            if on_progress:
                percent = (done_paragraphs / total_paragraphs * 100.0) if total_paragraphs else 100.0
                on_progress(
                    {
                        "event": "paragraph_done",
                        "done_paragraphs": done_paragraphs,
                        "total_paragraphs": total_paragraphs,
                        "paragraph_id": paragraph_id,
                        "percent": percent,
                        "message": (
                            f"已完成第 {done_paragraphs}/{total_paragraphs} 段（段落ID={paragraph_id}）"
                        ),
                    }
                )

        if on_progress:
            on_progress(
                {
                    "event": "done",
                    "done_paragraphs": done_paragraphs,
                    "total_paragraphs": total_paragraphs,
                    "percent": 100.0,
                    "message": f"核验完成，共处理 {done_paragraphs} 段",
                }
            )

        return {
            "schema_version": "1.0",
            "summary": {
                "paragraph_count": len(paragraph_results),
                "total_entities": total_entities,
                "verified_entities": verified_entities,
                "unresolved_entities": unresolved_entities,
                "degrade_stats": {
                    "aligner_fallbacks": aligner_fallbacks,
                    "extractor_failures": extractor_failures,
                    "verifier_failures": verifier_failures,
                },
            },
            "alignment_notes": alignment_notes,
            "degradation_notes": degradation_notes,
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

    @staticmethod
    def _fallback_alignment(
        zh_paragraphs: list[str],
        en_paragraphs: list[str],
        err: Exception,
    ) -> dict[str, Any]:
        total = max(len(zh_paragraphs), len(en_paragraphs))
        pairs = []
        for idx in range(total):
            pairs.append(
                {
                    "paragraph_id": idx + 1,
                    "zh": zh_paragraphs[idx] if idx < len(zh_paragraphs) else "",
                    "en": en_paragraphs[idx] if idx < len(en_paragraphs) else "",
                }
            )
        return {
            "schema_version": "1.0",
            "paragraph_pairs": pairs,
            "alignment_notes": [
                {
                    "type": "fallback",
                    "message": f"aligner_failed_degraded: {err}",
                }
            ],
        }

    @staticmethod
    def _fallback_unverified_entity(entity: dict[str, Any], err: Exception) -> dict[str, Any]:
        return {
            "entity_zh": str(entity.get("entity_zh", "")).strip(),
            "entity_en": str(entity.get("entity_en", "")).strip(),
            "type": str(entity.get("type", "other")).strip() or "other",
            "is_verified": False,
            "verification_status": "unverified",
            "sources": [],
            "final_recommendation": str(entity.get("final_recommendation", "")).strip(),
            "uncertainty_reason": f"verify_stage_degraded_due_to_json_error: {err}",
            "next_search_queries": [],
        }
