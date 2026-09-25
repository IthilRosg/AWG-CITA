"""Root-owned defaults for newly generated client files."""
from __future__ import annotations

import ipaddress
import json
import os
import stat
import sys
from pathlib import Path

ROOT = Path('/etc/awg-cita/client-templates')
PROFILES = frozenset({'awg3', 'awg2', 'wg'})
DEFAULT = {'allowed_ips': '0.0.0.0/0', 'mtu': 1420, 'keepalive': 25}
FIELDS = frozenset({'dns_server', *DEFAULT})


def validate(value: object) -> dict[str, object]:
    if not isinstance(value, dict) or set(value) != FIELDS:
        raise ValueError('invalid client template')
    dns, routes = value['dns_server'], value['allowed_ips']
    mtu, keepalive = value['mtu'], value['keepalive']
    if not isinstance(dns, str) or not isinstance(routes, str) or not 1 <= len(routes) <= 128:
        raise ValueError('invalid client template')
    try:
        ipaddress.ip_address(dns)
        networks = [ipaddress.ip_network(part.strip(), strict=True) for part in routes.split(',')]
    except ValueError as error:
        raise ValueError('invalid client template') from error
    if (not 1 <= len(networks) <= 8 or any(network.version != 4 for network in networks) or
        len(set(networks)) != len(networks) or
        type(mtu) is not int or not 1280 <= mtu <= 1500 or
        type(keepalive) is not int or not 0 <= keepalive <= 120):
        raise ValueError('invalid client template')
    return {'dns_server': str(ipaddress.ip_address(dns)),
            'allowed_ips': ', '.join(str(network) for network in networks),
            'mtu': mtu, 'keepalive': keepalive}


def read(name: str, fallback_dns: str | None = None) -> dict[str, object]:
    if name not in PROFILES:
        raise ValueError('invalid profile')
    path = ROOT / (name + '.json')
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    except FileNotFoundError:
        return validate({'dns_server': fallback_dns, **DEFAULT})
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o077:
            raise ValueError('unsafe client template')
        raw = os.read(fd, 513)
    finally:
        os.close(fd)
    if not 1 <= len(raw) <= 512:
        raise ValueError('invalid client template')
    def unique(pairs):
        result = {}
        for key, item in pairs:
            if key in result:
                raise ValueError('duplicate client template field')
            result[key] = item
        return result
    return validate(json.loads(raw, object_pairs_hook=unique))


def update(name: str, value: object) -> dict[str, object]:
    import fcntl
    settings = validate(value)
    if name not in PROFILES:
        raise ValueError('invalid profile')
    ROOT.mkdir(mode=0o700, parents=True, exist_ok=True)
    info = os.lstat(ROOT)
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o077:
        raise ValueError('unsafe client template directory')
    lock = ROOT / (name + '.lock')
    lock_fd = os.open(lock, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        fcntl.flock(lock_fd, fcntl.LOCK_EX)
        temp = ROOT / ('.' + name + '-' + str(os.getpid()))
        fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        try:
            with os.fdopen(fd, 'wb') as stream:
                stream.write((json.dumps(settings, separators=(',', ':')) + '\n').encode('ascii'))
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temp, ROOT / (name + '.json'))
            directory = os.open(ROOT, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
        finally:
            temp.unlink(missing_ok=True)
        return settings
    finally:
        os.close(lock_fd)


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if os.geteuid() != 0 or len(args) != 2 or args[0] not in PROFILES or args[1] not in {'show', 'update'}:
        print('invalid template operation', file=sys.stderr)
        return 64
    try:
        if args[1] == 'show':
            value = read(args[0])
        else:
            raw = sys.stdin.buffer.read(513)
            if not 1 <= len(raw) <= 512:
                raise ValueError('invalid template request')
            value = update(args[0], json.loads(raw))
        print(json.dumps({'schema_version': 1, 'profile': args[0], 'template': value}, separators=(',', ':')))
        return 0
    except Exception:
        print('template operation failed', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
