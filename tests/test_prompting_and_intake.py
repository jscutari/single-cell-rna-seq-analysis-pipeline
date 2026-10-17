"""agents/prompting.py and agents/intake.py."""

import json

from agents import intake, prompting
from agents.intake import BriefFields, IntakeTurn
from shared.schemas import Brief, ChatMessage, Role


def test_render_replaces_placeholders():
    assert "Propose 4 hypotheses" in prompting.render("planner", n=4)
    assert "{{" not in prompting.render("planner", n=4)


def test_every_prompt_file_renders(summary, brief):
    prefix = prompting.shared_prefix(summary, brief)
    for role in ["planner", "coder", "reader", "finding", "critic", "intake", "literature",
                 "novelty", "reporter", "baseline"]:
        text = prompting.messages(prefix, role, "u", n=3, max_cells=5)[0]["content"]
        assert "{{" not in text, role


def test_render_dataset_lists_levels_and_ranges_and_hides_noise(summary):
    text = prompting.render_dataset(summary)
    assert "`disease`: COVID-19 (600), normal (400)" in text
    assert "`nCount_RNA`: numeric, 500 to 9000" in text
    assert "observation_joinid" not in text and "ontology_term_id" not in text
    assert "IFN1, HLA1" in text


def test_render_brief_skips_empty_and_internal_fields(brief):
    text = prompting.render_brief(brief)
    assert "condition_column: disease" in text and '["COVID-19", "normal"]' in text
    assert "project_id" not in text and "online_search" not in text and "notes" not in text


def test_all_roles_share_the_same_system_prefix(summary, brief):
    """The prefix-cache design: every role's system message starts identically."""
    prefix = prompting.shared_prefix(summary, brief)
    systems = [prompting.messages(prefix, r, "x")[0]["content"] for r in ["coder", "critic", "reader"]]
    assert all(s.startswith(prefix) for s in systems)
    assert len({s[len(prefix):] for s in systems}) == 3


def test_messages_shape(summary, brief):
    msgs = prompting.messages(prompting.shared_prefix(summary, brief), "reader", "hello")
    assert [m["role"] for m in msgs] == ["system", "user"] and msgs[1]["content"] == "hello"


def test_shared_prefix_documents_helper_return_keys(summary, brief):
    prefix = prompting.shared_prefix(summary, brief)
    for key in ["welch_p", "cohens_d", "mannwhitney_p", "Never reassign `adata`"]:
        assert key in prefix


# --- intake ---

def test_problems_none_for_a_complete_brief(brief, summary):
    assert intake.problems(brief, summary) == []


def test_problems_flags_missing_and_unknown_columns(summary):
    b = Brief(project_id="p", condition_column="condition", condition_labels=["a"], goals="")
    issues = intake.problems(b, summary)
    assert "condition_column 'condition' is not a column in the dataset" in issues
    assert "donor_column is not set" in issues and "celltype_column is not set" in issues
    assert "goals are empty" in issues


def test_problems_flags_bad_labels(brief, summary):
    brief.condition_labels = ["COVID-19", "healthy"]
    assert any("healthy" in p for p in intake.problems(brief, summary))


def test_problems_needs_two_labels(brief, summary):
    brief.condition_labels = ["COVID-19"]
    assert "need at least two condition labels to compare" in intake.problems(brief, summary)


async def test_turn_sends_history_and_parses_the_structured_reply(monkeypatch, fake_llm, summary):
    turn = IntakeTurn(brief=BriefFields(organism="human", condition_column="disease",
                                        condition_labels=["COVID-19", "normal"], donor_column="donor_id",
                                        celltype_column="cell.type.coarse", gene_id_format="symbol",
                                        prior_analyses=[], goals="g", notes=""), reply="Ready?", ready=False)
    fake_llm.reply("intake", turn.model_dump_json())
    monkeypatch.setattr(intake, "chat", fake_llm)
    history = [ChatMessage(project_id="p", role=Role.user, content="Monocytes please")]
    result = await intake.turn("p", summary, Brief(project_id="p"), history)
    assert result.reply == "Ready?" and result.brief.condition_column == "disease"
    call = fake_llm.calls[0]
    assert call["kwargs"]["schema"] is IntakeTurn
    assert "user: Monocytes please" in call["messages"][1]["content"]


async def test_first_turn_says_project_just_created(monkeypatch, fake_llm, summary):
    fake_llm.reply("intake", json.dumps({"brief": BriefFields(
        organism=None, condition_column=None, condition_labels=[], donor_column=None, celltype_column=None,
        gene_id_format=None, prior_analyses=[], goals="", notes="").model_dump(), "reply": "Hi", "ready": False}))
    monkeypatch.setattr(intake, "chat", fake_llm)
    await intake.turn("p", summary, Brief(project_id="p"), [])
    assert "just created the project" in fake_llm.calls[0]["messages"][1]["content"]
