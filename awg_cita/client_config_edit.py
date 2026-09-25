"""Constrained, atomic edits to saved client configuration files."""
from __future__ import annotations

import hashlib
import os
import re
import stat
import sys
from pathlib import Path

from .client_templates import validate

_KEYS = {
    'Interface': {'DNS': 'dns_server', 'MTU': 'mtu'},
    'Peer': {'AllowedIPs': 'allowed_ips', 'PersistentKeepalive': 'keepalive'},
}
_REVISION = re.compile(r'[0-9a-f]{64}\Z')


def revision(text: str) -> str:
    return hashlib.sha256(text.encode('ascii')).hexdigest()


def editable_values(text: str) -> dict[str, object]:
    fields: dict[str, object] = {}
    section = ''
    for line in text.splitlines():
        if line in ('[Interface]', '[Peer]'):
            section = line[1:-1]
        elif ' = ' in line:
            key, value = line.split(' = ', 1)
            field = _KEYS.get(section, {}).get(key)
            if field:
                if field in fields:
                    raise ValueError('duplicate editable field')
                fields[field] = int(value) if field in {'mtu', 'keepalive'} else value
    if 'mtu' not in fields:
        fields['mtu'] = 1420
    return validate(fields)


def replace_editable(text: str, value: object) -> str:
    settings = validate(value)
    editable_values(text)
    section = ''
    seen: set[str] = set()
    lines: list[str] = []
    for line in text.splitlines():
        if line in ('[Interface]', '[Peer]'):
            if line == '[Peer]' and 'mtu' not in seen:
                lines.append(f'MTU = {settings["mtu"]}')
                seen.add('mtu')
            section = line[1:-1]
        elif ' = ' in line:
            key = line.split(' = ', 1)[0]
            field = _KEYS.get(section, {}).get(key)
            if field:
                line = f'{key} = {settings[field]}'
                seen.add(field)
        lines.append(line)
    if seen != set(settings):
        raise ValueError('incomplete editable fields')
    result = '\n'.join(lines) + '\n'
    if len(result.encode('ascii')) > 2400:
        raise ValueError('client configuration too long')
    return result


def atomic_replace(path: Path, expected: str, replacement: str) -> None:
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o077:
            raise ValueError('unsafe saved client configuration')
        if os.read(fd, 2401) != expected.encode('ascii'):
            raise ValueError('saved client configuration changed')
    finally:
        os.close(fd)
    temp = path.with_name('.' + path.name + '-' + str(os.getpid()))
    write_fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    try:
        with os.fdopen(write_fd, 'wb') as stream:
            stream.write(replacement.encode('ascii'))
            stream.flush()
            os.fsync(stream.fileno())
        verify_fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
        try:
            if os.read(verify_fd, 2401) != expected.encode('ascii'):
                raise ValueError('saved client configuration changed')
        finally:
            os.close(verify_fd)
        os.replace(temp, path)
        directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        temp.unlink(missing_ok=True)


def validate_revision(value: object) -> str:
    if not isinstance(value, str) or not _REVISION.fullmatch(value):
        raise ValueError('invalid configuration revision')
    return value


def read_update_request() -> tuple[str, dict[str, object]]:
    import json
    import select
    import time

    body = bytearray()
    deadline = time.monotonic() + 5
    while True:
        if not select.select([sys.stdin.fileno()], [], [], max(0, deadline - time.monotonic()))[0]:
            raise ValueError('incomplete configuration request')
        chunk = os.read(sys.stdin.fileno(), 513 - len(body))
        if not chunk:
            break
        body.extend(chunk)
        if len(body) > 512:
            raise ValueError('configuration request too long')
    def unique(pairs):
        result = {}
        for key, item in pairs:
            if key in result:
                raise ValueError('duplicate configuration field')
            result[key] = item
        return result
    value = json.loads(body.decode('ascii'), object_pairs_hook=unique)
    if not isinstance(value, dict) or set(value) != {'expectedRevision', 'settings'}:
        raise ValueError('invalid configuration request')
    return validate_revision(value['expectedRevision']), validate(value['settings'])
