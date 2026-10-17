"""shared/schemas.py and shared/events.py: the contract with the backend."""

import json

import pytest
from pydantic import ValidationError

from shared import events as ev
from shared.events import Event, EventType, emit, set_sink
from shared.schemas import (CellStatus, CodeCell, Finding, Hypothesis, HypothesisStatus, Novelty, Project,
                            ProjectStatus, Source, SourceKind)


def test_ids_and_timestamps_fill_themselves_in():
    a, b = Project(name="x", dataset_path="/d"), Project(name="y", dataset_path="/d")
    assert len(a.id) == 32 and a.id != b.id
    assert a.created_at.tzinfo is not None
    assert a.status == ProjectStatus.created


def test_status_enums_reject_typos():
    with pytest.raises(ValidationError):
        Hypothesis(project_id="p", title="t", status="aproved")
    assert Hypothesis(project_id="p", title="t", status="approved").status == HypothesisStatus.approved


def test_enums_serialize_as_plain_strings():
    f = Finding(hypothesis_id="h", claim="c", test="t", novelty=Novelty.partly_known)
    data = json.loads(f.model_dump_json())
    assert data["novelty"] == "partly_known"
    assert data["sources_searched"] == [] and data["citations"] == []


def test_source_model():
    s = Source(project_id="p", kind=SourceKind.europe_pmc, title="T", path_or_url="u", pmid="123")
    assert s.kind == "europe_pmc" and s.pmid == "123"


def test_event_accepts_a_model_payload_and_dumps_it_to_json():
    cell = CodeCell(hypothesis_id="h", index=0, source="1+1", status=CellStatus.ok)
    e = Event(type=EventType.cell_finished, project_id="p", payload=cell)
    assert e.payload["status"] == "ok" and e.payload["index"] == 0
    wire = json.loads(e.model_dump_json())
    assert set(wire) == {"id", "type", "project_id", "payload", "created_at"}
    assert wire["type"] == "cell_finished"


def test_event_accepts_a_dict_payload():
    e = Event(type="stage_done", project_id="p", payload={"stage": "intake", "summary": "ok"})
    assert e.type == EventType.stage_done and e.payload["stage"] == "intake"


def test_event_type_must_be_known():
    with pytest.raises(ValidationError):
        Event(type="not_an_event", project_id="p", payload={})


def test_all_eight_event_types_exist():
    assert {t.value for t in EventType} == {
        "llm_call", "brief_updated", "hypothesis_status", "cell_started",
        "cell_finished", "finding", "chat_reply", "stage_done"}


def test_emit_prints_json_by_default(capsys):
    set_sink(ev._print_sink)
    emit(Event(type="stage_done", project_id="p", payload={"stage": "s", "summary": "x"}))
    assert json.loads(capsys.readouterr().out)["payload"]["stage"] == "s"


def test_set_sink_redirects_emit(events):
    emit(Event(type="stage_done", project_id="p", payload={"stage": "s", "summary": "x"}))
    assert len(events) == 1 and events[0].project_id == "p"
