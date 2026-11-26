"""Pin check: every outside tool our images pull must have an exact version (and a checksum for plain downloads).

Rule: external tools get exact versions plus checksums, so the same Dockerfile builds the same image next month and
gives the same bytes. This finds what breaks it, by machine:
  - pip packages without ==, or a git+ URL without a commit;
  - git clone without a later checkout of a fixed commit;
  - curl / wget downloads without a sha256 check in the same RUN.

  python scripts/check_pins.py                      # our tool images (Dockerfile.tools, Dockerfile.rig, Dockerfile.artist)
  python scripts/check_pins.py Dockerfile.trellis2  # any others
Exit code 1 when something is loose. Licences are not checked here: they are written in research notes per tool.
"""

from __future__ import annotations

import re
import shlex
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT = ["Dockerfile.tools", "Dockerfile.rig", "Dockerfile.artist"]


def runs(text: str) -> list[tuple[int, str]]:
    """RUN commands with backslash lines joined, each with its first line number."""
    out, cur, start = [], "", 0
    for i, line in enumerate(text.splitlines(), 1):
        s = line.strip()
        if not cur:
            if not s.upper().startswith("RUN "):
                continue
            start, cur = i, s[4:]
        else:
            cur += " " + s
        if cur.endswith("\\"):
            cur = cur[:-1]
            continue
        out.append((start, cur))
        cur = ""
    return out


def pip_args(cmd: str) -> list[str]:
    found = []
    for part in re.split(r"&&|;|\|\|", cmd):
        try:
            words = shlex.split(part)
        except ValueError:
            words = part.split()
        if "pip" not in " ".join(words[:3]) or "install" not in words:
            continue
        skip = False
        for w in words[words.index("install") + 1:]:
            if skip:
                skip = False
                continue
            if w in ("-r", "-c", "-f", "--index-url", "--extra-index-url", "--find-links", "-i"):
                skip = w in ("-f", "--index-url", "--extra-index-url", "--find-links", "-i")  # -r/-c files: their own pins
                if w in ("-r", "-c"):
                    skip = True
                continue
            if w.startswith("-") or w.startswith("/") or w.startswith("."):
                continue
            found.append(w)
    return found


def variables(text: str) -> dict[str, str]:
    """ENV NAME=value / ARG NAME=value, so a pin written once (git checkout "$SKINTOKENS_SHA") is seen as a pin."""
    out = {}
    for m in re.finditer(r"^(?:ENV|ARG)\s+(\w+)[= ]\"?([^\s\"]*)", text, re.M):
        out[m.group(1)] = m.group(2)
    return out


def loose(path: Path) -> list[str]:
    bad = []
    text = path.read_text(encoding="utf-8")
    env = variables(text)
    for line, cmd in runs(text):
        cmd = re.sub(r"\$\{?(\w+)\}?", lambda m: env.get(m.group(1), m.group(0)), cmd)
        for pkg in pip_args(cmd):
            if pkg in ("pip", "setuptools", "wheel") and "--upgrade" in cmd:
                bad.append(f"{path.name}:{line} pip upgrades itself to whatever is newest ({pkg})")
            elif pkg.startswith("git+"):
                if not re.search(r"@[0-9a-f]{7,40}$", pkg):
                    bad.append(f"{path.name}:{line} git package without a commit: {pkg}")
            elif "==" not in pkg:
                bad.append(f"{path.name}:{line} pip package without an exact version: {pkg}")
        for m in re.finditer(r"git clone\s+(?:--[\w-]+\s+)*(\S+)", cmd):
            if not re.search(r"(checkout|reset --hard)\s+[\"']?[0-9a-f]{7,40}", cmd):
                bad.append(f"{path.name}:{line} git clone without a fixed commit: {m.group(1)}")
        if re.search(r"\b(curl|wget)\b[^&;|]*https?://", cmd) and "sha256" not in cmd:  # a real download, not apt installing curl
            bad.append(f"{path.name}:{line} download without a sha256 check")
    return bad


def main() -> int:
    names = sys.argv[1:] or DEFAULT
    bad, seen = [], 0
    for n in names:
        p = ROOT / n
        if not p.exists():
            continue
        seen += 1
        bad += loose(p)
    for b in bad:
        print(b)
    print(f"{seen} file(s), {len(bad)} loose pin(s)")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
