from __future__ import annotations

import json
import os
import sys
from datetime import datetime
from pathlib import Path

import streamlit as st

# Ensure `src` is importable when launched via `streamlit run src/app/streamlit_app.py`.
SRC_ROOT = Path(__file__).resolve().parents[1]
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from app.pipeline_runner import PipelineRunner, RunnerOptions
from app.ui_state import STAGE_ORDER, init_ui_state, reset_pipeline_state, update_from_run_result
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
    distill_model = _env_text("LLM_MODEL_B", "deepseek-ai/DeepSeek-R1-Distill-Qwen-32B")
    primary_model = _env_text(
        "SILICONFLOW_MODEL",
        _env_text("LLM_MODEL", "Pro/deepseek-ai/DeepSeek-R1"),
    )
    model_labels = ["Distill（默认）", "R1（主模型）"]
    model_values = {
        "Distill（默认）": distill_model,
        "R1（主模型）": primary_model,
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
        f"{'OK' if _env_ready_any('SILICONFLOW_API_KEY', 'LLM_API_KEY') else 'Missing'}"
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
                st.session_state["pipeline_stage_outputs"] = outputs
                logs = st.session_state.get("pipeline_runtime_logs", [])
                logs.append(
                    {
                        "time": datetime.now().strftime("%H:%M:%S"),
                        "stage": "verifier",
                        "message": (
                            "线上映射库写入完成："
                            f"扫描 {write_stats.get('scanned', 0)}，"
                            f"新增/更新 {write_stats.get('upserted', 0)}，"
                            f"当前总条目 {write_stats.get('entries', 0)}"
                        ),
                    }
                )
                st.session_state["pipeline_runtime_logs"] = logs
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

        paragraph_results = verifier_output.get("paragraph_results", [])
        if paragraph_results:
            for item in paragraph_results:
                paragraph_id = item.get("paragraph_id", "")
                with st.expander(f"段落 {paragraph_id}"):
                    st.caption("原文（中文）")
                    st.write(item.get("zh", ""))
                    st.caption("译文（英文）")
                    st.write(item.get("en", ""))

                    verified_entities = item.get("verified_entities", [])
                    if not verified_entities:
                        st.info("该段未识别到需要核验的实体。")
                        continue

                    for entity in verified_entities:
                        entity_zh = entity.get("entity_zh", "")
                        entity_en = entity.get("entity_en", "")
                        entity_type = entity.get("type", "other")
                        status = "已确认" if entity.get("is_verified", False) else "未确认"
                        verification_status = str(entity.get("verification_status", "")).strip()
                        status_suffix = f" | 来源：{verification_status}" if verification_status else ""
                        st.markdown(
                            f"**{entity_zh} / {entity_en}** ({entity_type}) - {status}{status_suffix}"
                        )
                        if entity.get("final_recommendation"):
                            st.write(f"建议：{entity.get('final_recommendation')}")
                        if entity.get("uncertainty_reason"):
                            st.warning(f"未确认原因：{entity.get('uncertainty_reason')}")
                        queries = entity.get("next_search_queries", [])
                        if queries:
                            st.caption(f"下一步检索建议：{', '.join(str(q) for q in queries)}")
                        sources = entity.get("sources", [])
                        if sources:
                            for src in sources:
                                url = src.get("url", "")
                                site = src.get("site", "")
                                note = src.get("evidence_note", "")
                                st.markdown(f"- [{site or url}]({url})")
                                if note:
                                    st.caption(f"证据说明：{note}")
                        else:
                            st.caption("未返回可点击证据链接。")
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
    if revised:
        st.write(f"模型：{revised.get('model', '')}")
        st.write(
            f"长度控制占位：title <= {revised.get('title_limit', 12)}, "
            f"caption <= {revised.get('caption_limit', 25)} words"
        )
        note = revised.get("placeholder_note") or revised.get("mock_note")
        if note:
            st.caption(note)
        st.text_area("revised_text", revised.get("revised_text", ""), height=300)
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

