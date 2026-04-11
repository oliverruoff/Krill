"""Reusable execution pipeline registry for common task shapes."""

from __future__ import annotations

from typing import TypedDict


class PipelineSpec(TypedDict):
    pipeline_id: str
    summary: str
    ordered_steps: list[str]
    fallback_policy: list[str]


_PIPELINES: dict[str, PipelineSpec] = {
    "fetch_validate_apply_verify_pipeline": {
        "pipeline_id": "fetch_validate_apply_verify_pipeline",
        "summary": "Fetch an artifact, validate it, apply it, then verify the outcome.",
        "ordered_steps": ["resolve inputs", "fetch", "validate", "apply", "verify", "finalize"],
        "fallback_policy": ["native integration", "alternate native route", "browser route", "manual artifact output"],
    },
    "repo_modify_diff_finalize_pipeline": {
        "pipeline_id": "repo_modify_diff_finalize_pipeline",
        "summary": "Inspect repo state, modify files, validate the diff, and finalize the requested repo action.",
        "ordered_steps": ["inspect", "modify", "validate diff", "finalize", "verify"],
        "fallback_policy": ["repo-aware tool", "local file route", "patch artifact"],
    },
    "resolve_target_apply_confirm_pipeline": {
        "pipeline_id": "resolve_target_apply_confirm_pipeline",
        "summary": "Resolve the target, apply the action, and confirm the resulting remote state.",
        "ordered_steps": ["resolve target", "apply action", "confirm state", "finalize"],
        "fallback_policy": ["native integration", "alternate integration", "browser route"],
    },
    "fetch_transform_publish_verify_pipeline": {
        "pipeline_id": "fetch_transform_publish_verify_pipeline",
        "summary": "Fetch structured data, transform it, publish it, and verify delivery.",
        "ordered_steps": ["fetch", "transform", "publish", "verify"],
        "fallback_policy": ["native integration", "alternate native route", "browser route"],
    },
    "inspect_route_execute_verify_pipeline": {
        "pipeline_id": "inspect_route_execute_verify_pipeline",
        "summary": "Inspect the task, route to the best tool family, execute, and verify the outcome.",
        "ordered_steps": ["inspect", "route", "execute", "verify"],
        "fallback_policy": ["preferred tool family", "alternate tool family", "browser route"],
    },
}


def get_pipeline_spec(pipeline_id: str) -> PipelineSpec:
    return _PIPELINES.get(pipeline_id, _PIPELINES["inspect_route_execute_verify_pipeline"])
