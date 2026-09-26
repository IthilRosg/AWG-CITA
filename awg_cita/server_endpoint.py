"""Atomic endpoint metadata updates and safe client configuration projection."""
from __future__ import annotations

import hashlib
import json
import os
import re
import select
import stat
import sys
import time
from pathlib import Path

from .real_awg import valid_endpoint_host

_REVISION = re.compile(r'[0-9a-f]{64}\Z')
_ENDPOINT = re.compile(r'Endpoint = ([A-Za-z0-9.-]{1,253}):([0-9]{1,5})\Z')
BACKUPS = Path('/var/backups/awg-cita-server-settings')


def revision(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def validate_request(value: object) -> tuple[str, str]:
    if (not isinstance(value, dict) or set(value) != {'expectedRevision', 'endpoint'} or
            not isinstance(value['expectedRevision'], str) or not _REVISION.fullmatch(value['expectedRevision']) or
            not valid_endpoint_host(value['endpoint'])):
        raise ValueError('invalid endpoint request')
    return value['expectedRevision'], value['endpoint']


def read_request() -> tuple[str, str]:
    body = bytearray()
    deadline = time.monotonic() + 5
    while True:
        if not select.select([sys.stdin.fileno()], [], [], max(0, deadline - time.monotonic()))[0]:
            raise ValueError('incomplete endpoint request')
        chunk = os.read(sys.stdin.fileno(), 513 - len(body))
        if not chunk:
            break
        body.extend(chunk)
        if len(body) > 512:
            raise ValueError('endpoint request too long')
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError('duplicate endpoint field')
            result[key] = value
        return result
    return validate_request(json.loads(body.decode('ascii'), object_pairs_hook=unique))


def project_client_endpoint(text: str, endpoint: str, port: int, *, expected_stored_port: int | None = None) -> str:
    """Materialize the current server host without changing stored keys or client edits."""
    if not valid_endpoint_host(endpoint) or type(port) is not int or not 1 <= port <= 65535:
        raise ValueError('invalid server endpoint')
    if not isinstance(text, str) or not text.endswith('\n') or len(text.encode('ascii')) > 2400:
        raise ValueError('invalid client configuration')
    section = ''
    found = 0
    lines = []
    for line in text.splitlines():
        if line in ('[Interface]', '[Peer]'):
            section = line
        elif line.startswith('Endpoint = '):
            match = _ENDPOINT.fullmatch(line)
            if (section != '[Peer]' or match is None or not valid_endpoint_host(match[1]) or
                    not 1 <= int(match[2]) <= 65535 or
                    (expected_stored_port is not None and int(match[2]) != expected_stored_port)):
                raise ValueError('invalid stored endpoint')
            line = f'Endpoint = {endpoint}:{port}'
            found += 1
        lines.append(line)
    if found != 1:
        raise ValueError('missing or duplicate endpoint')
    result = '\n'.join(lines) + '\n'
    if len(result.encode('ascii')) > 2400:
        raise ValueError('client configuration too long')
    return result


def read_root_settings(path: Path, limit: int) -> bytes:
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o077:
            raise ValueError('unsafe server settings')
        raw = os.read(fd, limit + 1)
    finally:
        os.close(fd)
    if not 1 <= len(raw) <= limit:
        raise ValueError('invalid server settings')
    return raw


def _write_new(path: Path, raw: bytes) -> None:
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
    except BaseException:
        path.unlink(missing_ok=True)
        raise


def _fsync_directory(path: Path) -> None:
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def replace_endpoint(path: Path, *, profile: str, expected_revision: str, endpoint: str,
                     limit: int, verify) -> str:
    """Change one root-owned metadata file; preserve a private backup and roll back on failure."""
    validate_request({'expectedRevision': expected_revision, 'endpoint': endpoint})
    if profile not in {'awg3', 'awg2', 'wg'}:
        raise ValueError('invalid profile')
    current = read_root_settings(path, limit)
    if revision(current) != expected_revision:
        raise ValueError('server settings changed')
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError('duplicate settings field')
            result[key] = value
        return result
    value = json.loads(current, object_pairs_hook=unique)
    if not isinstance(value, dict) or not valid_endpoint_host(value.get('endpoint_host')):
        raise ValueError('invalid server settings')
    if value['endpoint_host'] == endpoint:
        return expected_revision
    value['endpoint_host'] = endpoint
    replacement = (json.dumps(value, separators=(',', ':'), ensure_ascii=True) + '\n').encode('ascii')
    if len(replacement) > limit:
        raise ValueError('server settings too long')
    parent = os.lstat(path.parent)
    if not stat.S_ISDIR(parent.st_mode) or parent.st_uid != 0 or parent.st_mode & 0o022:
        raise ValueError('unsafe server settings directory')
    BACKUPS.mkdir(mode=0o700, exist_ok=True)
    backup_dir = os.lstat(BACKUPS)
    if not stat.S_ISDIR(backup_dir.st_mode) or backup_dir.st_uid != 0 or backup_dir.st_mode & 0o077:
        raise ValueError('unsafe server backup directory')
    backup = BACKUPS / (profile + '-' + str(time.time_ns()) + '.json')
    _write_new(backup, current)
    _fsync_directory(BACKUPS)
    temp = path.with_name('.' + path.name + '.awg-cita-' + str(os.getpid()))
    replaced = False
    try:
        _write_new(temp, replacement)
        if read_root_settings(path, limit) != current:
            raise ValueError('server settings changed')
        os.replace(temp, path)
        replaced = True
        _fsync_directory(path.parent)
        verify()
        if read_root_settings(path, limit) != replacement:
            raise ValueError('server settings readback failed')
        return revision(replacement)
    except BaseException:
        if replaced:
            restore = path.with_name('.' + path.name + '.rollback-' + str(os.getpid()))
            try:
                _write_new(restore, current)
                os.replace(restore, path)
                _fsync_directory(path.parent)
            finally:
                restore.unlink(missing_ok=True)
        raise
    finally:
        temp.unlink(missing_ok=True)
