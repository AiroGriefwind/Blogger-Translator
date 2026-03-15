from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any
import uuid

from config.settings import Settings
from formatter.docx_formatter import DocxFormatter
from revisor.revision_stage import RevisionStage
from scraper.bastille_scraper import BastilleScraper
from storage.firebase_storage_client import FirebaseStorageClient
from storage.repositories import RunRepository
from translator.siliconflow_client import SiliconFlowClient
from translator.translate_stage import TranslateStage
from verifier.name_extractor import NameExtractor


class PipelineOrchestrator:
    STEP_NAMES = ("scrape", "translate", "verify", "revise", "format", "upload")

    def __init__(self):
        self.settings = Settings.load()
        self.scraper = BastilleScraper()
        self.client = SiliconFlowClient(
            api_key=self.settings.siliconflow_api_key,
            base_url=self.settings.siliconflow_base_url,
            model=self.settings.siliconflow_model,
        )
        self.translator = TranslateStage(self.client)
        self.revisor = RevisionStage(self.client)
        self.name_extractor = NameExtractor()
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
            self._step_success(run_log, active_step, active_step_started_at)
            active_step = None

            active_step = "verify"
            active_step_started_at = self._step_running(run_log, active_step)
            original_text = "\n".join(scraped.get("body_paragraphs", []))
            name_questions = self.name_extractor.extract_questions(
                original_text=original_text,
                translated_text=translated.get("translated_text", ""),
            )
            name_questions_uri = self.repo.save_log(
                run_id, "name_questions", {"questions": name_questions}
            )
            run_log["artifacts"]["name_questions_uri"] = name_questions_uri
            self._step_success(run_log, active_step, active_step_started_at)
            active_step = None

            active_step = "revise"
            active_step_started_at = self._step_running(run_log, active_step)
            revised = self.revisor.run(scraped, translated)
            revised_uri = self.repo.save_revision(run_id, revised)
            run_log["artifacts"]["revised_uri"] = revised_uri
            self._step_success(run_log, active_step, active_step_started_at)
            active_step = None

            active_step = "format"
            active_step_started_at = self._step_running(run_log, active_step)
            output_file = Path(output_dir) / f"{run_id}.docx"
            self.formatter.build(
                output_path=output_file,
                title_en=f"{scraped.get('title', '')}",
                author_en=scraped.get("author", ""),
                body_blocks=[revised.get("revised_text", "")],
                ending_author_zh=scraped.get("author", ""),
                captions_blocks=scraped.get("captions", []),
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
                "name_questions": name_questions,
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
    def _new_run_id() -> str:
        ts = datetime.utcnow().strftime("%Y%m%d%H%M%S")
        return f"{ts}_{uuid.uuid4().hex[:8]}"

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

