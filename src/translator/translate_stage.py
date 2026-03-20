from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any, Callable

from translator.siliconflow_client import SiliconFlowClient


PROMPT_FILE = Path(__file__).resolve().parents[1] / "config" / "prompts" / "Translate_Bot_Prompt.md"
CHUNK_PROMPT_FILE = (
    Path(__file__).resolve().parents[1] / "config" / "prompts" / "Translate_Chunk_Prompt.md"
)


@dataclass
class TranslateStage:
    client: SiliconFlowClient
    temperature: float = 0.2
    chunk_enabled: bool = True
    chunk_max_paragraphs: int = 5
    chunk_parse_retries: int = 2

    def run(
        self,
        article: dict,
        on_progress: Callable[[dict[str, Any]], None] | None = None,
    ) -> dict:
        if not self.chunk_enabled:
            return self._run_single_call(article, on_progress=on_progress)
        paragraphs = self._as_string_list(article.get("body_paragraphs", []))
        if not paragraphs:
            return self._run_single_call(article, on_progress=on_progress)

        chunks = self._chunk_paragraphs(paragraphs, self.chunk_max_paragraphs)
        system_prompt = CHUNK_PROMPT_FILE.read_text(encoding="utf-8")
        chunk_outputs: list[dict[str, Any]] = []
        chunk_events: list[dict[str, Any]] = []
        total_attempts = 0
        total_chunks = len(chunks)
        self._emit_progress(
            on_progress,
            {
                "event": "translator_start",
                "mode": "chunked",
                "total_chunks": total_chunks,
                "message": f"翻译启动：共 {total_chunks} 个分块。",
            },
        )
        for index, chunk_paragraphs in enumerate(chunks, start=1):
            include_meta = index == 1
            payload = self._compose_chunk_payload(
                article=article,
                chunk_id=index,
                total_chunks=total_chunks,
                chunk_paragraphs=chunk_paragraphs,
                include_meta=include_meta,
            )
            user_prompt = (
                "请按系统提示完成当前翻译分块任务。仅输出一个合法 JSON 对象，不要输出其他文本。\n\n"
                f"{payload}"
            )
            self._emit_progress(
                on_progress,
                {
                    "event": "chunk_started",
                    "chunk_id": index,
                    "total_chunks": total_chunks,
                    "expected_paragraphs": len(chunk_paragraphs),
                    "message": f"开始翻译 chunk {index}/{total_chunks}（{len(chunk_paragraphs)} 段）。",
                },
            )
            chunk_payload, attempt_count, retry_count, retry_reasons = self._chat_chunk_with_retry(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                expected_paragraphs=len(chunk_paragraphs),
                chunk_id=index,
                total_chunks=total_chunks,
                include_meta=include_meta,
                on_progress=on_progress,
            )
            total_attempts += attempt_count
            chunk_outputs.append(chunk_payload)
            chunk_events.append(
                {
                    "chunk_id": index,
                    "total_chunks": total_chunks,
                    "expected_paragraphs": len(chunk_paragraphs),
                    "attempt_count": attempt_count,
                    "retry_count": retry_count,
                    "retry_reasons": retry_reasons,
                    "status": "success",
                }
            )
            self._emit_progress(
                on_progress,
                {
                    "event": "chunk_succeeded",
                    "chunk_id": index,
                    "total_chunks": total_chunks,
                    "attempt_count": attempt_count,
                    "retry_count": retry_count,
                    "message": f"chunk {index}/{total_chunks} 完成，尝试 {attempt_count} 次，重试 {retry_count} 次。",
                },
            )

        assembled = self._assemble_final_payload(chunk_outputs)
        total_retries = max(total_attempts - total_chunks, 0)
        metrics = {
            "chunk_mode": True,
            "chunk_max_paragraphs": self.chunk_max_paragraphs,
            "total_chunks": total_chunks,
            "total_attempts": total_attempts,
            "total_retries": total_retries,
            "truncated_retries": sum(
                1
                for event in chunk_events
                for reason in event.get("retry_reasons", [])
                if "expected" in str(reason)
            ),
        }
        self._emit_progress(
            on_progress,
            {
                "event": "translator_done",
                "mode": "chunked",
                "total_chunks": total_chunks,
                "total_attempts": total_attempts,
                "total_retries": total_retries,
                "message": (
                    f"翻译完成：{total_chunks} 个分块，"
                    f"总尝试 {total_attempts} 次（重试 {total_retries} 次）。"
                ),
            },
        )
        return {
            "source_url": article.get("url", ""),
            "model": self.client.model,
            "translated_text": json.dumps(assembled, ensure_ascii=False),
            "chunk_metrics": metrics,
            "chunk_events": chunk_events,
        }

    def _run_single_call(
        self,
        article: dict,
        on_progress: Callable[[dict[str, Any]], None] | None = None,
    ) -> dict:
        system_prompt = PROMPT_FILE.read_text(encoding="utf-8")
        source_text = self._compose_source_payload(article)
        user_prompt = (
            "请按系统提示翻译以下文章。仅输出翻译 JSON（包含 paragraphs_en 与 captions）。\n\n"
            f"{source_text}"
        )
        content = self.client.chat(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            temperature=self.temperature,
        )
        self._emit_progress(
            on_progress,
            {
                "event": "translator_done",
                "mode": "single_call",
                "total_chunks": 1,
                "total_attempts": 1,
                "total_retries": 0,
                "message": "翻译完成：单次调用模式。",
            },
        )
        return {
            "source_url": article.get("url", ""),
            "model": self.client.model,
            "translated_text": content,
            "chunk_metrics": {
                "chunk_mode": False,
                "chunk_max_paragraphs": self.chunk_max_paragraphs,
                "total_chunks": 1,
                "total_attempts": 1,
                "total_retries": 0,
                "truncated_retries": 0,
            },
            "chunk_events": [],
        }

    def _chat_chunk_with_retry(
        self,
        system_prompt: str,
        user_prompt: str,
        expected_paragraphs: int,
        chunk_id: int,
        total_chunks: int,
        include_meta: bool,
        on_progress: Callable[[dict[str, Any]], None] | None = None,
    ) -> tuple[dict[str, Any], int, int, list[str]]:
        last_error: Exception | None = None
        retry_reasons: list[str] = []
        for attempt in range(self.chunk_parse_retries + 1):
            prompt = user_prompt
            if attempt > 0:
                prompt = (
                    f"{user_prompt}\n\n"
                    "上一次输出不是合法或完整 JSON。请严格只输出一个 JSON 对象，"
                    "并确保 paragraphs_en 数量与输入段落数完全一致。"
                )
            raw = self.client.chat(
                system_prompt=system_prompt,
                user_prompt=prompt,
                temperature=self.temperature,
            )
            try:
                parsed = self._parse_chunk_output(
                    raw=raw,
                    expected_paragraphs=expected_paragraphs,
                    chunk_id=chunk_id,
                    total_chunks=total_chunks,
                    include_meta=include_meta,
                )
                return parsed, attempt + 1, attempt, retry_reasons
            except ValueError as exc:
                last_error = exc
                retry_reasons.append(str(exc))
                if attempt < self.chunk_parse_retries:
                    self._emit_progress(
                        on_progress,
                        {
                            "event": "chunk_retry",
                            "chunk_id": chunk_id,
                            "total_chunks": total_chunks,
                            "attempt": attempt + 1,
                            "next_attempt": attempt + 2,
                            "reason": str(exc),
                            "message": (
                                f"chunk {chunk_id}/{total_chunks} 第 {attempt + 1} 次输出异常，"
                                f"准备重试：{exc}"
                            ),
                        },
                    )
        raise RuntimeError(
            f"translator chunk {chunk_id}/{total_chunks} 输出不合法或被截断: {last_error}"
        )

    @staticmethod
    def _parse_chunk_output(
        raw: str,
        expected_paragraphs: int,
        chunk_id: int,
        total_chunks: int,
        include_meta: bool,
    ) -> dict[str, Any]:
        parsed = TranslateStage._extract_json_object(raw)
        if not isinstance(parsed, dict):
            raise ValueError("chunk response is not a JSON object")

        translation = parsed.get("translation", {})
        if not isinstance(translation, dict):
            raise ValueError("missing translation object")
        paragraphs_en = TranslateStage._as_string_list(translation.get("paragraphs_en", []))
        if len(paragraphs_en) != expected_paragraphs:
            raise ValueError(
                f"expected {expected_paragraphs} paragraphs, got {len(paragraphs_en)}"
            )

        normalized: dict[str, Any] = {
            "chunk_id": chunk_id,
            "total_chunks": total_chunks,
            "paragraphs_en": paragraphs_en,
            "title_en": "",
            "published_at": "",
            "author_en": "",
            "translated_captions": [],
        }
        if include_meta:
            normalized["title_en"] = str(translation.get("title_en", "")).strip()
            normalized["published_at"] = str(translation.get("published_at", "")).strip()
            normalized["author_en"] = str(translation.get("author_en", "")).strip()
            captions = parsed.get("captions", {})
            if isinstance(captions, dict):
                normalized["translated_captions"] = TranslateStage._as_string_list(
                    captions.get("translated_captions", [])
                )
        return normalized

    @staticmethod
    def _assemble_final_payload(chunks: list[dict[str, Any]]) -> dict[str, Any]:
        sorted_chunks = sorted(chunks, key=lambda item: int(item.get("chunk_id", 0)))
        paragraphs_en: list[str] = []
        title_en = ""
        published_at = ""
        author_en = ""
        translated_captions: list[str] = []
        for chunk in sorted_chunks:
            paragraphs_en.extend(TranslateStage._as_string_list(chunk.get("paragraphs_en", [])))
            if int(chunk.get("chunk_id", 0)) == 1:
                title_en = str(chunk.get("title_en", "")).strip()
                published_at = str(chunk.get("published_at", "")).strip()
                author_en = str(chunk.get("author_en", "")).strip()
                translated_captions = TranslateStage._as_string_list(
                    chunk.get("translated_captions", [])
                )

        full_text_en = "\n\n".join(paragraphs_en).strip()
        return {
            "schema_version": "1.1",
            "thought": {
                "summary": f"Translated in {len(sorted_chunks)} chunk(s) with stable assembly.",
            },
            "translation": {
                "title_en": title_en,
                "published_at": published_at,
                "author_en": author_en,
                "paragraphs_en": paragraphs_en,
                "full_text_en": full_text_en,
            },
            "captions": {"translated_captions": translated_captions},
        }

    @staticmethod
    def _compose_source_payload(article: dict) -> str:
        payload = {
            "title": article.get("title", ""),
            "published_at": article.get("published_at", ""),
            "author": article.get("author", ""),
            "paragraphs": article.get("body_paragraphs", []),
            "captions": article.get("captions", []),
        }
        return json.dumps(payload, ensure_ascii=False, indent=2)

    @staticmethod
    def _compose_chunk_payload(
        article: dict,
        chunk_id: int,
        total_chunks: int,
        chunk_paragraphs: list[str],
        include_meta: bool,
    ) -> str:
        payload = {
            "chunk_id": chunk_id,
            "total_chunks": total_chunks,
            "title": article.get("title", "") if include_meta else "",
            "published_at": article.get("published_at", "") if include_meta else "",
            "author": article.get("author", "") if include_meta else "",
            "paragraphs": chunk_paragraphs,
            "captions": article.get("captions", []) if include_meta else [],
        }
        return json.dumps(payload, ensure_ascii=False, indent=2)

    @staticmethod
    def _chunk_paragraphs(paragraphs: list[str], max_per_chunk: int) -> list[list[str]]:
        if max_per_chunk <= 0:
            raise ValueError("max_per_chunk must be positive")
        if not paragraphs:
            return []
        chunks: list[list[str]] = []
        for index in range(0, len(paragraphs), max_per_chunk):
            chunks.append(paragraphs[index : index + max_per_chunk])
        return chunks

    @staticmethod
    def _extract_json_object(raw: str) -> dict[str, Any] | None:
        text = str(raw).strip()
        if not text:
            return None

        if text.startswith("```"):
            lines = text.splitlines()
            if len(lines) >= 3 and lines[0].startswith("```") and lines[-1].strip() == "```":
                text = "\n".join(lines[1:-1]).strip()

        decoder = json.JSONDecoder()
        brace_positions = [pos for pos, char in enumerate(text) if char == "{"]
        if not brace_positions:
            return None

        for pos in brace_positions:
            try:
                obj, _ = decoder.raw_decode(text[pos:])
            except json.JSONDecodeError:
                continue
            if isinstance(obj, dict):
                return obj
        return None

    @staticmethod
    def _as_string_list(value: Any) -> list[str]:
        if not isinstance(value, list):
            return []
        return [str(item).strip() for item in value if str(item).strip()]

    @staticmethod
    def _emit_progress(
        callback: Callable[[dict[str, Any]], None] | None,
        payload: dict[str, Any],
    ) -> None:
        if callback:
            callback(payload)

