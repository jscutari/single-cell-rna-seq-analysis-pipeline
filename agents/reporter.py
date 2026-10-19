"""Reporter agent: the final report and Q&A over a project's results."""

from agents import prompting
from agents.llm import chat
from shared.schemas import Finding, Hypothesis


def _results(background: str, hypotheses: list[Hypothesis], findings: list[Finding]) -> str:
    by_h = {f.hypothesis_id: f for f in findings}
    parts = [f"Background:\n{background or '(none)'}", "Hypotheses and findings:"]
    for i, h in enumerate(hypotheses, 1):
        parts.append(f"{i}. {h.title} [status: {h.status}]")
        f = by_h.get(h.id)
        if f:
            parts.append(
                f"   claim: {f.claim}\n   test: {f.test}\n   statistic={f.statistic} p_adj={f.p_adj} "
                f"effect_size={f.effect_size}\n   critic: {f.critic_verdict}; {f.critic_notes}\n"
                f"   novelty: {f.novelty}; citations: {', '.join(f.citations) or 'none'}")
    return "\n".join(parts)


async def report(project_id: str, prefix: str, background: str,
                 hypotheses: list[Hypothesis], findings: list[Finding]) -> str:
    user = (_results(background, hypotheses, findings) + "\n\nWrite the final report in Markdown, starting directly "
            "with the report (no preamble such as 'Here is the report'): a two-sentence "
            "summary, then one short section per approved finding (result with numbers, novelty, what it means), "
            "then one line per rejected or failed hypothesis with the reason.")
    call = await chat("reporter", prompting.messages(prefix, "reporter", user),
                      project_id=project_id, reasoning=False)
    return call.output.strip()


async def answer(project_id: str, prefix: str, background: str, hypotheses: list[Hypothesis],
                 findings: list[Finding], history: list[tuple[str, str]], question: str,
                 progress: str = "") -> str:
    convo = "\n".join(f"{role}: {text}" for role, text in history[-8:]) or "(none)"
    user = (f"Progress: {progress or 'unknown'}\n\n{_results(background, hypotheses, findings)}"
            f"\n\nRecent chat:\n{convo}\n\nQuestion: {question}\n\nAnswer the question directly in at most "
            "200 words (short paragraphs or a few bullets; no headings, no tables) unless the user asks for "
            "more detail. Take donor counts from the findings, not from the dataset summary.")
    call = await chat("reporter", prompting.messages(prefix, "reporter", user),
                      project_id=project_id, reasoning=False)
    return call.output.strip()
