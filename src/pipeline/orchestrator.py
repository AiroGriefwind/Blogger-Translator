from __future__ import annotations

from datetime import datetime
from pathlib import Path
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
            self.client, temperature=self.settings.siliconflow_temperature
        )
        self.revisor = RevisionStage(self.client)
        self.name_extractor = NameExtractor()
        self.formatter = DocxFormatter()
        self.repo = RunRepository(
            FirebaseStorageClient(bucket_name=self.settings.firebase_storage_bucket)
        )

    def run(self, url: str, output_dir: str | Path = "outputs") -> dict:
        run_id = self._new_run_id()
        scraped = self.scraper.scrape(url).to_dict()
        self.repo.save_raw_article(run_id, scraped)

        translated = self.translator.run(scraped)
        self.repo.save_translation(run_id, translated)

        original_text = "\n".join(scraped.get("body_paragraphs", []))
        name_questions = self.name_extractor.extract_questions(
            original_text=original_text,
            translated_text=translated.get("translated_text", ""),
        )
        self.repo.save_log(run_id, "name_questions", {"questions": name_questions})

        revised = self.revisor.run(scraped, translated)
        self.repo.save_revision(run_id, revised)

        output_file = Path(output_dir) / f"{run_id}.docx"
        self.formatter.build(
            output_path=output_file,
            title_en=f"{scraped.get('title', '')}",
            author_en=scraped.get("author", ""),
            body_blocks=[revised.get("revised_text", "")],
            ending_author_zh=scraped.get("author", ""),
            captions_blocks=scraped.get("captions", []),
        )
        docx_uri = self.repo.save_output_docx(run_id, str(output_file))
        return {
            "run_id": run_id,
            "docx_local_path": str(output_file),
            "docx_cloud_path": docx_uri,
            "name_questions": name_questions,
        }

    @staticmethod
    def _new_run_id() -> str:
        ts = datetime.utcnow().strftime("%Y%m%d%H%M%S")
        return f"{ts}_{uuid.uuid4().hex[:8]}"

