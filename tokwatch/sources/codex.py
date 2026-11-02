"""OpenAI Codex CLI adapter.

Codex has no statusline/hook feed — it persists session tokens in SQLite.
Reads `~/.codex/state_5.sqlite` (`threads.tokens_used`, combined in+out).

Cost is an ESTIMATE: Codex does not split input/output, so we apply a 70/30
split against a small published-price table. Unknown models cost $0 (no guess).
Live quota is native `codex /status`; this adapter intentionally does not
re-implement provider auth.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

from ..core import ModelUsage, Stats

# input/1M, output/1M — published OpenAI rates (codex-usage project, 2026).
CODEX_PRICES: dict[str, tuple[float, float]] = {
    "gpt-5.4": (5.00, 20.00),
    "o4-mini": (1.10, 4.40),
    "o3": (10.00, 40.00),
    "gpt-4.1": (2.00, 8.00),
    "gpt-4o": (2.50, 10.00),
}

# Codex CLI's own blended input:output ratio used for estimation.
_INPUT_RATIO = 0.70


def _estimate_cost(model: str, tokens: int) -> float:
    """Estimate USD for combined tokens using 70/30 split + price table."""
    prices = CODEX_PRICES.get(model)
    if prices is None or tokens <= 0:
        return 0.0
    inp, out = prices
    in_tok = tokens * _INPUT_RATIO
    out_tok = tokens * (1.0 - _INPUT_RATIO)
    return (in_tok / 1_000_000) * inp + (out_tok / 1_000_000) * out


def scan_sqlite(db_path: str | Path) -> Stats:
    stats = Stats(host="codex")
    path = Path(db_path).expanduser()
    if not path.is_file():
        return stats

    try:
        con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    except sqlite3.Error:
        return stats
    try:
        cur = con.cursor()
        # Discover threads schema (tokens_used is documented; model is optional).
        try:
            cols = [r[1] for r in cur.execute("PRAGMA table_info(threads)")]
        except sqlite3.Error:
            return stats

        if "tokens_used" not in cols:
            return stats
        has_model = "model" in cols

        select = "SELECT " + (", ".join(("tokens_used", "model")) if has_model else "tokens_used") + " FROM threads"
        total_tokens = 0
        per_model: dict[str, int] = {}
        for row in cur.execute(select):
            tokens = int(row[0] or 0)
            model = str(row[1]) if has_model and row[1] else "codex"
            total_tokens += tokens
            per_model[model] = per_model.get(model, 0) + tokens

        for model, tokens in per_model.items():
            stats.add_model(
                f"codex/{model}",
                ModelUsage(
                    model=model,
                    provider="openai",
                    input=round(tokens * _INPUT_RATIO),
                    output=round(tokens * (1.0 - _INPUT_RATIO)),
                    cost=_estimate_cost(model, tokens),
                    calls=0,
                ),
            )
        stats.accumulate_model_totals()
    finally:
        con.close()
    return stats
