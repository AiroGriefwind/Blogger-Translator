from __future__ import annotations

import base64
import json
import os
import random
import sys
import time
from copy import deepcopy
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
from app.verifier_ui_utils import build_entity_search_terms, build_replacement_candidates
from config.settings import SettingsError
from formatter.byline_resolver import (
    fallback_short_title,
    needs_title_shorten,
    resolve_bylines,
    safe_docx_name,
)


st.set_page_config(page_title="Blogger Translator", layout="wide")
init_ui_state()
st.session_state.setdefault("pipeline_url_queue", [])
st.session_state.setdefault("pipeline_queue_results", [])
st.session_state.setdefault("recent_runs_cache", [])
st.session_state.setdefault("recent_run_detail_cache", {})
st.session_state.setdefault("history_run_edit_state", {})
st.session_state.setdefault("verifier_view_mode", "本次任务")
st.session_state.setdefault("selected_task_key", "__current__")
st.session_state.setdefault("last_selected_task_key", "__current__")


def _drafts_root() -> Path:
    root = SRC_ROOT.parent / "outputs" / "task_drafts"
    root.mkdir(parents=True, exist_ok=True)
    return root


def _safe_run_key(run_id: str) -> str:
    cleaned = re.sub(r"[^0-9A-Za-z_\-]+", "_", str(run_id).strip())
    return cleaned or "unknown_run"


def _task_draft_path(run_id: str) -> Path:
    return _drafts_root() / f"{_safe_run_key(run_id)}.json"


def _doc_sync_queue_path() -> Path:
    return _drafts_root() / "_doc_sync_queue.json"


def _load_json_file(path: Path) -> dict:
    try:
        if not path.exists():
            return {}
        raw = json.loads(path.read_text(encoding="utf-8"))
        return raw if isinstance(raw, dict) else {}
    except Exception:  # pragma: no cover
        return {}


def _save_json_file(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _load_task_draft(run_id: str) -> dict:
    if not str(run_id).strip():
        return {}
    payload = _load_json_file(_task_draft_path(run_id))
    return payload if isinstance(payload, dict) else {}


def _save_task_draft(run_id: str, payload: dict) -> None:
    if not str(run_id).strip():
        return
    data = payload if isinstance(payload, dict) else {}
    data["run_id"] = run_id
    data["updated_at"] = datetime.now().isoformat(timespec="seconds")
    _save_json_file(_task_draft_path(run_id), data)


def _load_doc_sync_snapshot() -> dict:
    payload = _load_json_file(_doc_sync_queue_path())
    items = payload.get("items", []) if isinstance(payload, dict) else []
    if not isinstance(items, list):
        items = []
    return {"items": items}


def _save_doc_sync_snapshot(snapshot: dict) -> None:
    payload = snapshot if isinstance(snapshot, dict) else {"items": []}
    items = payload.get("items", [])
    if not isinstance(items, list):
        items = []
    _save_json_file(_doc_sync_queue_path(), {"items": items})


st.session_state.setdefault("doc_sync_pending_snapshot", _load_doc_sync_snapshot())


def _env_ready(name: str) -> bool:
    return bool(os.getenv(name, "").strip())


def _env_ready_any(*names: str) -> bool:
    return any(_env_ready(name) for name in names)


def _env_text(name: str, default: str = "") -> str:
    raw = os.getenv(name, default)
    return raw.strip().strip('"').strip("'")


def _parse_urls_from_text(text: str) -> list[str]:
    rows = [line.strip() for line in str(text).splitlines()]
    urls: list[str] = []
    seen: set[str] = set()
    for row in rows:
        if not row:
            continue
        if row in seen:
            continue
        seen.add(row)
        urls.append(row)
    return urls


def _render_docx_download_link(file_bytes: bytes, file_name: str) -> None:
    b64_data = base64.b64encode(file_bytes).decode("ascii")
    href = (
        "data:application/vnd.openxmlformats-officedocument.wordprocessingml.document;"
        f"base64,{b64_data}"
    )
    st.markdown(
        (
            f'<a href="{href}" download="{file_name}" '
            'style="display:inline-block;padding:0.45rem 0.9rem;border-radius:0.5rem;'
            'background:#16a34a;color:white;text-decoration:none;font-weight:600;">'
            "下载生成的 docx"
            "</a>"
        ),
        unsafe_allow_html=True,
    )


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


def _extract_json_object(raw: str) -> dict:
    text = str(raw).strip()
    if not text:
        return {}
    if text.startswith("```"):
        lines = text.splitlines()
        if len(lines) >= 3 and lines[-1].strip() == "```":
            text = "\n".join(lines[1:-1]).strip()
    decoder = json.JSONDecoder()
    for pos, ch in enumerate(text):
        if ch != "{":
            continue
        try:
            obj, _ = decoder.raw_decode(text[pos:])
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict):
            return obj
    return {}


def _replace_ci(text: str, old: str, new: str) -> str:
    if not old:
        return text
    return re.sub(re.escape(old), new, text, flags=re.IGNORECASE)


def _get_translation_payload(translated: dict) -> dict:
    raw = str(translated.get("translated_text", "")).strip()
    parsed = _extract_json_object(raw)
    if isinstance(parsed, dict):
        return parsed
    return {}


def _write_translation_payload(translated: dict, payload: dict) -> None:
    translated["translated_text"] = json.dumps(payload, ensure_ascii=False)


def _sync_revised_text(revised: dict) -> None:
    revision_block = revised.get("revision", {})
    if not isinstance(revision_block, dict):
        return
    paragraphs = revision_block.get("paragraphs_revised_en", [])
    if isinstance(paragraphs, list):
        revised["revised_text"] = "\n\n".join(str(item).strip() for item in paragraphs if str(item).strip())


def _save_local_task_snapshot(run_id: str, outputs: dict, artifacts: dict) -> None:
    if not str(run_id).strip():
        return
    payload = {
        "scraped": deepcopy(outputs.get("scraped", {})) if isinstance(outputs.get("scraped", {}), dict) else {},
        "translated": deepcopy(outputs.get("translated", {})) if isinstance(outputs.get("translated", {}), dict) else {},
        "revised": deepcopy(outputs.get("revised", {})) if isinstance(outputs.get("revised", {}), dict) else {},
        "verifier": deepcopy(outputs.get("verifier", {})) if isinstance(outputs.get("verifier", {}), dict) else {},
        "artifacts": deepcopy(artifacts) if isinstance(artifacts, dict) else {},
    }
    _save_task_draft(run_id, payload)


def _apply_local_task_snapshot(run_id: str, outputs: dict, artifacts: dict) -> tuple[dict, dict]:
    draft = _load_task_draft(run_id)
    if not draft:
        _save_local_task_snapshot(run_id, outputs, artifacts)
        return outputs, artifacts
    merged_outputs = {
        "scraped": draft.get("scraped", {}) if isinstance(draft.get("scraped", {}), dict) else {},
        "translated": draft.get("translated", {}) if isinstance(draft.get("translated", {}), dict) else {},
        "revised": draft.get("revised", {}) if isinstance(draft.get("revised", {}), dict) else {},
        "verifier": draft.get("verifier", {}) if isinstance(draft.get("verifier", {}), dict) else {},
    }
    merged_artifacts = draft.get("artifacts", {}) if isinstance(draft.get("artifacts", {}), dict) else {}
    return merged_outputs, merged_artifacts


def _mark_doc_sync_pending(run_id: str, local_path: str) -> None:
    if not str(run_id).strip():
        return
    snapshot = st.session_state.get("doc_sync_pending_snapshot", {})
    items = snapshot.get("items", []) if isinstance(snapshot, dict) else []
    if not isinstance(items, list):
        items = []
    now = datetime.now().isoformat(timespec="seconds")
    found = False
    for item in items:
        if not isinstance(item, dict):
            continue
        if str(item.get("run_id", "")).strip() == run_id and str(item.get("status", "pending")) == "pending":
            item["updated_at"] = now
            item["local_docx_path"] = local_path
            found = True
            break
    if not found:
        items.append(
            {
                "id": str(uuid4()),
                "run_id": run_id,
                "status": "pending",
                "reason": "verifier_local_edit",
                "updated_at": now,
                "local_docx_path": local_path,
            }
        )
    new_snapshot = {"items": items}
    st.session_state["doc_sync_pending_snapshot"] = new_snapshot
    _save_doc_sync_snapshot(new_snapshot)


def _render_entity_card_actions(
    *,
    panel_key: str,
    paragraph_id: int | str,
    entity_index: int,
    entity: dict,
    paragraph_results: list[dict],
    translated: dict,
    revised: dict,
    runner: PipelineRunner,
    run_id: str,
) -> bool:
    changed = False
    entity_zh = str(entity.get("entity_zh", "")).strip()
    entity_en = str(entity.get("entity_en", "")).strip()
    entity_type = str(entity.get("type", "other")).strip() or "other"
    button_col_1, button_col_2, button_col_3 = st.columns(3)
    replace_key = f"{panel_key}_replace_{paragraph_id}_{entity_index}"
    modify_key = f"{panel_key}_modify_{paragraph_id}_{entity_index}"
    stage_key = f"{panel_key}_stage_{paragraph_id}_{entity_index}"

    with button_col_1:
        with st.popover("替换", use_container_width=True):
            st.caption("用于修正 LLM 返回的英文实体，并同步更新段落译文。")
            replacement = st.text_input(
                "替换为",
                value=entity_en,
                key=f"{replace_key}_value",
            )
            apply_replace = st.button("应用替换", key=f"{replace_key}_submit", use_container_width=True)
            if apply_replace and replacement.strip():
                payload = _get_translation_payload(translated)
                translation = payload.get("translation", {}) if isinstance(payload.get("translation", {}), dict) else {}
                paragraphs_en = translation.get("paragraphs_en", [])
                if not isinstance(paragraphs_en, list):
                    paragraphs_en = []
                full_text_en = str(translation.get("full_text_en", ""))

                search_terms = build_entity_search_terms(entity_en, entity_type)
                candidates = build_replacement_candidates(full_text_en, paragraph_results, search_terms)
                for candidate in candidates:
                    if not isinstance(candidate, dict):
                        continue
                    term = str(candidate.get("term", "")).strip()
                    if not term:
                        continue
                    if str(candidate.get("scope", "")) == "paragraph_en":
                        pid = candidate.get("paragraph_id")
                        try:
                            pid_int = int(pid)
                        except (TypeError, ValueError):
                            continue
                        if 1 <= pid_int <= len(paragraph_results):
                            target_paragraph = paragraph_results[pid_int - 1]
                            if isinstance(target_paragraph, dict):
                                target_paragraph["en"] = _replace_ci(
                                    str(target_paragraph.get("en", "")),
                                    term,
                                    replacement.strip(),
                                )
                            revision_block = revised.get("revision", {})
                            if isinstance(revision_block, dict):
                                revised_list = revision_block.get("paragraphs_revised_en", [])
                                if isinstance(revised_list, list) and 1 <= pid_int <= len(revised_list):
                                    revised_list[pid_int - 1] = _replace_ci(
                                        str(revised_list[pid_int - 1]),
                                        term,
                                        replacement.strip(),
                                    )
                    full_text_en = _replace_ci(full_text_en, term, replacement.strip())
                    for idx, block in enumerate(paragraphs_en):
                        paragraphs_en[idx] = _replace_ci(str(block), term, replacement.strip())

                entity["entity_en"] = replacement.strip()
                translation["paragraphs_en"] = paragraphs_en
                translation["full_text_en"] = full_text_en
                payload["translation"] = translation
                _write_translation_payload(translated, payload)
                _sync_revised_text(revised)
                st.success("替换已应用。")
                changed = True

    with button_col_2:
        with st.popover("修改", use_container_width=True):
            edit_zh = st.text_input("中文实体", value=entity_zh, key=f"{modify_key}_zh")
            edit_en = st.text_input("英文实体", value=entity_en, key=f"{modify_key}_en")
            edit_type = st.text_input("类型", value=entity_type, key=f"{modify_key}_type")
            edit_reco = st.text_area(
                "建议",
                value=str(entity.get("final_recommendation", "")),
                key=f"{modify_key}_reco",
            )
            edit_verified = st.checkbox(
                "已确认",
                value=bool(entity.get("is_verified", False)),
                key=f"{modify_key}_verified",
            )
            edit_sources = st.text_area(
                "来源(JSON数组)",
                value=json.dumps(entity.get("sources", []), ensure_ascii=False, indent=2),
                key=f"{modify_key}_sources",
                height=120,
            )
            save_modify = st.button("保存修改", key=f"{modify_key}_submit", use_container_width=True)
            if save_modify:
                try:
                    parsed_sources = json.loads(edit_sources) if edit_sources.strip() else []
                    if not isinstance(parsed_sources, list):
                        raise ValueError("sources 必须为 JSON 数组")
                except Exception as err:  # pragma: no cover
                    st.error(f"来源格式错误：{err}")
                else:
                    entity["entity_zh"] = edit_zh.strip()
                    entity["entity_en"] = edit_en.strip()
                    entity["type"] = edit_type.strip() or "other"
                    entity["final_recommendation"] = edit_reco.strip()
                    entity["is_verified"] = bool(edit_verified)
                    entity["verification_status"] = "verified" if edit_verified else "unverified"
                    entity["sources"] = parsed_sources
                    st.success("实体已更新。")
                    changed = True

    with button_col_3:
        if st.button("加入待确认", key=stage_key, use_container_width=True):
            pending = runner.add_pending_change(
                {
                    "id": str(uuid4()),
                    "action": "upsert_record",
                    "selector": {
                        "entity_zh": str(entity.get("entity_zh", "")).strip(),
                        "entity_en": str(entity.get("entity_en", "")).strip(),
                        "type": str(entity.get("type", "other")).strip() or "other",
                    },
                    "record": {
                        "entity_zh": str(entity.get("entity_zh", "")).strip(),
                        "entity_en": str(entity.get("entity_en", "")).strip(),
                        "type": str(entity.get("type", "other")).strip() or "other",
                        "is_verified": bool(entity.get("is_verified", False)),
                        "verification_status": str(
                            entity.get("verification_status", "verified" if entity.get("is_verified", False) else "unverified")
                        ).strip(),
                        "sources": entity.get("sources", []) if isinstance(entity.get("sources", []), list) else [],
                        "final_recommendation": str(entity.get("final_recommendation", "")).strip(),
                    },
                    "reason": "manual_from_verifier_card",
                }
            )
            st.session_state["pending_changes_snapshot"] = pending
            st.success("已加入待确认列表。")
    return changed


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
    batch_urls_text = st.text_area(
        "批量 URL（每行一个）",
        value="https://www.bastillepost.com/hongkong/article/15731771",
        key="input_batch_urls",
        height=120,
    )
    queue_col_1, queue_col_2 = st.columns(2)
    if queue_col_1.button("加入队列"):
        added = 0
        current_queue = st.session_state.get("pipeline_url_queue", [])
        if not isinstance(current_queue, list):
            current_queue = []
        existing = set(str(item).strip() for item in current_queue if str(item).strip())
        for item in _parse_urls_from_text(batch_urls_text):
            if item not in existing:
                current_queue.append(item)
                existing.add(item)
                added += 1
        st.session_state["pipeline_url_queue"] = current_queue
        st.success(f"已加入 {added} 条 URL。")
    if queue_col_2.button("清空队列"):
        st.session_state["pipeline_url_queue"] = []
        st.session_state["pipeline_queue_results"] = []
        st.info("已清空队列。")
    queued_urls = st.session_state.get("pipeline_url_queue", [])
    if isinstance(queued_urls, list) and queued_urls:
        st.caption(f"队列长度：{len(queued_urls)}")
        with st.expander("查看排队 URL", expanded=False):
            for idx, queued_url in enumerate(queued_urls, start=1):
                st.write(f"{idx}. {queued_url}")
    else:
        st.caption("队列长度：0")
    output_dir = st.text_input("本地输出目录", value="outputs", key="input_output_dir")

    run_mode = st.radio(
        "执行模式",
        ["Mock 优先（推荐联调）", "真实优先"],
        horizontal=False,
        index=1,
    )
    use_real_scraper = st.checkbox("抓取使用真实请求", value=(run_mode == "真实优先"))
    use_real_llm = st.checkbox("翻译/润色使用真实 LLM", value=(run_mode == "真实优先"))
    use_real_storage = st.checkbox("归档使用真实 Firebase Storage", value=(run_mode == "真实优先"))
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
    btn_col_1, btn_col_2, btn_col_3, btn_col_4, btn_col_5 = st.columns(5)
    run_all = btn_col_1.button("一键执行全流程", type="primary", use_container_width=True)
    run_scraper_only = btn_col_2.button("仅执行抓取预览", use_container_width=True)
    run_until_translator = btn_col_3.button("执行到翻译阶段", use_container_width=True)
    run_until_verifier = btn_col_4.button("执行到核验阶段", use_container_width=True)
    run_queue = btn_col_5.button("执行队列", use_container_width=True)

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

if run_all or run_scraper_only or run_until_translator or run_until_verifier or run_queue:
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
            run_until_stage = (
                "scraper"
                if run_scraper_only
                else ("translator" if run_until_translator else ("verifier" if run_until_verifier else None))
            )
            if run_queue:
                queue_urls = st.session_state.get("pipeline_url_queue", [])
                if not isinstance(queue_urls, list):
                    queue_urls = []
                queue_urls = [str(item).strip() for item in queue_urls if str(item).strip()]
                if not queue_urls:
                    st.warning("队列为空，请先加入 URL。")
                    result = None
                else:
                    queue_results: list[dict] = []
                    result = None
                    for idx, queued_url in enumerate(queue_urls, start=1):
                        status_placeholder.markdown(
                            f"### 阶段状态\n正在执行队列：{idx}/{len(queue_urls)}\n\nURL: `{queued_url}`"
                        )
                        result = runner.run_full(
                            url=queued_url,
                            output_dir=output_dir,
                            options=options,
                            on_stage_update=on_stage_update,
                            on_verifier_progress=on_verifier_progress,
                            run_until_stage=None,
                        )
                        queue_results.append(
                            {
                                "index": idx,
                                "url": queued_url,
                                "ok": bool(result.get("ok")),
                                "run_id": str(result.get("run_id", "")),
                                "error": (result.get("error") or {}).get("message", ""),
                                "docx_local_path": str(
                                    (result.get("artifacts") or {}).get("docx_local_path", "")
                                ),
                                "docx_cloud_path": str(
                                    (result.get("artifacts") or {}).get("docx_cloud_path", "")
                                ),
                            }
                        )
                        if idx < len(queue_urls):
                            sleep_seconds = random.uniform(2.0, 5.0)
                            logs = st.session_state.get("pipeline_runtime_logs", [])
                            logs.append(
                                {
                                    "time": datetime.now().strftime("%H:%M:%S"),
                                    "stage": "queue",
                                    "message": (
                                        f"[queue] 限流保护：任务间暂停 {sleep_seconds:.1f}s "
                                        f"（{idx}/{len(queue_urls)} -> {idx + 1}/{len(queue_urls)}）"
                                    ),
                                }
                            )
                            st.session_state["pipeline_runtime_logs"] = logs
                            _render_runtime_progress()
                            time.sleep(sleep_seconds)
                    st.session_state["pipeline_queue_results"] = queue_results
            else:
                queue_urls = st.session_state.get("pipeline_url_queue", [])
                if not isinstance(queue_urls, list):
                    queue_urls = []
                queue_urls = [str(item).strip() for item in queue_urls if str(item).strip()]
                if not queue_urls:
                    st.warning("队列为空，请先在“批量 URL”里加入至少一条。")
                    result = None
                else:
                    single_url = queue_urls[0]
                    status_placeholder.markdown(f"### 阶段状态\n当前 URL: `{single_url}`")
                    result = runner.run_full(
                        url=single_url,
                        output_dir=output_dir,
                        options=options,
                        on_stage_update=on_stage_update,
                        on_verifier_progress=on_verifier_progress,
                        run_until_stage=run_until_stage,
                    )
        if result:
            update_from_run_result(result)
        if result and result.get("ok"):
            if run_queue:
                st.success("队列执行完成。已展示最后一条任务结果。")
            else:
                st.success("执行完成。")
        else:
            if result:
                st.warning("执行中断，已保留可用阶段结果。")
    except SettingsError as err:
        st.error(str(err))
    except Exception as err:  # pragma: no cover
        st.exception(err)

st.markdown("### 阶段状态")
_render_stage_board(st.session_state.get("pipeline_stage_states", {}))
queue_results = st.session_state.get("pipeline_queue_results", [])
if isinstance(queue_results, list) and queue_results:
    with st.expander("最近一次队列执行结果", expanded=False):
        queue_runner = PipelineRunner()
        for item in queue_results:
            if not isinstance(item, dict):
                continue
            mark = "✅" if item.get("ok") else "❌"
            st.write(
                f"{mark} #{item.get('index', '')} | run_id={item.get('run_id', '')} | "
                f"url={item.get('url', '')}"
            )
            if item.get("docx_local_path"):
                st.caption(f"docx：{item.get('docx_local_path')}")
            if item.get("error"):
                st.caption(f"错误：{item.get('error')}")
            run_val = str(item.get("run_id", "")).strip()
            if run_val and st.button("回看此任务", key=f"queue_open_history_{run_val}"):
                try:
                    detail = queue_runner.load_run_detail(run_id=run_val)
                    st.session_state["recent_run_detail_cache"] = detail
                    st.session_state["history_run_edit_state"][run_val] = {
                        "scraped": detail.get("raw_article", {}) if isinstance(detail.get("raw_article", {}), dict) else {},
                        "translated": detail.get("translated", {}) if isinstance(detail.get("translated", {}), dict) else {},
                        "revised": detail.get("revised", {}) if isinstance(detail.get("revised", {}), dict) else {},
                        "verifier": detail.get("verifier", {}) if isinstance(detail.get("verifier", {}), dict) else {},
                        "artifacts": {
                            "docx_local_path": str(item.get("docx_local_path", "")),
                            "docx_cloud_path": str(detail.get("docx_cloud_path", "")),
                        },
                    }
                    st.session_state["selected_task_key"] = run_val
                    st.success(f"已加载回看任务：{run_val}")
                except Exception as err:  # pragma: no cover
                    st.exception(err)

task_picker_runner = PipelineRunner()
picker_col_1, picker_col_2 = st.columns([1, 3])
refresh_task_picker = picker_col_1.button("刷新任务列表", key="refresh_task_picker")
if refresh_task_picker or "recent_runs_cache" not in st.session_state:
    try:
        st.session_state["recent_runs_cache"] = task_picker_runner.list_recent_runs(limit=20)
        st.session_state.pop("recent_runs_error", None)
    except Exception as err:  # pragma: no cover
        st.session_state["recent_runs_error"] = str(err)
        st.session_state["recent_runs_cache"] = []
picker_runs = st.session_state.get("recent_runs_cache", [])
picker_options = ["__current__"]
if isinstance(picker_runs, list):
    for row in picker_runs:
        if not isinstance(row, dict):
            continue
        run_val = str(row.get("run_id", "")).strip()
        if run_val:
            picker_options.append(run_val)
selected_task_key = picker_col_2.selectbox(
    "任务选择（当前运行或历史任务）",
    options=picker_options,
    index=picker_options.index(st.session_state.get("selected_task_key", "__current__"))
    if st.session_state.get("selected_task_key", "__current__") in picker_options
    else 0,
    format_func=lambda key: (
        "当前运行结果"
        if key == "__current__"
        else (
            next(
                (
                    f"{str(item.get('run_id', ''))} | {str(item.get('overall_status', 'unknown'))} | "
                    f"{str(item.get('ended_at', '') or item.get('log_updated_at', ''))}"
                    for item in picker_runs
                    if isinstance(item, dict) and str(item.get("run_id", "")).strip() == key
                ),
                key,
            )
        )
    ),
    key="selected_task_key",
)
previous_task_key = str(st.session_state.get("last_selected_task_key", "__current__"))
if selected_task_key != previous_task_key:
    pending_payload_for_warn = st.session_state.get("pending_changes_snapshot", {})
    pending_items_for_warn = (
        pending_payload_for_warn.get("items", []) if isinstance(pending_payload_for_warn, dict) else []
    )
    db_pending_count = sum(
        1
        for item in (pending_items_for_warn if isinstance(pending_items_for_warn, list) else [])
        if isinstance(item, dict) and str(item.get("status", "pending")) == "pending"
    )
    doc_sync_snapshot = st.session_state.get("doc_sync_pending_snapshot", {})
    doc_sync_items = doc_sync_snapshot.get("items", []) if isinstance(doc_sync_snapshot, dict) else []
    doc_pending_count = sum(
        1
        for item in (doc_sync_items if isinstance(doc_sync_items, list) else [])
        if isinstance(item, dict) and str(item.get("status", "pending")) == "pending"
    )
    if db_pending_count or doc_pending_count:
        st.warning(
            "你有未同步变更："
            f"数据库待确认 {db_pending_count} 条，文档待同步 {doc_pending_count} 条。"
            "建议先到“确认修改”完成同步。"
        )
    st.session_state["last_selected_task_key"] = selected_task_key
if selected_task_key != "__current__":
    if selected_task_key not in st.session_state["history_run_edit_state"]:
        selected_row = next(
            (
                item
                for item in (picker_runs if isinstance(picker_runs, list) else [])
                if isinstance(item, dict) and str(item.get("run_id", "")).strip() == selected_task_key
            ),
            {},
        )
        try:
            detail = task_picker_runner.load_run_detail(
                run_id=selected_task_key,
                log_blob_path=str(selected_row.get("log_blob_path", "")) if isinstance(selected_row, dict) else "",
            )
            st.session_state["history_run_edit_state"][selected_task_key] = {
                "scraped": detail.get("raw_article", {}) if isinstance(detail.get("raw_article", {}), dict) else {},
                "translated": detail.get("translated", {}) if isinstance(detail.get("translated", {}), dict) else {},
                "revised": detail.get("revised", {}) if isinstance(detail.get("revised", {}), dict) else {},
                "verifier": detail.get("verifier", {}) if isinstance(detail.get("verifier", {}), dict) else {},
                "artifacts": {
                    "docx_local_path": "",
                    "docx_cloud_path": str(detail.get("docx_cloud_path", "")),
                },
            }
        except Exception as err:  # pragma: no cover
            st.error(f"加载历史任务失败：{err}")

tabs = st.tabs(["抓取", "翻译", "核验结果", "润色", "产物归档", "日志错误"])
verifier_tabs = []
if selected_task_key == "__current__":
    outputs = st.session_state.get("pipeline_stage_outputs", {})
    artifacts = st.session_state.get("pipeline_artifacts", {})
    error_payload = st.session_state.get("pipeline_error")
    run_id = st.session_state.get("pipeline_run_id", "")
else:
    cached_task = st.session_state["history_run_edit_state"].get(selected_task_key, {})
    outputs = {
        "scraped": cached_task.get("scraped", {}) if isinstance(cached_task, dict) else {},
        "translated": cached_task.get("translated", {}) if isinstance(cached_task, dict) else {},
        "revised": cached_task.get("revised", {}) if isinstance(cached_task, dict) else {},
        "verifier": cached_task.get("verifier", {}) if isinstance(cached_task, dict) else {},
    }
    artifacts = cached_task.get("artifacts", {}) if isinstance(cached_task, dict) else {}
    error_payload = None
    run_id = selected_task_key
if run_id:
    outputs, artifacts = _apply_local_task_snapshot(run_id, outputs, artifacts)
    _save_local_task_snapshot(run_id, outputs, artifacts if isinstance(artifacts, dict) else {})

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
    verifier_tabs = st.tabs(["本次核验", "大模型审核", "人工合并", "确认修改", "线上词库"])
    verifier_tab = verifier_tabs[0]
    review_tab = verifier_tabs[1]
    manual_merge_tab = verifier_tabs[2]
    confirm_tab = verifier_tabs[3]
    db_tab = verifier_tabs[4]

    with verifier_tab:
        history_runner = PipelineRunner()
        active_run_id = run_id
        active_scraped = outputs.get("scraped", {}) if isinstance(outputs.get("scraped", {}), dict) else {}
        active_translated = outputs.get("translated", {}) if isinstance(outputs.get("translated", {}), dict) else {}
        active_revised = outputs.get("revised", {}) if isinstance(outputs.get("revised", {}), dict) else {}
        active_verifier = outputs.get("verifier", {}) if isinstance(outputs.get("verifier", {}), dict) else {}
        active_artifacts = artifacts
        history_mode = selected_task_key != "__current__"
        st.caption(f"当前任务：{active_run_id or '未运行'}")

        if active_verifier:
            stage_col_1, stage_col_2 = st.columns(2)
            if stage_col_1.button(
                "将本页已确认实体加入待确认列表",
                key=f"stage_verifier_pending_{active_run_id or 'current'}",
            ):
                try:
                    staged_stats = history_runner.stage_verified_entities_as_pending(active_run_id or run_id, active_verifier)
                    snapshot = history_runner.get_synonym_review_snapshot()
                    st.session_state["pending_changes_snapshot"] = snapshot.get("pending", {})
                    st.success(
                        f"已加入待确认：扫描 {staged_stats.get('scanned', 0)}，新增 {staged_stats.get('staged', 0)}。"
                    )
                except Exception as err:  # pragma: no cover
                    st.exception(err)

            if stage_col_2.button(
                "重生成本地 docx（待同步线上）",
                key=f"rebuild_task_docx_{active_run_id or 'current'}",
            ):
                try:
                    rebuilt = history_runner.build_local_run_docx(
                        run_id=active_run_id,
                        scraped=active_scraped,
                        translated=active_translated,
                        revised=active_revised,
                        llm_model=selected_model,
                    )
                    active_artifacts.update(rebuilt)
                    if history_mode and active_run_id in st.session_state["history_run_edit_state"]:
                        st.session_state["history_run_edit_state"][active_run_id]["artifacts"] = active_artifacts
                    else:
                        st.session_state["pipeline_artifacts"] = {
                            **st.session_state.get("pipeline_artifacts", {}),
                            **active_artifacts,
                        }
                    queue_rows = st.session_state.get("pipeline_queue_results", [])
                    if isinstance(queue_rows, list):
                        for row in queue_rows:
                            if isinstance(row, dict) and str(row.get("run_id", "")) == active_run_id:
                                row["docx_local_path"] = rebuilt.get("docx_local_path", "")
                                row["docx_cloud_path"] = rebuilt.get("docx_cloud_path", "")
                        st.session_state["pipeline_queue_results"] = queue_rows
                    _mark_doc_sync_pending(active_run_id or run_id, rebuilt.get("docx_local_path", ""))
                    _save_local_task_snapshot(
                        active_run_id or run_id,
                        {
                            "scraped": active_scraped,
                            "translated": active_translated,
                            "revised": active_revised,
                            "verifier": active_verifier,
                        },
                        active_artifacts if isinstance(active_artifacts, dict) else {},
                    )
                    st.success("已更新本地 docx，并加入文档同步待确认。")
                except Exception as err:  # pragma: no cover
                    st.exception(err)

            summary = active_verifier.get("summary", {})
            c1, c2, c3 = st.columns(3)
            c1.metric("实体总数", int(summary.get("total_entities", 0)))
            c2.metric("已确认", int(summary.get("verified_entities", 0)))
            c3.metric("未确认", int(summary.get("unresolved_entities", 0)))

            notes = active_verifier.get("alignment_notes", [])
            if notes:
                with st.expander("段落对齐说明"):
                    st.json(notes)

            paragraph_results = active_verifier.get("paragraph_results", [])
            if isinstance(paragraph_results, list) and paragraph_results:
                changed = False
                runtime_statuses = {"runtime_cache_hit"}
                database_statuses = {"db_exact_hit", "db_synonym_hit"}
                for p_idx, item in enumerate(paragraph_results, start=1):
                    if not isinstance(item, dict):
                        continue
                    paragraph_id = item.get("paragraph_id", p_idx)
                    verified_entities = item.get("verified_entities", [])
                    if not isinstance(verified_entities, list):
                        verified_entities = []
                    runtime_hits: list[dict] = []
                    database_hits: list[dict] = []
                    llm_entities: list[dict] = []
                    for entity in verified_entities:
                        if not isinstance(entity, dict):
                            continue
                        status_key = str(entity.get("verification_status", "")).strip()
                        if status_key in runtime_statuses:
                            runtime_hits.append(entity)
                        elif status_key in database_statuses:
                            database_hits.append(entity)
                        else:
                            llm_entities.append(entity)
                    llm_verified_count = sum(
                        1 for entity in llm_entities if bool(entity.get("is_verified", False))
                    )
                    llm_unverified_count = max(len(llm_entities) - llm_verified_count, 0)
                    counter_parts: list[str] = []
                    if runtime_hits:
                        counter_parts.append(f"命中runtime缓存 {len(runtime_hits)}")
                    if database_hits:
                        counter_parts.append(f"命中database {len(database_hits)}")
                    if llm_verified_count:
                        counter_parts.append(f"verified {llm_verified_count}")
                    if llm_unverified_count:
                        counter_parts.append(f"unverified {llm_unverified_count}")
                    expander_title = f"段落 {paragraph_id}"
                    if counter_parts:
                        expander_title += f" | {'，'.join(counter_parts)}"
                    with st.expander(expander_title, expanded=False):
                        st.caption("中文")
                        st.write(item.get("zh", ""))
                        st.caption("英文")
                        st.write(item.get("en", ""))
                        if not llm_entities:
                            st.info("该段未识别到需要核验的实体。")
                        for e_idx, entity in enumerate(llm_entities):
                            if not isinstance(entity, dict):
                                continue
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
                            sources = entity.get("sources", [])
                            if isinstance(sources, list) and sources:
                                for src in sources:
                                    if not isinstance(src, dict):
                                        continue
                                    src_url = str(src.get("url", "")).strip()
                                    site = str(src.get("site", "")).strip()
                                    note = str(src.get("evidence_note", "")).strip()
                                    if src_url:
                                        st.markdown(f"- [{site or src_url}]({src_url})")
                                    if note:
                                        st.caption(f"证据说明：{note}")
                            changed = _render_entity_card_actions(
                                panel_key=f"{'history' if history_mode else 'current'}_{active_run_id}_{paragraph_id}",
                                paragraph_id=paragraph_id,
                                entity_index=e_idx,
                                entity=entity,
                                paragraph_results=paragraph_results,
                                translated=active_translated,
                                revised=active_revised,
                                runner=history_runner,
                                run_id=active_run_id or run_id,
                            ) or changed
                        if runtime_hits:
                            st.caption(f"命中 runtime 缓存（{len(runtime_hits)}）")
                            for entity in runtime_hits:
                                st.write(
                                    f"- {entity.get('entity_zh', '')} / "
                                    f"{entity.get('entity_en', '')} ({entity.get('type', 'other')})"
                                )
                        if database_hits:
                            st.caption(f"命中线上 database（{len(database_hits)}）")
                            for entity in database_hits:
                                st.write(
                                    f"- {entity.get('entity_zh', '')} / "
                                    f"{entity.get('entity_en', '')} ({entity.get('type', 'other')})"
                                )

                if changed:
                    if history_mode and active_run_id:
                        st.session_state["history_run_edit_state"][active_run_id] = {
                            "scraped": active_scraped,
                            "translated": active_translated,
                            "revised": active_revised,
                            "verifier": active_verifier,
                            "artifacts": active_artifacts if isinstance(active_artifacts, dict) else {},
                        }
                    else:
                        outputs["translated"] = active_translated
                        outputs["revised"] = active_revised
                        outputs["verifier"] = active_verifier
                        st.session_state["pipeline_stage_outputs"] = outputs
                    if active_run_id:
                        try:
                            rebuilt = history_runner.build_local_run_docx(
                                run_id=active_run_id,
                                scraped=active_scraped,
                                translated=active_translated,
                                revised=active_revised,
                                llm_model=selected_model,
                            )
                            active_artifacts.update(rebuilt)
                            if history_mode and active_run_id:
                                st.session_state["history_run_edit_state"][active_run_id]["artifacts"] = (
                                    active_artifacts
                                )
                            else:
                                st.session_state["pipeline_artifacts"] = {
                                    **st.session_state.get("pipeline_artifacts", {}),
                                    **active_artifacts,
                                }
                            queue_rows = st.session_state.get("pipeline_queue_results", [])
                            if isinstance(queue_rows, list):
                                for row in queue_rows:
                                    if isinstance(row, dict) and str(row.get("run_id", "")) == active_run_id:
                                        row["docx_local_path"] = rebuilt.get("docx_local_path", "")
                                        row["docx_cloud_path"] = rebuilt.get("docx_cloud_path", "")
                                st.session_state["pipeline_queue_results"] = queue_rows
                            _mark_doc_sync_pending(active_run_id, rebuilt.get("docx_local_path", ""))
                            _save_local_task_snapshot(
                                active_run_id,
                                {
                                    "scraped": active_scraped,
                                    "translated": active_translated,
                                    "revised": active_revised,
                                    "verifier": active_verifier,
                                },
                                active_artifacts if isinstance(active_artifacts, dict) else {},
                            )
                            st.success("已更新本地 docx，并加入文档同步待确认。")
                        except Exception as err:  # pragma: no cover
                            st.warning(f"自动重生成 docx 失败：{err}")
                    st.rerun()
            else:
                st.info("暂无逐段核验结果。")
        else:
            st.info("当前模式下暂无核验结果。")

    with verifier_tabs[1]:
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

    with verifier_tabs[2]:
        st.caption("人工补充合并：左右各选一条，先模拟合并，再确认写入待处理条目。")
        runner = PipelineRunner()
        selected_left_item = None
        selected_right_item = None
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

    with verifier_tabs[3]:
        st.caption("所有改动先落本地；在此页手动同步到线上。")
        runner = PipelineRunner()
        st.markdown("#### 数据库同步")
        st.caption("这里处理实体词库变更（pending_changes）。")
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
        waiting_items: list[tuple[int, dict]] = []
        history_items: list[tuple[int, dict]] = []
        for idx, item in enumerate(pending_items):
            if not isinstance(item, dict):
                continue
            status = str(item.get("status", "pending")).strip() or "pending"
            if status == "pending":
                waiting_items.append((idx, item))
            else:
                history_items.append((idx, item))
        st.metric("待处理条目数", len(waiting_items))
        for idx, item in waiting_items:
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
        st.markdown("#### 历史修改检索（已处理）")
        st.caption("默认不加载历史结果，只有点击搜索后才渲染结果。")
        st.session_state.setdefault("pending_history_search_results", [])
        st.session_state.setdefault("pending_history_search_executed", False)
        with st.form("pending_history_search_form"):
            search_task = st.text_input("任务关键词", key="pending_history_search_task")
            search_time = st.text_input("时间关键词", key="pending_history_search_time")
            search_action = st.selectbox(
                "动作类型",
                options=["全部", "update_record", "delete_record", "merge_records", "mark_reviewed"],
                key="pending_history_search_action",
            )
            submit_col_1, submit_col_2 = st.columns(2)
            run_history_search = submit_col_1.form_submit_button("搜索")
            clear_history_search = submit_col_2.form_submit_button("清空结果")
        if clear_history_search:
            st.session_state["pending_history_search_results"] = []
            st.session_state["pending_history_search_executed"] = False
        if run_history_search:
            filtered_history: list[tuple[int, dict]] = []
            for idx, item in history_items:
                action = str(item.get("action", "")).strip()
                run_scope = str(item.get("run_scope", item.get("run_id", ""))).strip()
                saved_at = str(item.get("saved_at", item.get("updated_at", ""))).strip()
                if search_action != "全部" and action != search_action:
                    continue
                if search_task.strip() and search_task.strip() not in run_scope:
                    continue
                if search_time.strip() and search_time.strip() not in saved_at:
                    continue
                filtered_history.append((idx, item))
            st.session_state["pending_history_search_results"] = filtered_history[:50]
            st.session_state["pending_history_search_executed"] = True
        if st.session_state.get("pending_history_search_executed", False):
            filtered_history = st.session_state.get("pending_history_search_results", [])
            st.caption(f"命中历史条目：{len(filtered_history)}（最多展示 50 条）")
            for idx, item in filtered_history:
                action = str(item.get("action", ""))
                status = str(item.get("status", ""))
                run_scope = str(item.get("run_scope", item.get("run_id", ""))).strip()
                saved_at = str(item.get("saved_at", item.get("updated_at", ""))).strip()
                with st.expander(
                    f"{idx + 1}. {action} | status={status} | run={run_scope or '-'} | {saved_at or '-'}",
                    expanded=False,
                ):
                    st.json(item)
        else:
            st.caption("请输入检索条件并点击“搜索”后再查看历史结果。")
        if st.button("确认同步数据库", type="primary", key="apply_pending_changes"):
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
        st.markdown("---")
        st.markdown("#### 文档同步")
        st.caption("这里把本地草稿文档同步到线上 runs 文档。")
        doc_sync_snapshot = st.session_state.get("doc_sync_pending_snapshot", {})
        doc_sync_items = doc_sync_snapshot.get("items", []) if isinstance(doc_sync_snapshot, dict) else []
        if not isinstance(doc_sync_items, list):
            doc_sync_items = []
        doc_pending_items = [
            item
            for item in doc_sync_items
            if isinstance(item, dict) and str(item.get("status", "pending")) == "pending"
        ]
        st.metric("文档待同步任务数", len(doc_pending_items))
        for idx, item in enumerate(doc_pending_items):
            doc_run_id = str(item.get("run_id", "")).strip()
            local_docx_path = str(item.get("local_docx_path", "")).strip()
            updated_at = str(item.get("updated_at", "")).strip()
            st.write(
                f"{idx + 1}. run_id={doc_run_id or '-'} | 本地文档={local_docx_path or '-'} | 更新时间={updated_at or '-'}"
            )
        if st.button("确认同步文档到线上", key="apply_pending_doc_sync"):
            updated_items: list[dict] = []
            success_count = 0
            for item in doc_sync_items:
                if not isinstance(item, dict):
                    continue
                if str(item.get("status", "pending")) != "pending":
                    updated_items.append(item)
                    continue
                doc_run_id = str(item.get("run_id", "")).strip()
                if not doc_run_id:
                    item["status"] = "failed"
                    item["error"] = "missing run_id"
                    updated_items.append(item)
                    continue
                draft_payload = _load_task_draft(doc_run_id)
                scraped_payload = (
                    draft_payload.get("scraped", {}) if isinstance(draft_payload.get("scraped", {}), dict) else {}
                )
                translated_payload = (
                    draft_payload.get("translated", {})
                    if isinstance(draft_payload.get("translated", {}), dict)
                    else {}
                )
                revised_payload = (
                    draft_payload.get("revised", {}) if isinstance(draft_payload.get("revised", {}), dict) else {}
                )
                if not scraped_payload or not revised_payload:
                    item["status"] = "failed"
                    item["error"] = "missing local draft payload"
                    updated_items.append(item)
                    continue
                try:
                    synced = runner.rebuild_run_docx(
                        run_id=doc_run_id,
                        scraped=scraped_payload,
                        translated=translated_payload,
                        revised=revised_payload,
                        llm_model=selected_model,
                    )
                    artifacts_payload = (
                        draft_payload.get("artifacts", {})
                        if isinstance(draft_payload.get("artifacts", {}), dict)
                        else {}
                    )
                    artifacts_payload.update(synced)
                    draft_payload["artifacts"] = artifacts_payload
                    _save_task_draft(doc_run_id, draft_payload)
                    if doc_run_id in st.session_state["history_run_edit_state"]:
                        st.session_state["history_run_edit_state"][doc_run_id]["artifacts"] = artifacts_payload
                    if doc_run_id == run_id:
                        st.session_state["pipeline_artifacts"] = {
                            **st.session_state.get("pipeline_artifacts", {}),
                            **artifacts_payload,
                        }
                    item["status"] = "synced"
                    item["synced_at"] = datetime.now().isoformat(timespec="seconds")
                    item["cloud_docx_path"] = synced.get("docx_cloud_path", "")
                    success_count += 1
                except Exception as err:  # pragma: no cover
                    item["status"] = "failed"
                    item["error"] = str(err)
                updated_items.append(item)
            new_doc_snapshot = {"items": updated_items}
            st.session_state["doc_sync_pending_snapshot"] = new_doc_snapshot
            _save_doc_sync_snapshot(new_doc_snapshot)
            st.success(f"文档同步完成：成功 {success_count} 条。")

    with verifier_tabs[4]:
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
    scraped_output = outputs.get("scraped", {}) if isinstance(outputs.get("scraped", {}), dict) else {}
    if scraped_output:
        byline_preview = resolve_bylines(
            scraped_author=str(scraped_output.get("author", "")),
            scraped_title=str(scraped_output.get("title", "")),
        )
        missing_items: list[str] = []
        if not str(byline_preview.get("ending_author_en", "")).strip():
            missing_items.append("作者映射")
        if not str(byline_preview.get("ending_column_en", "")).strip():
            missing_items.append("栏目映射")
        if missing_items:
            st.warning(
                "命名映射未命中："
                f"{'、'.join(missing_items)}。"
                "当前文档将不会填入对应英文字段，请检查对照表是否包含该作者/栏目别名。"
            )
        else:
            st.caption(
                "命名映射命中："
                f"作者={byline_preview.get('ending_author_en', '')} | "
                f"栏目={byline_preview.get('ending_column_en', '')}"
            )
    st.write(f"run_id：`{run_id}`" if run_id else "run_id：尚未生成")
    local_path = artifacts.get("docx_local_path", "")
    cloud_path = artifacts.get("docx_cloud_path", "")
    st.write(f"本地 docx：`{local_path}`" if local_path else "本地 docx：暂无")
    st.write(f"云端路径：`{cloud_path}`" if cloud_path else "云端路径：暂无")
    revised_output = outputs.get("revised", {}) if isinstance(outputs.get("revised", {}), dict) else {}
    preview_text = str(revised_output.get("revised_text", "")).strip()
    if not preview_text:
        revision_block = revised_output.get("revision", {}) if isinstance(revised_output, dict) else {}
        revised_paragraphs = (
            revision_block.get("revised_paragraphs", []) if isinstance(revision_block, dict) else []
        )
        if isinstance(revised_paragraphs, list) and revised_paragraphs:
            preview_text = "\n\n".join(str(item).strip() for item in revised_paragraphs if str(item).strip())
    if preview_text:
        st.markdown("#### 当前文档预览")
        st.text_area(
            "latest_doc_preview",
            value=preview_text,
            height=260,
            key=f"latest_doc_preview_{run_id or 'none'}",
        )
    else:
        st.info("当前任务暂无可预览文稿。")
    if local_path and Path(local_path).exists():
        revision_block = revised_output.get("revision", {}) if isinstance(revised_output, dict) else {}
        title_for_download = ""
        if isinstance(revision_block, dict):
            title_for_download = str(revision_block.get("title_revised_en", "")).strip()
        if needs_title_shorten(title_for_download, max_words=10):
            title_for_download = fallback_short_title(title_for_download, max_words=10)
        st.markdown("#### 下载当前最新文档")
        with Path(local_path).open("rb") as fp:
            _render_docx_download_link(
                file_bytes=fp.read(),
                file_name=safe_docx_name(title=title_for_download, fallback=Path(local_path).stem),
            )
    elif run_id:
        st.caption("当前任务暂无本地 docx 文件。可在“核验结果”页点击“重生成并覆盖本任务 docx”后再下载。")
    queue_results = st.session_state.get("pipeline_queue_results", [])
    if selected_task_key == "__current__" and isinstance(queue_results, list) and queue_results:
        st.markdown("#### 队列任务 docx 下载")
        for item in queue_results:
            if not isinstance(item, dict):
                continue
            if not item.get("ok"):
                continue
            item_path = str(item.get("docx_local_path", "")).strip()
            if not item_path or not Path(item_path).exists():
                continue
            label = (
                f"队列#{item.get('index', '')} | run_id={item.get('run_id', '')} | "
                f"url={item.get('url', '')}"
            )
            st.caption(label)
            with Path(item_path).open("rb") as fp:
                _render_docx_download_link(
                    file_bytes=fp.read(),
                    file_name=Path(item_path).name,
                )

with tabs[5]:
    st.subheader("日志与错误")
    if selected_task_key == "__current__":
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
    else:
        st.caption("历史任务模式仅展示当前选中任务的结果快照，不展示当次运行时日志。")
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

