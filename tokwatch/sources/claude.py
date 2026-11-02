"""Claude Code adapter.

Two paths:
  * live  — `statusLine` stdin JSON (context window + cost + model), per turn
  * store — `~/.claude/projects/**/*.jsonl` `cost-state` lines (cumulative)
"""
from __future__ import annotations

import json
from pathlib import Path

from ..core import ModelUsage, Stats

# Real `cost-state` line observed 2026-10-29 (DeepSeek/Claude proxy):
#   {"type":"cost-state","sessionId":...,"totalCostUSD":0.23,...,
#    "modelUsage":{"Claude Sonnet 5.5":{"inputTokens":45388,"outputTokens":130,
#      "thinkingTokens":0,"cacheReadInputTokens":0,"cacheCreationInputTokens":0,
#      "webSearchRequests":0,"costUSD":0.23}}}


def parse_statusline_stdin(raw: str) -> Stats:
    """Parse Claude Code `statusLine.command` stdin JSON into a live Stats."""
    try:
        data = json.loads(raw) if raw.strip() else {}
    except json.JSONDecodeError:
        data = {}

    stats = Stats(host="claude")

    model = data.get("model") or {}
    if isinstance(model, dict):
        stats.model_name = model.get("display_name") or model.get("id") or ""

    ctx = data.get("context_window") or {}
    if isinstance(ctx, dict):
        pct = ctx.get("used_percentage")
        size = ctx.get("context_window_size")
        if isinstance(pct, (int, float)):
            stats.context_used_pct = float(pct)
        if isinstance(size, (int, float)):
            stats.context_size = int(size)
        # Some feeds carry token totals directly on context_window.
        inp = ctx.get("total_input_tokens")
        out = ctx.get("total_output_tokens")
        if isinstance(inp, (int, float)) and isinstance(out, (int, float)):
            mu = ModelUsage(model=stats.model_name, input=int(inp), output=int(out))
            stats.add_model(stats.model_name, mu)

    cost = data.get("cost") or {}
    if isinstance(cost, dict):
        c = cost.get("total_cost_usd")
        if isinstance(c, (int, float)):
            stats.cost = float(c)
        d = cost.get("total_duration_ms")
        if isinstance(d, (int, float)):
            stats.duration_ms = int(d)
        la = cost.get("total_lines_added")
        lr = cost.get("total_lines_removed")
        if isinstance(la, (int, float)):
            stats.lines_added = int(la)
        if isinstance(lr, (int, float)):
            stats.lines_removed = int(lr)

    return stats


def _parse_cost_state(obj: dict) -> Stats:
    stats = Stats(host="claude")
    stats.sessions = 1
    c = obj.get("totalCostUSD")
    if isinstance(c, (int, float)):
        stats.cost = float(c)
    d = obj.get("totalDuration")
    if isinstance(d, (int, float)):
        stats.duration_ms = int(d)
    la = obj.get("totalLinesAdded")
    lr = obj.get("totalLinesRemoved")
    if isinstance(la, (int, float)):
        stats.lines_added = int(la)
    if isinstance(lr, (int, float)):
        stats.lines_removed = int(lr)

    for model, mu in (obj.get("modelUsage") or {}).items():
        if not isinstance(mu, dict):
            continue

        def _n(key):
            v = mu.get(key)
            return int(v) if isinstance(v, (int, float)) else 0

        cost = mu.get("costUSD")
        stats.add_model(
            model,
            ModelUsage(
                model=model,
                provider="anthropic",
                input=_n("inputTokens"),
                output=_n("outputTokens"),
                cache_read=_n("cacheReadInputTokens"),
                cache_write=_n("cacheCreationInputTokens"),
                thinking=_n("thinkingTokens"),
                cost=float(cost) if isinstance(cost, (int, float)) else 0.0,
                calls=1,
            ),
        )
    return stats


def scan_jsonl(projects_dir: str | Path) -> Stats:
    """Aggregate final per-session `cost-state` lines across all projects."""
    root = Path(projects_dir).expanduser()
    if not root.is_dir():
        return Stats(host="claude")

    # Last `cost-state` per sessionId wins (a session may snapshot multiple
    # times, or span files after a resume).
    per_session: dict[str, dict] = {}
    for file in root.rglob("*.jsonl"):
        try:
            with file.open("r", encoding="utf-8", errors="replace") as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        obj = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if obj.get("type") == "cost-state":
                        sid = obj.get("sessionId") or str(file)
                        per_session[sid] = obj
        except OSError:
            continue

    total = Stats(host="claude")
    for s in per_session.values():
        total.add(_parse_cost_state(s))
    total.sessions = len(per_session)
    total.accumulate_model_totals()
    return total
