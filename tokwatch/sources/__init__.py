"""Host data-source adapters. Each exposes a scan function returning Stats."""
from .claude import parse_statusline_stdin, scan_jsonl as scan_claude
from .omp import scan_sessions as scan_omp
from .codex import scan_sqlite as scan_codex

__all__ = [
    "parse_statusline_stdin",
    "scan_claude",
    "scan_omp",
    "scan_codex",
]
