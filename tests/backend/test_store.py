"""backend/store.py: views folded from events, ordering, dedupe, run status."""

import pytest

from backend.store import InMemoryStore, summarize_llm_call
from shared.schemas import CellStatus, ChatMessage, CodeCell, Finding, Hypothesis, HypothesisStatus, LLMCall, Role


def dump(model) -> dict:
    return model.model_dump(mode="json")


@pytest.fixture
def store() -> InMemoryStore:
    return InMemoryStore()


def test_serials_are_global_and_increasing(store):
    a = store.append("stage_done", "p1", {"stage": "preprocess", "summary": ""})
    b = store.append("stage_done", "p2", {"stage": "preprocess", "summary": ""})
    c = store.append("stage_done", "p1", {"stage": "intake", "summary": ""})
    assert [a.id, b.id, c.id] == [1, 2, 3]
    assert store.last_event_id == 3


def test_events_after_filters_by_project_and_serial(store):
    for i in range(10):
        store.append("stage_done", "p1" if i % 2 == 0 else "p2", {"stage": f"s{i}", "summary": ""})
    assert [e.id for e in store.events_after("p1", 0)] == [1, 3, 5, 7, 9]
    assert [e.id for e in store.events_after("p1", 4)] == [5, 7, 9]
    assert [e.id for e in store.events_after("p1", 9)] == []
    assert store.events_after("unknown", 0) == []


def test_chat_reply_and_user_messages_keep_arrival_order(store):
    user = ChatMessage(project_id="p1", role=Role.user, content="hi")
    reply = ChatMessage(project_id="p1", role=Role.assistant, content="hello")
    store.append("user_message", "p1", dump(user))
    store.append("chat_reply", "p1", dump(reply))
    assert [m["content"] for m in store.messages("p1")] == ["hi", "hello"]


def test_duplicate_user_message_is_ignored(store):
    msg = dump(ChatMessage(id="m1", project_id="p1", role=Role.user, content="hi"))
    assert store.append("user_message", "p1", msg) is not None
    assert store.append("user_message", "p1", {**msg, "content": "changed"}) is None
    assert [m["content"] for m in store.messages("p1")] == ["hi"]
    assert store.last_event_id == 1


def test_messages_for_unknown_project_is_empty(store):
    assert store.messages("nope") == []
    assert store.status("nope") == "idle"


def test_hypothesis_status_updates_in_place(store):
    h = Hypothesis(id="h1", project_id="p1", title="ISG up")
    store.append("hypothesis_status", "p1", dump(h))
    store.append("hypothesis_status", "p1", dump(h.model_copy(update={"status": HypothesisStatus.approved})))
    assert list(store.view("p1").hypotheses) == ["h1"]
    assert store.view("p1").hypotheses["h1"]["status"] == "approved"


def test_cell_finished_replaces_started(store):
    cell = CodeCell(id="c1", hypothesis_id="h1", index=0, source="print(1)")
    store.append("cell_started", "p1", dump(cell))
    store.append("cell_finished", "p1", dump(cell.model_copy(update={"status": CellStatus.ok, "stdout": "1\n"})))
    cells = store.view("p1").cells["h1"]
    assert list(cells) == ["c1"] and cells["c1"]["stdout"] == "1\n"


def test_brief_and_findings(store):
    store.append("brief_updated", "p1", {"project_id": "p1", "organism": "human"})
    f = Finding(id="f1", hypothesis_id="h1", claim="ISG up", test="DESeq2")
    store.append("finding", "p1", dump(f))
    assert store.view("p1").brief["organism"] == "human"
    assert store.view("p1").findings["f1"]["claim"] == "ISG up"


def test_llm_call_kept_in_full_but_view_is_trimmed(store):
    call = LLMCall(id="l1", project_id="p1", agent="critic", messages=[{"role": "user", "content": "x" * 10_000}])
    store.append("llm_call", "p1", dump(call))
    assert store.llm_call("l1")["messages"][0]["content"] == "x" * 10_000
    summary = store.view("p1").llm_calls["l1"]
    assert "messages" not in summary and summary["message_count"] == 1 and summary["agent"] == "critic"
    assert store.llm_call("missing") is None


def test_restored_trimmed_llm_call_is_not_mistaken_for_a_full_one(store):
    store.append("llm_call", "p1", {"id": "l1", "agent": "critic", "message_count": 4})
    assert store.llm_call("l1") is None  # the full call must come from the database
    assert store.view("p1").llm_calls["l1"]["message_count"] == 4


def test_summarize_llm_call_handles_missing_messages():
    assert summarize_llm_call({"id": "l1"}) == {"id": "l1", "message_count": 0}


def test_summarize_llm_call_is_idempotent():
    once = summarize_llm_call({"id": "l1", "messages": [{}, {}, {}]})
    assert summarize_llm_call(once) == once == {"id": "l1", "message_count": 3}


def test_restore_keeps_ids_and_rejects_out_of_order():
    from backend.store import StoredEvent

    store = InMemoryStore()
    store.restore(StoredEvent(5, "stage_done", "p1", {"stage": "intake", "summary": ""}, "t"))
    assert store.last_event_id == 5
    assert store.append("stage_done", "p1", {"stage": "planning", "summary": ""}).id == 6
    with pytest.raises(ValueError, match="id order"):
        store.restore(StoredEvent(3, "stage_done", "p1", {}, "t"))


@pytest.mark.parametrize(
    ("stage", "status"),
    [("preprocess", "running"), ("intake", "running"), ("analysis", "running"),
     ("report", "done"), ("stopped", "stopped"), ("failed", "failed")],
)
def test_stage_done_sets_final_statuses(store, stage, status):
    store.append("run_status", "p1", {"status": "running"})
    store.append("stage_done", "p1", {"stage": stage, "summary": ""})
    assert store.view("p1").stage == stage
    assert store.status("p1") == status


def test_running_projects(store):
    store.append("run_status", "p1", {"status": "running"})
    store.append("run_status", "p2", {"status": "running"})
    store.append("stage_done", "p2", {"stage": "report", "summary": ""})
    assert store.running_projects() == ["p1"]
