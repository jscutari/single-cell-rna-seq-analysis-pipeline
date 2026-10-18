"""Intake agent: a short chat with the biologist that fills in the Brief."""

from pydantic import BaseModel

from agents import prompting
from agents.llm import chat, chat_json
from shared.schemas import Brief, ChatMessage


class BriefFields(BaseModel):
    organism: str | None
    condition_column: str | None
    condition_labels: list[str]
    donor_column: str | None
    celltype_column: str | None
    gene_id_format: str | None
    prior_analyses: list[str]
    goals: str
    notes: str


class IntakeTurn(BaseModel):
    brief: BriefFields
    reply: str
    ready: bool


async def turn(project_id: str, summary: dict, brief: Brief, history: list[ChatMessage]) -> IntakeTurn:
    convo = "\n".join(f"{m.role}: {m.content}" for m in history) or "(The user just created the project.)"
    user = (f"Current brief draft:\n{brief.model_dump_json(exclude={'project_id'}, indent=2)}\n\n"
            f"Conversation so far:\n{convo}\n\nWrite the next assistant turn.")
    prefix = prompting.shared_prefix(summary, brief)
    _, result = await chat_json("intake", prompting.messages(prefix, "intake", user), IntakeTurn,
                                chat_fn=chat, project_id=project_id)
    return result


def problems(brief: Brief, summary: dict) -> list[str]:
    """Deterministic checks before analysis may start: every named column and label must exist."""
    cols = summary["obs_columns"]
    out = []
    for field in ("condition_column", "donor_column", "celltype_column"):
        col = getattr(brief, field)
        if not col:
            out.append(f"{field} is not set")
        elif col not in cols:
            out.append(f"{field} '{col}' is not a column in the dataset")
    if brief.condition_column in cols:
        known = set(cols[brief.condition_column].get("counts", {}))
        bad = [lab for lab in brief.condition_labels if lab not in known]
        if len(brief.condition_labels) < 2:
            out.append("need at least two condition labels to compare")
        if bad:
            out.append(f"condition labels {bad} not found in '{brief.condition_column}'")
    if not brief.goals.strip():
        out.append("goals are empty")
    return out
