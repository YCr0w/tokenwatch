"""Unified usage model and pure formatting helpers (no I/O, no deps)."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class ModelUsage:
    """Per-model token/cost bucket, aggregated across calls/sessions."""

    model: str
    provider: str = ""
    input: int = 0
    output: int = 0
    cache_read: int = 0
    cache_write: int = 0
    thinking: int = 0
    cost: float = 0.0
    calls: int = 0

    @property
    def total(self) -> int:
        return self.input + self.output + self.cache_read + self.cache_write

    def add(self, other: "ModelUsage") -> None:
        self.input += other.input
        self.output += other.output
        self.cache_read += other.cache_read
        self.cache_write += other.cache_write
        self.thinking += other.thinking
        self.cost += other.cost
        self.calls += other.calls


@dataclass
class Stats:
    """Host-level aggregate, plus live context-window fields when known."""

    host: str = ""
    input: int = 0
    output: int = 0
    cache_read: int = 0
    cache_write: int = 0
    thinking: int = 0
    cost: float = 0.0
    duration_ms: int = 0
    lines_added: int = 0
    lines_removed: int = 0
    sessions: int = 0
    models: dict[str, ModelUsage] = field(default_factory=dict)

    # Live-only (Claude Code statusline stdin). None = "unknown / not a live feed".
    context_used_pct: Optional[float] = None
    context_size: Optional[int] = None
    model_name: str = ""

    @property
    def total_tokens(self) -> int:
        return self.input + self.output + self.cache_read + self.cache_write

    @property
    def context_remaining(self) -> Optional[int]:
        if self.context_size is None or self.context_used_pct is None:
            return None
        return int(round(self.context_size * (1.0 - self.context_used_pct / 100.0)))

    def add_model(self, key: str, mu: ModelUsage) -> None:
        if key in self.models:
            self.models[key].add(mu)
        else:
            self.models[key] = mu

    def accumulate_model_totals(self) -> None:
        """Recompute flat totals from the model buckets (source of truth)."""
        self.input = sum(m.input for m in self.models.values())
        self.output = sum(m.output for m in self.models.values())
        self.cache_read = sum(m.cache_read for m in self.models.values())
        self.cache_write = sum(m.cache_write for m in self.models.values())
        self.thinking = sum(m.thinking for m in self.models.values())
        self.cost = sum(m.cost for m in self.models.values())

    def add(self, other: "Stats") -> None:
        self.input += other.input
        self.output += other.output
        self.cache_read += other.cache_read
        self.cache_write += other.cache_write
        self.thinking += other.thinking
        self.cost += other.cost
        self.duration_ms += other.duration_ms
        self.lines_added += other.lines_added
        self.lines_removed += other.lines_removed
        self.sessions += other.sessions
        for key, mu in other.models.items():
            self.add_model(key, mu)


# --------------------------------------------------------------------------- #
# Pure formatting (mirrors oh-my-claude's short/bar helpers)
# --------------------------------------------------------------------------- #

def short(n: float | int) -> str:
    """84_000 -> '84k', 1_200_000 -> '1.2M', else integer string."""
    n = float(n)
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M"
    if n >= 1_000:
        return f"{round(n / 1000)}k"
    return str(int(n))


def _bar_glyph(filled: int, width: int, style: str) -> str:
    if style == "ascii":
        return "#" * filled + "-" * (width - filled)
    if style == "thin":
        return "\u2588" * filled + "\u2591" * (width - filled)
    return "\u2593" * filled + "\u2591" * (width - filled)


def bar(pct: float, width: int = 10, warn: float = 60.0, critical: float = 80.0,
        style: str = "block") -> tuple[str, str]:
    """Return (glyph_text, level) where level in {ok, warn, critical}.

    pct is clamped to [0, 100]. level drives colour at the call site.
    """
    pct = max(0.0, min(100.0, float(pct)))
    filled = round(pct / 100.0 * width)
    if pct >= critical:
        level = "critical"
    elif pct >= warn:
        level = "warn"
    else:
        level = "ok"
    return _bar_glyph(filled, width, style), level


def money(n: float, precision: int = 2) -> str:
    return f"${n:.{precision}f}"
