"""Sweep status text and end-of-run report formatting."""

from __future__ import annotations

from slskd_importer.sweep.outcomes import OUTCOME_LABELS, SweepReport
from slskd_importer.telegram.ui.markdown import escape_md

SWEEP_OUTCOME_ORDER = (
    "review",
    "none_qualified",
    "no_better_copy",
    "no_match",
    "hires",
    "review_waiting",
    "skipped",
    "error",
    "upgraded",
)


def status_text(st: dict) -> str:
    """Markdown status for `/sweep status`."""
    lines = [f"🧹 *Library sweep*: {'running' if st['running'] else 'idle'}"]
    if not st["enabled"]:
        lines.append("_Off_ — no allowed Telegram users configured.")
        return "\n".join(lines)
    run = st.get("run")
    if run:
        started = run.get("started_at") or "?"
        if st["running"]:
            lines.append(
                f"Sweep {run['id']} ({escape_md(run['trigger'])}, since {escape_md(started)}): "
                f"{run['position']} of {run['files']} files"
            )
            if run.get("current"):
                lines.append(f"Current: `{escape_md(run['current'])}`")
        else:
            finished = run.get("finished_at") or started
            lines.append(
                f"Last sweep {run['id']} ({escape_md(run['trigger'])}): "
                f"{escape_md(run['status'])} {escape_md(finished)}"
            )
        counts = run.get("counts") or {}
        parts = [f"{OUTCOME_LABELS.get(k, k).lower()} {counts[k]}" for k in SWEEP_OUTCOME_ORDER if counts.get(k)]
        if parts:
            lines.append(", ".join(parts))
    lines.append(f"Schedule: `{escape_md(st['schedule'])}`")
    if st.get("next_scheduled"):
        lines.append(f"Next: `{escape_md(st['next_scheduled'])}`")
    waiting = st.get("reviews_waiting") or 0
    lines.append(f"Pairs waiting: {waiting}" + (" (`/sweep reviews`)" if waiting else ""))
    missing = st.get("missing_tools") or []
    if missing:
        lines.append(f"Missing tools: {escape_md(', '.join(missing))}")
    elif not st.get("fingerprint"):
        lines.append("_fpcalc_ missing — same-recording check uses length/tags only.")
    return "\n".join(lines)


def report_caption(report: SweepReport) -> str:
    run = report.run
    if report.in_progress:
        return f"🧹 Sweep {run.id} still running ({run.done}/{run.total}). Pairs wait until it finishes."
    counts = run.counts or {}
    parts = [f"{OUTCOME_LABELS.get(k, k).lower()} {counts[k]}" for k in SWEEP_OUTCOME_ORDER if counts.get(k)]
    summary = ", ".join(parts) if parts else "nothing was due"
    return f"🧹 *Library sweep* {run.id} done: {escape_md(summary)}"
