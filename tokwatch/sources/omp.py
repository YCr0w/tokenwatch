"""omp (Oh My Pi) adapter.

Token accounting lives in `~/.omp/agent/sessions/**/*.jsonl`, on two line types
with an identical `usage` schema:

  # type "message" (authoritative per-call, 2026-10 observed):
  {"type":"message","message":{"role":"assistant","model":"k3","provider":"kimi-code",
   "usage":{"input":266,"output":107,"cacheRead":7168,"cacheWrite":0,
            "totalTokens":7541,"cost":{...,"total":0.0045}}}}

  # type "model_usage" (auxiliary records, e.g. purpose="job-widget"):
  {"type":"model_usage","model":"k3","provider":"kimi-code","usage":{...same...}}

Live provider quota (5h/monthly windows) is native `omp usage --json`; expose it
as `read_limits()` rather than re-implementing provider auth.
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

from ..core import ModelUsage, Stats


def _usage_record(obj: dict):
    """Return (model, provider, usage_dict) for a usage-bearing line, else None."""
    if obj.get("type") == "model_usage":
        return obj.get("model"), obj.get("provider"), obj.get("usage")
    if obj.get("type") == "message":
        m = obj.get("message")
        if isinstance(m, dict) and m.get("usage") is not None:
            return m.get("model"), m.get("provider"), m.get("usage")
    return None


def scan_sessions(sessions_dir: str | Path) -> Stats:
    root = Path(sessions_dir).expanduser()
    stats = Stats(host="omp")
    if not root.is_dir():
        return stats

    session_files = 0
    for file in root.rglob("*.jsonl"):
        if ".lock" in file.name:
            continue
        session_files += 1
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
                    rec = _usage_record(obj)
                    if rec is None:
                        continue
                    model, provider, u = rec
                    if not isinstance(u, dict):
                        continue
                    c = u.get("cost") if isinstance(u, dict) else {}
                    model = model or "unknown"
                    provider = provider or ""
                    key = f"{provider}/{model}" if provider else model

                    def _n(d, k):
                        v = d.get(k) if isinstance(d, dict) else 0
                        return int(v) if isinstance(v, (int, float)) else 0

                    stats.add_model(
                        key,
                        ModelUsage(
                            model=model,
                            provider=provider,
                            input=_n(u, "input"),
                            output=_n(u, "output"),
                            cache_read=_n(u, "cacheRead"),
                            cache_write=_n(u, "cacheWrite"),
                            cost=float(c.get("total", 0)) if isinstance(c, dict) else 0.0,
                            calls=1,
                        ),
                    )
        except OSError:
            continue

    stats.sessions = session_files
    stats.accumulate_model_totals()
    return stats


def read_limits() -> dict:
    """Return omp's native provider quota snapshot (best-effort).

    Returns {} if `omp` is absent or fails — caller should degrade gracefully.
    """
    try:
        out = subprocess.run(
            ["omp", "usage", "--json"],
            capture_output=True, text=True, timeout=20,
        )
        if out.returncode != 0:
            return {}
        return json.loads(out.stdout) if out.stdout.strip() else {}
    except (OSError, subprocess.TimeoutExpired, json.JSONDecodeError):
        return {}
