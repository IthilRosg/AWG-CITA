"""Bounded, reversible listen-port migration for one isolated server interface."""
from __future__ import annotations

import base64
import json
import os
import re
import select
import socket
import stat
import subprocess
import sys
import time
from pathlib import Path

from .server_endpoint import BACKUPS, _fsync_directory, _write_new, read_root_settings, revision

_REVISION = re.compile(r'[0-9a-f]{64}\Z')
_ENV = {'PATH': '/usr/sbin:/usr/bin:/sbin:/bin', 'LANG': 'C', 'LC_ALL': 'C'}
_UFW = '/usr/sbin/ufw'


def validate_request(value: object) -> tuple[str, int]:
    if (not isinstance(value, dict) or set(value) != {'expectedRevision', 'listenPort'} or
            not isinstance(value['expectedRevision'], str) or not _REVISION.fullmatch(value['expectedRevision']) or
            type(value['listenPort']) is not int or not 1 <= value['listenPort'] <= 65535):
        raise ValueError('invalid listen port request')
    return value['expectedRevision'], value['listenPort']


def read_request() -> tuple[str, int]:
    body = bytearray()
    deadline = time.monotonic() + 5
    while True:
        if not select.select([sys.stdin.fileno()], [], [], max(0, deadline - time.monotonic()))[0]:
            raise ValueError('incomplete listen port request')
        chunk = os.read(sys.stdin.fileno(), 513 - len(body))
        if not chunk:
            break
        body.extend(chunk)
        if len(body) > 512:
            raise ValueError('listen port request too long')
    def unique(pairs):
        value = {}
        for key, item in pairs:
            if key in value:
                raise ValueError('duplicate request field')
            value[key] = item
        return value
    return validate_request(json.loads(body.decode('ascii'), object_pairs_hook=unique))


def replace_config_port(raw: bytes, old: int, new: int) -> bytes:
    if type(old) is not int or type(new) is not int or not 1 <= old <= 65535 or not 1 <= new <= 65535:
        raise ValueError('invalid listen port')
    lines = raw.splitlines(keepends=True)
    section = ''
    found = 0
    output = []
    for line in lines:
        if line.startswith(b'['):
            section = line.decode('ascii').strip()
        if line.startswith(b'ListenPort'):
            if section != '[Interface]' or line != f'ListenPort = {old}\n'.encode('ascii'):
                raise ValueError('server listen port drift')
            line = f'ListenPort = {new}\n'.encode('ascii')
            found += 1
        output.append(line)
    if found != 1:
        raise ValueError('missing or duplicate listen port')
    result = b''.join(output)
    if len(result) > 65536:
        raise ValueError('server config too long')
    return result


def _run(*args: str, output: bool = False) -> bytes:
    result = subprocess.run(args, stdout=subprocess.PIPE if output else subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL, timeout=20, env=_ENV)
    if result.returncode or (output and len(result.stdout) > 32768):
        raise ValueError('firewall operation failed')
    return result.stdout if output else b''


def preflight_firewall(old: int, new: int) -> None:
    if old == new:
        raise ValueError('unchanged listen port')
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
        probe.bind(('0.0.0.0', new))
    status = _run(_UFW, 'status', output=True).decode('ascii')
    if 'Status: active' not in status or not re.search(rf'(?m)^\s*{old}/udp\s+ALLOW(?: IN)?\s+', status):
        raise ValueError('existing firewall rule missing')
    if re.search(rf'(?m)^\s*{new}/udp\s+', status):
        raise ValueError('new firewall port already configured')


def allow_port(new: int, profile: str) -> None:
    if profile not in {'awg3', 'awg2', 'wg'}:
        raise ValueError('invalid profile')
    _run(_UFW, 'allow', f'{new}/udp', 'comment', 'AWG-CITA ' + profile)


def remove_new_port(new: int) -> None:
    _run(_UFW, '--force', 'delete', 'allow', f'{new}/udp')


def _pending_path(profile: str) -> Path:
    if profile not in {'awg3', 'awg2', 'wg'}:
        raise ValueError('invalid profile')
    return BACKUPS / (profile + '-port.pending')


def _metadata_port(raw: bytes, old: int, new: int, limit: int) -> bytes:
    def unique(pairs):
        value = {}
        for key, item in pairs:
            if key in value:
                raise ValueError('duplicate setting')
            value[key] = item
        return value
    value = json.loads(raw, object_pairs_hook=unique)
    if not isinstance(value, dict) or type(value.get('listen_port')) is not int or value['listen_port'] != old:
        raise ValueError('server listen port drift')
    value['listen_port'] = new
    replacement = (json.dumps(value, separators=(',', ':'), ensure_ascii=True) + '\n').encode('ascii')
    if len(replacement) > limit:
        raise ValueError('server settings too long')
    return replacement


def _secure_backup_directory() -> None:
    BACKUPS.mkdir(mode=0o700, exist_ok=True)
    info = os.lstat(BACKUPS)
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o077:
        raise ValueError('unsafe server backup directory')


def _start_journal(profile: str, old: int, new: int, config: bytes, metadata: bytes) -> None:
    _secure_backup_directory()
    pending = _pending_path(profile)
    if pending.exists() or pending.is_symlink():
        raise ValueError('pending listen port migration')
    value = {'profile': profile, 'oldPort': old, 'newPort': new,
             'config': base64.b64encode(config).decode('ascii'),
             'metadata': base64.b64encode(metadata).decode('ascii')}
    raw = (json.dumps(value, separators=(',', ':')) + '\n').encode('ascii')
    temp = BACKUPS / ('.' + pending.name + '-' + str(os.getpid()))
    try:
        _write_new(temp, raw)
        os.replace(temp, pending)
        _fsync_directory(BACKUPS)
    finally:
        temp.unlink(missing_ok=True)


def _finish_journal(profile: str) -> None:
    _pending_path(profile).unlink()
    _fsync_directory(BACKUPS)


def recover_pending(*, profile: str, path: Path, limit: int, read_config,
                    write_config, sync_runtime, verify_runtime) -> bool:
    """Conservatively restore the old state after an interrupted migration."""
    pending = _pending_path(profile)
    try:
        raw = read_root_settings(pending, 140000)
    except FileNotFoundError:
        return False
    def unique(pairs):
        value = {}
        for key, item in pairs:
            if key in value:
                raise ValueError('duplicate journal field')
            value[key] = item
        return value
    value = json.loads(raw, object_pairs_hook=unique)
    if not isinstance(value, dict) or set(value) != {'profile', 'oldPort', 'newPort', 'config', 'metadata'} or value['profile'] != profile:
        raise ValueError('invalid port journal')
    old, new = value['oldPort'], value['newPort']
    if (type(old) is not int or type(new) is not int or not 1 <= old <= 65535 or
            not 1 <= new <= 65535 or old == new):
        raise ValueError('invalid port journal')
    original_config = base64.b64decode(value['config'], validate=True)
    original_metadata = base64.b64decode(value['metadata'], validate=True)
    if not 1 <= len(original_config) <= 65536 or not 1 <= len(original_metadata) <= limit:
        raise ValueError('invalid port journal')
    changed_config = replace_config_port(original_config, old, new)
    changed_metadata = _metadata_port(original_metadata, old, new, limit)
    current_metadata = read_root_settings(path, limit)
    current_config = read_config()
    if current_metadata not in (original_metadata, changed_metadata) or current_config not in (original_config, changed_config):
        raise ValueError('port migration recovery drift')
    if current_metadata == changed_metadata:
        replace_metadata_port(path, profile=profile, expected_revision=revision(changed_metadata),
                              old=new, new=old, limit=limit, verify=lambda: None)
    if current_config == changed_config:
        write_config(changed_config, original_config)
    sync_runtime()
    verify_runtime(old)
    status = _run(_UFW, 'status', output=True).decode('ascii')
    if re.search(rf'(?m)^\s*{new}/udp\s+ALLOW(?: IN)?\s+.*# AWG-CITA {profile}\b', status):
        remove_new_port(new)
    elif re.search(rf'(?m)^\s*{new}/udp\s+', status):
        raise ValueError('new firewall rule changed')
    _finish_journal(profile)
    return True


def replace_metadata_port(path: Path, *, profile: str, expected_revision: str,
                          old: int, new: int, limit: int, verify) -> str:
    validate_request({'expectedRevision': expected_revision, 'listenPort': new})
    if profile not in {'awg3', 'awg2', 'wg'}:
        raise ValueError('invalid profile')
    parent = os.lstat(path.parent)
    if not stat.S_ISDIR(parent.st_mode) or parent.st_uid != 0 or parent.st_mode & 0o022:
        raise ValueError('unsafe server settings directory')
    current = read_root_settings(path, limit)
    if revision(current) != expected_revision:
        raise ValueError('server settings changed')
    replacement = _metadata_port(current, old, new, limit)
    _secure_backup_directory()
    backup = BACKUPS / (profile + '-port-' + str(time.time_ns()) + '.json')
    _write_new(backup, current)
    _fsync_directory(BACKUPS)
    temp = path.with_name('.' + path.name + '.port-' + str(os.getpid()))
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
            restore = path.with_name('.' + path.name + '.port-rollback-' + str(os.getpid()))
            try:
                _write_new(restore, current)
                os.replace(restore, path)
                _fsync_directory(path.parent)
            finally:
                restore.unlink(missing_ok=True)
        raise
    finally:
        temp.unlink(missing_ok=True)


def apply_port(*, profile: str, path: Path, limit: int, config: bytes, write_config,
               read_config, settings_port: int, expected_revision: str, new_port: int,
               verify_settings, sync_runtime, verify_runtime) -> str:
    """Open the new firewall port, switch config and metadata, then restart and verify."""
    validate_request({'expectedRevision': expected_revision, 'listenPort': new_port})
    preflight_firewall(settings_port, new_port)
    changed_config = replace_config_port(config, settings_port, new_port)
    metadata = read_root_settings(path, limit)
    if revision(metadata) != expected_revision:
        raise ValueError('server settings changed')
    _start_journal(profile, settings_port, new_port, config, metadata)
    opened = False
    config_written = False
    metadata_revision = None
    try:
        allow_port(new_port, profile)
        opened = True
        write_config(config, changed_config)
        config_written = True
        metadata_revision = replace_metadata_port(path, profile=profile, expected_revision=expected_revision,
                                                  old=settings_port, new=new_port, limit=limit,
                                                  verify=verify_settings)
        sync_runtime()
        verify_runtime(new_port)
        _finish_journal(profile)
        return metadata_revision
    except BaseException as original:
        failures = []
        if metadata_revision is not None:
            try:
                replace_metadata_port(path, profile=profile, expected_revision=metadata_revision,
                                      old=new_port, new=settings_port, limit=limit, verify=verify_settings)
            except BaseException as error:
                failures.append(error)
        try:
            config_written = config_written or read_config() == changed_config
        except BaseException as error:
            failures.append(error)
        if config_written:
            try:
                if read_config() == changed_config:
                    write_config(changed_config, config)
                sync_runtime()
                verify_runtime(settings_port)
            except BaseException as error:
                failures.append(error)
        if opened and not failures:
            try:
                remove_new_port(new_port)
            except BaseException as error:
                failures.append(error)
        if not failures:
            try:
                _finish_journal(profile)
            except BaseException as error:
                failures.append(error)
        if failures:
            raise RuntimeError('listen port rollback failed') from original
        raise
