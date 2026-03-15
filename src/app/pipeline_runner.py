from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
import os
import traceback
from typing import Callable

from app.mock_pipeline import (
    build_mock_docx,
    build_mock_name_questions,
    build_mock_revised,
    build_mock_scraped,
    build_mock_translated,
    new_mock_run_id,
)
from app.ui_state import STAGE_ORDER, make_empty_stage_states
from config.settings import SettingsError
from formatter.docx_formatter import DocxFormatter
from revisor.revision_stage import RevisionStage
from scraper.bastille_scraper import BastilleScraper
from storage.firebase_storage_client import FirebaseStorageClient
from storage.repositories import RunRepository
from translator.siliconflow_client import SiliconFlowClient
from translator.translate_stage import TranslateStage
from verifier.name_extractor import NameExtractor


@dataclass
class RunnerOptions:
    mode: str = "mock"  # "mock" | "real" | "hybrid"
    use_real_scraper: bool = False
    use_real_llm: bool = False
    use_real_storage: bool = False
    mock_fail_stage: str = ""


class PipelineRunner:
    def run_full(
        self,
        url: str,
        output_dir: str | Path,
        options: RunnerOptions,
        on_stage_update: Callable[[str, str, str], None] | None = None,
        run_until_stage: str | None = None,
    ) -> dict:
        if not url.strip():
            raise ValueError("URL 不能为空。")

        run_id = new_mock_run_id()
        stage_states = make_empty_stage_states()
        stage_outputs: dict = {}
        artifacts: dict = {}
        error: dict | None = None
        should_stop_after = run_until_stage if run_until_stage in STAGE_ORDER else None

        def emit(stage: str, status: str, detail: str) -> None:
            stage_states[stage] = {"status": status, "detail": detail}
            if on_stage_update:
                on_stage_update(stage, status, detail)

        try:
            scraped = self._run_scraper(url, options, emit)
            stage_outputs["scraped"] = scraped
            self._maybe_stop("scraper", should_stop_after, stage_states)

            translated = self._run_translator(scraped, options, emit)
            stage_outputs["translated"] = translated
            self._maybe_stop("translator", should_stop_after, stage_states)

            questions = self._run_verifier(scraped, translated, emit, options.mock_fail_stage)
            stage_outputs["name_questions"] = questions
            self._maybe_stop("verifier", should_stop_after, stage_states)

            revised = self._run_revisor(scraped, translated, options, emit)
            stage_outputs["revised"] = revised
            self._maybe_stop("revisor", should_stop_after, stage_states)

            output_file = self._run_formatter(
                run_id, output_dir, scraped, revised, emit, options.mock_fail_stage
            )
            artifacts["docx_local_path"] = str(output_file)
            self._maybe_stop("formatter", should_stop_after, stage_states)

            cloud_path = self._run_storage(
                run_id, scraped, translated, revised, questions, output_file, options, emit
            )
            artifacts["docx_cloud_path"] = cloud_path
        except StopIteration:
            pass
        except Exception as err:  # pragma: no cover - UI fallback
            failed_stage = self._first_running_stage(stage_states)
            if failed_stage:
                emit(failed_stage, "failed", str(err))
            error = {
                "stage": failed_stage or "unknown",
                "message": str(err),
                "traceback": traceback.format_exc(),
            }

        ok = error is None
        return {
            "ok": ok,
            "mode": options.mode,
            "run_id": run_id,
            "stage_states": stage_states,
            "stage_outputs": stage_outputs,
            "artifacts": artifacts,
            "error": error,
            "finished_at": datetime.utcnow().isoformat(),
            "result": {
                "run_id": run_id,
                "docx_local_path": artifacts.get("docx_local_path", ""),
                "docx_cloud_path": artifacts.get("docx_cloud_path", ""),
                "name_questions": stage_outputs.get("name_questions", []),
            },
        }

    @staticmethod
    def _maybe_fail(stage: str, fail_stage: str) -> None:
        if fail_stage and stage == fail_stage:
            raise RuntimeError(f"Mock 注入失败：{stage} 阶段故意失败。")

    @staticmethod
    def _maybe_stop(current_stage: str, run_until_stage: str | None, stage_states: dict) -> None:
        if run_until_stage and current_stage == run_until_stage:
            for stage in STAGE_ORDER[STAGE_ORDER.index(current_stage) + 1 :]:
                stage_states[stage] = {"status": "pending", "detail": "尚未执行"}
            raise StopIteration

    @staticmethod
    def _first_running_stage(stage_states: dict[str, dict[str, str]]) -> str | None:
        for stage in STAGE_ORDER:
            if stage_states.get(stage, {}).get("status") == "running":
                return stage
        return None

    def _run_scraper(self, url: str, options: RunnerOptions, emit: Callable) -> dict:
        emit("scraper", "running", "正在抓取文章...")
        self._maybe_fail("scraper", options.mock_fail_stage)
        if options.use_real_scraper:
            scraped = BastilleScraper().scrape(url).to_dict()
            emit("scraper", "success", "真实抓取完成")
            return scraped
        scraped = build_mock_scraped(url)
        emit("scraper", "mocked", "使用 mock 抓取数据")
        return scraped

    def _run_translator(self, scraped: dict, options: RunnerOptions, emit: Callable) -> dict:
        emit("translator", "running", "正在进行首轮翻译...")
        self._maybe_fail("translator", options.mock_fail_stage)
        if options.use_real_llm:
            env = self._load_runtime_env()
            self._validate_llm_env(env)
            client = SiliconFlowClient(
                api_key=env["SILICONFLOW_API_KEY"],
                base_url=env["SILICONFLOW_BASE_URL"],
                model=env["SILICONFLOW_MODEL"],
            )
            translated = TranslateStage(client).run(scraped)
            emit("translator", "success", "真实 LLM 翻译完成")
            return translated
        translated = build_mock_translated(scraped)
        emit("translator", "mocked", "使用 mock 翻译结果")
        return translated

    def _run_verifier(
        self, scraped: dict, translated: dict, emit: Callable, fail_stage: str
    ) -> list[str]:
        emit("verifier", "running", "正在生成人名核对问题...")
        self._maybe_fail("verifier", fail_stage)
        original_text = "\n".join(scraped.get("body_paragraphs", []))
        translated_text = translated.get("translated_text", "")
        questions = NameExtractor().extract_questions(
            original_text=original_text, translated_text=translated_text
        )
        if not questions:
            questions = build_mock_name_questions()
        emit("verifier", "success", f"生成 {len(questions)} 条问题")
        return questions

    def _run_revisor(self, scraped: dict, translated: dict, options: RunnerOptions, emit: Callable) -> dict:
        emit("revisor", "running", "正在进行二轮润色...")
        self._maybe_fail("revisor", options.mock_fail_stage)
        if options.use_real_llm:
            env = self._load_runtime_env()
            self._validate_llm_env(env)
            client = SiliconFlowClient(
                api_key=env["SILICONFLOW_API_KEY"],
                base_url=env["SILICONFLOW_BASE_URL"],
                model=env["SILICONFLOW_MODEL"],
            )
            revised = RevisionStage(client).run(scraped, translated)
            revised["placeholder_note"] = "长度控制逻辑已预留，当前仍由下游后端完善。"
            emit("revisor", "success", "真实 LLM 润色完成")
            return revised
        revised = build_mock_revised(scraped, translated)
        emit("revisor", "mocked", "使用 mock 润色结果")
        return revised

    def _run_formatter(
        self,
        run_id: str,
        output_dir: str | Path,
        scraped: dict,
        revised: dict,
        emit: Callable,
        fail_stage: str,
    ) -> Path:
        emit("formatter", "running", "正在生成 docx...")
        self._maybe_fail("formatter", fail_stage)
        if revised.get("model", "").startswith("mock-"):
            output_file = build_mock_docx(output_dir, run_id, scraped, revised)
            emit("formatter", "mocked", "使用 mock 文本生成 docx")
            return output_file
        output_file = Path(output_dir) / f"{run_id}.docx"
        DocxFormatter().build(
            output_path=output_file,
            title_en=f"{scraped.get('title', '')}",
            author_en=scraped.get("author", ""),
            body_blocks=[revised.get("revised_text", "")],
            ending_author_zh=scraped.get("author", ""),
            captions_blocks=scraped.get("captions", []),
        )
        emit("formatter", "success", "docx 已生成")
        return output_file

    def _run_storage(
        self,
        run_id: str,
        scraped: dict,
        translated: dict,
        revised: dict,
        questions: list[str],
        output_file: Path,
        options: RunnerOptions,
        emit: Callable,
    ) -> str:
        emit("storage", "running", "正在归档结果...")
        self._maybe_fail("storage", options.mock_fail_stage)
        if options.use_real_storage:
            env = self._load_runtime_env()
            self._validate_storage_env(env)
            repo = RunRepository(FirebaseStorageClient(bucket_name=env["FIREBASE_STORAGE_BUCKET"]))
            repo.save_raw_article(run_id, scraped)
            repo.save_translation(run_id, translated)
            repo.save_log(run_id, "name_questions", {"questions": questions})
            repo.save_revision(run_id, revised)
            cloud_path = repo.save_output_docx(run_id, str(output_file))
            emit("storage", "success", "已上传到 Firebase Storage")
            return cloud_path
        cloud_path = f"gs://mock-bucket/runs/{run_id}/output/final.docx"
        emit("storage", "mocked", "使用 mock 云端路径")
        return cloud_path

    @staticmethod
    def _load_runtime_env() -> dict[str, str]:
        return {
            "SILICONFLOW_API_KEY": os.getenv("SILICONFLOW_API_KEY", "").strip(),
            "SILICONFLOW_BASE_URL": os.getenv("SILICONFLOW_BASE_URL", "https://api.siliconflow.cn/v1").strip(),
            "SILICONFLOW_MODEL": os.getenv("SILICONFLOW_MODEL", "deepseek-r1").strip(),
            "FIREBASE_STORAGE_BUCKET": os.getenv("FIREBASE_STORAGE_BUCKET", "").strip(),
            "GOOGLE_APPLICATION_CREDENTIALS": os.getenv("GOOGLE_APPLICATION_CREDENTIALS", "").strip(),
        }

    @staticmethod
    def _validate_llm_env(env: dict[str, str]) -> None:
        missing = []
        if not env["SILICONFLOW_API_KEY"]:
            missing.append("SILICONFLOW_API_KEY")
        if missing:
            raise SettingsError(f"真实翻译模式缺少环境变量: {', '.join(missing)}")

    @staticmethod
    def _validate_storage_env(env: dict[str, str]) -> None:
        missing = []
        if not env["FIREBASE_STORAGE_BUCKET"]:
            missing.append("FIREBASE_STORAGE_BUCKET")
        if not env["GOOGLE_APPLICATION_CREDENTIALS"]:
            missing.append("GOOGLE_APPLICATION_CREDENTIALS")
        if missing:
            raise SettingsError(f"真实存储模式缺少环境变量: {', '.join(missing)}")

