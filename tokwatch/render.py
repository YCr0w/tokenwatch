"""Rendering: one-line statusline + full CLI report. No deps, optional ANSI."""
from __future__ import annotations

import os
import shutil
from typing import Iterable

from .core import Stats, ModelUsage, bar, money, short

_COLORS = {
    "ok": "\x1b[32m",
    "warn": "\x1b[33m",
    "critical": "\x1b[31m",
    "dim": "\x1b[2m",
    "bold": "\x1b[1m",
    "reset": "\x1b[0m",
}


def _color_enabled() -> bool:
    return os.environ.get("TOKWATCH_COLOR", "") == "1"


def _paint(text: str, level: str) -> str:
    if not _color_enabled():
        return text
    return _COLORS.get(level, "") + text + _COLORS["reset"]


def statusline(stats: Stats, width: int = 10) -> str:
    """One compact line for Claude Code's `statusLine` (plain text)."""
    parts: list[str] = []

    if stats.model_name:
        parts.append(stats.model_name)

    if stats.context_used_pct is not None:
        glyph, level = bar(stats.context_used_pct, width=width)
        pct = f"{round(stats.context_used_pct)}%"
        seg = f"ctx {glyph} {pct}"
        if stats.context_size is not None:
            used = stats.context_size - (stats.context_remaining or 0)
            seg += f" ({short(used)}/{short(stats.context_size)})"
        elif stats.context_remaining is not None:
            seg += f" ({short(stats.context_remaining)} left)"
        parts.append(_paint(seg, level))

    if stats.cost:
        parts.append(_paint(money(stats.cost), "dim"))

    return " ".join(parts)


def _fmt_int(n: int) -> str:
    return f"{n:,}"


def report(stats_list: Iterable[Stats]) -> str:
    """Multi-host tabular report."""
    lines: list[str] = []
    for stats in stats_list:
        if stats.total_tokens == 0 and stats.cost == 0 and stats.sessions == 0:
            lines.append(f"[{stats.host}] no data found")
            continue

        lines.append(f"[{stats.host}]")
        lines.append(
            f"  tokens  in {_fmt_int(stats.input)}  out {_fmt_int(stats.output)}"
            f"  cache_r {_fmt_int(stats.cache_read)}  cache_w {_fmt_int(stats.cache_write)}"
        )
        lines.append(
            f"  total   {_fmt_int(stats.total_tokens)} tokens"
            f"  ·  {money(stats.cost)}"
            f"  ·  sessions {stats.sessions}"
        )
        if stats.duration_ms:
            lines.append(f"  time    {stats.duration_ms / 3_600_000:.2f}h")
        if stats.lines_added or stats.lines_removed:
            lines.append(f"  lines   +{stats.lines_added} -{stats.lines_removed}")

        if stats.models:
            lines.append("  models:")
            rows = sorted(
                stats.models.values(),
                key=lambda m: m.cost if m.cost else m.total,
                reverse=True,
            )
            hdr = f"    {'model':<28} {'in':>9} {'out':>9} {'cache_r':>8} {'cache_w':>8} {'cost':>10}"
            lines.append(hdr)
            for m in rows:
                name = f"{m.provider}/{m.model}" if m.provider else m.model
                lines.append(
                    f"    {name:<28} {_fmt_int(m.input):>9} {_fmt_int(m.output):>9}"
                    f" {_fmt_int(m.cache_read):>8} {_fmt_int(m.cache_write):>8}"
                    f" {money(m.cost):>10}"
                )
        lines.append("")
    return "\n".join(lines).rstrip()


def json_report(stats_list: Iterable[Stats]) -> str:
    import json

    def s(stats: Stats) -> dict:
        return {
            "host": stats.host,
            "tokens": {
                "input": stats.input,
                "output": stats.output,
                "cache_read": stats.cache_read,
                "cache_write": stats.cache_write,
                "total": stats.total_tokens,
            },
            "cost": round(stats.cost, 4),
            "duration_ms": stats.duration_ms,
            "lines_added": stats.lines_added,
            "lines_removed": stats.lines_removed,
            "sessions": stats.sessions,
            "context": {
                "used_percentage": stats.context_used_pct,
                "size": stats.context_size,
                "remaining": stats.context_remaining,
            },
            "models": [
                {
                    "model": m.model,
                    "provider": m.provider,
                    "input": m.input,
                    "output": m.output,
                    "cache_read": m.cache_read,
                    "cache_write": m.cache_write,
                    "cost": round(m.cost, 4),
                }
                for m in sorted(stats.models.values(), key=lambda x: x.cost, reverse=True)
            ],
        }

    return json.dumps([s(x) for x in stats_list], indent=2)


def _terminal_width() -> int:
    cols = shutil.get_terminal_size((120, 24)).columns
    return cols if cols > 0 else 120


def _countdown(epoch_ms: int) -> str:
    import time

    secs = int(epoch_ms / 1000 - time.time())
    if secs <= 0:
        return "now"
    if secs < 3600:
        return f"{secs // 60}m"
    h, rem = divmod(secs, 3600)
    m = rem // 60
    if h >= 24:
        return f"{h // 24}d{h % 24}h"
    return f"{h}h{m:02d}m"


def render_limits(limits: dict) -> str:
    """Render omp `usage --json` quota snapshot as a compact table."""
    lines: list[str] = []
    for report in limits.get("reports", []) or []:
        provider = report.get("provider", "?")
        lines.append(f"[{provider}]")
        for lim in report.get("limits", []) or []:
            label = lim.get("label", "?")
            amount = lim.get("amount") or {}
            used_frac = amount.get("usedFraction")
            rem_frac = amount.get("remainingFraction")
            resets = (lim.get("window") or {}).get("resetsAt")
            status = lim.get("status", "?")

            seg = f"  {label:<18}"
            if isinstance(used_frac, (int, float)):
                glyph, level = bar(used_frac * 100, width=10)
                seg += f" {glyph} {used_frac * 100:5.1f}% used"
            if isinstance(rem_frac, (int, float)):
                seg += f" ({rem_frac * 100:.1f}% left)"
            if isinstance(resets, (int, float)):
                seg += f"  resets {_countdown(int(resets))}"
            seg += f"  [{status}]"
            lines.append(seg)
    return "\n".join(lines) if lines else "(no quota data)"

