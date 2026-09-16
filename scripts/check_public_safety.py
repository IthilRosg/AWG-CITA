"""Fail closed on unsafe content in the exact intended public release file set."""

from __future__ import annotations

import ipaddress

import re
import stat
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TEXT_SUFFIXES = {"", ".md", ".py", ".js", ".json", ".toml", ".yml", ".yaml"}
FORBIDDEN_NAMES = {".env", ".env.local", ".env.production"}
FORBIDDEN_SUFFIXES = {".pem", ".key", ".p12", ".pfx", ".crt", ".cer"}
PATTERNS = {
    "private_key_block": r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----",
    "bcrypt_hash": r"\$2[aby]\$\d{2}\$[./A-Za-z0-9]{53}",
    "awg_or_wireguard_uri": r"(?i)\b(?:amneziawg|wireguard)://",
    "github_token": r"\bgh[pousr]_[A-Za-z0-9_]{20,}\b",
    "openai_key": rf"\b{'s' + 'k'}-[A-Za-z0-9_-]{{20,}}\b",
    "gitlab_token": rf"\b{'gl' + 'pat'}-[A-Za-z0-9_-]{{20,}}\b",
    "google_api_key": rf"\b{'AI' + 'za'}[A-Za-z0-9_-]{{20,}}\b",
    "jwt": r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\b",
    "aws_access_key": r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b",
    "slack_token": r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b",
    "sensitive_assignment": r"(?i)\b(?:api[_ -]?(?:key|token)|secret|password|preshared[_ -]?key)\s*[:=]\s*['\"]?[A-Za-z0-9_./+=-]{8,}",
    "wireguard_style_key": r"(?<![A-Za-z0-9+/=])[A-Za-z0-9+/]{43}=(?![A-Za-z0-9+/=])",
    "known_production_marker": rf"(?i)\b(?:{'cita' + 'eris'}\.{'xyz'}|{'se' + '-1'}|{'de' + '-1'})\b",
}
IP_CANDIDATE = re.compile(r"(?<![\w:])(?:[0-9A-Fa-f:.]{2,})(?![\w:])")


def candidate_files() -> list[Path]:
    result = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
        cwd=ROOT,
        check=True,
        capture_output=True,
    )
    paths: list[Path] = []
    for raw_path in result.stdout.split(b"\0"):
        if not raw_path:
            continue
        try:
            relative = raw_path.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise RuntimeError("non_utf8_candidate_path") from exc
        paths.append(ROOT / relative)
    return sorted(paths)


def public_ip_literals(text: str) -> list[str]:
    found: list[str] = []
    for candidate in IP_CANDIDATE.findall(text):
        if candidate.count(".") == 3 and ":" in candidate:
            candidate = candidate.split(":", 1)[0]
        if not any(character.isdigit() for character in candidate):
            continue
        try:
            address = ipaddress.ip_address(candidate)
        except ValueError:
            continue
        if not address.is_loopback:
            found.append(candidate)
    return found


def main() -> int:
    failures: list[str] = []
    files = candidate_files()
    for path in files:
        relative = path.relative_to(ROOT)
        mode = path.lstat().st_mode
        if path.is_symlink() or not stat.S_ISREG(mode):
            failures.append(f"non_regular_candidate_file:{relative}")
            continue
        if relative.name in FORBIDDEN_NAMES or relative.suffix.lower() in FORBIDDEN_SUFFIXES:
            failures.append(f"forbidden_file:{relative}")
            continue
        if relative.suffix.lower() not in TEXT_SUFFIXES:
            failures.append(f"unclassified_candidate_file:{relative}")
            continue
        raw = path.read_bytes()
        if b"\0" in raw:
            failures.append(f"binary_candidate_file:{relative}")
            continue
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError:
            failures.append(f"non_utf8_candidate_file:{relative}")
            continue
        for label, pattern in PATTERNS.items():
            if re.search(pattern, text):
                failures.append(f"{label}:{relative}")
        for address in public_ip_literals(text):
            failures.append(f"non_loopback_ip:{relative}:{address}")
    if failures:
        print("public_safety=FAIL " + ", ".join(failures))
        return 1
    print(f"public_safety=PASS files_scanned={len(files)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
