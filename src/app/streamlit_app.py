from __future__ import annotations

import json
import os
import sys
from datetime import datetime
from pathlib import Path
import re
from uuid import uuid4

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


def _normalize_search_text(value: str) -> str:
    text = str(value).strip().lower()
    if not text:
        return ""
    return re.sub(r"[\s\-_/\\|,;:(){}\[\]<>\"'`。，“”‘’！？、]+", "", text)


def _filter_online_entities(
    rows: list[dict],
    search_field: str,
    keyword: str,
    category: str,
    review_scope: str = "全部",
) -> list[dict]:
    normalized_keyword = _normalize_search_text(keyword)
    filtered: list[dict] = []
    for row in rows:
        row_type = str(row.get("type", "other")).strip() or "other"
        if category != "全部" and row_type != category:
            continue
        reviewed_zh = bool(row.get("synonym_reviewed_zh", False))
        reviewed_en = bool(row.get("synonym_reviewed_en", False))
        if review_scope == "新内容" and (reviewed_zh and reviewed_en):
            continue
        if review_scope == "老内容" and not (reviewed_zh and reviewed_en):
            continue
        haystack = str(row.get(search_field, ""))
        if normalized_keyword and normalized_keyword not in _normalize_search_text(haystack):
            continue
        filtered.append(row)
    return filtered


def _find_pending_index_by_action_key(pending_items: list[dict], action: str, key: str) -> int | None:
    for idx, item in enumerate(pending_items):
        if not isinstance(item, dict):
            continue
        if str(item.get("status", "pending")) != "pending":
            continue
        if str(item.get("action", "")) != action:
            continue
        selector = item.get("selector", {})
        if not isinstance(selector, dict):
            continue
        if str(selector.get("key", "")) == key:
            return idx
    return None


def _build_pending_maps(pending_items: list[dict]) -> tuple[set[str], dict[str, dict]]:
    delete_keys: set[str] = set()
    update_map: dict[str, dict] = {}
    for item in pending_items:
        if not isinstance(item, dict):
            continue
        if str(item.get("status", "pending")) != "pending":
            continue
        action = str(item.get("action", ""))
        selector = item.get("selector", {})
        if not isinstance(selector, dict):
            continue
        key = str(selector.get("key", "")).strip()
        if not key:
            continue
        if action == "delete_record":
            delete_keys.add(key)
        if action == "update_record":
            update_map[key] = item
    return delete_keys, update_map


def _parse_sources_from_json(text: str) -> list[dict]:
    if not text.strip():
        return []
    parsed = json.loads(text)
    if not isinstance(parsed, list):
        return []
    cleaned: list[dict] = []
    for item in parsed:
        if not isinstance(item, dict):
            continue
        cleaned.append(
            {
                "url": str(item.get("url", "")).strip(),
                "site": str(item.get("site", "")).strip(),
                "evidence_note": str(item.get("evidence_note", "")).strip(),
            }
        )
    return cleaned


def _render_online_entity_cards(
    rows: list[dict],
    pending_items: list[dict],
    runner: PipelineRunner,
) -> None:
    delete_keys, update_map = _build_pending_maps(pending_items)
    grouped: dict[str, list[dict]] = {}
    for row in rows:
        row_type = str(row.get("type", "other")).strip() or "other"
        grouped.setdefault(row_type, []).append(row)

    ordered_types = sorted(grouped.keys(), key=lambda item: (-len(grouped[item]), item))
    if not ordered_types:
        st.info("没有匹配到词条。")
        return

    for entity_type in ordered_types:
        items = grouped[entity_type]
        with st.expander(f"{entity_type}（{len(items)}）", expanded=False):
            for item in items:
                key = str(item.get("key", "")).strip()
                pending_delete = key in delete_keys
                pending_update = update_map.get(key)
                display_item = dict(item)
                changed_fields: set[str] = set()
                if isinstance(pending_update, dict):
                    record = pending_update.get("record", {})
                    if isinstance(record, dict):
                        for field in [
                            "entity_zh",
                            "entity_en",
                            "type",
                            "final_recommendation",
                            "zh_aliases",
                            "en_aliases",
                            "sources",
                        ]:
                            if field in record and record.get(field) != display_item.get(field):
                                changed_fields.add(field)
                                display_item[field] = record.get(field)
                with st.container(border=True):
                    st.markdown(
                        (
                            f"**中文：{display_item.get('entity_zh', '')}**  \n"
                            f"英文：`{display_item.get('entity_en', '')}`  \n"
                            f"类型：`{display_item.get('type', 'other')}`"
                        )
                    )
                    if pending_update:
                        st.warning("修改待确认")
                        if changed_fields:
                            st.markdown(
                                f"<span style='color:#f59e0b'>已改动字段：{', '.join(sorted(changed_fields))}</span>",
                                unsafe_allow_html=True,
                            )
                    if pending_delete:
                        st.error("删除待确认")
                    st.caption(
                        "审查状态："
                        f"中文={display_item.get('synonym_reviewed_zh', False)} | "
                        f"英文={display_item.get('synonym_reviewed_en', False)}"
                    )
                    recommendation = str(display_item.get("final_recommendation", "")).strip()
                    if recommendation:
                        st.caption(f"建议：{recommendation}")
                    st.caption(
                        f"更新时间：{display_item.get('updated_at', '') or '未知'} | "
                        f"run_id：{display_item.get('last_run_id', '') or '未知'}"
                    )
                    sources = display_item.get("sources", [])
                    if isinstance(sources, list) and sources:
                        st.markdown("来源：")
                        for src in sources:
                            url = str(src.get("url", "")).strip()
                            site = str(src.get("site", "")).strip()
                            note = str(src.get("evidence_note", "")).strip()
                            if url:
                                st.markdown(f"- [{site or url}]({url})")
                            if note:
                                st.caption(f"证据说明：{note}")
                    btn_col_1, btn_col_2 = st.columns(2)
                    with btn_col_1:
                        with st.popover("修改", disabled=pending_delete):
                            current_record = pending_update.get("record", {}) if pending_update else display_item
                            with st.form(key=f"edit_form_{key}"):
                                new_zh = st.text_input("中文", value=str(current_record.get("entity_zh", "")))
                                new_en = st.text_input("英文", value=str(current_record.get("entity_en", "")))
                                new_type = st.text_input("类型", value=str(current_record.get("type", "other")))
                                new_zh_aliases = st.text_input(
                                    "中文同义词（逗号分隔）",
                                    value=", ".join(current_record.get("zh_aliases", [])),
                                )
                                new_en_aliases = st.text_input(
                                    "英文同义词（逗号分隔）",
                                    value=", ".join(current_record.get("en_aliases", [])),
                                )
                                new_recommendation = st.text_area(
                                    "建议",
                                    value=str(current_record.get("final_recommendation", "")),
                                    height=80,
                                )
                                new_sources_text = st.text_area(
                                    "来源（JSON数组）",
                                    value=json.dumps(current_record.get("sources", []), ensure_ascii=False, indent=2),
                                    height=140,
                                )
                                confirm_edit = st.form_submit_button("确认修改")
                                if confirm_edit:
                                    try:
                                        new_sources = _parse_sources_from_json(new_sources_text)
                                    except Exception as err:  # pragma: no cover
                                        st.error(f"来源 JSON 解析失败：{err}")
                                        new_sources = None
                                    if new_sources is not None:
                                        old_idx = _find_pending_index_by_action_key(
                                            pending_items, "update_record", key
                                        )
                                        if old_idx is not None:
                                            pending_payload = runner.remove_pending_change(old_idx)
                                            pending_items = pending_payload.get("items", [])
                                        pending = runner.add_pending_change(
                                            {
                                                "id": str(uuid4()),
                                                "action": "update_record",
                                                "selector": {"key": key},
                                                "record": {
                                                    "entity_zh": new_zh.strip(),
                                                    "entity_en": new_en.strip(),
                                                    "type": new_type.strip() or "other",
                                                    "zh_aliases": [
                                                        v.strip()
                                                        for v in new_zh_aliases.split(",")
                                                        if v.strip()
                                                    ],
                                                    "en_aliases": [
                                                        v.strip()
                                                        for v in new_en_aliases.split(",")
                                                        if v.strip()
                                                    ],
                                                    "final_recommendation": new_recommendation.strip(),
                                                    "sources": new_sources,
                                                    "is_verified": True,
                                                    "verification_status": "verified",
                                                },
                                            }
                                        )
                                        st.session_state["pending_changes_snapshot"] = pending
                                        st.success("已加入修改待确认。")
                                        st.rerun()
                    with btn_col_2:
                        if pending_delete:
                            if st.button("取消删除", key=f"cancel_delete_{key}"):
                                idx = _find_pending_index_by_action_key(
                                    pending_items, "delete_record", key
                                )
                                if idx is not None:
                                    pending = runner.remove_pending_change(idx)
                                    st.session_state["pending_changes_snapshot"] = pending
                                    st.success("已取消删除待确认。")
                                    st.rerun()
                        else:
                            if st.button("删除", key=f"mark_delete_{key}"):
                                pending = runner.add_pending_change(
                                    {
                                        "id": str(uuid4()),
                                        "action": "delete_record",
                                        "selector": {"key": key},
                                    }
                                )
                                st.session_state["pending_changes_snapshot"] = pending
                                st.warning("已标记删除待确认。")
                                st.rerun()


def _render_entity_detail_card(title: str, item: dict | None) -> None:
    st.markdown(f"**{title}**")
    if not item:
        st.info("未选择条目。")
        return
    with st.container(border=True):
        st.markdown(
            f"中文：`{item.get('entity_zh', '')}`  \n"
            f"英文：`{item.get('entity_en', '')}`  \n"
            f"类型：`{item.get('type', 'other')}`  \n"
            f"key：`{item.get('key', '')}`"
        )
        st.caption(
            "同义词状态："
            f"中文={item.get('synonym_reviewed_zh', False)} | "
            f"英文={item.get('synonym_reviewed_en', False)}"
        )
        st.caption(
            f"中文同义词：{', '.join(item.get('zh_aliases', [])) or '无'}"
        )
        st.caption(
            f"英文同义词：{', '.join(item.get('en_aliases', [])) or '无'}"
        )


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
    verifier_tab, review_tab, manual_merge_tab, confirm_tab, db_tab = st.tabs(
        ["本次核验", "大模型审核", "人工合并", "确认修改", "线上词库"]
    )

    with verifier_tab:
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
                    st.session_state.pop("online_entities_cache", None)
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
                        st.caption("中文")
                        st.write(item.get("zh", ""))
                        st.caption("英文")
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

    with review_tab:
        st.caption("按分类 + 语言执行同义词大模型审查，每次只推进一批，支持中断恢复。")
        runner = PipelineRunner()
        control_col_1, control_col_2, control_col_3, control_col_4 = st.columns(4)
        language_mode = control_col_1.selectbox(
            "审查语言",
            options=["中文", "英文"],
            key="synonym_review_language_mode",
        )
        language_value = "zh" if language_mode == "中文" else "en"
        try:
            all_rows_for_category = runner.list_online_all_entities()
        except Exception:  # pragma: no cover
            all_rows_for_category = []
        category_options = sorted(
            {str(item.get("type", "other")).strip() or "other" for item in all_rows_for_category}
        )
        category = control_col_2.selectbox(
            "分类",
            options=category_options or ["other"],
            key="synonym_review_category",
        )
        new_batch_size = int(
            control_col_3.number_input("新词批大小", min_value=1, max_value=100, value=20, step=1)
        )
        reviewed_batch_size = int(
            control_col_4.number_input("老词批大小", min_value=1, max_value=200, value=50, step=1)
        )
        review_model = st.text_input("审查模型（可留空使用侧栏模型）", value=selected_model)
        run_review = st.button("开始/继续一批大模型审查", key="run_synonym_review_batch")
        refresh_review_snapshot = st.button("刷新审查进度", key="refresh_synonym_review_snapshot")

        if run_review:
            try:
                review_result = runner.run_synonym_review_batch(
                    language_mode=language_value,
                    category=category,
                    llm_model=review_model.strip(),
                    new_batch_size=new_batch_size,
                    reviewed_batch_size=reviewed_batch_size,
                )
                st.session_state["synonym_review_snapshot"] = {
                    "state": review_result.get("state", {}),
                    "results": review_result.get("results", {}),
                }
                st.success(str(review_result.get("message", "执行完成。")))
            except Exception as err:  # pragma: no cover
                st.exception(err)
        if refresh_review_snapshot or "synonym_review_snapshot" not in st.session_state:
            try:
                snapshot = runner.get_synonym_review_snapshot()
                st.session_state["synonym_review_snapshot"] = snapshot
                st.session_state.pop("synonym_review_error", None)
            except Exception as err:  # pragma: no cover
                st.session_state["synonym_review_error"] = str(err)
                st.session_state["synonym_review_snapshot"] = {}

        snapshot_error = st.session_state.get("synonym_review_error")
        if snapshot_error:
            st.error(snapshot_error)
        snapshot = st.session_state.get("synonym_review_snapshot", {})
        state = snapshot.get("state", {}) if isinstance(snapshot, dict) else {}
        results_payload = snapshot.get("results", {}) if isinstance(snapshot, dict) else {}
        st.markdown("#### 当前进度")
        st.json(state)

        review_rows = results_payload.get("results", [])
        if isinstance(review_rows, list) and review_rows:
            latest = review_rows[-1]
            output = latest.get("output", {}) if isinstance(latest, dict) else {}
            matches = output.get("matches", []) if isinstance(output, dict) else []
            st.markdown("#### 最新候选同义词")
            if matches:
                for idx, match in enumerate(matches):
                    if not isinstance(match, dict):
                        continue
                    with st.expander(
                        f"候选 {idx + 1}: {match.get('new_id', '')} -> {match.get('reviewed_id', '')}"
                    ):
                        st.write(f"置信度：{match.get('confidence', 'low')}")
                        st.write(f"依据：{match.get('reason', '')}")
                        accept_col, reject_col = st.columns(2)
                        if accept_col.button("接受合并建议", key=f"accept_match_{idx}"):
                            pending = runner.add_pending_change(
                                {
                                    "id": str(uuid4()),
                                    "action": "merge_records",
                                    "language_mode": language_value,
                                    "target_selector": {"key": str(match.get("reviewed_id", ""))},
                                    "source_selector": {"key": str(match.get("new_id", ""))},
                                    "reason": str(match.get("reason", "")),
                                }
                            )
                            st.session_state["pending_changes_snapshot"] = pending
                            st.success("已加入待处理条目（未写线上库）。")
                        if reject_col.button("拒绝并标记已审查", key=f"reject_match_{idx}"):
                            pending = runner.add_pending_change(
                                {
                                    "id": str(uuid4()),
                                    "action": "mark_reviewed",
                                    "language_mode": language_value,
                                    "selector": {"key": str(match.get("new_id", ""))},
                                    "reason": str(match.get("reason", "")),
                                }
                            )
                            st.session_state["pending_changes_snapshot"] = pending
                            st.success("已加入待处理条目（未写线上库）。")
            else:
                st.info("本批没有返回同义词候选。")
            if st.button("将当前批新词标记为已人工审查（不合并）", key="mark_current_batch_reviewed"):
                new_keys = (
                    state.get("active", {}).get("new_keys", [])
                    if isinstance(state.get("active", {}), dict)
                    else []
                )
                if not isinstance(new_keys, list) or not new_keys:
                    st.warning("当前没有可标记的新词批。")
                else:
                    for item_key in new_keys:
                        runner.add_pending_change(
                            {
                                "id": str(uuid4()),
                                "action": "mark_reviewed",
                                "language_mode": language_value,
                                "selector": {"key": str(item_key)},
                                "reason": "manual_mark_reviewed_without_merge",
                            }
                        )
                    st.success("已加入待处理条目（未写线上库）。")
        else:
            st.info("暂无审查结果。")

    with manual_merge_tab:
        st.caption("人工补充合并：左右各选一条，先模拟合并，再确认写入待处理条目。")
        runner = PipelineRunner()
        refresh_manual = st.button("刷新线上条目", key="refresh_manual_merge_entities")
        if refresh_manual or "manual_merge_entities" not in st.session_state:
            try:
                st.session_state["manual_merge_entities"] = runner.list_online_all_entities()
                st.session_state.pop("manual_merge_error", None)
            except Exception as err:  # pragma: no cover
                st.session_state["manual_merge_error"] = str(err)
                st.session_state["manual_merge_entities"] = []
        manual_err = st.session_state.get("manual_merge_error")
        if manual_err:
            st.error(manual_err)
        all_entities = st.session_state.get("manual_merge_entities", [])
        if not isinstance(all_entities, list):
            all_entities = []
        categories = sorted({str(item.get("type", "other")) for item in all_entities if isinstance(item, dict)})

        left_col, right_col = st.columns(2)
        with left_col:
            st.markdown("#### 内容1筛选器")
            c1 = st.selectbox("分类", options=["全部"] + categories, key="merge_filter_left_category")
            z1 = st.text_input("中文关键词", key="merge_filter_left_zh")
            e1 = st.text_input("英文关键词", key="merge_filter_left_en")
            s1 = st.selectbox("新/老/全部", options=["全部", "新内容", "老内容"], key="merge_filter_left_scope")
            search1 = st.button("搜索内容1", key="search_merge_left")
            if search1:
                filtered1 = _filter_online_entities(
                    rows=[item for item in all_entities if isinstance(item, dict)],
                    search_field="entity_zh",
                    keyword=z1,
                    category=c1,
                    review_scope=s1,
                )
                if e1.strip():
                    filtered1 = _filter_online_entities(
                        rows=filtered1,
                        search_field="entity_en",
                        keyword=e1,
                        category="全部",
                        review_scope="全部",
                    )
                st.session_state["merge_left_results"] = filtered1
            left_results = st.session_state.get("merge_left_results", [])
            left_labels = [
                f"{idx + 1}. {item.get('entity_zh', '')} / {item.get('entity_en', '')}"
                for idx, item in enumerate(left_results)
            ]
            selected_left_idx = st.selectbox(
                "内容1结果",
                options=list(range(len(left_labels))),
                format_func=lambda i: left_labels[i] if left_labels else "无结果",
                key="merge_left_selected_idx",
            ) if left_labels else None
            selected_left_item = left_results[selected_left_idx] if selected_left_idx is not None else None
            _render_entity_detail_card("内容1详情", selected_left_item)

        with right_col:
            st.markdown("#### 内容2筛选器")
            c2 = st.selectbox("分类", options=["全部"] + categories, key="merge_filter_right_category")
            z2 = st.text_input("中文关键词", key="merge_filter_right_zh")
            e2 = st.text_input("英文关键词", key="merge_filter_right_en")
            s2 = st.selectbox("新/老/全部", options=["全部", "新内容", "老内容"], key="merge_filter_right_scope")
            search2 = st.button("搜索内容2", key="search_merge_right")
            if search2:
                filtered2 = _filter_online_entities(
                    rows=[item for item in all_entities if isinstance(item, dict)],
                    search_field="entity_zh",
                    keyword=z2,
                    category=c2,
                    review_scope=s2,
                )
                if e2.strip():
                    filtered2 = _filter_online_entities(
                        rows=filtered2,
                        search_field="entity_en",
                        keyword=e2,
                        category="全部",
                        review_scope="全部",
                    )
                st.session_state["merge_right_results"] = filtered2
            right_results = st.session_state.get("merge_right_results", [])
            right_labels = [
                f"{idx + 1}. {item.get('entity_zh', '')} / {item.get('entity_en', '')}"
                for idx, item in enumerate(right_results)
            ]
            selected_right_idx = st.selectbox(
                "内容2结果",
                options=list(range(len(right_labels))),
                format_func=lambda i: right_labels[i] if right_labels else "无结果",
                key="merge_right_selected_idx",
            ) if right_labels else None
            selected_right_item = right_results[selected_right_idx] if selected_right_idx is not None else None
            _render_entity_detail_card("内容2详情", selected_right_item)

        st.markdown("#### 合并策略")
        keep_col_1, keep_col_2, keep_col_3, keep_col_4 = st.columns(4)
        keep_zh = keep_col_1.checkbox("保留中文", value=True, key="merge_keep_zh")
        keep_en = keep_col_2.checkbox("保留英文", value=True, key="merge_keep_en")
        keep_url = keep_col_3.checkbox("保留URL", value=False, key="merge_keep_url")
        keep_note = keep_col_4.checkbox("保留Note", value=False, key="merge_keep_note")
        preview_merge = st.button("合并（模拟）", key="preview_manual_merge")
        if preview_merge:
            if not selected_left_item or not selected_right_item:
                st.warning("请先在左右两侧各选择一个条目。")
            else:
                merged = {
                    "entity_zh": selected_right_item.get("entity_zh", ""),
                    "entity_en": selected_right_item.get("entity_en", ""),
                    "type": selected_right_item.get("type", "other"),
                    "zh_aliases": sorted(
                        set(selected_right_item.get("zh_aliases", []))
                        | (set(selected_left_item.get("zh_aliases", [])) if keep_zh else set())
                    ),
                    "en_aliases": sorted(
                        set(selected_right_item.get("en_aliases", []))
                        | (set(selected_left_item.get("en_aliases", [])) if keep_en else set())
                    ),
                    "sources": selected_right_item.get("sources", [])
                    + (selected_left_item.get("sources", []) if keep_url or keep_note else []),
                    "final_recommendation": selected_right_item.get("final_recommendation", ""),
                    "is_verified": True,
                    "verification_status": "verified",
                    "synonym_reviewed_zh": True,
                    "synonym_reviewed_en": True,
                }
                st.session_state["manual_merge_preview"] = {
                    "source": selected_left_item,
                    "target": selected_right_item,
                    "merged": merged,
                }
        preview_payload = st.session_state.get("manual_merge_preview")
        if isinstance(preview_payload, dict):
            st.markdown("#### 模拟合并结果")
            _render_entity_detail_card("合并后条目", preview_payload.get("merged"))
            action_col_1, action_col_2 = st.columns(2)
            if action_col_1.button("返回", key="cancel_manual_merge_preview"):
                st.session_state.pop("manual_merge_preview", None)
                st.rerun()
            if action_col_2.button("确认", key="confirm_manual_merge_preview"):
                source_item = preview_payload.get("source", {})
                target_item = preview_payload.get("target", {})
                pending = runner.add_pending_change(
                    {
                        "id": str(uuid4()),
                        "action": "merge_records",
                        "language_mode": "zh",
                        "source_selector": {"key": str(source_item.get("key", ""))},
                        "target_selector": {"key": str(target_item.get("key", ""))},
                        "record": preview_payload.get("merged", {}),
                        "reason": "manual_merge_confirmed",
                    }
                )
                st.session_state["pending_changes_snapshot"] = pending
                st.success("已加入待处理条目（未写线上库）。")
                st.session_state.pop("manual_merge_preview", None)

    with confirm_tab:
        st.caption("此处只处理待处理条目；点击发送才会真正写入线上数据库。")
        runner = PipelineRunner()
        refresh_pending = st.button("刷新待处理条目", key="refresh_pending_changes")
        if refresh_pending or "pending_changes_snapshot" not in st.session_state:
            try:
                snapshot = runner.get_synonym_review_snapshot()
                st.session_state["pending_changes_snapshot"] = snapshot.get("pending", {})
                st.session_state.pop("pending_changes_error", None)
            except Exception as err:  # pragma: no cover
                st.session_state["pending_changes_error"] = str(err)
                st.session_state["pending_changes_snapshot"] = {"items": []}
        pending_error = st.session_state.get("pending_changes_error")
        if pending_error:
            st.error(pending_error)
        pending_payload = st.session_state.get("pending_changes_snapshot", {})
        pending_items = pending_payload.get("items", []) if isinstance(pending_payload, dict) else []
        if not isinstance(pending_items, list):
            pending_items = []
        st.metric("待处理条目数", len(pending_items))
        for idx, item in enumerate(pending_items):
            if not isinstance(item, dict):
                continue
            action = str(item.get("action", ""))
            status = str(item.get("status", "pending"))
            title = f"{idx + 1}. {action} | status={status}"
            selector = item.get("selector", {})
            if action in {"update_record", "delete_record"} and isinstance(selector, dict):
                title += f" | key={selector.get('key', '')}"
            with st.expander(
                title
            ):
                if action == "update_record":
                    st.caption("修改待确认")
                elif action == "delete_record":
                    st.caption("删除待确认")
                elif action == "merge_records":
                    st.caption("合并待确认")
                st.json(item)
                if st.button("删除此条", key=f"delete_pending_{idx}"):
                    try:
                        new_pending = runner.remove_pending_change(idx)
                        st.session_state["pending_changes_snapshot"] = new_pending
                        st.success("已删除。")
                        st.rerun()
                    except Exception as err:  # pragma: no cover
                        st.exception(err)
        if st.button("发送到线上数据库", type="primary", key="apply_pending_changes"):
            try:
                result = runner.apply_pending_changes_to_online_db(run_id=run_id or "manual_db_update")
                st.success(
                    "线上数据库更新完成："
                    f"applied={result.get('applied', 0)}, "
                    f"skipped={result.get('skipped', 0)}"
                )
                st.caption(f"audit_log: {result.get('audit_log_path', '')}")
                snapshot = runner.get_synonym_review_snapshot()
                st.session_state["pending_changes_snapshot"] = snapshot.get("pending", {})
                st.session_state.pop("online_entities_cache", None)
                st.session_state.pop("online_entities_error", None)
            except Exception as err:  # pragma: no cover
                st.exception(err)

    with db_tab:
        st.caption("展示线上 `name_map/entity_map_v1.json` 词条，并可发起修改/删除待确认。")
        runner = PipelineRunner()
        if "pending_changes_snapshot" not in st.session_state:
            try:
                snapshot = runner.get_synonym_review_snapshot()
                st.session_state["pending_changes_snapshot"] = snapshot.get("pending", {"items": []})
            except Exception:  # pragma: no cover
                st.session_state["pending_changes_snapshot"] = {"items": []}
        pending_payload = st.session_state.get("pending_changes_snapshot", {})
        pending_items = pending_payload.get("items", []) if isinstance(pending_payload, dict) else []
        if not isinstance(pending_items, list):
            pending_items = []
        refresh_cols = st.columns([1, 1, 3])
        refresh_clicked = refresh_cols[0].button("刷新线上词库", key="refresh_online_entities")
        reset_filter_clicked = refresh_cols[1].button("重置筛选", key="reset_online_entity_filters")
        if reset_filter_clicked:
            st.session_state["online_entity_search_mode"] = "中文"
            st.session_state["online_entity_keyword"] = ""
            st.session_state["online_entity_category"] = "全部"
            st.session_state["online_entity_review_scope"] = "全部"
            st.rerun()

        if refresh_clicked or "online_entities_cache" not in st.session_state:
            try:
                st.session_state["online_entities_cache"] = runner.list_online_verified_entities()
                st.session_state.pop("online_entities_error", None)
            except SettingsError as err:
                st.session_state["online_entities_error"] = str(err)
                st.session_state["online_entities_cache"] = []
            except Exception as err:  # pragma: no cover
                st.session_state["online_entities_error"] = str(err)
                st.session_state["online_entities_cache"] = []

        online_error = st.session_state.get("online_entities_error")
        if online_error:
            st.error(online_error)
        else:
            online_rows = st.session_state.get("online_entities_cache", [])
            categories = sorted(
                {
                    str(item.get("type", "other")).strip() or "other"
                    for item in online_rows
                    if isinstance(item, dict)
                }
            )
            search_mode = st.radio(
                "搜索字段",
                options=["中文", "英文"],
                horizontal=True,
                key="online_entity_search_mode",
            )
            search_field = "entity_zh" if search_mode == "中文" else "entity_en"
            keyword = st.text_input("关键词", key="online_entity_keyword")
            selected_category = st.selectbox(
                "分类",
                options=["全部"] + categories,
                index=0,
                key="online_entity_category",
            )
            review_scope = st.selectbox(
                "新/老/全部",
                options=["全部", "新内容", "老内容"],
                index=0,
                key="online_entity_review_scope",
            )

            filtered_rows = _filter_online_entities(
                rows=[item for item in online_rows if isinstance(item, dict)],
                search_field=search_field,
                keyword=keyword,
                category=selected_category,
                review_scope=review_scope,
            )
            metric_col_1, metric_col_2 = st.columns(2)
            metric_col_1.metric("当前筛选结果", len(filtered_rows))
            metric_col_2.metric("线上总词条", len(online_rows))
            _render_online_entity_cards(filtered_rows, pending_items=pending_items, runner=runner)

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

