"""Scan every reachable Git blob without printing possible secret values."""

from __future__ import annotations

import re
import subprocess
from pathlib import PurePosixPath

from check_public_safety import FORBIDDEN_NAMES, FORBIDDEN_SUFFIXES, PATTERNS, ROOT, public_ip_literals


def git(*args: str) -> bytes:
    return subprocess.check_output(("git", *args), cwd=ROOT)


def main() -> int:
    findings: list[str] = []
    visited: set[str] = set()
    for item in git("rev-list", "--objects", "--all").splitlines():
        oid, _, raw_path = item.partition(b" ")
        sha = oid.decode("ascii")
        path = raw_path.decode("utf-8", "replace") or "<unknown>"
        name = PurePosixPath(path)
        if name.name in FORBIDDEN_NAMES or name.suffix.lower() in FORBIDDEN_SUFFIXES:
            findings.append(f"sensitive_filename:{sha[:12]}:{path}")
        if sha in visited:
            continue
        visited.add(sha)
        if git("cat-file", "-t", sha).strip() != b"blob":
            continue
        raw = git("cat-file", "blob", sha)
        if len(raw) > 1_000_000:
            findings.append(f"large_blob:{sha[:12]}:{path}")
        if b"\0" in raw:
            findings.append(f"binary_blob:{sha[:12]}:{path}")
            continue
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError:
            findings.append(f"non_utf8_blob:{sha[:12]}:{path}")
            continue
        for label, pattern in PATTERNS.items():
            # Historical synthetic tests intentionally use fields such as
            # privateKey and X-CSRF-Token. Strong token formats and key blocks
            # remain checked, while contextual assignments are reviewed in
            # the current candidate scan.
            if label == "sensitive_assignment":
                continue
            if re.search(pattern, text):
                findings.append(f"{label}:{sha[:12]}:{path}")
        for _address in public_ip_literals(text):
            findings.append(f"non_loopback_ip:{sha[:12]}:{path}")
    if findings:
        print("git_history_safety=FAIL " + ", ".join(sorted(set(findings))))
        return 1
    print(f"git_history_safety=PASS objects_scanned={len(visited)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
