from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
import os
import traceback
from time import strftime
from typing import Callable
from copy import deepcopy

from app.mock_pipeline import (
    build_mock_docx,
    build_mock_name_questions,
    build_mock_verifier_output,
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
from verifier.verify_stage import VerifyStage
from verifier.synonym_review_stage import SynonymReviewStage


@dataclass
class RunnerOptions:
    mode: str = "mock"  # "mock" | "real" | "hybrid"
    use_real_scraper: bool = False
    use_real_llm: bool = False
    use_real_storage: bool = False
    use_entity_db_lookup: bool = True
    mock_fail_stage: str = ""
    llm_model: str = ""


class PipelineRunner:
    def run_full(
        self,
        url: str,
        output_dir: str | Path,
        options: RunnerOptions,
        on_stage_update: Callable[[str, str, str], None] | None = None,
        on_verifier_progress: Callable[[dict], None] | None = None,
        on_translator_progress: Callable[[dict], None] | None = None,
        run_until_stage: str | None = None,
    ) -> dict:
        if not url.strip():
            raise ValueError("URL 不能为空。")

        run_id = new_mock_run_id()
        stage_states = make_empty_stage_states()
        stage_outputs: dict = {}
        artifacts: dict = {}
        error: dict | None = None
        runtime = {
            "verify_progress": {"done": 0, "total": 0, "percent": 0.0},
            "translator_progress": {
                "total_chunks": 0,
                "current_chunk": 0,
                "total_retries": 0,
            },
            "logs": [],
        }
        should_stop_after = run_until_stage if run_until_stage in STAGE_ORDER else None

        def emit(stage: str, status: str, detail: str) -> None:
            stage_states[stage] = {"status": status, "detail": detail}
            if on_stage_update:
                on_stage_update(stage, status, detail)
            runtime["logs"].append(
                {"time": strftime("%H:%M:%S"), "stage": stage, "message": f"[{status}] {detail}"}
            )

        def emit_verifier_progress(payload: dict) -> None:
            done = int(payload.get("done_paragraphs", 0))
            total = int(payload.get("total_paragraphs", 0))
            percent = float(payload.get("percent", 0.0))
            runtime["verify_progress"] = {"done": done, "total": total, "percent": percent}
            runtime["logs"].append(
                {
                    "time": strftime("%H:%M:%S"),
                    "stage": "verifier",
                    "message": str(payload.get("message", "")),
                }
            )
            if on_verifier_progress:
                on_verifier_progress(payload)

        def emit_translator_progress(payload: dict) -> None:
            event = str(payload.get("event", "")).strip()
            if event == "translator_start":
                runtime["translator_progress"]["total_chunks"] = int(payload.get("total_chunks", 0))
                runtime["translator_progress"]["current_chunk"] = 0
                runtime["translator_progress"]["total_retries"] = 0
            elif event == "chunk_started":
                runtime["translator_progress"]["current_chunk"] = int(payload.get("chunk_id", 0))
            elif event == "chunk_retry":
                runtime["translator_progress"]["total_retries"] = int(
                    runtime["translator_progress"].get("total_retries", 0)
                ) + 1
            elif event == "translator_done":
                runtime["translator_progress"]["total_chunks"] = int(payload.get("total_chunks", 0))

            message = str(payload.get("message", "")).strip()
            if message:
                runtime["logs"].append(
                    {
                        "time": strftime("%H:%M:%S"),
                        "stage": "translator",
                        "message": message,
                    }
                )
            if on_translator_progress:
                on_translator_progress(payload)

        try:
            scraped = self._run_scraper(url, options, emit)
            stage_outputs["scraped"] = scraped
            self._maybe_stop("scraper", should_stop_after, stage_states)

            translated = self._run_translator(
                scraped,
                options,
                emit,
                on_translator_progress=emit_translator_progress,
            )
            stage_outputs["translated"] = translated
            self._maybe_stop("translator", should_stop_after, stage_states)

            verifier_output = self._run_verifier(
                scraped,
                translated,
                options,
                emit,
                emit_verifier_progress,
            )
            stage_outputs["verifier"] = verifier_output
            stage_outputs["name_questions"] = self._build_compat_name_questions(verifier_output)
            self._maybe_stop("verifier", should_stop_after, stage_states)

            revised = self._run_revisor(scraped, translated, verifier_output, options, emit)
            stage_outputs["revised"] = revised
            self._maybe_stop("revisor", should_stop_after, stage_states)

            output_file = self._run_formatter(
                run_id, output_dir, scraped, revised, emit, options.mock_fail_stage
            )
            artifacts["docx_local_path"] = str(output_file)
            self._maybe_stop("formatter", should_stop_after, stage_states)

            cloud_path = self._run_storage(
                run_id, scraped, translated, revised, verifier_output, output_file, options, emit
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
            "runtime": runtime,
            "finished_at": datetime.utcnow().isoformat(),
            "result": {
                "run_id": run_id,
                "docx_local_path": artifacts.get("docx_local_path", ""),
                "docx_cloud_path": artifacts.get("docx_cloud_path", ""),
                "name_questions": stage_outputs.get("name_questions", []),
                "verifier": stage_outputs.get("verifier", {}),
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

    def _run_translator(
        self,
        scraped: dict,
        options: RunnerOptions,
        emit: Callable,
        on_translator_progress: Callable[[dict], None] | None = None,
    ) -> dict:
        emit("translator", "running", "正在进行首轮翻译...")
        self._maybe_fail("translator", options.mock_fail_stage)
        if options.use_real_llm:
            env = self._load_runtime_env(model_override=options.llm_model)
            self._validate_llm_env(env)
            client = SiliconFlowClient(
                api_key=env["SILICONFLOW_API_KEY"],
                base_url=env["SILICONFLOW_BASE_URL"],
                model=env["SILICONFLOW_MODEL"],
                timeout=env["SILICONFLOW_TIMEOUT_SECONDS"],
                max_retries=env["SILICONFLOW_MAX_RETRIES"],
            )
            translated = TranslateStage(
                client,
                temperature=env["SILICONFLOW_TEMPERATURE"],
                chunk_enabled=bool(env["TRANSLATOR_CHUNK_ENABLED"]),
                chunk_max_paragraphs=int(env["TRANSLATOR_CHUNK_MAX_PARAGRAPHS"]),
            ).run(scraped, on_progress=on_translator_progress)
            emit("translator", "success", "真实 LLM 翻译完成")
            return translated
        translated = build_mock_translated(scraped)
        if on_translator_progress:
            on_translator_progress(
                {
                    "event": "translator_done",
                    "mode": "mock",
                    "total_chunks": 1,
                    "total_attempts": 1,
                    "total_retries": 0,
                    "message": "翻译完成：mock 模式。",
                }
            )
        emit("translator", "mocked", "使用 mock 翻译结果")
        return translated

    def _run_verifier(
        self,
        scraped: dict,
        translated: dict,
        options: RunnerOptions,
        emit: Callable,
        on_verifier_progress: Callable[[dict], None] | None = None,
    ) -> dict:
        emit("verifier", "running", "正在执行联网实体核验...")
        self._maybe_fail("verifier", options.mock_fail_stage)
        if options.use_real_llm:
            env = self._load_runtime_env(model_override=options.llm_model)
            self._validate_llm_env(env)
            client = SiliconFlowClient(
                api_key=env["SILICONFLOW_API_KEY"],
                base_url=env["SILICONFLOW_BASE_URL"],
                model=env["SILICONFLOW_MODEL"],
                timeout=env["SILICONFLOW_TIMEOUT_SECONDS"],
                max_retries=env["SILICONFLOW_MAX_RETRIES"],
            )
            repo: RunRepository | None = None
            if options.use_entity_db_lookup:
                self._validate_storage_env(env)
                repo = RunRepository(FirebaseStorageClient(bucket_name=env["FIREBASE_STORAGE_BUCKET"]))

            def lookup_exact(entity: dict) -> dict | None:
                if not repo or not options.use_entity_db_lookup:
                    return None
                return repo.find_entity_by_synonym_set(entity)

            verifier_output = VerifyStage(client, temperature=env["SILICONFLOW_TEMPERATURE"]).run(
                scraped,
                translated,
                on_progress=on_verifier_progress,
                lookup_exact=lookup_exact,
            )
            if options.use_entity_db_lookup:
                verifier_output["entity_db"] = {"write_enabled": False}
            total = int(verifier_output.get("summary", {}).get("total_entities", 0))
            emit("verifier", "success", f"完成联网核验，共处理 {total} 个实体")
            return verifier_output
        verifier_output = build_mock_verifier_output()
        paragraph_results = verifier_output.get("paragraph_results", [])
        total = len(paragraph_results) if isinstance(paragraph_results, list) else 0
        if on_verifier_progress:
            on_verifier_progress(
                {
                    "event": "start",
                    "done_paragraphs": 0,
                    "total_paragraphs": total,
                    "percent": 0.0,
                    "message": f"核验启动，共 {total} 段待处理（mock）",
                }
            )
            for idx, item in enumerate(paragraph_results, start=1):
                pid = item.get("paragraph_id", idx) if isinstance(item, dict) else idx
                on_verifier_progress(
                    {
                        "event": "paragraph_done",
                        "done_paragraphs": idx,
                        "total_paragraphs": total,
                        "paragraph_id": pid,
                        "percent": (idx / total * 100.0) if total else 100.0,
                        "message": f"已完成第 {idx}/{total} 段（段落ID={pid}）（mock）",
                    }
                )
            on_verifier_progress(
                {
                    "event": "done",
                    "done_paragraphs": total,
                    "total_paragraphs": total,
                    "percent": 100.0,
                    "message": f"核验完成，共处理 {total} 段（mock）",
                }
            )
        mock_questions = verifier_output.get("compat_name_questions", build_mock_name_questions())
        emit("verifier", "mocked", f"使用 mock 核验结果（{len(mock_questions)} 条）")
        return verifier_output

    def _run_revisor(
        self,
        scraped: dict,
        translated: dict,
        verifier_output: dict,
        options: RunnerOptions,
        emit: Callable,
    ) -> dict:
        emit("revisor", "running", "正在进行二轮润色...")
        self._maybe_fail("revisor", options.mock_fail_stage)
        if options.use_real_llm:
            env = self._load_runtime_env(model_override=options.llm_model)
            self._validate_llm_env(env)
            client = SiliconFlowClient(
                api_key=env["SILICONFLOW_API_KEY"],
                base_url=env["SILICONFLOW_BASE_URL"],
                model=env["SILICONFLOW_MODEL"],
                timeout=env["SILICONFLOW_TIMEOUT_SECONDS"],
                max_retries=env["SILICONFLOW_MAX_RETRIES"],
            )
            revised = RevisionStage(client).run(scraped, translated, verifier_output)
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
        revision_block = revised.get("revision", {})
        if not isinstance(revision_block, dict):
            revision_block = {}
        DocxFormatter().build(
            output_path=output_file,
            title_en=str(revision_block.get("title_revised_en", "")).strip() or f"{scraped.get('title', '')}",
            author_en=scraped.get("author", ""),
            body_blocks=self._build_formatter_body_blocks(scraped, revised),
            ending_author_zh=scraped.get("author", ""),
            captions_blocks=self._build_formatter_captions(scraped, revised),
        )
        emit("formatter", "success", "docx 已生成")
        return output_file

    def _run_storage(
        self,
        run_id: str,
        scraped: dict,
        translated: dict,
        revised: dict,
        verifier_output: dict,
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
            chunk_metrics = translated.get("chunk_metrics", {})
            chunk_events = translated.get("chunk_events", [])
            if isinstance(chunk_metrics, dict) and chunk_metrics:
                repo.save_log(run_id, "translator_chunk_metrics", chunk_metrics)
            if isinstance(chunk_events, list) and chunk_events:
                repo.save_log(run_id, "translator_chunk_events", {"events": chunk_events})
            repo.save_log(run_id, "verifier_entities", verifier_output)
            repo.save_log(
                run_id,
                "name_questions",
                {"questions": self._build_compat_name_questions(verifier_output)},
            )
            revision_outline = revised.get("revision_outline")
            if isinstance(revision_outline, dict) and revision_outline:
                repo.save_log(run_id, "revision_outline", revision_outline)
            repo.save_revision(run_id, revised)
            cloud_path = repo.save_output_docx(run_id, str(output_file))
            emit("storage", "success", "已上传到 Firebase Storage")
            return cloud_path
        cloud_path = f"gs://mock-bucket/runs/{run_id}/output/final.docx"
        emit("storage", "mocked", "使用 mock 云端路径")
        return cloud_path

    @staticmethod
    def _load_runtime_env(model_override: str = "") -> dict[str, str | int | float | bool]:
        base_url = (
            os.getenv("SILICONFLOW_BASE_URL", "").strip()
            or os.getenv("LLM_BASE_URL", "").strip()
            or os.getenv("MAYNOR_BASE_URL", "").strip()
            or "https://api.siliconflow.cn/v1"
        )
        if "maynor1024.live" in base_url:
            api_key = (
                os.getenv("MAYNOR_API_KEY", "").strip()
                or os.getenv("SILICONFLOW_API_KEY", "").strip()
                or os.getenv("LLM_API_KEY", "").strip()
            )
        else:
            api_key = (
                os.getenv("SILICONFLOW_API_KEY", "").strip()
                or os.getenv("LLM_API_KEY", "").strip()
                or os.getenv("MAYNOR_API_KEY", "").strip()
            )
        model = (
            os.getenv("SILICONFLOW_MODEL", "").strip()
            or os.getenv("LLM_MODEL", "").strip()
            or os.getenv("MAYNOR_MODEL", "").strip()
            or "deepseek-r1"
        )
        if model_override.strip():
            model = model_override.strip()
        timeout_seconds = PipelineRunner._read_int_env(
            "SILICONFLOW_TIMEOUT_SECONDS", "LLM_TIMEOUT_SECONDS", 120
        )
        max_retries = PipelineRunner._read_int_env(
            "SILICONFLOW_MAX_RETRIES", "LLM_MAX_RETRIES", 2
        )
        temperature = PipelineRunner._read_float_env(
            "SILICONFLOW_TEMPERATURE", "LLM_TEMPERATURE", 0.2
        )
        translator_chunk_enabled = PipelineRunner._read_bool_env(
            "TRANSLATOR_CHUNK_ENABLED", True
        )
        translator_chunk_max_paragraphs = PipelineRunner._read_int_env(
            "TRANSLATOR_CHUNK_MAX_PARAGRAPHS", "", 5
        )
        return {
            "SILICONFLOW_API_KEY": api_key,
            "SILICONFLOW_BASE_URL": base_url,
            "SILICONFLOW_MODEL": model,
            "SILICONFLOW_TEMPERATURE": temperature,
            "SILICONFLOW_TIMEOUT_SECONDS": timeout_seconds,
            "SILICONFLOW_MAX_RETRIES": max_retries,
            "TRANSLATOR_CHUNK_ENABLED": translator_chunk_enabled,
            "TRANSLATOR_CHUNK_MAX_PARAGRAPHS": translator_chunk_max_paragraphs,
            "FIREBASE_STORAGE_BUCKET": os.getenv("FIREBASE_STORAGE_BUCKET", "").strip(),
            "GOOGLE_APPLICATION_CREDENTIALS": os.getenv("GOOGLE_APPLICATION_CREDENTIALS", "").strip(),
        }

    @staticmethod
    def _validate_llm_env(env: dict[str, str | int | float]) -> None:
        missing = []
        if not env["SILICONFLOW_API_KEY"]:
            missing.append("SILICONFLOW_API_KEY / LLM_API_KEY / MAYNOR_API_KEY")
        if missing:
            raise SettingsError(f"真实翻译模式缺少环境变量: {', '.join(missing)}")

    @staticmethod
    def _read_int_env(primary_key: str, fallback_key: str, default: int) -> int:
        raw = os.getenv(primary_key, "").strip()
        if not raw and fallback_key:
            raw = os.getenv(fallback_key, "").strip()
        if not raw:
            return default
        try:
            return int(raw)
        except ValueError as exc:
            raise SettingsError(f"{primary_key}/{fallback_key} 必须是整数") from exc

    @staticmethod
    def _read_float_env(primary_key: str, fallback_key: str, default: float) -> float:
        raw = os.getenv(primary_key, "").strip() or os.getenv(fallback_key, "").strip()
        if not raw:
            return default
        try:
            return float(raw)
        except ValueError as exc:
            raise SettingsError(f"{primary_key}/{fallback_key} 必须是数字") from exc

    @staticmethod
    def _read_bool_env(primary_key: str, default: bool) -> bool:
        raw = os.getenv(primary_key, "").strip().lower()
        if not raw:
            return default
        if raw in {"1", "true", "yes", "on"}:
            return True
        if raw in {"0", "false", "no", "off"}:
            return False
        raise SettingsError(f"{primary_key} 必须是布尔值(true/false)")

    @staticmethod
    def _validate_storage_env(env: dict[str, str]) -> None:
        missing = []
        if not env["FIREBASE_STORAGE_BUCKET"]:
            missing.append("FIREBASE_STORAGE_BUCKET")
        if not env["GOOGLE_APPLICATION_CREDENTIALS"]:
            missing.append("GOOGLE_APPLICATION_CREDENTIALS")
        if missing:
            raise SettingsError(f"真实存储模式缺少环境变量: {', '.join(missing)}")

    @staticmethod
    def _build_compat_name_questions(verifier_output: dict) -> list[str]:
        compat = verifier_output.get("compat_name_questions", [])
        if isinstance(compat, list) and compat:
            return [str(item) for item in compat]

        questions: list[str] = []
        paragraph_results = verifier_output.get("paragraph_results", [])
        if not isinstance(paragraph_results, list):
            return questions

        for paragraph in paragraph_results:
            if not isinstance(paragraph, dict):
                continue
            pid = paragraph.get("paragraph_id", "")
            verified_entities = paragraph.get("verified_entities", [])
            if not isinstance(verified_entities, list):
                continue
            for entity in verified_entities:
                if not isinstance(entity, dict):
                    continue
                entity_zh = str(entity.get("entity_zh", "")).strip()
                entity_en = str(entity.get("entity_en", "")).strip()
                status = "verified" if entity.get("is_verified", False) else "unverified"
                questions.append(f"[p{pid}] {entity_zh} / {entity_en} -> {status}")
        return questions

    @staticmethod
    def _build_formatter_body_blocks(scraped: dict, revised: dict) -> list[str]:
        revision_block = revised.get("revision", {})
        if not isinstance(revision_block, dict):
            revision_block = {}
        revised_paragraphs = PipelineRunner._as_string_list(
            revision_block.get("paragraphs_revised_en", [])
        )
        if not revised_paragraphs:
            revised_paragraphs = PipelineRunner._as_string_list(
                str(revised.get("revised_text", "")).split("\n\n")
            )
        source_paragraphs = PipelineRunner._as_string_list(scraped.get("body_paragraphs", []))
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
            pair_lines = [f"译文：{revised_en}"]
            if source_zh:
                pair_lines.append(f"原文：{source_zh}")
            blocks.append("\n".join(pair_lines).strip())
        if blocks:
            return blocks
        fallback = str(revised.get("revised_text", "")).strip()
        return [fallback] if fallback else []

    @staticmethod
    def _build_formatter_captions(scraped: dict, revised: dict) -> list[str]:
        revision_block = revised.get("revision", {})
        if isinstance(revision_block, dict):
            revised_captions = PipelineRunner._as_string_list(
                revision_block.get("captions_revised_en", [])
            )
            if revised_captions:
                return revised_captions
        return PipelineRunner._as_string_list(scraped.get("captions", []))

    @staticmethod
    def _as_string_list(value) -> list[str]:
        if not isinstance(value, list):
            return []
        return [str(item).strip() for item in value if str(item).strip()]

    def write_verified_entities_to_online_db(self, run_id: str, verifier_output: dict) -> dict[str, int]:
        env = self._load_runtime_env()
        self._validate_storage_env(env)
        repo = RunRepository(FirebaseStorageClient(bucket_name=env["FIREBASE_STORAGE_BUCKET"]))
        return repo.upsert_verified_entities(run_id=run_id, verifier_output=verifier_output)

    def list_online_verified_entities(self) -> list[dict]:
        env = self._load_runtime_env()
        self._validate_storage_env(env)
        repo = RunRepository(FirebaseStorageClient(bucket_name=env["FIREBASE_STORAGE_BUCKET"]))
        return repo.list_verified_entities()

    def list_online_all_entities(self) -> list[dict]:
        env = self._load_runtime_env()
        self._validate_storage_env(env)
        repo = RunRepository(FirebaseStorageClient(bucket_name=env["FIREBASE_STORAGE_BUCKET"]))
        return repo.list_all_entities()

    def get_synonym_review_snapshot(self) -> dict:
        env = self._load_runtime_env()
        self._validate_storage_env(env)
        repo = RunRepository(FirebaseStorageClient(bucket_name=env["FIREBASE_STORAGE_BUCKET"]))
        return {
            "state": repo.load_review_state(),
            "results": repo.load_review_results(),
            "pending": repo.load_pending_changes(),
        }

    def run_synonym_review_batch(
        self,
        *,
        language_mode: str,
        category: str,
        llm_model: str = "",
        new_batch_size: int = 20,
        reviewed_batch_size: int = 50,
    ) -> dict:
        env = self._load_runtime_env(model_override=llm_model)
        self._validate_llm_env(env)
        self._validate_storage_env(env)
        repo = RunRepository(FirebaseStorageClient(bucket_name=env["FIREBASE_STORAGE_BUCKET"]))
        state = repo.load_review_state()
        results = repo.load_review_results()
        all_entities = repo.list_all_entities()
        scoped = [item for item in all_entities if str(item.get("type", "")) == category]
        reviewed_field = "synonym_reviewed_zh" if language_mode == "zh" else "synonym_reviewed_en"
        reviewed_entities = [item for item in scoped if bool(item.get(reviewed_field, False))]
        new_entities = [item for item in scoped if not bool(item.get(reviewed_field, False))]

        active = state.get("active", {})
        if not isinstance(active, dict):
            active = {}
        should_reinit = (
            active.get("language_mode") != language_mode
            or active.get("category") != category
            or not isinstance(active.get("new_keys", []), list)
        )
        if should_reinit:
            active = {
                "language_mode": language_mode,
                "category": category,
                "new_keys": [str(item.get("key", "")) for item in new_entities[: max(new_batch_size, 1)]],
                "reviewed_offset": 0,
                "new_offset": max(new_batch_size, 1),
                "new_batch_size": max(new_batch_size, 1),
                "reviewed_batch_size": max(reviewed_batch_size, 1),
            }
        new_keys = [str(item) for item in active.get("new_keys", []) if str(item).strip()]
        if not new_keys:
            return {
                "ok": True,
                "message": "当前分类和语言下没有待审查新词。",
                "state": state,
                "results": results,
            }

        reviewed_offset = int(active.get("reviewed_offset", 0))
        reviewed_batch_size = int(active.get("reviewed_batch_size", reviewed_batch_size))
        reviewed_slice = reviewed_entities[reviewed_offset : reviewed_offset + max(reviewed_batch_size, 1)]
        if not reviewed_slice:
            return {
                "ok": True,
                "message": "已无可比较的已审查词条，请直接进入人工处理。",
                "state": state,
                "results": results,
            }

        key_to_entity = {str(item.get("key", "")): item for item in scoped}
        new_batch = [key_to_entity[key] for key in new_keys if key in key_to_entity]
        stage = SynonymReviewStage(
            SiliconFlowClient(
                api_key=env["SILICONFLOW_API_KEY"],
                base_url=env["SILICONFLOW_BASE_URL"],
                model=env["SILICONFLOW_MODEL"],
                timeout=env["SILICONFLOW_TIMEOUT_SECONDS"],
                max_retries=env["SILICONFLOW_MAX_RETRIES"],
            ),
            temperature=env["SILICONFLOW_TEMPERATURE"],
        )
        stage_output = stage.run(
            language_mode=language_mode,
            category=category,
            new_items=[
                {
                    "id": item.get("key", ""),
                    "entity_zh": item.get("entity_zh", ""),
                    "entity_en": item.get("entity_en", ""),
                    "zh_aliases": item.get("zh_aliases", []),
                    "en_aliases": item.get("en_aliases", []),
                    "type": item.get("type", ""),
                }
                for item in new_batch
            ],
            reviewed_items_batch=[
                {
                    "id": item.get("key", ""),
                    "entity_zh": item.get("entity_zh", ""),
                    "entity_en": item.get("entity_en", ""),
                    "zh_aliases": item.get("zh_aliases", []),
                    "en_aliases": item.get("en_aliases", []),
                    "type": item.get("type", ""),
                }
                for item in reviewed_slice
            ],
            known_synonym_groups=[
                {
                    "id": item.get("key", ""),
                    "zh_aliases": item.get("zh_aliases", []),
                    "en_aliases": item.get("en_aliases", []),
                }
                for item in reviewed_slice
            ],
        )
        result_rows = results.get("results", [])
        if not isinstance(result_rows, list):
            result_rows = []
        result_rows.append(
            {
                "saved_at": datetime.utcnow().isoformat(),
                "language_mode": language_mode,
                "category": category,
                "reviewed_offset": reviewed_offset,
                "reviewed_batch_size": reviewed_batch_size,
                "new_keys": new_keys,
                "output": stage_output,
            }
        )
        results["results"] = result_rows
        repo.save_review_results(results)

        active["reviewed_offset"] = reviewed_offset + len(reviewed_slice)
        current_new_offset = int(active.get("new_offset", len(new_keys)))
        if active["reviewed_offset"] >= len(reviewed_entities):
            next_batch = new_entities[current_new_offset : current_new_offset + max(new_batch_size, 1)]
            active["new_keys"] = [str(item.get("key", "")) for item in next_batch]
            active["new_offset"] = current_new_offset + len(next_batch)
            active["reviewed_offset"] = 0
        active["updated_at"] = datetime.utcnow().isoformat()
        state["active"] = active
        state["language_mode"] = language_mode
        state["category"] = category
        state["new_batch_size"] = int(active.get("new_batch_size", new_batch_size))
        state["reviewed_batch_size"] = reviewed_batch_size
        history = state.get("history", [])
        if not isinstance(history, list):
            history = []
        history.append(
            {
                "saved_at": datetime.utcnow().isoformat(),
                "language_mode": language_mode,
                "category": category,
                "reviewed_offset": active["reviewed_offset"],
                "new_keys": new_keys,
            }
        )
        state["history"] = history[-100:]
        repo.save_review_state(state)
        return {
            "ok": True,
            "message": "已完成一批同义词审查。",
            "state": state,
            "results": results,
            "output": stage_output,
        }

    def add_pending_change(self, item: dict) -> dict:
        env = self._load_runtime_env()
        self._validate_storage_env(env)
        repo = RunRepository(FirebaseStorageClient(bucket_name=env["FIREBASE_STORAGE_BUCKET"]))
        pending = repo.load_pending_changes()
        items = pending.get("items", [])
        if not isinstance(items, list):
            items = []
        new_item = deepcopy(item)
        new_item["status"] = str(new_item.get("status", "pending"))
        new_item["saved_at"] = datetime.utcnow().isoformat()
        items.append(new_item)
        pending["items"] = items
        repo.save_pending_changes(pending)
        return pending

    def remove_pending_change(self, index: int) -> dict:
        env = self._load_runtime_env()
        self._validate_storage_env(env)
        repo = RunRepository(FirebaseStorageClient(bucket_name=env["FIREBASE_STORAGE_BUCKET"]))
        pending = repo.load_pending_changes()
        items = pending.get("items", [])
        if not isinstance(items, list):
            items = []
        if 0 <= index < len(items):
            items.pop(index)
        pending["items"] = items
        repo.save_pending_changes(pending)
        return pending

    def apply_pending_changes_to_online_db(self, run_id: str) -> dict:
        env = self._load_runtime_env()
        self._validate_storage_env(env)
        repo = RunRepository(FirebaseStorageClient(bucket_name=env["FIREBASE_STORAGE_BUCKET"]))
        return repo.apply_pending_changes(run_id=run_id)

    def upsert_single_entity_to_online_db(self, run_id: str, entity: dict) -> dict[str, int]:
        env = self._load_runtime_env()
        self._validate_storage_env(env)
        repo = RunRepository(FirebaseStorageClient(bucket_name=env["FIREBASE_STORAGE_BUCKET"]))
        return repo.upsert_single_verified_entity(run_id=run_id, entity=entity)
