"""Fixed root-only operations for the two additional AWG-CITA interfaces."""
from __future__ import annotations

import base64
import fcntl
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

from .canary_helper import _read_create_request, _root_regular, _write_all
from .real_awg import CanaryPeerController, PersistentCanaryConfig, _valid_key, valid_endpoint_host

AWG = '/usr/local/bin/awg'
ROOT = Path('/etc/amnezia/amneziawg')
PROFILE_ROOT = Path('/etc/awg-cita/profiles')
STATE_ROOT = Path('/var/lib/awg-cita/client-configs')
BACKUP_ROOT = Path('/var/backups/awg-cita-profiles')
_ENV = {'PATH': '/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin', 'LANG': 'C', 'LC_ALL': 'C'}
_ID = re.compile(r'peer-[0-9a-f]{16}\Z')
_INTERFACES = {'awg2': 'awg-cita2', 'wg': 'awg-cita-wg'}
_OBF = frozenset({'S1', 'S2', 'S3', 'S4', 'H1', 'H2', 'H3', 'H4'})


def _read_root_file(path: Path, limit: int) -> bytes:
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        _root_regular(fd)
        raw = os.read(fd, limit + 1)
    finally:
        os.close(fd)
    if not 1 <= len(raw) <= limit:
        raise ValueError('invalid profile file')
    return raw


class ProfileOps:
    def __init__(self, name: str) -> None:
        if name not in _INTERFACES:
            raise ValueError('invalid profile')
        self.name = name
        self.interface = _INTERFACES[name]
        self.config = ROOT / (self.interface + '.conf')
        self.profile = PROFILE_ROOT / (name + '.json')
        self.storage = STATE_ROOT / name
        self.backups = BACKUP_ROOT / name
        self.lock = Path('/run/lock') / ('awg-cita-' + name + '.lock')
        self.service = 'awg-cita-' + name + '.service'

    @contextmanager
    def locked(self):
        fd = os.open(self.lock, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        try:
            _root_regular(fd)
            deadline = time.monotonic() + 5
            while True:
                try:
                    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except BlockingIOError:
                    if time.monotonic() >= deadline:
                        raise TimeoutError('profile operation busy') from None
                    time.sleep(0.05)
            yield
        finally:
            os.close(fd)

    def settings(self) -> tuple[str, str, int, dict[str, str]]:
        raw = _read_root_file(self.profile, 2048)
        def unique(pairs):
            result = {}
            for key, value in pairs:
                if key in result:
                    raise ValueError('duplicate profile setting')
                result[key] = value
            return result
        value = json.loads(raw, object_pairs_hook=unique)
        if not isinstance(value, dict) or set(value) != {'endpoint_host', 'dns_server', 'interface_address', 'listen_port', 'obfuscation'}:
            raise ValueError('invalid profile settings')
        endpoint, dns, address, port, obf = (value[key] for key in
                                              ('endpoint_host', 'dns_server', 'interface_address', 'listen_port', 'obfuscation'))
        if not valid_endpoint_host(endpoint) or not isinstance(obf, dict):
            raise ValueError('invalid profile settings')
        try:
            ipaddress.ip_address(dns)
        except (ValueError, TypeError) as error:
            raise ValueError('invalid profile DNS') from error
        try:
            parsed_address = ipaddress.ip_interface(address)
        except (ValueError, TypeError) as error:
            raise ValueError('invalid profile address') from error
        if (parsed_address.version != 4 or not 24 <= parsed_address.network.prefixlen <= 29 or
            type(port) is not int or not 1 <= port <= 65535):
            raise ValueError('invalid profile address or port')
        if set(obf) != (_OBF if self.name == 'awg2' else set()) or not all(
                isinstance(item, str) and item.isascii() and item.isdecimal() and
                0 <= int(item) <= 4294967295 for item in obf.values()):
            raise ValueError('invalid profile obfuscation')
        return endpoint, str(ipaddress.ip_address(dns)), str(parsed_address), port, obf

    def read_config(self) -> bytes:
        raw = _read_root_file(self.config, 65536)
        PersistentCanaryConfig(raw)
        return raw

    def write_config(self, expected: bytes, replacement: bytes) -> None:
        if self.read_config() != expected:
            raise ValueError('profile config drift')
        PersistentCanaryConfig(replacement)
        info = os.lstat(self.config)
        if not stat.S_ISREG(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o077:
            raise ValueError('unsafe profile config')
        self.backups.mkdir(mode=0o700, parents=True, exist_ok=True)
        for directory in (BACKUP_ROOT, self.backups):
            entry = os.lstat(directory)
            if not stat.S_ISDIR(entry.st_mode) or entry.st_uid != 0 or entry.st_mode & 0o077:
                raise ValueError('unsafe backup directory')
        backup = self.backups / (str(time.time_ns()) + '.conf')
        _write_all(os.open(backup, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600), expected)
        temp = self.config.with_name('.' + self.interface + '.awg-cita-' + str(os.getpid()))
        fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        try:
            os.fchown(fd, info.st_uid, info.st_gid)
            os.fchmod(fd, stat.S_IMODE(info.st_mode))
            _write_all(fd, replacement)
            if self.read_config() != expected:
                raise ValueError('profile config drift')
            os.replace(temp, self.config)
            directory = os.open(self.config.parent, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
        finally:
            temp.unlink(missing_ok=True)

    def command(self, args: tuple[str, ...], *, input_key: str | None = None,
                limit: int = 65536, timeout: int = 5) -> bytes:
        if input_key is not None:
            _valid_key(input_key.encode('ascii'))
        result = subprocess.run(args, input=(input_key + '\n').encode('ascii') if input_key else None,
                                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                timeout=timeout, env=_ENV)
        if result.returncode or not 1 <= len(result.stdout) <= limit:
            raise ValueError('profile command failed')
        return result.stdout

    def read_dump(self) -> str:
        return self.command((AWG, 'show', self.interface, 'dump')).decode('utf-8')

    def sync_runtime(self) -> None:
        result = subprocess.run(('/usr/bin/systemctl', 'restart', self.service),
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                timeout=30, env=_ENV)
        if result.returncode:
            state = subprocess.run(('/usr/bin/systemctl', 'show', '--value', '--property=Result', self.service),
                                   capture_output=True, timeout=5, env=_ENV)
            if state.returncode or state.stdout.strip() != b'start-limit-hit':
                raise ValueError('profile restart failed')
            reset = subprocess.run(('/usr/bin/systemctl', 'reset-failed', self.service),
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                   timeout=5, env=_ENV)
            started = subprocess.run(('/usr/bin/systemctl', 'start', self.service),
                                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                     timeout=30, env=_ENV) if not reset.returncode else reset
            if started.returncode:
                raise ValueError('profile restart failed')

    def key(self, args: tuple[str, ...], input_key: str | None = None) -> str:
        return _valid_key(self.command((AWG, *args), input_key=input_key, limit=64).strip())

    def controller(self) -> CanaryPeerController:
        from .client_templates import read as read_template
        endpoint, dns, address, port, obf = self.settings()
        template = read_template(self.name, dns)
        persisted = PersistentCanaryConfig(self.read_config())
        return CanaryPeerController(self.read_config, self.read_dump,
                                    write_config=self.write_config, sync_runtime=self.sync_runtime,
                                    mutable_keys=set(persisted.peers()), endpoint_host=endpoint,
                                    dns_server=template['dns_server'], expected_obfuscation=obf,
                                    expected_interface_address=address,
                                    expected_listen_port=port,
                                    client_allowed_ips=template['allowed_ips'], client_mtu=template['mtu'],
                                    client_keepalive=template['keepalive'])

    def config_path(self, client_id: str) -> Path:
        if not _ID.fullmatch(client_id):
            raise ValueError('invalid peer id')
        self.storage.mkdir(mode=0o700, parents=True, exist_ok=True)
        for directory in (STATE_ROOT.parent, STATE_ROOT, self.storage):
            entry = os.lstat(directory)
            if not stat.S_ISDIR(entry.st_mode) or entry.st_uid != 0 or entry.st_mode & 0o077:
                raise ValueError('unsafe client config directory')
        return self.storage / (client_id + '.conf')

    def store_config(self, client_id: str, config_text: str) -> None:
        if not isinstance(config_text, str) or not 1 <= len(config_text) <= 2400:
            raise ValueError('invalid client configuration')
        path = self.config_path(client_id)
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        try:
            _write_all(fd, config_text.encode('ascii'))
        except Exception:
            path.unlink(missing_ok=True)
            raise
        directory = os.open(self.storage, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)

    def load_config(self, client_id: str, controller: CanaryPeerController) -> dict[str, object]:
        from .client_config_edit import revision
        client = next((item for item in controller.list_clients() if item['id'] == client_id), None)
        if client is None:
            raise ValueError('peer not found')
        raw = _read_root_file(self.config_path(client_id), 2400)
        config_text = raw.decode('ascii')
        fields = dict(line.split(' = ', 1) for line in config_text.splitlines() if ' = ' in line)
        server_fields = dict(line.split(' = ', 1) for line in self.read_config().split(b'\n[Peer]\n', 1)[0].decode('ascii').splitlines() if ' = ' in line)
        for name in (*_OBF, 'Jc', 'Jmin', 'Jmax', 'HeaderProtectionKey'):
            if fields.get(name) != server_fields.get(name):
                raise ValueError('stored client profile mismatch')
        private = _valid_key(fields['PrivateKey'].encode('ascii'))
        public = self.key(('pubkey',), private)
        server_public = self.key(('show', self.interface, 'public-key'))
        if ('peer-' + hashlib.sha256(base64.b64decode(public)).hexdigest()[:16] != client_id or
                fields.get('PublicKey') != server_public):
            raise ValueError('stored client config mismatch')
        from .server_endpoint import project_client_endpoint
        endpoint, _dns, _address, port, _obf = self.settings()
        config_text = project_client_endpoint(config_text, endpoint, port)
        import segno
        qr_uri = segno.make_qr(config_text).png_data_uri(scale=4)
        return {'schema_version': 1, 'client': client, 'configText': config_text, 'qrDataUri': qr_uri,
                'revision': revision(config_text)}

    def update_config(self, client_id: str, controller: CanaryPeerController,
                      expected_revision: str, settings: dict[str, object]) -> dict[str, object]:
        from .client_config_edit import atomic_replace, replace_editable
        current = self.load_config(client_id, controller)
        if current['revision'] != expected_revision:
            raise ValueError('saved configuration changed')
        replacement = replace_editable(current['configText'], settings)
        if replacement != current['configText']:
            raw = _read_root_file(self.config_path(client_id), 2400).decode('ascii')
            atomic_replace(self.config_path(client_id), raw, replacement)
        return self.load_config(client_id, controller)

    def execute(self, args: list[str]) -> dict[str, object]:
        operation = args[0]
        request = _read_create_request() if operation == 'create' else None
        update_request = None
        if operation == 'config-update':
            from .client_config_edit import read_update_request
            update_request = read_update_request()
        endpoint_request = None
        if operation == 'endpoint-update':
            from .server_endpoint import read_request
            endpoint_request = read_request()
        port_request = None
        if operation == 'port-update':
            from .server_port import read_request
            port_request = read_request()
        with self.locked():
            self.recover_port_migration()
            controller = self.controller()
            if operation == 'list':
                return {'schema_version': 1, 'clients': controller.list_clients()}
            if operation == 'server':
                from .server_endpoint import read_root_settings, revision
                endpoint, _dns, address, port, _obf = self.settings()
                runtime = self.read_dump().splitlines()[0].split('\t')
                if len(runtime) < 3 or runtime[2] != str(port):
                    raise ValueError('profile runtime drift')
                return {'schema_version': 1, 'profile': self.name, 'interface': self.interface,
                        'endpoint': endpoint, 'address': address, 'listenPort': port,
                        'state': 'ACTIVE', 'clientCount': len(controller.list_clients()),
                        'revision': revision(read_root_settings(self.profile, 2048))}
            if operation == 'endpoint-update':
                from .server_endpoint import project_client_endpoint, read_root_settings, replace_endpoint, revision
                expected, endpoint = endpoint_request
                _old_endpoint, _dns, _address, old_port, _obf = self.settings()
                for record in controller.list_clients():
                    path = self.config_path(record['id'])
                    if path.exists() or path.is_symlink():
                        project_client_endpoint(_read_root_file(path, 2400).decode('ascii'),
                                                _old_endpoint, old_port)
                replace_endpoint(self.profile, profile=self.name, expected_revision=expected,
                                 endpoint=endpoint, limit=2048,
                                 verify=lambda: (self.settings(), self.controller().list_clients()))
                endpoint, _dns, address, port, _obf = self.settings()
                return {'schema_version': 1, 'profile': self.name, 'interface': self.interface,
                        'endpoint': endpoint, 'address': address, 'listenPort': port,
                        'state': 'ACTIVE', 'clientCount': len(self.controller().list_clients()),
                        'revision': revision(read_root_settings(self.profile, 2048))}
            if operation == 'port-update':
                from .server_endpoint import project_client_endpoint, read_root_settings, revision
                from .server_port import apply_port
                expected, new_port = port_request
                old_endpoint, _dns, _address, old_port, _obf = self.settings()
                for record in controller.list_clients():
                    path = self.config_path(record['id'])
                    if path.exists() or path.is_symlink():
                        project_client_endpoint(_read_root_file(path, 2400).decode('ascii'),
                                                old_endpoint, old_port)
                def verify_runtime(port):
                    runtime = self.read_dump().splitlines()[0].split('\t')
                    if len(runtime) < 3 or runtime[2] != str(port):
                        raise ValueError('profile runtime port drift')
                    self.controller().list_clients()
                apply_port(profile=self.name, path=self.profile, limit=2048,
                           config=self.read_config(), write_config=self.write_config,
                           read_config=self.read_config, settings_port=old_port,
                           expected_revision=expected, new_port=new_port,
                           verify_settings=self.settings, sync_runtime=self.sync_runtime,
                           verify_runtime=verify_runtime)
                endpoint, _dns, address, port, _obf = self.settings()
                return {'schema_version': 1, 'profile': self.name, 'interface': self.interface,
                        'endpoint': endpoint, 'address': address, 'listenPort': port,
                        'state': 'ACTIVE', 'clientCount': len(self.controller().list_clients()),
                        'revision': revision(read_root_settings(self.profile, 2048))}
            if operation == 'create':
                return controller.create(request['name'], request['tags'], request['idempotencyKey'],
                                         lambda: (private := self.key(('genkey',)), self.key(('pubkey',), private)),
                                         lambda: self.key(('show', self.interface, 'public-key')),
                                         self.store_config)
            if operation == 'config':
                return self.load_config(args[1], controller)
            if operation == 'config-update':
                return self.update_config(args[1], controller, *update_request)
            value = controller.mutate(operation, args[1])
            if operation == 'delete':
                self.config_path(args[1]).unlink(missing_ok=True)
                return {'schema_version': 1, 'id': args[1], 'deleted': True}
            return {'schema_version': 1, 'client': value}

    def recover_port_migration(self) -> None:
        from .server_port import recover_pending
        def verify_runtime(port):
            runtime = self.read_dump().splitlines()[0].split('\t')
            if len(runtime) < 3 or runtime[2] != str(port):
                raise ValueError('profile runtime port drift')
            self.controller().list_clients()
        recover_pending(profile=self.name, path=self.profile, limit=2048,
                        read_config=self.read_config, write_config=self.write_config,
                        sync_runtime=self.sync_runtime, verify_runtime=verify_runtime)


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if (os.geteuid() != 0 or len(args) not in (2, 3) or args[0] not in _INTERFACES or
        not ((len(args) == 2 and args[1] in {'list', 'server', 'create', 'endpoint-update', 'port-update'}) or
             (len(args) == 3 and args[1] in {'config', 'config-update', 'enable', 'disable', 'delete'} and _ID.fullmatch(args[2])))):
        print('invalid profile operation', file=sys.stderr)
        return 64
    try:
        result = ProfileOps(args[0]).execute(args[1:])
        print(json.dumps(result, separators=(',', ':')))
        return 0
    except Exception:
        print('profile operation failed', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
