"""Check that frontend/src/types mirrors shared/ (the source of truth).

Compares, by name:
  - every pydantic model in shared/schemas.py  <-> the TS interface of the same name
  - every StrEnum in shared/schemas.py          <-> the TS string-union type of the same name
  - shared/events.py EventType                  <-> EVENT_TYPES and EventPayloads keys
  - shared/events.py Event fields               <-> the ScrapEvent envelope
Checks field names, enum values, and nullability (`X | None` <-> `| null`).
Standard library only. Exits 1 on drift.

Run after pulling changes to shared/:  npm run check:contract
"""

import ast
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SHARED = ROOT / "shared"
TYPES = ROOT / "frontend" / "src" / "types"


def parse_python(path: Path) -> tuple[dict[str, dict[str, bool]], dict[str, list[str]]]:
    """Returns ({model: {field: nullable}}, {enum: [values]})."""
    models: dict[str, dict[str, bool]] = {}
    enums: dict[str, list[str]] = {}
    for node in ast.parse(path.read_text()).body:
        if not isinstance(node, ast.ClassDef):
            continue
        bases = {ast.unparse(b) for b in node.bases}
        if "BaseModel" in bases:
            models[node.name] = {
                stmt.target.id: "None" in ast.unparse(stmt.annotation)
                for stmt in node.body
                if isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name)
            }
        elif "StrEnum" in bases:
            enums[node.name] = [
                stmt.value.value
                for stmt in node.body
                if isinstance(stmt, ast.Assign) and isinstance(stmt.value, ast.Constant)
            ]
    return models, enums


def strip_comments(ts: str) -> str:
    ts = re.sub(r"/\*.*?\*/", "", ts, flags=re.S)
    return re.sub(r"//[^\n]*", "", ts)


def ts_fields(body: str) -> dict[str, bool]:
    """{field: nullable} from the body of an interface or object type."""
    fields = {}
    for name, type_ in re.findall(r"^\s*(\w+)\??:\s*([^;]+);", body, flags=re.M):
        fields[name] = bool(re.search(r"\bnull\b", type_))
    return fields


def parse_ts() -> tuple[dict[str, dict[str, bool]], dict[str, list[str]], str]:
    source = strip_comments("\n".join(p.read_text() for p in sorted(TYPES.glob("*.ts"))))
    interfaces = {
        name: ts_fields(body)
        for name, body in re.findall(r"export interface (\w+)\s*{([^}]*)}", source)
    }
    unions = {
        name: re.findall(r'"([^"]+)"', body)
        for name, body in re.findall(r"export type (\w+)\s*=\s*((?:\s*\|?\s*\"[^\"]+\")+)\s*;", source)
    }
    return interfaces, unions, source


def compare_fields(label: str, expected: dict[str, bool], actual: dict[str, bool] | None) -> list[str]:
    if actual is None:
        return [f"{label}: missing in frontend types"]
    problems = []
    for name in expected.keys() - actual.keys():
        problems.append(f"{label}.{name}: missing in frontend")
    for name in actual.keys() - expected.keys():
        problems.append(f"{label}.{name}: not in shared/ (remove or ask Alex)")
    for name in expected.keys() & actual.keys():
        if expected[name] != actual[name]:
            want = "nullable" if expected[name] else "not nullable"
            problems.append(f"{label}.{name}: should be {want}")
    return problems


def compare_values(label: str, expected: list[str], actual: list[str] | None) -> list[str]:
    if actual is None:
        return [f"{label}: missing in frontend types"]
    problems = [f"{label}: value {v!r} missing in frontend" for v in expected if v not in actual]
    problems += [f"{label}: value {v!r} not in shared/" for v in actual if v not in expected]
    return problems


def main() -> int:
    models, enums = parse_python(SHARED / "schemas.py")
    event_models, event_enums = parse_python(SHARED / "events.py")
    interfaces, unions, ts_source = parse_ts()
    problems: list[str] = []

    for name, fields in models.items():
        problems += compare_fields(name, fields, interfaces.get(name))
    for name, values in enums.items():
        problems += compare_values(name, values, unions.get(name))

    # Events
    event_types = event_enums["EventType"]
    match = re.search(r"EVENT_TYPES\s*=\s*\[([^\]]*)\]", ts_source)
    ts_event_types = re.findall(r'"([^"]+)"', match.group(1)) if match else None
    problems += compare_values("EventType (EVENT_TYPES)", event_types, ts_event_types)
    if ts_event_types and ts_event_types != event_types and set(ts_event_types) == set(event_types):
        problems.append("EVENT_TYPES: same values but different order than EventType")
    payload_keys = list(interfaces.get("EventPayloads", {}))
    problems += compare_values("EventPayloads keys", event_types, payload_keys)

    envelope = re.search(r"export type ScrapEvent\s*=\s*{[^{]*{([^}]*)}", ts_source)
    problems += compare_fields(
        "Event (ScrapEvent)", event_models["Event"], ts_fields(envelope.group(1)) if envelope else None
    )

    checked = f"{len(models)} models, {len(enums)} enums, {len(event_types)} event types"
    if problems:
        print(f"Contract drift ({checked}):")
        for problem in sorted(problems):
            print(f"  - {problem}")
        return 1
    print(f"Frontend types match shared/ ({checked}).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
