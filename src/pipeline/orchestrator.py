from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any
import uuid
from zoneinfo import ZoneInfo

from config.settings import Settings
from formatter.byline_resolver import (
    fallback_short_title,
    needs_title_shorten,
    resolve_bylines,
    safe_docx_name,
)
from formatter.docx_formatter import DocxFormatter
from revisor.revision_stage import RevisionStage
from scraper.bastille_scraper import BastilleScraper
from storage.firebase_storage_client import FirebaseStorageClient
from storage.repositories import RunRepository
from translator.siliconflow_client import SiliconFlowClient
from translator.translate_stage import TranslateStage
from verifier.verify_stage import VerifyStage


class PipelineOrchestrator:
    STEP_NAMES = ("scrape", "translate", "verify", "revise", "format", "upload")

    def __init__(self):
        self.settings = Settings.load()
        self.scraper = BastilleScraper()
        self.client = SiliconFlowClient(
            api_key=self.settings.siliconflow_api_key,
            base_url=self.settings.siliconflow_base_url,
            model=self.settings.siliconflow_model,
            timeout=self.settings.siliconflow_timeout_seconds,
            max_retries=self.settings.siliconflow_max_retries,
        )
        self.translator = TranslateStage(
            self.client,
            temperature=self.settings.siliconflow_temperature,
            chunk_enabled=self.settings.translator_chunk_enabled,
            chunk_max_paragraphs=self.settings.translator_chunk_max_paragraphs,
        )
        self.revisor = RevisionStage(self.client)
        self.verifier = VerifyStage(self.client, temperature=self.settings.siliconflow_temperature)
        self.formatter = DocxFormatter()
        self.repo = RunRepository(
            FirebaseStorageClient(bucket_name=self.settings.firebase_storage_bucket)
        )

    def run(self, url: str, output_dir: str | Path = "outputs") -> dict:
        run_id = self._new_run_id()
        started_at = self._utc_now()
        date_key = started_at.strftime("%Y%m%d")
        run_log = self._init_run_log(run_id=run_id, date_key=date_key, url=url, started_at=started_at)

        result: dict[str, Any] | None = None
        active_step: str | None = None
        active_step_started_at: datetime | None = None

        try:
            active_step = "scrape"
            active_step_started_at = self._step_running(run_log, active_step)
            scraped = self.scraper.scrape(url).to_dict()
            raw_article_uri = self.repo.save_raw_article(run_id, scraped)
            run_log["artifacts"]["raw_article_uri"] = raw_article_uri
            self._step_success(run_log, active_step, active_step_started_at)
            active_step = None

            active_step = "translate"
            active_step_started_at = self._step_running(run_log, active_step)
            translated = self.translator.run(scraped)
            translated_uri = self.repo.save_translation(run_id, translated)
            run_log["artifacts"]["translated_uri"] = translated_uri
            chunk_metrics = translated.get("chunk_metrics", {})
            chunk_events = translated.get("chunk_events", [])
            if isinstance(chunk_metrics, dict) and chunk_metrics:
                translator_metrics_uri = self.repo.save_log(
                    run_id, "translator_chunk_metrics", chunk_metrics
                )
                run_log["artifacts"]["translator_chunk_metrics_uri"] = translator_metrics_uri
            if isinstance(chunk_events, list) and chunk_events:
                translator_events_uri = self.repo.save_log(
                    run_id, "translator_chunk_events", {"events": chunk_events}
                )
                run_log["artifacts"]["translator_chunk_events_uri"] = translator_events_uri
            self._step_success(run_log, active_step, active_step_started_at)
            active_step = None

            active_step = "verify"
            active_step_started_at = self._step_running(run_log, active_step)
            verifier_output = self.verifier.run(scraped, translated)
            name_questions_uri = self.repo.save_log(
                run_id, "name_questions", {"questions": self._build_compat_name_questions(verifier_output)}
            )
            verifier_entities_uri = self.repo.save_log(run_id, "verifier_entities", verifier_output)
            run_log["artifacts"]["name_questions_uri"] = name_questions_uri
            run_log["artifacts"]["verifier_entities_uri"] = verifier_entities_uri
            self._step_success(run_log, active_step, active_step_started_at)
            active_step = None

            active_step = "revise"
            active_step_started_at = self._step_running(run_log, active_step)
            revised = self.revisor.run(scraped, translated, verifier_output)
            revision_outline = revised.get("revision_outline")
            if isinstance(revision_outline, dict) and revision_outline:
                outline_uri = self.repo.save_log(run_id, "revision_outline", revision_outline)
                run_log["artifacts"]["revision_outline_uri"] = outline_uri
            revised_uri = self.repo.save_revision(run_id, revised)
            run_log["artifacts"]["revised_uri"] = revised_uri
            self._step_success(run_log, active_step, active_step_started_at)
            active_step = None

            active_step = "format"
            active_step_started_at = self._step_running(run_log, active_step)
            revision_block = revised.get("revision", {})
            if not isinstance(revision_block, dict):
                revision_block = {}
            translated_meta = self._extract_translated_meta(translated)
            byline = resolve_bylines(
                scraped_author=str(scraped.get("author", "")),
                scraped_title=str(scraped.get("title", "")),
            )
            title_en = str(revision_block.get("title_revised_en", "")).strip() or str(
                translated_meta.get("title_en", "")
            ).strip()
            if not title_en:
                title_en = str(scraped.get("title", "")).strip()
            title_en = self._shorten_title_if_needed(title_en)
            filename = safe_docx_name(title=title_en, fallback=run_id)
            output_file = Path(output_dir) / filename
            self.formatter.build(
                output_path=output_file,
                title_en=title_en,
                header_byline_en=byline.get("header_line_en", ""),
                body_blocks=self._build_formatter_body_blocks(scraped, revised),
                ending_author_en=byline.get("ending_author_en", ""),
                ending_column_en=byline.get("ending_column_en", ""),
                captions_blocks=self._build_formatter_captions(scraped, revised),
            )
            run_log["artifacts"]["docx_local_path"] = str(output_file)
            self._step_success(run_log, active_step, active_step_started_at)
            active_step = None

            active_step = "upload"
            active_step_started_at = self._step_running(run_log, active_step)
            docx_uri = self.repo.save_output_docx(run_id, str(output_file))
            run_log["artifacts"]["docx_cloud_path"] = docx_uri
            self._step_success(run_log, active_step, active_step_started_at)
            active_step = None

            run_log["overall_status"] = "success"
            result = {
                "run_id": run_id,
                "docx_local_path": str(output_file),
                "docx_cloud_path": docx_uri,
                "name_questions": self._build_compat_name_questions(verifier_output),
                "verifier": verifier_output,
            }
        except Exception as exc:
            if active_step and active_step_started_at:
                self._step_failed(run_log, active_step, active_step_started_at, exc)
            self._mark_pending_steps_as_skipped(run_log)
            run_log["overall_status"] = "failed"
            raise
        finally:
            ended_at = self._utc_now()
            run_log["ended_at"] = ended_at.isoformat()
            run_log_uri = self.repo.save_run_log(date_key=date_key, run_id=run_id, payload=run_log)
            if result is not None:
                result["run_log_cloud_path"] = run_log_uri

        return result

    @staticmethod
    def _new_run_id(source_title: str = "") -> str:
        ts = datetime.now(tz=ZoneInfo("Asia/Hong_Kong")).strftime("%Y%m%d%H%M%S")
        prefix = "".join(
            ch
            for ch in str(source_title).strip()
            if ch not in '<>:"/\\|?*' and (ch.isalnum() or ("\u4e00" <= ch <= "\u9fff"))
        )[:6]
        if not prefix:
            prefix = "untitl"
        return f"{prefix}_{ts}_{uuid.uuid4().hex[:8]}"

    @staticmethod
    def _utc_now() -> datetime:
        return datetime.now(tz=timezone.utc)

    def _init_run_log(
        self, run_id: str, date_key: str, url: str, started_at: datetime
    ) -> dict[str, Any]:
        steps = {
            name: {
                "status": "pending",
                "started_at": None,
                "ended_at": None,
                "duration_ms": None,
                "error": None,
            }
            for name in self.STEP_NAMES
        }
        return {
            "run_id": run_id,
            "date_key": date_key,
            "url": url,
            "started_at": started_at.isoformat(),
            "ended_at": None,
            "overall_status": "running",
            "steps": steps,
            "artifacts": {
                "raw_article_uri": None,
                "translated_uri": None,
                "name_questions_uri": None,
                "verifier_entities_uri": None,
                "revision_outline_uri": None,
                "revised_uri": None,
                "docx_local_path": None,
                "docx_cloud_path": None,
            },
        }

    def _step_running(self, run_log: dict[str, Any], step_name: str) -> datetime:
        started_at = self._utc_now()
        step = run_log["steps"][step_name]
        step["status"] = "running"
        step["started_at"] = started_at.isoformat()
        return started_at

    def _step_success(
        self, run_log: dict[str, Any], step_name: str, started_at: datetime
    ) -> None:
        ended_at = self._utc_now()
        step = run_log["steps"][step_name]
        step["status"] = "success"
        step["ended_at"] = ended_at.isoformat()
        step["duration_ms"] = int((ended_at - started_at).total_seconds() * 1000)

    def _step_failed(
        self, run_log: dict[str, Any], step_name: str, started_at: datetime, err: Exception
    ) -> None:
        ended_at = self._utc_now()
        step = run_log["steps"][step_name]
        step["status"] = "failed"
        step["ended_at"] = ended_at.isoformat()
        step["duration_ms"] = int((ended_at - started_at).total_seconds() * 1000)
        step["error"] = {"type": err.__class__.__name__, "message": str(err)}

    @staticmethod
    def _mark_pending_steps_as_skipped(run_log: dict[str, Any]) -> None:
        for step in run_log["steps"].values():
            if step["status"] == "pending":
                step["status"] = "skipped"

    @staticmethod
    def _build_compat_name_questions(verifier_output: dict[str, Any]) -> list[str]:
        questions: list[str] = []
        paragraph_results = verifier_output.get("paragraph_results", [])
        if not isinstance(paragraph_results, list):
            return questions

        for paragraph in paragraph_results:
            if not isinstance(paragraph, dict):
                continue
            paragraph_id = paragraph.get("paragraph_id", "")
            verified_entities = paragraph.get("verified_entities", [])
            if not isinstance(verified_entities, list):
                continue
            for entity in verified_entities:
                if not isinstance(entity, dict):
                    continue
                entity_zh = str(entity.get("entity_zh", "")).strip()
                entity_en = str(entity.get("entity_en", "")).strip()
                status = "verified" if entity.get("is_verified", False) else "unverified"
                questions.append(f"[p{paragraph_id}] {entity_zh} / {entity_en} -> {status}")
        return questions

    @staticmethod
    def _build_formatter_body_blocks(scraped: dict[str, Any], revised: dict[str, Any]) -> list[str]:
        revision_block = revised.get("revision", {})
        if not isinstance(revision_block, dict):
            revision_block = {}
        revised_paragraphs = PipelineOrchestrator._as_string_list(
            revision_block.get("paragraphs_revised_en", [])
        )
        if not revised_paragraphs:
            revised_paragraphs = PipelineOrchestrator._as_string_list(
                str(revised.get("revised_text", "")).split("\n\n")
            )
        source_paragraphs = PipelineOrchestrator._as_string_list(scraped.get("body_paragraphs", []))
        subtitle_map: dict[int, str] = {}
        for item in revision_block.get("subtitles_en", []):
            if not isinstance(item, dict):
                continue
            subtitle = str(item.get("subtitle", "")).strip()
            if not subtitle:
                continue
            try:
                insert_before = int(item.get("insert_before_paragraph", 0))
            except (TypeError, ValueError):
                continue
            if insert_before > 0:
                subtitle_map[insert_before] = subtitle

        blocks: list[str] = []
        for idx, revised_en in enumerate(revised_paragraphs, start=1):
            if idx in subtitle_map:
                blocks.append(subtitle_map[idx])
            source_zh = source_paragraphs[idx - 1] if idx - 1 < len(source_paragraphs) else ""
            blocks.append(revised_en)
            if source_zh:
                blocks.append(source_zh)
            blocks.append("")
        if blocks:
            while blocks and not blocks[-1].strip():
                blocks.pop()
            return blocks
        fallback = str(revised.get("revised_text", "")).strip()
        return [fallback] if fallback else []

    @staticmethod
    def _build_formatter_captions(scraped: dict[str, Any], revised: dict[str, Any]) -> list[str]:
        revision_block = revised.get("revision", {})
        if isinstance(revision_block, dict):
            revised_captions = PipelineOrchestrator._as_string_list(
                revision_block.get("captions_revised_en", [])
            )
            if revised_captions:
                return revised_captions
        return PipelineOrchestrator._as_string_list(scraped.get("captions", []))

    @staticmethod
    def _as_string_list(value: Any) -> list[str]:
        if not isinstance(value, list):
            return []
        return [str(item).strip() for item in value if str(item).strip()]

    @staticmethod
    def _extract_translated_meta(translated: dict[str, Any]) -> dict[str, str]:
        raw = str(translated.get("translated_text", "")).strip()
        if not raw:
            return {"title_en": "", "author_en": ""}
        try:
            payload = TranslateStage._extract_json_object(raw)  # pylint: disable=protected-access
        except Exception:
            payload = None
        if not isinstance(payload, dict):
            return {"title_en": "", "author_en": ""}
        translation = payload.get("translation", {})
        if not isinstance(translation, dict):
            return {"title_en": "", "author_en": ""}
        return {
            "title_en": str(translation.get("title_en", "")).strip(),
            # byline is mapping-driven from scraped metadata; do not trust LLM author text.
            "author_en": "",
        }

    def _shorten_title_if_needed(self, title_en: str) -> str:
        title = str(title_en).strip()
        if not needs_title_shorten(title, max_words=10):
            return title
        try:
            prompt = (
                "Rewrite the following article title to be shorter and punchier.\n"
                "Constraints:\n"
                "- Keep the original stance and key meaning.\n"
                "- Output ONE line only.\n"
                "- Maximum 10 words.\n\n"
                f"Title: {title}"
            )
            shorter = str(
                self.client.chat(
                    system_prompt="You write concise, punchy English news headlines.",
                    user_prompt=prompt,
                    temperature=self.settings.siliconflow_temperature,
                )
            ).strip()
            shorter = shorter.replace('"', "").replace("'", "").strip()
            if shorter and not needs_title_shorten(shorter, max_words=10):
                return shorter
        except Exception:
            pass
        return fallback_short_title(title, max_words=10)

