from __future__ import annotations

import json
import os
import sys
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

    st.markdown("---")
    mock_fail_stage = st.selectbox("调试：注入失败阶段", options=["无"] + STAGE_ORDER, index=0)
    if st.button("清空当前运行状态"):
        reset_pipeline_state()
        st.rerun()

    st.markdown("---")
    st.subheader("环境检查")
    st.write(f"SILICONFLOW_API_KEY: {'OK' if _env_ready('SILICONFLOW_API_KEY') else 'Missing'}")
    st.write(f"FIREBASE_STORAGE_BUCKET: {'OK' if _env_ready('FIREBASE_STORAGE_BUCKET') else 'Missing'}")
    st.write(
        "GOOGLE_APPLICATION_CREDENTIALS: "
        f"{'OK' if _env_ready('GOOGLE_APPLICATION_CREDENTIALS') else 'Missing'}"
    )

left_col, right_col = st.columns([3, 2])
with left_col:
    st.subheader("执行区")
    st.write("支持全流程执行，以及先抓取再继续的分步联调。")
    btn_col_1, btn_col_2 = st.columns(2)
    run_all = btn_col_1.button("一键执行全流程", type="primary", use_container_width=True)
    run_scraper_only = btn_col_2.button("仅执行抓取预览", use_container_width=True)

with right_col:
    st.subheader("占位能力提示")
    st.info("长度控制逻辑与结构化失败日志仍在后端完善；当前 UI 已预留展示位，可用 mock 数据联调。")

status_placeholder = st.empty()
status_placeholder.markdown("### 阶段状态\n尚未运行。")

if run_all or run_scraper_only:
    options = RunnerOptions(
        mode="real" if run_mode == "真实优先" else "mock",
        use_real_scraper=use_real_scraper,
        use_real_llm=use_real_llm,
        use_real_storage=use_real_storage,
        mock_fail_stage="" if mock_fail_stage == "无" else mock_fail_stage,
    )
    runner = PipelineRunner()

    live_states = st.session_state.get("pipeline_stage_states", {})

    def on_stage_update(stage: str, status: str, detail: str) -> None:
        live_states[stage] = {"status": status, "detail": detail}
        status_placeholder.markdown(f"### 阶段状态\n{_stage_board_markdown(live_states)}")

    try:
        with st.spinner("正在执行流水线，请稍候..."):
            result = runner.run_full(
                url=url,
                output_dir=output_dir,
                options=options,
                on_stage_update=on_stage_update,
                run_until_stage="scraper" if run_scraper_only else None,
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

tabs = st.tabs(["抓取", "翻译", "核对问题", "润色", "产物归档", "日志错误"])
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
    questions = outputs.get("name_questions", [])
    if questions:
        for idx, q in enumerate(questions, start=1):
            st.write(f"{idx}. {q}")
    else:
        st.info("暂无核对问题。")

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
                },
                ensure_ascii=False,
                indent=2,
            )
        )

