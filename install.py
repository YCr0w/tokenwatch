#!/usr/bin/env python3
"""tokwatch installer — auto-detect Claude Code / Codex / omp and register into each.

Detects a host by its CLI binary on PATH or its config/data directory, then
installs to that host's real config location (idempotent, non-destructive):

  Claude Code : ~/.claude/settings.json   -> statusLine.command
  omp         : ~/.omp/agent/config.yml   -> statusLine (native `usage` segment)
  Codex CLI   : no hook mechanism         -> report only (use `codex /status`)

Also copies the CLI + `tokwatch` package into each detected host's plugin dir
(~/.claude/tokwatch, ~/.codex/tokwatch, ~/.omp/tokwatch — self-contained, the
repo can be moved or deleted afterwards) and adds each tokwatch/bin to PATH.

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
HOST_DIRS = {"claude": HOME / ".claude", "codex": HOME / ".codex", "omp": HOME / ".omp"}
CLI_NAMES = ("tokwatch", "tokwatch-claude-statusline")


def install_dir(host: str) -> Path:
    """Per-host plugin home: ~/.claude/tokwatch, ~/.codex/tokwatch, ~/.omp/tokwatch."""
    return HOST_DIRS[host] / "tokwatch"


def bin_dir(host: str) -> Path:
    return install_dir(host) / "bin"

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


def _norm(p: str) -> str:
    return os.path.normcase(os.path.normpath(p))


def install_files(hosts: list[str], dry_run: bool = False) -> list[str]:
    """Copy bin/ + the tokwatch package into each host's dir, put bins on PATH."""
    out: list[str] = []
    for host in hosts:
        d, b = install_dir(host), bin_dir(host)
        if dry_run:
            out.append(f"would copy bin/ + tokwatch/ -> {d}")
            if os.name == "nt":
                out.extend(f"would write {b / (n + '.cmd')}" for n in CLI_NAMES)
            out.extend(ensure_on_path(b, dry_run=True))
            continue
        b.mkdir(parents=True, exist_ok=True)
        for name in CLI_NAMES:
            shutil.copy2(REPO / "bin" / name, b / name)
            (b / name).chmod(0o755)
            if os.name == "nt":
                # Windows cannot exec extensionless scripts from PATH — add .cmd shims.
                (b / f"{name}.cmd").write_text(
                    f'@echo off\r\n"{sys.executable}" "%~dp0{name}" %*\r\n',
                    encoding="utf-8",
                )
        shutil.copytree(REPO / "tokwatch", d / "tokwatch", dirs_exist_ok=True)
        out.append(f"installed {d} (bin/ + tokwatch/ package — repo no longer needed)")
        out.extend(ensure_on_path(b))
    return out


def ensure_on_path(bdir: Path, dry_run: bool = False) -> list[str]:
    target = _norm(str(bdir))
    session = [_norm(p) for p in os.environ.get("PATH", "").split(os.pathsep) if p.strip()]
    if target in session:
        return [f"path: {bdir} already on PATH"]
    if os.name == "nt":
        return _win_ensure_path(bdir, dry_run)
    return _posix_ensure_path(bdir, dry_run)


def _win_ensure_path(bdir: Path, dry_run: bool) -> list[str]:
    import winreg

    target = _norm(str(bdir))
    with winreg.OpenKey(
        winreg.HKEY_CURRENT_USER, "Environment", 0, winreg.KEY_READ | winreg.KEY_WRITE
    ) as key:
        try:
            raw, typ = winreg.QueryValueEx(key, "Path")
        except FileNotFoundError:
            raw, typ = "", winreg.REG_EXPAND_SZ
        if typ not in (winreg.REG_SZ, winreg.REG_EXPAND_SZ):
            typ = winreg.REG_EXPAND_SZ
        parts = [p for p in raw.split(";") if p.strip()]
        if any(_norm(os.path.expandvars(p)) == target for p in parts):
            return [f"path: {bdir} already in user PATH (open a new terminal to pick it up)"]
        if dry_run:
            return [f"would add {bdir} to user PATH (HKCU\\Environment)"]
        winreg.SetValueEx(key, "Path", 0, typ, ";".join([*parts, str(bdir)]))
    return [f"path: added {bdir} to user PATH (HKCU\\Environment) — open a new terminal"]


def _posix_ensure_path(bdir: Path, dry_run: bool) -> list[str]:
    rc = HOME / ".profile"
    line = f'export PATH="{bdir}:$PATH"'
    text = rc.read_text(encoding="utf-8") if rc.is_file() else ""
    if line in text:
        return [f"path: {bdir} export already in {rc} (open a new shell)"]
    if dry_run:
        return [f"would append PATH export -> {rc}"]
    rc.write_text(text.rstrip() + "\n" + line + "\n", encoding="utf-8")
    return [f"path: appended {bdir} export -> {rc} (open a new shell)"]


def uninstall_files(hosts: list[str]) -> list[str]:
    out: list[str] = []
    for host in hosts:
        d = install_dir(host)
        if d.exists():
            shutil.rmtree(d, ignore_errors=True)
            out.append(f"removed {d}")
        else:
            out.append(f"nothing to remove at {d}")
        out.extend(_remove_from_path(bin_dir(host)))
    return out


def _remove_from_path(bdir: Path) -> list[str]:
    target = _norm(str(bdir))
    if os.name == "nt":
        import winreg

        try:
            with winreg.OpenKey(
                winreg.HKEY_CURRENT_USER, "Environment", 0, winreg.KEY_READ | winreg.KEY_WRITE
            ) as key:
                raw, typ = winreg.QueryValueEx(key, "Path")
                if typ not in (winreg.REG_SZ, winreg.REG_EXPAND_SZ):
                    typ = winreg.REG_EXPAND_SZ
                parts = [p for p in raw.split(";") if p.strip()]
                kept = [p for p in parts if _norm(os.path.expandvars(p)) != target]
                if len(kept) == len(parts):
                    return [f"path: {bdir} not in user PATH"]
                winreg.SetValueEx(key, "Path", 0, typ, ";".join(kept))
            return [f"path: removed {bdir} from user PATH"]
        except FileNotFoundError:
            return ["path: no user PATH entry"]
    rc = HOME / ".profile"
    line = f'export PATH="{bdir}:$PATH"'
    text = rc.read_text(encoding="utf-8") if rc.is_file() else ""
    if line not in text:
        return ["path: nothing to remove"]
    rc.write_text(text.replace(line + "\n", "").replace(line, ""), encoding="utf-8")
    return [f"path: removed {bdir} export from {rc}"]


def _read_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _statusline_cmd() -> str:
    script = bin_dir("claude") / "tokwatch-claude-statusline"
    if os.name == "nt":
        return f'"{sys.executable}" "{script}"'
    return f"python3 {script}"


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
    ap.add_argument("--no-copy", action="store_true", help="skip copying CLI into agent dirs and PATH setup")
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

    if args.uninstall:
        for line in uninstall_files(hosts):
            print(line)
    elif not args.no_copy:
        for line in install_files(hosts, dry_run=args.dry_run):
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
