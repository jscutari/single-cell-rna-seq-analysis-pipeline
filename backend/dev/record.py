"""Record a run from a running backend into a replay file.

    uv run python -m backend.dev.record <project_id> out.jsonl [--base http://127.0.0.1:8080]

Streams the project's events from the start until the run ends (report,
stopped or failed), keeps their relative timing, then appends the project's
results (project_state.json) so a replay shows the same files and findings.
Add an {"type": "_await_user"} line by hand where the replay should wait for
the user (after the intake greeting).
"""

import argparse
import json
import sys
import time
from pathlib import Path

import httpx

FINAL_STAGES = {"report", "stopped", "failed"}


def parse_block(block: str) -> dict | None:
    data = [line[6:] for line in block.splitlines() if line.startswith("data: ")]
    return json.loads("".join(data)) if data else None


def record(base: str, project_id: str, out: Path, timeout: float = 3600) -> int:
    records: list[dict] = []
    start = None
    deadline = time.monotonic() + timeout
    with httpx.Client(base_url=base, timeout=None) as http:
        with http.stream("GET", f"/api/projects/{project_id}/events", params={"after": 0}) as r:
            r.raise_for_status()
            buf, done = "", False
            for chunk in r.iter_text():
                buf += chunk
                while "\n\n" in buf and not done:
                    block, buf = buf.split("\n\n", 1)
                    event = parse_block(block)
                    if event is None or event["type"] in ("user_message", "run_status"):
                        continue
                    now = time.monotonic()
                    start = start or now
                    records.append({"t": round(now - start, 2), "type": event["type"], "payload": event["payload"]})
                    done = event["type"] == "stage_done" and event["payload"].get("stage") in FINAL_STAGES
                if done or time.monotonic() > deadline:
                    break
        state = http.get(f"/api/projects/{project_id}/state").json().get("results")
    if state:
        records.append({"t": records[-1]["t"] if records else 0, "type": "_project_state", "payload": state})
    out.write_text("".join(json.dumps(r) + "\n" for r in records))
    return len(records)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("project_id")
    parser.add_argument("out", type=Path)
    parser.add_argument("--base", default="http://127.0.0.1:8080")
    args = parser.parse_args(argv)
    n = record(args.base, args.project_id, args.out)
    print(f"Recorded {n} records to {args.out}", file=sys.stderr)


if __name__ == "__main__":
    main()
