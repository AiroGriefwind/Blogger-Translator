from __future__ import annotations

from copy import deepcopy
from typing import Any

import streamlit as st


STAGE_ORDER = ["scraper", "translator", "verifier", "revisor", "formatter", "storage"]


def make_empty_stage_states() -> dict[str, dict[str, str]]:
    return {stage: {"status": "pending", "detail": ""} for stage in STAGE_ORDER}


def init_ui_state() -> None:
    st.session_state.setdefault("pipeline_stage_states", make_empty_stage_states())
    st.session_state.setdefault("pipeline_stage_outputs", {})
    st.session_state.setdefault("pipeline_error", None)
    st.session_state.setdefault("pipeline_artifacts", {})
    st.session_state.setdefault("pipeline_run_id", "")
    st.session_state.setdefault("pipeline_last_mode", "mock")
    st.session_state.setdefault("pipeline_verify_progress", {"done": 0, "total": 0, "percent": 0.0})
    st.session_state.setdefault("pipeline_runtime_logs", [])


def reset_pipeline_state() -> None:
    st.session_state["pipeline_stage_states"] = make_empty_stage_states()
    st.session_state["pipeline_stage_outputs"] = {}
    st.session_state["pipeline_error"] = None
    st.session_state["pipeline_artifacts"] = {}
    st.session_state["pipeline_run_id"] = ""
    st.session_state["pipeline_verify_progress"] = {"done": 0, "total": 0, "percent": 0.0}
    st.session_state["pipeline_runtime_logs"] = []


def update_from_run_result(result: dict[str, Any]) -> None:
    st.session_state["pipeline_stage_states"] = deepcopy(
        result.get("stage_states", make_empty_stage_states())
    )
    st.session_state["pipeline_stage_outputs"] = deepcopy(result.get("stage_outputs", {}))
    st.session_state["pipeline_error"] = deepcopy(result.get("error"))
    st.session_state["pipeline_artifacts"] = deepcopy(result.get("artifacts", {}))
    st.session_state["pipeline_run_id"] = str(result.get("run_id", ""))
    st.session_state["pipeline_last_mode"] = str(result.get("mode", "unknown"))
    runtime = result.get("runtime", {})
    st.session_state["pipeline_verify_progress"] = deepcopy(
        runtime.get("verify_progress", {"done": 0, "total": 0, "percent": 0.0})
    )
    st.session_state["pipeline_runtime_logs"] = deepcopy(runtime.get("logs", []))

