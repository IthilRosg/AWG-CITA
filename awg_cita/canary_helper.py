"""Fixed root-only operations for the awg-canary0 persistent peer file."""
from __future__ import annotations

import fcntl
import base64
import hashlib
import ipaddress
import json
import os
import re
import stat
import subprocess
import sys
import time
from contextlib import contextmanager
from pathlib import Path

from .real_awg import CanaryPeerController, PersistentCanaryConfig, _ALLOWED, _valid_key, valid_endpoint_host

CONFIG = Path('/etc/amnezia/amneziawg/awg-canary0.conf')
LOCK = Path('/run/lock/awg-cita-canary.lock')
BACKUPS = Path('/var/backups/awg-cita-canary')
READ = '/usr/local/sbin/awg-manager-read'
AWG = '/usr/local/bin/awg'
RESTART = ('/usr/bin/systemctl', 'restart', 'awg-canary0.service')
_ID = re.compile(r'peer-[0-9a-f]{16}\Z')
_ENV = {'PATH': '/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin', 'LANG': 'C', 'LC_ALL': 'C'}
PROTECTED_PROFILE_FILE = Path('/etc/awg-cita/protected-peer.json')
CLIENT_CONFIGS = Path('/var/lib/awg-cita/client-configs')


def _root_regular(fd: int) -> os.stat_result:
    info = os.fstat(fd)
    if not stat.S_ISREG(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o077:
        raise ValueError('unsafe canary file')
    return info


@contextmanager
def _locked():
    fd = os.open(LOCK, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        _root_regular(fd)
        deadline = time.monotonic() + 5
        while True:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError('canary operation busy') from None
                time.sleep(min(0.05, remaining))
        yield
    finally:
        os.close(fd)


def _read_config() -> bytes:
    fd = os.open(CONFIG, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        _root_regular(fd)
        data = os.read(fd, 65537)
    finally:
        os.close(fd)
    PersistentCanaryConfig(data)
    return data


def _write_all(fd: int, data: bytes) -> None:
    with os.fdopen(fd, 'wb', closefd=True) as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())


def _write_config(expected: bytes, replacement: bytes) -> None:
    current = _read_config()
    if current != expected:
        raise ValueError('config drift')
    PersistentCanaryConfig(replacement)
    info = os.stat(CONFIG, follow_symlinks=False)
    if not stat.S_ISREG(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o077:
        raise ValueError('unsafe canary file')
    BACKUPS.mkdir(mode=0o700, exist_ok=True)
    if BACKUPS.stat().st_uid != 0 or BACKUPS.stat().st_mode & 0o077:
        raise ValueError('unsafe backup directory')
    backup = BACKUPS / ('awg-canary0-' + str(time.time_ns()) + '.conf')
    _write_all(os.open(backup, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600), current)
    temp = CONFIG.with_name('.awg-canary0.conf.awg-cita-' + str(os.getpid()))
    fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    try:
        os.fchown(fd, info.st_uid, info.st_gid)
        os.fchmod(fd, stat.S_IMODE(info.st_mode))
        _write_all(fd, replacement)
        if _read_config() != expected:
            raise ValueError('config drift')
        os.replace(temp, CONFIG)
        directory = os.open(CONFIG.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        if temp.exists():
            temp.unlink()


def _read_dump() -> str:
    result = subprocess.run((READ,), capture_output=True, timeout=5, env=_ENV)
    if result.returncode or result.stderr or len(result.stdout) > 65536:
        raise ValueError('canary read failed')
    return result.stdout.decode('utf-8')


def _sync_runtime() -> None:
    result = subprocess.run(RESTART, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=30, env=_ENV)
    if result.returncode:
        state = subprocess.run(('/usr/bin/systemctl', 'show', '--value', '--property=Result', 'awg-canary0.service'),
                               capture_output=True, timeout=5, env=_ENV)
        if state.returncode or state.stdout.strip() != b'start-limit-hit':
            raise ValueError('canary restart failed')
        reset = subprocess.run(('/usr/bin/systemctl', 'reset-failed', 'awg-canary0.service'),
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=5, env=_ENV)
        started = subprocess.run(('/usr/bin/systemctl', 'start', 'awg-canary0.service'),
                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=30, env=_ENV) if not reset.returncode else reset
        if started.returncode:
            raise ValueError('canary restart failed')


def _protected_peer_profile() -> tuple[str, bytes, str, str, dict[str, str], str, int]:
    parent = os.lstat(PROTECTED_PROFILE_FILE.parent)
    if not stat.S_ISDIR(parent.st_mode) or parent.st_uid != 0 or parent.st_mode & 0o022:
        raise ValueError('unsafe protected profile directory')
    fd = os.open(PROTECTED_PROFILE_FILE, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        _root_regular(fd)
        raw = os.read(fd, 513)
    finally:
        os.close(fd)
    if len(raw) > 512:
        raise ValueError('invalid protected peer profile')
    def unique(pairs):
        result = {}
        for name, item in pairs:
            if name in result:
                raise ValueError('duplicate protected profile field')
            result[name] = item
        return result
    value = json.loads(raw, object_pairs_hook=unique)
    if not isinstance(value, dict) or set(value) != {'public_key', 'route', 'endpoint_host', 'dns_server', 'obfuscation', 'interface_address', 'listen_port'}:
        raise ValueError('invalid protected peer profile')
    key = _valid_key(value['public_key'].encode('ascii'))
    route = ipaddress.ip_network(value['route'], strict=True)
    if route.version != 4 or route.prefixlen != 32:
        raise ValueError('invalid protected peer route')
    if not valid_endpoint_host(value['endpoint_host']) or not isinstance(value['dns_server'], str):
        raise ValueError('invalid protected peer profile')
    ipaddress.ip_address(value['dns_server'])
    expected = value['obfuscation']
    if not isinstance(expected, dict) or set(expected) != {'S1', 'S2', 'S3', 'S4', 'H1', 'H2', 'H3', 'H4'} or not all(isinstance(item, str) for item in expected.values()):
        raise ValueError('invalid protected peer profile')
    interface = ipaddress.ip_interface(value['interface_address'])
    port = value['listen_port']
    if interface.version != 4 or type(port) is not int or not 1 <= port <= 65535:
        raise ValueError('invalid protected peer profile')
    return key, str(route).encode('ascii'), value['endpoint_host'], value['dns_server'], expected, str(interface), port


def _read_protected_config() -> bytes:
    data = _read_config()
    persisted = PersistentCanaryConfig(data)
    original_key, original_route, _endpoint, _dns, _obfuscation, _address, _port = _protected_peer_profile()
    protected = set()
    for key, (_status, _representation, block) in persisted._entries.items():
        routes = [_ALLOWED.fullmatch(line).group(1) for line in block.splitlines(keepends=True) if _ALLOWED.fullmatch(line)]
        if routes == [original_route]:
            protected.add(key)
    if protected != {original_key} or persisted.peers().get(original_key) != 'enabled':
        raise ValueError('protected original peer drift')
    return data

def _controller() -> CanaryPeerController:
    from .client_templates import read as read_template
    persisted = PersistentCanaryConfig(_read_protected_config())
    protected_key, _route, endpoint, dns, obfuscation, address, port = _protected_peer_profile()
    template = read_template('awg3', dns)
    protected = {protected_key}
    return CanaryPeerController(_read_protected_config, _read_dump, write_config=_write_config,
                                sync_runtime=_sync_runtime, mutable_keys=set(persisted.peers()) - protected,
                                endpoint_host=endpoint, dns_server=template['dns_server'], expected_obfuscation=obfuscation,
                                expected_interface_address=address, expected_listen_port=port,
                                client_allowed_ips=template['allowed_ips'], client_mtu=template['mtu'],
                                client_keepalive=template['keepalive'])


def _awg_key(argv: tuple[str, ...], input_key: str | None = None) -> str:
    """Run one fixed AWG key command, never exposing its output to errors."""
    if argv not in ((AWG, 'genkey'), (AWG, 'pubkey'), (AWG, 'show', 'awg-canary0', 'public-key'),
                    (AWG, 'show', 'awg-canary0', 'header-protection-key')):
        raise ValueError('invalid key operation')
    process = subprocess.Popen(argv, stdin=subprocess.PIPE if input_key is not None else subprocess.DEVNULL,
                               stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, env=_ENV)
    try:
        if input_key is not None:
            from .real_awg import _valid_key
            _valid_key(input_key.encode('ascii'))
            process.stdin.write((input_key + '\n').encode('ascii'))
            process.stdin.close()
        import select
        ready, _, _ = select.select([process.stdout], [], [], 5)
        if not ready:
            raise ValueError('AWG key command timeout')
        output = os.read(process.stdout.fileno(), 65)
        if len(output) > 64 or process.wait(timeout=5) != 0:
            raise ValueError('AWG key command failed')
        from .real_awg import _valid_key
        return _valid_key(output.strip())
    except Exception:
        raise ValueError('AWG key command failed') from None
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=5)
        process.stdout.close()


def _keypair() -> tuple[str, str]:
    private = _awg_key((AWG, 'genkey'))
    return private, _awg_key((AWG, 'pubkey'), private)


def _server_public() -> str:
    return _awg_key((AWG, 'show', 'awg-canary0', 'public-key'))


def _runtime_header_protection() -> str:
    return _awg_key((AWG, 'show', 'awg-canary0', 'header-protection-key'))


def _config_directory() -> None:
    parent = CLIENT_CONFIGS.parent
    if not parent.exists():
        parent.mkdir(mode=0o700)
    info = os.lstat(parent)
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o077:
        raise ValueError('unsafe client config parent')
    CLIENT_CONFIGS.mkdir(mode=0o700, exist_ok=True)
    info = os.lstat(CLIENT_CONFIGS)
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o077:
        raise ValueError('unsafe client config directory')


def _config_path(client_id: str) -> Path:
    if not _ID.fullmatch(client_id):
        raise ValueError('invalid client id')
    _config_directory()
    return CLIENT_CONFIGS / (client_id + '.conf')


def _store_client_config(client_id: str, config_text: str) -> None:
    if not isinstance(config_text, str) or not 1 <= len(config_text) <= 2400:
        raise ValueError('invalid client configuration')
    path = _config_path(client_id)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    try:
        _write_all(fd, config_text.encode('ascii'))
    except Exception:
        path.unlink(missing_ok=True)
        raise
    directory = os.open(CLIENT_CONFIGS, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(directory)
    finally:
        os.close(directory)


def _load_client_config(client_id: str, controller: CanaryPeerController) -> dict[str, object]:
    from .client_config_edit import revision
    client = next((record for record in controller.list_clients() if record['id'] == client_id), None)
    if client is None or not any('peer-' + hashlib.sha256(base64.b64decode(key)).hexdigest()[:16] == client_id
                                 for key in controller._mutable_keys):
        raise ValueError('peer not authorized')
    fd = os.open(_config_path(client_id), os.O_RDONLY | os.O_NOFOLLOW)
    try:
        _root_regular(fd)
        raw = os.read(fd, 2401)
    finally:
        os.close(fd)
    if not 1 <= len(raw) <= 2400:
        raise ValueError('invalid stored client configuration')
    config_text = raw.decode('ascii')
    fields = dict(line.split(' = ', 1) for line in config_text.splitlines() if ' = ' in line)
    server_interface = _read_protected_config().split(b'\n[Peer]\n', 1)[0].decode('ascii')
    server_fields = dict(line.split(' = ', 1) for line in server_interface.splitlines() if ' = ' in line)
    for name in ('S1', 'S2', 'S3', 'S4', 'H1', 'H2', 'H3', 'H4', 'HeaderProtectionKey'):
        if fields.get(name) != server_fields.get(name):
            raise ValueError('stored client obfuscation mismatch')
    if server_fields.get('HeaderProtectionKey') and _runtime_header_protection() != server_fields['HeaderProtectionKey']:
        raise ValueError('canary header protection differs from runtime')
    private = _valid_key(fields['PrivateKey'].encode('ascii'))
    public = _awg_key((AWG, 'pubkey'), private)
    if ('peer-' + hashlib.sha256(base64.b64decode(public)).hexdigest()[:16] != client_id or
            fields.get('PublicKey') != _server_public()):
        raise ValueError('stored client configuration mismatch')
    from .server_endpoint import project_client_endpoint
    _key, _route, endpoint, _dns, _obf, _address, port = _protected_peer_profile()
    config_text = project_client_endpoint(config_text, endpoint, port)
    import segno
    qr_uri = segno.make_qr(config_text).png_data_uri(scale=4)
    return {'schema_version': 1, 'client': client, 'configText': config_text,
            'qrDataUri': qr_uri, 'revision': revision(config_text)}


def _update_client_config(client_id: str, controller: CanaryPeerController,
                          expected_revision: str, settings: dict[str, object]) -> dict[str, object]:
    from .client_config_edit import atomic_replace, replace_editable
    current = _load_client_config(client_id, controller)
    if current['revision'] != expected_revision:
        raise ValueError('saved configuration changed')
    replacement = replace_editable(current['configText'], settings)
    if replacement != current['configText']:
        raw = _read_root_client_config(_config_path(client_id))
        atomic_replace(_config_path(client_id), raw, replacement)
    return _load_client_config(client_id, controller)


def _read_root_client_config(path: Path) -> str:
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        _root_regular(fd)
        raw = os.read(fd, 2401)
    finally:
        os.close(fd)
    if not 1 <= len(raw) <= 2400:
        raise ValueError('invalid stored client configuration')
    return raw.decode('ascii')


def _recover_port_migration() -> None:
    from .server_port import recover_pending
    def verify_runtime(port):
        runtime = _read_dump().splitlines()[0].split('\t')
        if len(runtime) < 3 or runtime[2] != str(port):
            raise ValueError('canary runtime port drift')
        _controller().list_clients()
    recover_pending(profile='awg3', path=PROTECTED_PROFILE_FILE, limit=512,
                    read_config=_read_config, write_config=_write_config,
                    sync_runtime=_sync_runtime, verify_runtime=verify_runtime)


def _read_create_request() -> dict[str, object]:
    import select
    fd = sys.stdin.fileno()
    body = bytearray()
    deadline = time.monotonic() + 5
    while True:
        if not select.select([fd], [], [], max(0, deadline - time.monotonic()))[0]:
            raise ValueError('incomplete create request')
        chunk = os.read(fd, 1025 - len(body))
        if not chunk:
            break
        body.extend(chunk)
        if len(body) > 1024:
            raise ValueError('invalid create request')
    if not body:
        raise ValueError('invalid create request')
    def unique(pairs):
        value = {}
        for key, item in pairs:
            if key in value:
                raise ValueError('duplicate request field')
            value[key] = item
        return value
    request = json.loads(body.decode('ascii'), object_pairs_hook=unique)
    if not isinstance(request, dict) or set(request) != {'name', 'tags', 'idempotencyKey'}:
        raise ValueError('invalid create request')
    return request

def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if os.geteuid() != 0 or not ((len(args) == 1 and args[0] in {'list', 'server', 'endpoint-update', 'port-update'}) or
                                  (len(args) == 2 and args[0] in {'disable', 'enable', 'delete', 'config', 'config-update'} and _ID.fullmatch(args[1])) or
                                  (len(args) == 1 and args[0] == 'create')):
        print('invalid canary operation', file=sys.stderr)
        return 64
    try:
        request = _read_create_request() if args[0] == 'create' else None
        update_request = None
        if args[0] == 'config-update':
            from .client_config_edit import read_update_request
            update_request = read_update_request()
        endpoint_request = None
        if args[0] == 'endpoint-update':
            from .server_endpoint import read_request
            endpoint_request = read_request()
        port_request = None
        if args[0] == 'port-update':
            from .server_port import read_request
            port_request = read_request()
        with _locked():
            _recover_port_migration()
            controller = _controller()
            if args[0] == 'list':
                result = {'schema_version': 1, 'clients': controller.list_clients()}
            elif args[0] == 'server':
                from .server_endpoint import read_root_settings, revision
                _key, _route, endpoint, _dns, _obf, address, port = _protected_peer_profile()
                runtime = _read_dump().splitlines()[0].split('\t')
                if len(runtime) < 3 or runtime[2] != str(port):
                    raise ValueError('canary runtime drift')
                result = {'schema_version': 1, 'profile': 'awg3', 'interface': 'awg-canary0',
                          'endpoint': endpoint, 'address': address, 'listenPort': port,
                          'state': 'ACTIVE', 'clientCount': len(controller.list_clients()),
                          'revision': revision(read_root_settings(PROTECTED_PROFILE_FILE, 512))}
            elif args[0] == 'endpoint-update':
                from .server_endpoint import project_client_endpoint, replace_endpoint
                expected, endpoint = endpoint_request
                _key, _route, current_endpoint, _dns, _obf, _address, current_port = _protected_peer_profile()
                records = controller.list_clients()
                for record in records:
                    path = _config_path(record['id'])
                    if path.exists() or path.is_symlink():
                        project_client_endpoint(_read_root_client_config(path), current_endpoint, current_port)
                replace_endpoint(PROTECTED_PROFILE_FILE, profile='awg3', expected_revision=expected,
                                 endpoint=endpoint, limit=512,
                                 verify=lambda: (_protected_peer_profile(), _controller().list_clients()))
                _key, _route, endpoint, _dns, _obf, address, port = _protected_peer_profile()
                from .server_endpoint import read_root_settings, revision
                result = {'schema_version': 1, 'profile': 'awg3', 'interface': 'awg-canary0',
                          'endpoint': endpoint, 'address': address, 'listenPort': port,
                          'state': 'ACTIVE', 'clientCount': len(_controller().list_clients()),
                          'revision': revision(read_root_settings(PROTECTED_PROFILE_FILE, 512))}
            elif args[0] == 'port-update':
                from .server_endpoint import project_client_endpoint, read_root_settings, revision
                from .server_port import apply_port
                expected, new_port = port_request
                _key, _route, old_endpoint, _dns, _obf, _address, old_port = _protected_peer_profile()
                for record in controller.list_clients():
                    path = _config_path(record['id'])
                    if path.exists() or path.is_symlink():
                        project_client_endpoint(_read_root_client_config(path), old_endpoint, old_port)
                def verify_runtime(port):
                    runtime = _read_dump().splitlines()[0].split('\t')
                    if len(runtime) < 3 or runtime[2] != str(port):
                        raise ValueError('canary runtime port drift')
                    _controller().list_clients()
                apply_port(profile='awg3', path=PROTECTED_PROFILE_FILE, limit=512,
                           config=_read_protected_config(), write_config=_write_config,
                           read_config=_read_config, settings_port=old_port,
                           expected_revision=expected, new_port=new_port,
                           verify_settings=_protected_peer_profile, sync_runtime=_sync_runtime,
                           verify_runtime=verify_runtime)
                _key, _route, endpoint, _dns, _obf, address, port = _protected_peer_profile()
                result = {'schema_version': 1, 'profile': 'awg3', 'interface': 'awg-canary0',
                          'endpoint': endpoint, 'address': address, 'listenPort': port,
                          'state': 'ACTIVE', 'clientCount': len(_controller().list_clients()),
                          'revision': revision(read_root_settings(PROTECTED_PROFILE_FILE, 512))}
            elif args[0] == 'create':
                result = controller.create(request['name'], request['tags'], request['idempotencyKey'],
                                           _keypair, _server_public, _store_client_config,
                                           _runtime_header_protection)
            elif args[0] == 'config':
                result = _load_client_config(args[1], controller)
            elif args[0] == 'config-update':
                result = _update_client_config(args[1], controller, *update_request)
            else:
                value = controller.mutate(args[0], args[1])
                if args[0] == 'delete':
                    path = _config_path(args[1])
                    if path.exists():
                        path.unlink()
                result = {'schema_version': 1, **({'id': args[1], 'deleted': True} if args[0] == 'delete' else {'client': value})}
        print(json.dumps(result, separators=(',', ':')))
        return 0
    except Exception:
        # Never emit a traceback: exceptions may have traversed key material.
        print('canary operation failed', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
