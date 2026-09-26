"""Validate and prepare network changes for isolated AWG-CITA profiles.

These functions have no side effects. The root helper must journal every server
and client file before using their output in a live migration.
"""
from __future__ import annotations

import base64
import hashlib
import ipaddress
import json
import os
import re
import select
import stat
import subprocess
import sys
import time
from pathlib import Path

from .real_awg import PersistentCanaryConfig
from .server_endpoint import BACKUPS, _fsync_directory, _write_new, read_root_settings, revision

_OBF_KEYS = ('S1', 'S2', 'S3', 'S4', 'H1', 'H2', 'H3', 'H4')
_ADDRESS = re.compile(rb'Address = ([0-9./]+)\n')
_ROUTE = re.compile(rb'AllowedIPs = ([0-9./]+)\n')
_REVISION = re.compile(r'[0-9a-f]{64}\Z')
_PROFILES = frozenset({'awg2', 'wg'})


def validate_address_change(old: str, new: str) -> tuple[ipaddress.IPv4Interface, ipaddress.IPv4Interface]:
    """Keep the host offset and prefix so every existing peer maps exactly once."""
    try:
        source = ipaddress.ip_interface(old)
        target = ipaddress.ip_interface(new)
    except (TypeError, ValueError) as error:
        raise ValueError('invalid interface address') from error
    if (not isinstance(source, ipaddress.IPv4Interface) or
            not isinstance(target, ipaddress.IPv4Interface) or
            not 24 <= source.network.prefixlen <= 29 or
            source.network.prefixlen != target.network.prefixlen or
            source.ip == target.ip or source.network == target.network or
            source.ip not in source.network.hosts() or target.ip not in target.network.hosts() or
            int(source.ip) - int(source.network.network_address) !=
            int(target.ip) - int(target.network.network_address)):
        raise ValueError('unsafe interface address change')
    return source, target


def _map_peer(raw: bytes, source: ipaddress.IPv4Interface,
              target: ipaddress.IPv4Interface) -> bytes:
    match = _ROUTE.fullmatch(raw)
    if match is None:
        raise ValueError('invalid peer route')
    route = ipaddress.ip_network(match[1].decode('ascii'), strict=True)
    if not isinstance(route, ipaddress.IPv4Network) or route.prefixlen != 32 or route.network_address not in source.network:
        raise ValueError('peer route outside source network')
    offset = int(route.network_address) - int(source.network.network_address)
    translated = ipaddress.IPv4Address(int(target.network.network_address) + offset)
    if translated == target.ip or translated not in target.network.hosts():
        raise ValueError('peer route collides with target interface')
    return f'AllowedIPs = {translated}/32\n'.encode('ascii')


def rewrite_server_address(raw: bytes, old: str, new: str) -> bytes:
    """Rewrite Address, six NAT/forward hooks and all enabled/disabled peer routes."""
    source, target = validate_address_change(old, new)
    parsed = PersistentCanaryConfig(raw)
    result = parsed.source
    expected = f'Address = {source}\n'.encode('ascii')
    if result.count(expected) != 1 or not result.startswith(b'[Interface]\n'):
        raise ValueError('server address drift')
    result = result.replace(expected, f'Address = {target}\n'.encode('ascii'), 1)
    old_network = str(source.network).encode('ascii')
    new_network = str(target.network).encode('ascii')
    lines = result.splitlines(keepends=True)
    hooks = 0
    for index, line in enumerate(lines):
        if line.startswith((b'PostUp = ', b'PostDown = ')):
            if line.count(old_network) != 1:
                raise ValueError('server firewall hook drift')
            lines[index] = line.replace(old_network, new_network, 1)
            hooks += 1
    if hooks != 6:
        raise ValueError('server firewall hook drift')
    result = b''.join(lines)
    for _key, (status, representation, block) in parsed._entries.items():
        old_route = next((line for line in block.splitlines(keepends=True) if line.startswith(b'AllowedIPs = ')), None)
        if old_route is None or block.count(old_route) != 1:
            raise ValueError('peer route drift')
        new_block = block.replace(old_route, _map_peer(old_route, source, target), 1)
        replacement = new_block if status == 'enabled' else b'# AWG-CITA-DISABLED ' + base64.b64encode(new_block) + b'\n'
        if result.count(representation) != 1:
            raise ValueError('peer representation drift')
        result = result.replace(representation, replacement, 1)
    PersistentCanaryConfig(result)
    return result


def rewrite_client_address(text: str, old: str, new: str) -> str:
    source, target = validate_address_change(old, new)
    raw = text.encode('ascii')
    matches = _ADDRESS.findall(raw)
    if len(matches) != 1:
        raise ValueError('client address drift')
    address = ipaddress.ip_interface(matches[0].decode('ascii'))
    if not isinstance(address, ipaddress.IPv4Interface) or address.network.prefixlen != 32 or address.ip not in source.network:
        raise ValueError('client address outside source network')
    offset = int(address.ip) - int(source.network.network_address)
    mapped = ipaddress.IPv4Address(int(target.network.network_address) + offset)
    replacement = raw.replace(b'Address = ' + matches[0] + b'\n', f'Address = {mapped}/32\n'.encode('ascii'), 1)
    if len(replacement) > 2400:
        raise ValueError('client configuration too long')
    return replacement.decode('ascii')


def validate_obfuscation(value: object) -> dict[str, str]:
    if (not isinstance(value, dict) or set(value) != set(_OBF_KEYS) or
            any(not isinstance(item, str) or not item.isascii() or not item.isdecimal() or
                    len(item) > 10 or not 0 <= int(item) <= 4294967295 for item in value.values())):
        raise ValueError('invalid AWG2 obfuscation')
    headers = [int(value[key]) for key in ('H1', 'H2', 'H3', 'H4')]
    if len(set(headers)) != 4 or any(header < 5 for header in headers):
        raise ValueError('invalid AWG2 headers')
    return value


def rewrite_obfuscation(raw: bytes, old: dict[str, str], new: dict[str, str]) -> bytes:
    validate_obfuscation(old)
    validate_obfuscation(new)
    if old == new:
        raise ValueError('unchanged obfuscation')
    result = raw
    for key in _OBF_KEYS:
        before = f'{key} = {old[key]}\n'.encode('ascii')
        after = f'{key} = {new[key]}\n'.encode('ascii')
        if result.count(before) != 1:
            raise ValueError('obfuscation drift')
        result = result.replace(before, after, 1)
    if len(result) > 65536:
        raise ValueError('obfuscation config too long')
    return result


def validate_request(value: object, profile: str) -> tuple[str, str, object]:
    if profile not in _PROFILES or not isinstance(value, dict) or 'expectedRevision' not in value or (
            not isinstance(value['expectedRevision'], str) or not _REVISION.fullmatch(value['expectedRevision'])):
        raise ValueError('invalid network request')
    if set(value) == {'expectedRevision', 'address'} and isinstance(value['address'], str):
        try:
            target = ipaddress.ip_interface(value['address'])
        except ValueError as error:
            raise ValueError('invalid target address') from error
        if not isinstance(target, ipaddress.IPv4Interface) or not 24 <= target.network.prefixlen <= 29:
            raise ValueError('invalid target address')
        return value['expectedRevision'], 'address', str(target)
    if set(value) == {'expectedRevision', 'obfuscation'} and profile == 'awg2':
        return value['expectedRevision'], 'obfuscation', validate_obfuscation(value['obfuscation'])
    raise ValueError('invalid network request')


def read_request(profile: str) -> tuple[str, str, object]:
    body = bytearray()
    deadline = time.monotonic() + 5
    while True:
        if not select.select([sys.stdin.fileno()], [], [], max(0, deadline - time.monotonic()))[0]:
            raise ValueError('incomplete network request')
        chunk = os.read(sys.stdin.fileno(), 1025 - len(body))
        if not chunk:
            break
        body.extend(chunk)
        if len(body) > 1024:
            raise ValueError('network request too long')
    def unique(pairs):
        result = {}
        for key, item in pairs:
            if key in result:
                raise ValueError('duplicate network field')
            result[key] = item
        return result
    return validate_request(json.loads(body.decode('ascii'), object_pairs_hook=unique), profile)


def _metadata_change(raw: bytes, kind: str, target: object, limit: int) -> bytes:
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise ValueError('invalid profile metadata')
    key = 'interface_address' if kind == 'address' else 'obfuscation'
    if key not in value:
        raise ValueError('invalid profile metadata')
    value[key] = target
    output = (json.dumps(value, separators=(',', ':'), ensure_ascii=True) + '\n').encode('ascii')
    if len(output) > limit:
        raise ValueError('profile metadata too long')
    return output


def _pending_path(profile: str) -> Path:
    if profile not in _PROFILES:
        raise ValueError('invalid network profile')
    return BACKUPS / (profile + '-network.pending')


def _secure_backup_directory() -> None:
    BACKUPS.mkdir(mode=0o700, exist_ok=True)
    info = os.lstat(BACKUPS)
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o077:
        raise ValueError('unsafe network journal directory')


def _write_journal(profile: str, kind: str, files: dict[str, tuple[bytes, bytes]]) -> None:
    _secure_backup_directory()
    pending = _pending_path(profile)
    if pending.exists() or pending.is_symlink():
        raise ValueError('pending network migration')
    value = {'profile': profile, 'kind': kind,
             'files': {name: [base64.b64encode(before).decode('ascii'),
                              base64.b64encode(after).decode('ascii')]
                       for name, (before, after) in files.items()}}
    raw = (json.dumps(value, separators=(',', ':')) + '\n').encode('ascii')
    if len(raw) > 512000:
        raise ValueError('network journal too long')
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


def _atomic_root_replace(path: Path, before: bytes, after: bytes, limit: int) -> None:
    if read_root_settings(path, limit) != before:
        raise ValueError('network metadata drift')
    parent = os.lstat(path.parent)
    if not stat.S_ISDIR(parent.st_mode) or parent.st_uid != 0 or parent.st_mode & 0o022:
        raise ValueError('unsafe profile settings directory')
    temp = path.with_name('.' + path.name + '.network-' + str(os.getpid()))
    try:
        _write_new(temp, after)
        if read_root_settings(path, limit) != before:
            raise ValueError('network metadata drift')
        os.replace(temp, path)
        _fsync_directory(path.parent)
    finally:
        temp.unlink(missing_ok=True)


def preflight_route(target: str, current: str, interface: str) -> None:
    """Reject a target subnet already routed through any other interface."""
    source, destination = validate_address_change(current, target)
    result = subprocess.run(('/usr/sbin/ip', '-j', '-4', 'route', 'show', 'table', 'all'),
                            capture_output=True, timeout=10, env={'PATH': '/usr/sbin:/usr/bin:/sbin:/bin', 'LANG': 'C'})
    if result.returncode or len(result.stdout) > 131072:
        raise ValueError('route preflight failed')
    routes = json.loads(result.stdout)
    if not isinstance(routes, list):
        raise ValueError('route preflight failed')
    for route in routes:
        if not isinstance(route, dict) or route.get('dev') == interface or route.get('dst') == 'default':
            continue
        destination_text = route.get('dst')
        if isinstance(destination_text, str):
            try:
                occupied = ipaddress.ip_network(destination_text, strict=False)
            except ValueError as error:
                raise ValueError('route preflight failed') from error
            if isinstance(occupied, ipaddress.IPv4Network) and occupied.overlaps(destination.network):
                raise ValueError('target subnet overlaps an existing route')
    if source.network.overlaps(destination.network):
        raise ValueError('target subnet overlaps source')


def _parse_journal(profile: str) -> dict[str, tuple[bytes, bytes]] | None:
    try:
        raw = read_root_settings(_pending_path(profile), 512000)
    except FileNotFoundError:
        return None
    value = json.loads(raw)
    if (not isinstance(value, dict) or set(value) != {'profile', 'kind', 'files'} or
            value['profile'] != profile or value['kind'] not in {'address', 'obfuscation'} or
            not isinstance(value['files'], dict) or not 2 <= len(value['files']) <= 66 or
            not {'config', 'metadata'} <= set(value['files'])):
        raise ValueError('invalid network journal')
    files = {}
    for name, pair in value['files'].items():
        if (name not in {'config', 'metadata'} and not re.fullmatch(r'peer-[0-9a-f]{16}', name)) or (
                not isinstance(pair, list) or len(pair) != 2 or any(not isinstance(item, str) for item in pair)):
            raise ValueError('invalid network journal')
        before, after = (base64.b64decode(item, validate=True) for item in pair)
        limit = 65536 if name == 'config' else 2048 if name == 'metadata' else 2400
        if not 1 <= len(before) <= limit or not 1 <= len(after) <= limit or before == after:
            raise ValueError('invalid network journal')
        files[name] = (before, after)
    return files


def _read_file(ops, name: str) -> bytes:
    if name == 'config':
        return ops.read_config()
    if name == 'metadata':
        return read_root_settings(ops.profile, 2048)
    return read_root_settings(ops.config_path(name), 2400)


def _replace_file(ops, name: str, before: bytes, after: bytes) -> None:
    if name == 'config':
        ops.write_config(before, after)
    elif name == 'metadata':
        _atomic_root_replace(ops.profile, before, after, 2048)
    else:
        from .client_config_edit import atomic_replace
        atomic_replace(ops.config_path(name), before.decode('ascii'), after.decode('ascii'))


def recover_pending(ops) -> bool:
    files = _parse_journal(ops.name)
    if files is None:
        return False
    for name, (before, after) in files.items():
        if _read_file(ops, name) not in (before, after):
            raise ValueError('network migration recovery drift')
    ops.stop_runtime()
    for name in [*sorted(files.keys() - {'config', 'metadata'}), 'metadata', 'config']:
        before, after = files[name]
        if _read_file(ops, name) == after:
            _replace_file(ops, name, after, before)
    ops.start_runtime()
    ops.verify_runtime()
    _finish_journal(ops.name)
    return True


def apply_change(ops, expected_revision: str, kind: str, target: object) -> str:
    if ops.name not in _PROFILES or kind not in {'address', 'obfuscation'}:
        raise ValueError('invalid network change')
    metadata = read_root_settings(ops.profile, 2048)
    if revision(metadata) != expected_revision:
        raise ValueError('profile settings changed')
    endpoint, dns, address, port, obfuscation = ops.settings()
    if kind == 'address':
        validate_address_change(address, target)
        preflight_route(target, address, ops.interface)
    elif ops.name != 'awg2':
        raise ValueError('WireGuard has no obfuscation')
    else:
        validate_obfuscation(target)
    config = ops.read_config()
    new_config = (rewrite_server_address(config, address, target) if kind == 'address' else
                  rewrite_obfuscation(config, obfuscation, target))
    new_metadata = _metadata_change(metadata, kind, target, 2048)
    files = {'config': (config, new_config), 'metadata': (metadata, new_metadata)}
    peer_routes = {}
    for key, (_status, _representation, block) in PersistentCanaryConfig(config)._entries.items():
        name = 'peer-' + hashlib.sha256(base64.b64decode(key)).hexdigest()[:16]
        route = next((line[len(b'AllowedIPs = '):-1].decode('ascii') for line in block.splitlines(keepends=True)
                      if line.startswith(b'AllowedIPs = ')), None)
        if route is None or name in peer_routes:
            raise ValueError('invalid peer route inventory')
        peer_routes[name] = route
    controller = ops.controller()
    for record in controller.list_clients():
        name = record['id']
        # The old client artifact and key must be present and internally valid.
        ops.load_config(name, controller)
        stored = _read_file(ops, name)
        if kind == 'address':
            client_addresses = _ADDRESS.findall(stored)
            if len(client_addresses) != 1 or client_addresses[0].decode('ascii') != peer_routes[name]:
                raise ValueError('client address differs from server route')
            new_text = rewrite_client_address(stored.decode('ascii'), address, target)
        else:
            new_text = rewrite_obfuscation(stored, obfuscation, target).decode('ascii')
            if len(new_text.encode('ascii')) > 2400:
                raise ValueError('client configuration too long')
        files[name] = (stored, new_text.encode('ascii'))
    _write_journal(ops.name, kind, files)
    try:
        ops.stop_runtime()
        for name in ['config', 'metadata', *sorted(files.keys() - {'config', 'metadata'})]:
            before, after = files[name]
            _replace_file(ops, name, before, after)
        ops.start_runtime()
        ops.verify_runtime()
        for record in ops.controller().list_clients():
            ops.load_config(record['id'], ops.controller())
        _finish_journal(ops.name)
        return revision(new_metadata)
    except BaseException as error:
        try:
            recover_pending(ops)
        except BaseException:
            raise RuntimeError('network migration rollback failed') from error
        raise
