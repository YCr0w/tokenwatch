#!/usr/bin/env python3
"""tokwatch installer — auto-detect Claude Code / Codex / omp and register into each.

Detects a host by its CLI binary on PATH or its config/data directory, then
installs to that host's real config location (idempotent, non-destructive):

  Claude Code : ~/.claude/settings.json   -> statusLine.command
  omp         : ~/.omp/agent/config.yml   -> statusLine (native `usage` segment)
  Codex CLI   : no hook mechanism         -> report only (use `codex /status`)

Also symlinks the `tokwatch` CLI into a bin dir already on PATH.

  python3 install.py                # detect + install
  python3 install.py --dry-run      # print what would change, write nothing
  python3 install.py --uninstall    # remove registrations
  python3 install.py --only claude,omp
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from pathlib import Path

HOME = Path.home()
REPO = Path(__file__).resolve().parent

OMP_BLOCK = """# tokwatch: show provider quota (5h/7d etc.) in the omp statusline.
# Merge with an existing statusLine: key by hand if one is already present.
statusLine:
  preset: custom
  separator: powerline-thin
  leftSegments: [pi, model, mode, collab, path, git, pr, context_pct, cost]
  rightSegments: [usage, session_name]
  segmentOptions:
    model:
      showThinkingLevel: true
    path:
      abbreviate: true
      maxLength: 40
      stripWorkPrefix: true
    git:
      showBranch: true
      showStaged: true
      showUnstaged: true
      showUntracked: true
"""


def detect_hosts() -> dict[str, bool]:
    return {
        "claude": bool(shutil.which("claude")) or (HOME / ".claude").is_dir(),
        "codex": bool(shutil.which("codex")) or (HOME / ".codex").is_dir(),
        "omp": bool(shutil.which("omp")) or (HOME / ".omp").is_dir(),
    }


def choose_bin_dir() -> Path:
    path_dirs = {Path(p) for p in os.environ.get("PATH", "").split(os.pathsep) if p}
    for cand in (
        os.environ.get("TOKWATCH_BIN_DIR"),
        str(HOME / ".local" / "bin"),
        str(HOME / "bin"),
    ):
        if cand and Path(cand) in path_dirs:
            return Path(cand)
    return HOME / ".local" / "bin"


def symlink_cli(bin_dir: Path, dry_run: bool = False) -> list[str]:
    out: list[str] = []
    if dry_run:
        for name in ("tokwatch", "tokwatch-claude-statusline"):
            out.append(f"would link {bin_dir / name} -> {REPO / 'bin' / name}")
        path_dirs = {Path(p) for p in os.environ.get("PATH", "").split(os.pathsep) if p}
        if bin_dir not in path_dirs:
            out.append(f"warn: {bin_dir} is not on PATH — add it to your shell rc")
        return out

    bin_dir.mkdir(parents=True, exist_ok=True)
    for name in ("tokwatch", "tokwatch-claude-statusline"):
        dst = bin_dir / name
        src = REPO / "bin" / name
        try:
            if dst.is_symlink() or dst.exists():
                dst.unlink()
            os.symlink(src, dst)
            out.append(f"linked {dst} -> {src}")
        except OSError as e:
            out.append(f"warn: cannot link {dst}: {e}")
    path_dirs = {Path(p) for p in os.environ.get("PATH", "").split(os.pathsep) if p}
    if bin_dir not in path_dirs:
        out.append(f"warn: {bin_dir} is not on PATH — add it to your shell rc")
    return out


def _read_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _statusline_cmd() -> str:
    return f"python3 {REPO / 'bin' / 'tokwatch-claude-statusline'}"


def install_claude(dry_run: bool) -> str:
    settings_path = HOME / ".claude" / "settings.json"
    settings = _read_json(settings_path)
    cmd = _statusline_cmd()
    if settings.get("statusLine", {}).get("command") == cmd:
        return "claude: already installed"
    settings["statusLine"] = {"type": "command", "command": cmd}
    if dry_run:
        return f"claude (dry-run): set statusLine -> {cmd}"
    settings_path.parent.mkdir(parents=True, exist_ok=True)
    settings_path.write_text(
        json.dumps(settings, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    return f"claude: set statusLine -> {cmd}"


def uninstall_claude() -> str:
    settings_path = HOME / ".claude" / "settings.json"
    settings = _read_json(settings_path)
    if "statusLine" in settings:
        del settings["statusLine"]
        settings_path.write_text(
            json.dumps(settings, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
        return "claude: removed statusLine"
    return "claude: nothing to remove"


def install_omp(dry_run: bool) -> str:
    cfg = HOME / ".omp" / "agent" / "config.yml"
    text = cfg.read_text(encoding="utf-8") if cfg.is_file() else ""
    if "statusLine:" in text:
        return "omp: statusLine already present (add 'usage' to rightSegments manually)"
    if dry_run:
        return "omp (dry-run): would append statusLine (native `usage` segment)"
    cfg.parent.mkdir(parents=True, exist_ok=True)
    cfg.write_text(text.rstrip() + "\n" + OMP_BLOCK, encoding="utf-8")
    return f"omp: appended statusLine -> {cfg}"


def uninstall_omp() -> str:
    return "omp: remove the 'statusLine' block from config.yml manually"


def codex_info() -> str:
    return "codex: no hook to register — use `codex /status` for quota, `tokwatch codex` for tokens"


def main() -> int:
    ap = argparse.ArgumentParser(prog="tokwatch-install")
    ap.add_argument("--dry-run", action="store_true", help="print changes, write nothing")
    ap.add_argument("--uninstall", action="store_true", help="remove registrations")
    ap.add_argument("--only", help="comma-separated hosts (claude,codex,omp)")
    ap.add_argument("--no-symlink", action="store_true", help="skip CLI symlinks")
    args = ap.parse_args()

    detected = detect_hosts()
    order = ("claude", "codex", "omp")
    hosts = [h for h in order if detected[h]]

    print("detected:", ", ".join(hosts) if hosts else "none")
    if args.only:
        wanted = {x.strip() for x in args.only.split(",") if x.strip()}
        hosts = [h for h in hosts if h in wanted]
        for h in wanted:
            if h not in detected:
                print(f"skip {h}: not detected on this system")

    if not args.no_symlink and not args.uninstall:
        for line in symlink_cli(choose_bin_dir(), dry_run=args.dry_run):
            print(line)

    print()
    for h in hosts:
        if h == "claude":
            print(uninstall_claude() if args.uninstall else install_claude(args.dry_run))
        elif h == "omp":
            print(uninstall_omp() if args.uninstall else install_omp(args.dry_run))
        elif h == "codex":
            print(codex_info())

    if not args.uninstall and not args.dry_run:
        print("\ntokwatch ready. Try: tokwatch all | tokwatch omp --limits")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
