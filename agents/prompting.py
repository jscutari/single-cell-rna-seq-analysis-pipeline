"""Builds agent messages from agents/prompts/*.md.

Every system message starts with the same shared prefix (environment, helpers,
dataset, brief) followed by the role's instructions. vLLM's prefix cache then
computes the shared part once and reuses it for every agent and every call.
"""

import json
from functools import cache
from pathlib import Path
from typing import Any

from shared.schemas import Brief

PROMPTS = Path(__file__).parent / "prompts"
# Columns that add tokens but nothing an analyst would use.
_HIDDEN_COLUMN_SUFFIXES = ("_ontology_term_id",)
_HIDDEN_COLUMNS = {"observation_joinid", "is_primary_data", "suspension_type", "tissue_type"}


@cache
def _template(name: str) -> str:
    return (PROMPTS / f"{name}.md").read_text()


def render(name: str, **values: Any) -> str:
    text = _template(name)
    for key, value in values.items():
        text = text.replace("{{" + key + "}}", str(value))
    return text


def render_dataset(summary: dict) -> str:
    lines = [f"{summary['n_cells']} cells x {summary['n_genes']} genes. Cell metadata columns (`adata.obs`):"]
    for col, info in summary["obs_columns"].items():
        if col in _HIDDEN_COLUMNS or col.endswith(_HIDDEN_COLUMN_SUFFIXES):
            continue
        if "counts" in info:
            levels = ", ".join(f"{k} ({v})" for k, v in info["counts"].items())
            lines.append(f"- `{col}`: {levels}")
        elif "range" in info:
            lo, hi = info["range"]
            lines.append(f"- `{col}`: numeric, {lo:g} to {hi:g}")
        else:
            lines.append(f"- `{col}`: {info['n_unique']} distinct values")
    if summary.get("removed_columns"):
        lines.append(f"(Removed precomputed scores: {', '.join(summary['removed_columns'])}.)")
    return "\n".join(lines)


def render_brief(brief: Brief) -> str:
    fields = brief.model_dump(exclude={"project_id", "online_search"})
    return "\n".join(f"- {k}: {json.dumps(v) if isinstance(v, list) else v}" for k, v in fields.items() if v)


def shared_prefix(summary: dict, brief: Brief) -> str:
    return render("shared", dataset=render_dataset(summary), brief=render_brief(brief))


def messages(prefix: str, role: str, user: str, **role_values: Any) -> list[dict[str, str]]:
    return [
        {"role": "system", "content": prefix + "\n" + render(role, **role_values)},
        {"role": "user", "content": user},
    ]
