"""Shared fixtures. Unit tests fake the model (FakeLLM) and capture emitted events."""

import json
from collections import defaultdict
from collections.abc import Callable

import pytest

from shared import events as events_module
from shared.events import Event
from shared.schemas import Brief, LLMCall

SUMMARY = {
    "n_cells": 1000,
    "n_genes": 500,
    "gene_id_format": "symbol",
    "example_genes": ["ISG15", "CD14"],
    "layers": {"X": "log1p", "counts": "raw"},
    "embeddings": ["X_pca", "X_umap"],
    "obs_columns": {
        "disease": {"dtype": "category", "n_unique": 2, "counts": {"COVID-19": 600, "normal": 400}},
        "donor_id": {"dtype": "category", "n_unique": 4, "counts": {"C1": 300, "C2": 300, "H1": 200, "H2": 200}},
        "cell.type.coarse": {"dtype": "category", "n_unique": 2, "counts": {"CD14 Monocyte": 500, "NK": 500}},
        "nCount_RNA": {"dtype": "float64", "n_unique": 900, "range": [500.0, 9000.0]},
        "observation_joinid": {"dtype": "str", "n_unique": 1000},
        "tissue_ontology_term_id": {"dtype": "category", "n_unique": 1, "counts": {"UBERON:0000178": 1000}},
    },
    "removed_columns": ["IFN1", "HLA1"],
}


@pytest.fixture
def summary() -> dict:
    return json.loads(json.dumps(SUMMARY))


@pytest.fixture
def brief() -> Brief:
    return Brief(project_id="p1", organism="human", condition_column="disease",
                 condition_labels=["COVID-19", "normal"], donor_column="donor_id",
                 celltype_column="cell.type.coarse", gene_id_format="symbol",
                 goals="Compare monocytes between COVID-19 and healthy donors.")


@pytest.fixture
def events():
    """Capture every emitted event; restores the console sink afterwards."""
    captured: list[Event] = []
    events_module.set_sink(captured.append)
    yield captured
    events_module.set_sink(events_module._print_sink)


class FakeLLM:
    """Stands in for agents.llm.chat. Replies are scripted per agent name.

    A reply can be a string (used as output) or a callable(messages, kwargs) -> str.
    The last scripted reply for an agent repeats once the list is used up.
    """

    def __init__(self, script: dict[str, list] | None = None):
        self.script = {k: list(v) for k, v in (script or {}).items()}
        self.calls: list[dict] = []
        self._used = defaultdict(int)

    def reply(self, agent: str, *replies) -> "FakeLLM":
        self.script.setdefault(agent, []).extend(replies)
        return self

    def by_agent(self, agent: str) -> list[dict]:
        return [c for c in self.calls if c["agent"] == agent]

    async def __call__(self, agent: str, messages: list[dict], **kwargs) -> LLMCall:
        replies = self.script.get(agent)
        if not replies:
            raise AssertionError(f"FakeLLM has no reply scripted for agent {agent!r}")
        i = min(self._used[agent], len(replies) - 1)
        self._used[agent] += 1
        r = replies[i]
        output = r(messages, kwargs) if isinstance(r, Callable) else r
        call = LLMCall(project_id=kwargs.get("project_id", "p"), hypothesis_id=kwargs.get("hypothesis_id"),
                       agent=agent, messages=messages, output=output,
                       parent_call_id=kwargs.get("parent_call_id"))
        self.calls.append({"agent": agent, "messages": messages, "kwargs": kwargs, "call": call})
        return call


@pytest.fixture
def fake_llm() -> FakeLLM:
    return FakeLLM()
