"""Unified CLI: `tokwatch <host> [flags]` across Claude Code / Codex / omp."""
from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

from .core import Stats
from . import render
from . import sources

HOME = Path.home()


def _default_paths() -> dict:
    return {
        "claude": os.environ.get("TOKWATCH_CLAUDE_DIR", str(HOME / ".claude" / "projects")),
        "codex": os.environ.get("TOKWATCH_CODEX_DB", str(HOME / ".codex" / "state_5.sqlite")),
        "omp": os.environ.get("TOKWATCH_OMP_DIR", str(HOME / ".omp" / "agent" / "sessions")),
    }


def _scan(host: str) -> Stats:
    paths = _default_paths()
    if host == "claude":
        return sources.scan_claude(paths["claude"])
    if host == "codex":
        return sources.scan_codex(paths["codex"])
    if host == "omp":
        return sources.scan_omp(paths["omp"])
    raise ValueError(f"unknown host: {host}")


def _collect(hosts: list[str]) -> list[Stats]:
    return [_scan(h) for h in hosts]


def _emit(stats_list: list[Stats], as_json: bool) -> None:
    if as_json:
        print(render.json_report(stats_list))
    else:
        print(render.report(stats_list))


def _watch(hosts: list[str], interval: int, as_json: bool) -> None:
    try:
        while True:
            os.system("cls" if os.name == "nt" else "clear")
            print(f"tokwatch {','.join(hosts)}  (refresh {interval}s, Ctrl-C to stop)")
            _emit(_collect(hosts), as_json)
            time.sleep(interval)
    except KeyboardInterrupt:
        print()


def statusline_main() -> int:
    """Claude Code `statusLine.command` entrypoint: stdin JSON -> one line."""
    try:
        raw = sys.stdin.read()
    except OSError:
        raw = ""
    stats = sources.parse_statusline_stdin(raw)
    line = render.statusline(stats)
    try:
        sys.stdout.write(line + "\n")
        sys.stdout.flush()
    except BrokenPipeError:
        # Claude Code closed the pipe (typing/debounce) — normal, exit cleanly.
        pass
    return 0


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="tokwatch",
        description="Cross-host AI coding CLI token usage watcher "
        "(Claude Code / Codex / omp). Zero dependencies.",
    )
    p.add_argument(
        "host",
        nargs="?",
        default="all",
        choices=["claude", "codex", "omp", "all"],
        help="which host to read (default: all)",
    )
    p.add_argument("--json", action="store_true", help="machine-readable output")
    p.add_argument("--watch", type=int, metavar="SEC", help="poll mode (file-backed hosts)")
    p.add_argument("--width", type=int, default=10, help="statusline bar width")
    p.add_argument("--limits", action="store_true", help="omp only: show native provider quota")
    return p


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)

    if args.limits:
        if args.host not in ("omp", "all"):
            print("--limits is omp-only", file=sys.stderr)
            return 2
        from .sources.omp import read_limits

        limits = read_limits()
        if not limits:
            print("no quota data (is `omp` authenticated? run `omp usage`)", file=sys.stderr)
            return 1
        print(render.render_limits(limits))
        return 0

    hosts = ["claude", "codex", "omp"] if args.host == "all" else [args.host]

    if args.watch:
        _watch(hosts, args.watch, args.json)
        return 0

    _emit(_collect(hosts), args.json)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
