from __future__ import annotations

import json
import os
import sys
from datetime import datetime
from pathlib import Path
import re

import streamlit as st

# Ensure `src` is importable when launched via `streamlit run src/app/streamlit_app.py`.
SRC_ROOT = Path(__file__).resolve().parents[1]
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from app.pipeline_runner import PipelineRunner, RunnerOptions
from app.ui_state import STAGE_ORDER, init_ui_state, reset_pipeline_state, update_from_run_result
from app.verifier_ui_utils import (
    build_entity_groups,
    build_entity_search_terms,
    build_replacement_candidates,
)
from config.settings import SettingsError


st.set_page_config(page_title="Blogger Translator", layout="wide")
init_ui_state()


def _env_ready(name: str) -> bool:
    return bool(os.getenv(name, "").strip())


def _env_ready_any(*names: str) -> bool:
    return any(_env_ready(name) for name in names)


def _env_text(name: str, default: str = "") -> str:
    raw = os.getenv(name, default)
    return raw.strip().strip('"').strip("'")


def _stage_board_markdown(stage_states: dict) -> str:
    icon_map = {
        "pending": "⚪",
        "running": "🟡",
        "success": "🟢",
        "failed": "🔴",
        "mocked": "🟣",
    }
    rows = []
    for stage in STAGE_ORDER:
        status = stage_states.get(stage, {}).get("status", "pending")
        detail = stage_states.get(stage, {}).get("detail", "")
        rows.append(f"- {icon_map.get(status, '⚪')} **{stage}**：`{status}` {detail}")
    return "\n".join(rows)


def _render_stage_board(stage_states: dict) -> None:
    st.markdown(_stage_board_markdown(stage_states))


def _as_text_list(value) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def _build_revisor_pairs(scraped: dict, revised: dict) -> tuple[list[dict], list[dict]]:
    revision = revised.get("revision", {})
    if not isinstance(revision, dict):
        revision = {}

    revised_paragraphs = _as_text_list(revision.get("paragraphs_revised_en", []))
    if not revised_paragraphs:
        revised_paragraphs = [block.strip() for block in str(revised.get("revised_text", "")).split("\n\n") if block.strip()]

    source_paragraphs = _as_text_list(scraped.get("body_paragraphs", []))
    pairs: list[dict] = []
    for idx, revised_en in enumerate(revised_paragraphs, start=1):
        source_zh = source_paragraphs[idx - 1] if idx - 1 < len(source_paragraphs) else ""
        pairs.append({"paragraph_id": idx, "en": revised_en, "zh": source_zh})

    outline = revised.get("revision_outline", {})
    parts = outline.get("parts", []) if isinstance(outline, dict) else []
    normalized_parts: list[dict] = []
    used_ids: set[int] = set()
    if isinstance(parts, list):
        for part in parts:
            if not isinstance(part, dict):
                continue
            raw_ids = part.get("paragraph_ids", [])
            if not isinstance(raw_ids, list):
                continue
            ids: list[int] = []
            for raw in raw_ids:
                try:
                    pid = int(raw)
                except (TypeError, ValueError):
                    continue
                if 1 <= pid <= len(pairs):
                    ids.append(pid)
            if not ids:
                continue
            normalized_parts.append(
                {
                    "part_id": int(part.get("part_id", len(normalized_parts) + 1)),
                    "subtitle_en": str(part.get("subtitle_en", "")).strip(),
                    "paragraph_ids": ids,
                }
            )
            used_ids.update(ids)

    missing_ids = [idx for idx in range(1, len(pairs) + 1) if idx not in used_ids]
    if missing_ids:
        normalized_parts.append(
            {
                "part_id": len(normalized_parts) + 1,
                "subtitle_en": "",
                "paragraph_ids": missing_ids,
            }
        )
    if not normalized_parts and pairs:
        normalized_parts = [{"part_id": 1, "subtitle_en": "", "paragraph_ids": list(range(1, len(pairs) + 1))}]
    return pairs, normalized_parts


st.title("Blogger Translator")
st.caption("完整 UI 编排版：支持真实/Mock 混合执行、分阶段可视化、错误追踪和产物下载。")

with st.sidebar:
    st.subheader("运行参数")
    url = st.text_input(
        "文章 URL",
        value="https://www.bastillepost.com/hongkong/article/15731771",
        key="input_url",
    )
    output_dir = st.text_input("本地输出目录", value="outputs", key="input_output_dir")

    run_mode = st.radio("执行模式", ["Mock 优先（推荐联调）", "真实优先"], horizontal=False)
    use_real_scraper = st.checkbox("抓取使用真实请求", value=(run_mode == "真实优先"))
    use_real_llm = st.checkbox("翻译/润色使用真实 LLM", value=(run_mode == "真实优先"))
    use_real_storage = st.checkbox("归档使用真实 Firebase Storage", value=False)
    use_entity_db_lookup = st.checkbox("核验前查线上映射库（完全一致）", value=True)
    claude_model = _env_text(
        "MAYNOR_MODEL_A",
        _env_text("MAYNOR_MODEL_CLAUDE", "claude-sonnet-4-6-thinking"),
    )
    gemini_model = _env_text(
        "MAYNOR_MODEL_B",
        _env_text("MAYNOR_MODEL_GEMINI", "gemini-3.1-pro-preview"),
    )
    maynor_model = _env_text("MAYNOR_MODEL", claude_model)
    model_labels = ["Claude（模型1）", "Gemini（模型2）", "Maynor（自定义）"]
    model_values = {
        "Claude（模型1）": claude_model,
        "Gemini（模型2）": gemini_model,
        "Maynor（自定义）": maynor_model,
    }
    selected_model_label = st.selectbox("LLM 模型", options=model_labels, index=0)
    selected_model = model_values[selected_model_label]
    st.caption(f"当前将使用：`{selected_model}`")

    st.markdown("---")
    mock_fail_stage = st.selectbox("调试：注入失败阶段", options=["无"] + STAGE_ORDER, index=0)
    if st.button("清空当前运行状态"):
        reset_pipeline_state()
        st.rerun()

    st.markdown("---")
    st.subheader("环境检查")
    st.write(
        "LLM API KEY: "
        f"{'OK' if _env_ready_any('SILICONFLOW_API_KEY', 'LLM_API_KEY', 'MAYNOR_API_KEY') else 'Missing'}"
    )
    st.write(f"FIREBASE_STORAGE_BUCKET: {'OK' if _env_ready('FIREBASE_STORAGE_BUCKET') else 'Missing'}")
    st.write(
        "GOOGLE_APPLICATION_CREDENTIALS: "
        f"{'OK' if _env_ready('GOOGLE_APPLICATION_CREDENTIALS') else 'Missing'}"
    )

left_col, right_col = st.columns([3, 2])
with left_col:
    st.subheader("执行区")
    st.write("支持全流程执行，以及先抓取/翻译/核验再继续的分步联调。")
    btn_col_1, btn_col_2, btn_col_3, btn_col_4 = st.columns(4)
    run_all = btn_col_1.button("一键执行全流程", type="primary", use_container_width=True)
    run_scraper_only = btn_col_2.button("仅执行抓取预览", use_container_width=True)
    run_until_translator = btn_col_3.button("执行到翻译阶段", use_container_width=True)
    run_until_verifier = btn_col_4.button("执行到核验阶段", use_container_width=True)

with right_col:
    st.subheader("占位能力提示")
    st.info("长度控制逻辑与结构化失败日志仍在后端完善；当前 UI 已预留展示位，可用 mock 数据联调。")

status_placeholder = st.empty()
status_placeholder.markdown("### 阶段状态\n尚未运行。")
progress_placeholder = st.empty()
progress_text_placeholder = st.empty()
log_placeholder = st.empty()


def _render_runtime_progress() -> None:
    verify_progress = st.session_state.get(
        "pipeline_verify_progress", {"done": 0, "total": 0, "percent": 0.0}
    )
    done = int(verify_progress.get("done", 0))
    total = int(verify_progress.get("total", 0))
    percent = float(verify_progress.get("percent", 0.0))
    text = (
        f"核验进度：{done}/{total} 段"
        if total > 0
        else "核验进度：等待开始"
    )
    progress_placeholder.progress(min(max(percent / 100.0, 0.0), 1.0))
    progress_text_placeholder.caption(text)

    runtime_logs = st.session_state.get("pipeline_runtime_logs", [])
    if runtime_logs:
        lines = [f"[{item.get('time', '--:--:--')}] {item.get('message', '')}" for item in runtime_logs[-12:]]
        log_placeholder.markdown("### 实时日志\n" + "\n".join(f"- {line}" for line in lines))
    else:
        log_placeholder.markdown("### 实时日志\n- 暂无日志。")


_render_runtime_progress()

if run_all or run_scraper_only or run_until_translator or run_until_verifier:
    options = RunnerOptions(
        mode="real" if run_mode == "真实优先" else "mock",
        use_real_scraper=use_real_scraper,
        use_real_llm=use_real_llm,
        use_real_storage=use_real_storage,
        use_entity_db_lookup=use_entity_db_lookup,
        mock_fail_stage="" if mock_fail_stage == "无" else mock_fail_stage,
        llm_model=selected_model,
    )
    runner = PipelineRunner()

    live_states = st.session_state.get("pipeline_stage_states", {})
    st.session_state["pipeline_runtime_logs"] = []
    st.session_state["pipeline_verify_progress"] = {"done": 0, "total": 0, "percent": 0.0}
    _render_runtime_progress()

    def on_stage_update(stage: str, status: str, detail: str) -> None:
        live_states[stage] = {"status": status, "detail": detail}
        status_placeholder.markdown(f"### 阶段状态\n{_stage_board_markdown(live_states)}")
        logs = st.session_state.get("pipeline_runtime_logs", [])
        logs.append(
            {
                "time": datetime.now().strftime("%H:%M:%S"),
                "stage": stage,
                "message": f"[{stage}] {detail}",
            }
        )
        st.session_state["pipeline_runtime_logs"] = logs
        _render_runtime_progress()

    def on_verifier_progress(payload: dict) -> None:
        done = int(payload.get("done_paragraphs", 0))
        total = int(payload.get("total_paragraphs", 0))
        percent = float(payload.get("percent", 0.0))
        st.session_state["pipeline_verify_progress"] = {
            "done": done,
            "total": total,
            "percent": percent,
        }
        logs = st.session_state.get("pipeline_runtime_logs", [])
        logs.append(
            {
                "time": datetime.now().strftime("%H:%M:%S"),
                "stage": "verifier",
                "message": str(payload.get("message", "")),
            }
        )
        st.session_state["pipeline_runtime_logs"] = logs
        _render_runtime_progress()

    try:
        with st.spinner("正在执行流水线，请稍候..."):
            result = runner.run_full(
                url=url,
                output_dir=output_dir,
                options=options,
                on_stage_update=on_stage_update,
                on_verifier_progress=on_verifier_progress,
                run_until_stage=(
                    "scraper"
                    if run_scraper_only
                    else (
                        "translator"
                        if run_until_translator
                        else ("verifier" if run_until_verifier else None)
                    )
                ),
            )
        update_from_run_result(result)
        if result.get("ok"):
            st.success("执行完成。")
        else:
            st.warning("执行中断，已保留可用阶段结果。")
    except SettingsError as err:
        st.error(str(err))
    except Exception as err:  # pragma: no cover
        st.exception(err)

st.markdown("### 阶段状态")
_render_stage_board(st.session_state.get("pipeline_stage_states", {}))

tabs = st.tabs(["抓取", "翻译", "核验结果", "润色", "产物归档", "日志错误"])
outputs = st.session_state.get("pipeline_stage_outputs", {})
artifacts = st.session_state.get("pipeline_artifacts", {})
error_payload = st.session_state.get("pipeline_error")
run_id = st.session_state.get("pipeline_run_id", "")

with tabs[0]:
    st.subheader("Scraper 结果")
    scraped = outputs.get("scraped", {})
    if scraped:
        meta = scraped.get("scrape_meta", {})
        m1, m2, m3 = st.columns(3)
        m1.metric("段落数", int(meta.get("paragraph_count", len(scraped.get("body_paragraphs", [])))))
        m2.metric("Caption 数", int(meta.get("caption_count", len(scraped.get("captions", [])))))
        m3.metric("LDJSON回退", "是" if meta.get("used_ldjson_fallback") else "否")
        st.write(f"标题：{scraped.get('title', '')}")
        st.write(f"作者：{scraped.get('author', '')}")
        st.write(f"发布时间：{scraped.get('published_at', '')}")
        with st.expander("查看正文段落"):
            st.json(scraped.get("body_paragraphs", []))
        with st.expander("查看 captions"):
            st.json(scraped.get("captions", []))
    else:
        st.info("暂无抓取结果。")

with tabs[1]:
    st.subheader("Translator 结果")
    translated = outputs.get("translated", {})
    if translated:
        st.write(f"模型：{translated.get('model', '')}")
        st.text_area("translated_text", translated.get("translated_text", ""), height=260)
    else:
        st.info("暂无翻译结果。")

with tabs[2]:
    st.subheader("Verifier 结果")
    verifier_output = outputs.get("verifier", {})

    def _append_runtime_log(message: str) -> None:
        logs = st.session_state.get("pipeline_runtime_logs", [])
        logs.append(
            {
                "time": datetime.now().strftime("%H:%M:%S"),
                "stage": "verifier",
                "message": message,
            }
        )
        st.session_state["pipeline_runtime_logs"] = logs

    def _update_outputs_state() -> None:
        st.session_state["pipeline_stage_outputs"] = outputs

    def _entity_brief(entity: dict) -> str:
        zh = str(entity.get("entity_zh", "")).strip()
        en = str(entity.get("entity_en", "")).strip()
        if zh and en:
            return f"{zh}/{en}"
        return zh or en or "unknown"

    def _replace_once_by_candidate(text: str, candidate: dict, replacement: str) -> tuple[str, bool]:
        start = int(candidate.get("start", -1))
        end = int(candidate.get("end", -1))
        matched_text = str(candidate.get("matched_text", ""))
        term = str(candidate.get("term", ""))
        if 0 <= start < end <= len(text):
            current = text[start:end]
            if current.lower() == matched_text.lower():
                return text[:start] + replacement + text[end:], True
        if not term:
            return text, False
        pattern = re.compile(rf"(?<!\w){re.escape(term)}(?!\w)", flags=re.IGNORECASE)
        new_text, replaced = pattern.subn(replacement, text, count=1)
        return new_text, replaced > 0

    def _apply_replacement(candidate: dict, replacement: str) -> bool:
        scope = candidate.get("scope")
        if scope == "translated_text":
            translated = outputs.get("translated", {})
            source = str(translated.get("translated_text", ""))
            updated, changed = _replace_once_by_candidate(source, candidate, replacement)
            if changed:
                translated["translated_text"] = updated
                outputs["translated"] = translated
                _update_outputs_state()
            return changed

        if scope == "paragraph_en":
            paragraph_id = candidate.get("paragraph_id")
            paragraph_results = verifier_output.get("paragraph_results", [])
            if not isinstance(paragraph_results, list):
                return False
            changed_any = False
            for item in paragraph_results:
                if not isinstance(item, dict):
                    continue
                if item.get("paragraph_id") != paragraph_id:
                    continue
                source = str(item.get("en", ""))
                updated, changed = _replace_once_by_candidate(source, candidate, replacement)
                if changed:
                    item["en"] = updated
                    changed_any = True
            if changed_any:
                pairs = verifier_output.get("paragraph_pairs", [])
                if isinstance(pairs, list):
                    for pair in pairs:
                        if not isinstance(pair, dict):
                            continue
                        if pair.get("paragraph_id") == paragraph_id:
                            source = str(pair.get("en", ""))
                            updated, changed = _replace_once_by_candidate(source, candidate, replacement)
                            if changed:
                                pair["en"] = updated
                outputs["verifier"] = verifier_output
                _update_outputs_state()
            return changed_any
        return False

    def _mark_entity_saved(paragraph_id: int | str, entity_index: int, saved_payload: dict) -> None:
        paragraph_results = verifier_output.get("paragraph_results", [])
        if not isinstance(paragraph_results, list):
            return
        for paragraph in paragraph_results:
            if not isinstance(paragraph, dict):
                continue
            if paragraph.get("paragraph_id") != paragraph_id:
                continue
            entities = paragraph.get("verified_entities", [])
            if not isinstance(entities, list) or entity_index >= len(entities):
                continue
            entity = entities[entity_index]
            if not isinstance(entity, dict):
                continue
            entity["manual_db_saved"] = True
            entity["manual_db_saved_at"] = datetime.utcnow().isoformat()
            entity["sources"] = saved_payload.get("sources", entity.get("sources", []))
            entity["entity_zh"] = saved_payload.get("entity_zh", entity.get("entity_zh", ""))
            entity["entity_en"] = saved_payload.get("entity_en", entity.get("entity_en", ""))
            entity["type"] = saved_payload.get("type", entity.get("type", "other"))
            entity["final_recommendation"] = saved_payload.get(
                "final_recommendation", entity.get("final_recommendation", "")
            )
            break
        outputs["verifier"] = verifier_output
        _update_outputs_state()

    @st.dialog("替换译文（逐条确认）")
    def _replace_dialog() -> None:
        target = st.session_state.get("verifier_replace_target")
        if not isinstance(target, dict):
            st.info("暂无替换目标。")
            return
        entity = target.get("entity", {})
        if not isinstance(entity, dict):
            st.info("替换目标数据异常。")
            return

        default_text = str(entity.get("entity_en", "")).strip()
        replace_value = st.text_input(
            "正确译文",
            value=st.session_state.get("verifier_replace_text", default_text) or default_text,
            key="verifier_replace_text",
        ).strip()
        if not replace_value:
            st.warning("请先输入正确译文。")
            return

        translated = outputs.get("translated", {})
        translated_text = str(translated.get("translated_text", ""))
        paragraph_results = verifier_output.get("paragraph_results", [])
        if not isinstance(paragraph_results, list):
            paragraph_results = []
        search_terms = build_entity_search_terms(
            entity_en=str(entity.get("entity_en", "")),
            entity_type=str(entity.get("type", "other")),
        )
        st.caption(f"检索词：{', '.join(search_terms) if search_terms else '(空)'}")
        candidates = build_replacement_candidates(translated_text, paragraph_results, search_terms)
        if not candidates:
            st.info("没有找到可替换项。")
        for idx, candidate in enumerate(candidates):
            scope = candidate.get("scope_label", "")
            context = str(candidate.get("context", ""))
            matched = str(candidate.get("matched_text", ""))
            st.markdown(f"**{idx + 1}. {scope}**")
            st.caption(f"命中：`{matched}`")
            st.code(context)
            if st.button("确认替换", key=f"confirm_replace_{idx}_{candidate.get('scope', '')}"):
                changed = _apply_replacement(candidate, replace_value)
                if changed:
                    _append_runtime_log(
                        f"已替换命中词：{_entity_brief(entity)} -> {replace_value} ({scope})"
                    )
                    st.rerun()
                st.warning("替换失败：命中位置已变化，请重新检查。")

        if st.button("关闭替换窗口", key="close_replace_dialog"):
            st.session_state["verifier_replace_target"] = None
            st.session_state.pop("verifier_replace_text", None)
            st.rerun()

    @st.dialog("录入线上映射库")
    def _insert_dialog() -> None:
        target = st.session_state.get("verifier_insert_target")
        form = st.session_state.get("verifier_insert_form")
        if not isinstance(target, dict) or not isinstance(form, dict):
            st.info("暂无录入目标。")
            return

        st.session_state["insert_entity_zh"] = st.session_state.get(
            "insert_entity_zh", str(form.get("entity_zh", ""))
        )
        st.session_state["insert_entity_en"] = st.session_state.get(
            "insert_entity_en", str(form.get("entity_en", ""))
        )
        st.session_state["insert_entity_type"] = st.session_state.get(
            "insert_entity_type", str(form.get("type", "other"))
        )
        st.session_state["insert_entity_recommendation"] = st.session_state.get(
            "insert_entity_recommendation", str(form.get("final_recommendation", ""))
        )

        st.text_input("原文实体（中文）", key="insert_entity_zh")
        st.text_input("译文实体（英文）", key="insert_entity_en")
        st.text_input("实体类型", key="insert_entity_type")
        st.text_area("建议映射/备注", key="insert_entity_recommendation", height=90)

        urls = form.get("sources", [])
        if not isinstance(urls, list):
            urls = []
        form["sources"] = urls

        st.markdown("**验证 URL（可增删）**")
        for idx, source in enumerate(urls):
            if not isinstance(source, dict):
                source = {}
                urls[idx] = source
            col_url, col_note, col_del = st.columns([5, 3, 1])
            url_key = f"insert_url_{idx}"
            note_key = f"insert_note_{idx}"
            if url_key not in st.session_state:
                st.session_state[url_key] = str(source.get("url", ""))
            if note_key not in st.session_state:
                st.session_state[note_key] = str(source.get("evidence_note", ""))
            with col_url:
                st.text_input(f"URL {idx + 1}", key=url_key, label_visibility="collapsed")
            with col_note:
                st.text_input(f"证据说明 {idx + 1}", key=note_key, label_visibility="collapsed")
            with col_del:
                if st.button("-", key=f"remove_url_{idx}"):
                    urls.pop(idx)
                    st.session_state["verifier_insert_form"] = form
                    st.rerun()

        if st.button("+ 新增 URL", key="add_insert_url"):
            urls.append({"url": "", "site": "", "evidence_note": ""})
            st.session_state["verifier_insert_form"] = form
            st.rerun()

        if st.button("确认录入线上映射库", type="primary", key="confirm_insert_entity"):
            payload_sources = []
            for idx, _ in enumerate(urls):
                url = str(st.session_state.get(f"insert_url_{idx}", "")).strip()
                note = str(st.session_state.get(f"insert_note_{idx}", "")).strip()
                if not url:
                    continue
                payload_sources.append({"url": url, "site": "", "evidence_note": note})

            payload = {
                "entity_zh": str(st.session_state.get("insert_entity_zh", "")).strip(),
                "entity_en": str(st.session_state.get("insert_entity_en", "")).strip(),
                "type": str(st.session_state.get("insert_entity_type", "other")).strip() or "other",
                "is_verified": True,
                "verification_status": "verified",
                "sources": payload_sources,
                "final_recommendation": str(
                    st.session_state.get("insert_entity_recommendation", "")
                ).strip(),
            }
            try:
                write_stats = PipelineRunner().upsert_single_entity_to_online_db(
                    run_id=run_id,
                    entity=payload,
                )
                if int(write_stats.get("upserted", 0)) > 0:
                    _mark_entity_saved(
                        paragraph_id=target.get("paragraph_id", ""),
                        entity_index=int(target.get("entity_index", -1)),
                        saved_payload=payload,
                    )
                    _append_runtime_log(
                        "手动录入线上映射库成功："
                        f"{payload.get('entity_zh', '')}/{payload.get('entity_en', '')}"
                    )
                    st.success("已录入线上映射库。")
                    st.session_state["verifier_insert_target"] = None
                    st.session_state["verifier_insert_form"] = None
                    st.rerun()
                else:
                    st.error("录入失败：至少需要一条有效 URL。")
            except SettingsError as err:
                st.error(str(err))
            except Exception as err:  # pragma: no cover
                st.exception(err)

        if st.button("关闭录入窗口", key="close_insert_dialog"):
            st.session_state["verifier_insert_target"] = None
            st.session_state["verifier_insert_form"] = None
            st.rerun()

    if verifier_output:
        write_to_db = st.button("确认写入线上映射库", key="write_entity_map_btn")
        if write_to_db:
            try:
                write_stats = PipelineRunner().write_verified_entities_to_online_db(
                    run_id=run_id,
                    verifier_output=verifier_output,
                )
                verifier_output["entity_db"] = {
                    "write_enabled": True,
                    "scanned": int(write_stats.get("scanned", 0)),
                    "upserted": int(write_stats.get("upserted", 0)),
                    "entries": int(write_stats.get("entries", 0)),
                }
                outputs["verifier"] = verifier_output
                _update_outputs_state()
                _append_runtime_log(
                    "线上映射库写入完成："
                    f"扫描 {write_stats.get('scanned', 0)}，"
                    f"新增/更新 {write_stats.get('upserted', 0)}，"
                    f"当前总条目 {write_stats.get('entries', 0)}"
                )
                _render_runtime_progress()
                st.success("已按确认写入线上映射库。")
            except SettingsError as err:
                st.error(str(err))
            except Exception as err:  # pragma: no cover
                st.exception(err)
        summary = verifier_output.get("summary", {})
        c1, c2, c3 = st.columns(3)
        c1.metric("实体总数", int(summary.get("total_entities", 0)))
        c2.metric("已确认", int(summary.get("verified_entities", 0)))
        c3.metric("未确认", int(summary.get("unresolved_entities", 0)))
        degrade_stats = summary.get("degrade_stats", {})
        if isinstance(degrade_stats, dict):
            a = int(degrade_stats.get("aligner_fallbacks", 0))
            b = int(degrade_stats.get("extractor_failures", 0))
            c = int(degrade_stats.get("verifier_failures", 0))
            st.caption(
                "降级统计："
                f"aligner_fallbacks={a}, "
                f"extractor_failures={b}, "
                f"verifier_failures={c}"
            )
            if a > 0 or b > 0 or c > 0:
                st.warning("本次核验触发了降级兜底，请查看日志与降级说明。")
        entity_db = verifier_output.get("entity_db", {})
        if isinstance(entity_db, dict) and entity_db:
            st.caption(
                "线上映射库："
                f"write_enabled={entity_db.get('write_enabled', False)}, "
                f"scanned={entity_db.get('scanned', 0)}, "
                f"upserted={entity_db.get('upserted', 0)}, "
                f"entries={entity_db.get('entries', 0)}"
            )

        notes = verifier_output.get("alignment_notes", [])
        if notes:
            with st.expander("段落对齐说明"):
                st.json(notes)
        degradation_notes = verifier_output.get("degradation_notes", [])
        if isinstance(degradation_notes, list) and degradation_notes:
            with st.expander("核验降级说明"):
                for note in degradation_notes:
                    st.write(f"- {note}")

        paragraph_results = verifier_output.get("paragraph_results", [])
        if isinstance(paragraph_results, list) and paragraph_results:
            grouped = build_entity_groups(paragraph_results)

            st.markdown("#### LLM 返回实体（可操作）")
            llm_items = grouped.get("llm", [])
            if not llm_items:
                st.info("暂无需要人工处理的 LLM 返回实体。")
            for row_idx, row in enumerate(llm_items):
                entity = row.get("entity", {})
                if not isinstance(entity, dict):
                    continue
                paragraph_id = row.get("paragraph_id", "")
                entity_index = int(row.get("entity_index", -1))
                with st.container(border=True):
                    title = _entity_brief(entity)
                    status = "已确认" if entity.get("is_verified", False) else "未确认"
                    verification_status = str(entity.get("verification_status", "")).strip()
                    st.markdown(
                        f"**{title}** ({entity.get('type', 'other')}) - {status} | 来源：{verification_status or 'llm'}"
                    )
                    st.caption(f"段落 p{paragraph_id}")
                    st.write(f"原文：{row.get('paragraph_zh', '')}")
                    st.write(f"译文：{row.get('paragraph_en', '')}")
                    if entity.get("final_recommendation"):
                        st.write(f"建议：{entity.get('final_recommendation')}")
                    if entity.get("uncertainty_reason"):
                        st.warning(f"未确认原因：{entity.get('uncertainty_reason')}")
                    queries = entity.get("next_search_queries", [])
                    if isinstance(queries, list) and queries:
                        st.caption(f"下一步检索建议：{', '.join(str(q) for q in queries)}")
                    sources = entity.get("sources", [])
                    if isinstance(sources, list) and sources:
                        for src in sources:
                            if not isinstance(src, dict):
                                continue
                            url = src.get("url", "")
                            site = src.get("site", "")
                            note = src.get("evidence_note", "")
                            st.markdown(f"- [{site or url}]({url})")
                            if note:
                                st.caption(f"证据说明：{note}")
                    else:
                        st.caption("未返回可点击证据链接。")

                    left_action, right_action = st.columns(2)
                    if left_action.button("替换", key=f"entity_replace_{row_idx}_{paragraph_id}_{entity_index}"):
                        st.session_state["verifier_replace_target"] = row
                        st.session_state["verifier_replace_text"] = str(entity.get("entity_en", "")).strip()
                        st.rerun()
                    if right_action.button("录入", key=f"entity_insert_{row_idx}_{paragraph_id}_{entity_index}"):
                        seed_sources = entity.get("sources", [])
                        if not isinstance(seed_sources, list) or not seed_sources:
                            seed_sources = [{"url": "", "site": "", "evidence_note": ""}]
                        st.session_state["verifier_insert_target"] = row
                        st.session_state["verifier_insert_form"] = {
                            "entity_zh": str(entity.get("entity_zh", "")).strip(),
                            "entity_en": str(entity.get("entity_en", "")).strip(),
                            "type": str(entity.get("type", "other")).strip() or "other",
                            "final_recommendation": str(entity.get("final_recommendation", "")).strip(),
                            "sources": seed_sources,
                        }
                        st.rerun()
                    if entity.get("manual_db_saved"):
                        st.success("该实体已手动录入线上映射库。")

            def _render_skip_group(group_key: str, title: str) -> None:
                items = grouped.get(group_key, [])
                if not items:
                    return
                labels = []
                for item in items:
                    ent = item.get("entity", {})
                    if isinstance(ent, dict):
                        labels.append(_entity_brief(ent))
                summary = ", ".join(labels) if labels else "无"
                with st.expander(f"{title}（{len(items)}）: {summary}"):
                    for item in items:
                        ent = item.get("entity", {})
                        if not isinstance(ent, dict):
                            continue
                        st.markdown(
                            f"- **p{item.get('paragraph_id', '')}** {_entity_brief(ent)} "
                            f"| status={ent.get('verification_status', '')}"
                        )
                        sources = ent.get("sources", [])
                        if isinstance(sources, list) and sources:
                            for src in sources:
                                if not isinstance(src, dict):
                                    continue
                                url = src.get("url", "")
                                site = src.get("site", "")
                                note = src.get("evidence_note", "")
                                st.markdown(f"  - [{site or url}]({url})")
                                if note:
                                    st.caption(f"    证据说明：{note}")
                        else:
                            st.caption("  - 无可点击 URL")

            st.markdown("#### 跳过项")
            _render_skip_group("db_exact_hit", "线上映射命中（db_exact_hit）")
            _render_skip_group("runtime_cache_hit", "运行内缓存命中（runtime_cache_hit）")
            if st.session_state.get("verifier_replace_target"):
                _replace_dialog()
            if st.session_state.get("verifier_insert_target"):
                _insert_dialog()
        else:
            st.info("暂无逐段核验结果。")
    else:
        questions = outputs.get("name_questions", [])
        if questions:
            st.info("当前展示兼容模式结果（旧格式）。")
            for idx, q in enumerate(questions, start=1):
                st.write(f"{idx}. {q}")
        else:
            st.info("暂无核验结果。")

with tabs[3]:
    st.subheader("Revisor 结果")
    revised = outputs.get("revised", {})
    scraped = outputs.get("scraped", {})
    if revised:
        st.write(f"模型：{revised.get('model', '')}")
        st.write(
            f"长度控制占位：title <= {revised.get('title_limit', 12)}, "
            f"caption <= {revised.get('caption_limit', 25)} words"
        )
        note = revised.get("placeholder_note") or revised.get("mock_note")
        if note:
            st.caption(note)

        revision_block = revised.get("revision", {})
        if not isinstance(revision_block, dict):
            revision_block = {}
        title_revised = str(revision_block.get("title_revised_en", "")).strip()
        if title_revised:
            st.markdown(f"**润色标题**：{title_revised}")

        pairs, parts = _build_revisor_pairs(scraped if isinstance(scraped, dict) else {}, revised)
        if pairs:
            st.markdown("#### 分段对照（译文 / 原文）")
            for part in parts:
                if not isinstance(part, dict):
                    continue
                part_id = int(part.get("part_id", 0))
                subtitle = str(part.get("subtitle_en", "")).strip()
                title = f"Part {part_id}" if part_id > 0 else "Part"
                if subtitle:
                    st.markdown(f"##### {title}: {subtitle}")
                else:
                    st.markdown(f"##### {title}")
                paragraph_ids = part.get("paragraph_ids", [])
                if not isinstance(paragraph_ids, list):
                    continue
                for paragraph_id in paragraph_ids:
                    try:
                        pid = int(paragraph_id)
                    except (TypeError, ValueError):
                        continue
                    if not (1 <= pid <= len(pairs)):
                        continue
                    row = pairs[pid - 1]
                    with st.container(border=True):
                        st.caption(f"段落 p{pid}")
                        col_en, col_zh = st.columns(2)
                        with col_en:
                            st.markdown("**译文**")
                            st.write(row.get("en", ""))
                        with col_zh:
                            st.markdown("**原文**")
                            st.write(row.get("zh", "") or "（缺失原文段落）")
        else:
            st.info("暂无可分段展示的润色结果。")

        with st.expander("查看 merged revised_text"):
            st.text_area("revised_text", revised.get("revised_text", ""), height=220)

        captions = _as_text_list(revision_block.get("captions_revised_en", []))
        if captions:
            with st.expander("查看润色 captions"):
                for idx, cap in enumerate(captions, start=1):
                    st.write(f"{idx}. {cap}")

        with st.expander("查看 revision_meta / revision_outline"):
            st.json(
                {
                    "revision_meta": revised.get("revision_meta", {}),
                    "revision_outline": revised.get("revision_outline", {}),
                }
            )
    else:
        st.info("暂无润色结果。")

with tabs[4]:
    st.subheader("产物与归档")
    st.write(f"run_id：`{run_id}`" if run_id else "run_id：尚未生成")
    local_path = artifacts.get("docx_local_path", "")
    cloud_path = artifacts.get("docx_cloud_path", "")
    st.write(f"本地 docx：`{local_path}`" if local_path else "本地 docx：暂无")
    st.write(f"云端路径：`{cloud_path}`" if cloud_path else "云端路径：暂无")
    if local_path and Path(local_path).exists():
        with Path(local_path).open("rb") as fp:
            st.download_button(
                label="下载生成的 docx",
                data=fp.read(),
                file_name=Path(local_path).name,
                mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            )

with tabs[5]:
    st.subheader("日志与错误")
    st.write(f"最后执行模式：`{st.session_state.get('pipeline_last_mode', 'unknown')}`")
    st.json(st.session_state.get("pipeline_stage_states", {}))
    runtime_logs = st.session_state.get("pipeline_runtime_logs", [])
    if runtime_logs:
        st.markdown("#### 运行日志")
        for item in runtime_logs:
            st.write(f"[{item.get('time', '--:--:--')}] {item.get('message', '')}")
    if error_payload:
        st.error(
            f"失败阶段：{error_payload.get('stage', 'unknown')} | "
            f"{error_payload.get('message', 'Unknown error')}"
        )
        with st.expander("展开 traceback"):
            st.code(error_payload.get("traceback", ""))
    else:
        st.success("暂无错误。")
    with st.expander("查看统一 result payload"):
        st.code(
            json.dumps(
                {
                    "run_id": run_id,
                    "docx_local_path": artifacts.get("docx_local_path", ""),
                    "docx_cloud_path": artifacts.get("docx_cloud_path", ""),
                    "name_questions": outputs.get("name_questions", []),
                    "verifier": outputs.get("verifier", {}),
                },
                ensure_ascii=False,
                indent=2,
            )
        )

