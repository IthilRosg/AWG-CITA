"""Persistent AWG canary peer stanza handling (no command execution)."""
from __future__ import annotations

import base64
import datetime as dt
import hashlib
import ipaddress
import json
import re
import time
from typing import Any, Callable

from .lifecycle import CLIENT_FIELDS, ClientRecord, ClientUpdate, LifecycleError
from .snapshot import parse_awg_dump, classify_peer

_MARKER = b'# AWG-CITA-DISABLED '
_KEY = re.compile(rb'[A-Za-z0-9+/]{43}=')
_SECTION = re.compile(rb'\[[A-Za-z][A-Za-z0-9]*\][ \t]*\n')
_PUBLIC = re.compile(rb'PublicKey[ \t]*=[ \t]*([^ \t\r\n]+)[ \t]*\n')
_ALLOWED = re.compile(rb'AllowedIPs[ \t]*=[ \t]*([^ \t\r\n]+)[ \t]*\n')
_DNS_LABEL = re.compile(r'[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\Z')
ACTION_HELPER_TIMEOUT = 300  # Includes bounded lock, restart/recovery and one rollback.


def valid_endpoint_host(value: str) -> bool:
    return (isinstance(value, str) and 1 <= len(value) <= 253 and
            all(_DNS_LABEL.fullmatch(label) for label in value.split('.')))


def _valid_key(raw: bytes) -> str:
    if not _KEY.fullmatch(raw):
        raise ValueError('invalid public key')
    try:
        decoded = base64.b64decode(raw, validate=True)
    except ValueError as error:
        raise ValueError('invalid public key') from error
    if len(decoded) != 32:
        raise ValueError('invalid public key')
    return raw.decode('ascii')


def _stanza_key(block: bytes) -> str:
    lines = block.splitlines(keepends=True)
    if not lines or lines[0] != b'[Peer]\n':
        raise ValueError('invalid peer section')
    keys = [_PUBLIC.fullmatch(line).group(1) for line in lines[1:] if _PUBLIC.fullmatch(line)]
    if len(keys) != 1:
        raise ValueError('peer must have one public key')
    routes = [_ALLOWED.fullmatch(line).group(1) for line in lines[1:] if _ALLOWED.fullmatch(line)]
    if len(routes) != 1:
        raise ValueError('peer must have one route')
    try:
        ipaddress.ip_network(routes[0].decode('ascii'), strict=True)
    except (ValueError, UnicodeError) as error:
        raise ValueError('invalid peer route') from error
    return _valid_key(keys[0])


class PersistentCanaryConfig:
    """Preserve original bytes, including unknown AWG parameters and comments."""

    def __init__(self, source: bytes) -> None:
        if not isinstance(source, bytes) or not 1 <= len(source) <= 65536 or b'\0' in source or b'\r' in source:
            raise ValueError('invalid AWG config')
        lines = source.splitlines(keepends=True)
        if not lines or lines[0] != b'[Interface]\n' or not source.endswith(b'\n'):
            raise ValueError('invalid AWG config')
        self.source = source
        self._entries: dict[str, tuple[str, bytes, bytes]] = {}
        self._index(lines)

    def _index(self, lines: list[bytes]) -> None:
        offsets = []
        position = 0
        for line in lines:
            offsets.append(position)
            position += len(line)
        sections = [i for i, line in enumerate(lines) if _SECTION.fullmatch(line)]
        if not sections or sections[0] != 0:
            raise ValueError('invalid AWG config')
        if any(lines[i] not in (b'[Interface]\n', b'[Peer]\n') for i in sections):
            raise ValueError('unexpected section')
        if lines.count(b'[Interface]\n') != 1:
            raise ValueError('duplicate interface')
        starts = sorted(set(sections + [i for i, line in enumerate(lines) if line.startswith(_MARKER)]))
        for index, start in enumerate(starts[1:], 1):
            line = lines[start]
            if line.startswith(_MARKER):
                payload = line[len(_MARKER):-1]
                try:
                    block = base64.b64decode(payload, validate=True)
                except ValueError as error:
                    raise ValueError('malformed disabled peer') from error
                key = _stanza_key(block)
                status, representation = 'disabled', line
            else:
                stop = starts[index + 1] if index + 1 < len(starts) else len(lines)
                block = self.source[offsets[start]:(offsets[stop] if stop < len(lines) else len(self.source))]
                key = _stanza_key(block)
                status, representation = 'enabled', block
            if key in self._entries:
                raise ValueError('duplicate peer')
            self._entries[key] = (status, representation, block)

    def peers(self) -> dict[str, str]:
        return {key: status for key, (status, _, _) in self._entries.items()}

    def active_config(self) -> bytes:
        data = self.source
        for status, representation, _block in self._entries.values():
            if status == 'disabled':
                data = data.replace(representation, b'', 1)
        return data

    def disable(self, key: str) -> bytes:
        status, representation, block = self._require(key)
        if status != 'enabled':
            return self.source
        marker = _MARKER + base64.b64encode(block) + b'\n'
        return self.source.replace(representation, marker, 1)

    def enable(self, key: str) -> bytes:
        status, representation, block = self._require(key)
        if status == 'enabled':
            return self.source
        return self.source.replace(representation, block, 1)

    def delete(self, key: str) -> bytes:
        _status, representation, _block = self._require(key)
        return self.source.replace(representation, b'', 1)

    def _require(self, key: str) -> tuple[str, bytes, bytes]:
        if not isinstance(key, str) or key not in self._entries:
            raise ValueError('peer not found')
        return self._entries[key]


class CanaryPeerController:
    """Read canary config and runtime together; never return key material."""

    def __init__(self, read_config: Callable[[], bytes], read_dump: Callable[[], str],
                 clock: Callable[[], float] = time.time, *,
                 write_config: Callable[[bytes, bytes], None] | None = None,
                 sync_runtime: Callable[[], None] | None = None,
                 mutable_keys: set[str] | None = None,
                 endpoint_host: str | None = None, dns_server: str | None = None,
                 expected_obfuscation: dict[str, str] | None = None,
                 expected_interface_address: str | None = None,
                 expected_listen_port: int | None = None,
                 client_allowed_ips: str = '0.0.0.0/0',
                 client_mtu: int | None = None,
                 client_keepalive: int = 25) -> None:
        self._read_config = read_config
        self._read_dump = read_dump
        self._clock = clock
        self._write_config = write_config
        self._sync_runtime = sync_runtime
        self._mutable_keys = frozenset(mutable_keys or ())
        self._endpoint_host = endpoint_host
        self._dns_server = dns_server
        self._expected_obfuscation = expected_obfuscation
        self._expected_interface_address = expected_interface_address
        self._expected_listen_port = expected_listen_port
        if not isinstance(client_allowed_ips, str) or not 1 <= len(client_allowed_ips) <= 128:
            raise ValueError('invalid client template')
        try:
            networks = [ipaddress.ip_network(item.strip(), strict=True) for item in client_allowed_ips.split(',')]
        except ValueError as error:
            raise ValueError('invalid client template') from error
        if (not 1 <= len(networks) <= 8 or any(network.version != 4 for network in networks) or
            type(client_mtu) not in (int, type(None)) or (client_mtu is not None and not 1280 <= client_mtu <= 1500) or
            type(client_keepalive) is not int or not 0 <= client_keepalive <= 120):
            raise ValueError('invalid client template')
        self._client_allowed_ips = client_allowed_ips
        self._client_mtu = client_mtu
        self._client_keepalive = client_keepalive

    def list_clients(self) -> list[ClientRecord]:
        persisted = PersistentCanaryConfig(self._read_config())
        raw = self._read_dump()
        if not isinstance(raw, str) or len(raw.encode('utf-8')) > 65536:
            raise ValueError('invalid runtime dump')
        parsed = parse_awg_dump(raw)
        rows = [line.split('\t') for line in raw.splitlines() if line.strip()][1:]
        if len(rows) != parsed['peer_count'] or len(rows) > 64 or len(persisted.peers()) > 64:
            raise ValueError('peer inventory bound exceeded')
        runtime: dict[str, dict[str, Any]] = {}
        for row, stats in zip(rows, parsed['peers']):
            key = _valid_key(row[0].encode('ascii'))
            if key in runtime or key not in persisted.peers() or persisted.peers()[key] != 'enabled':
                raise ValueError('runtime differs from persistent config')
            block = persisted._entries[key][2]
            route = next(_ALLOWED.fullmatch(line).group(1).decode('ascii') for line in block.splitlines(keepends=True) if _ALLOWED.fullmatch(line))
            if row[3] != route:
                raise ValueError('runtime route differs from persistent config')
            runtime[key] = stats
        if set(runtime) != {key for key, state in persisted.peers().items() if state == 'enabled'}:
            raise ValueError('runtime differs from persistent config')
        now = int(self._clock())
        records: list[ClientRecord] = []
        for key, state in persisted.peers().items():
            stats = runtime.get(key)
            handshake = stats['latest_handshake'] if stats else 0
            classified = classify_peer(handshake, now) if state == 'enabled' else 'DISABLED'
            status = 'IDLE' if classified == 'OFFLINE' else classified
            if status not in {'ONLINE', 'IDLE', 'STALE', 'NEVER', 'DISABLED'}:
                raise ValueError('invalid runtime status')
            stamp = dt.datetime.fromtimestamp(handshake, dt.timezone.utc).isoformat() if handshake else None
            peer_id = 'peer-' + hashlib.sha256(base64.b64decode(key)).hexdigest()[:16]
            block = persisted._entries[key][2]
            metadata_lines = [line[len(b'# AWG-CITA-META '):].strip() for line in block.splitlines()
                              if line.startswith(b'# AWG-CITA-META ')]
            name, tags = 'Peer ' + peer_id[5:13], []
            if metadata_lines:
                if len(metadata_lines) != 1 or len(metadata_lines[0]) > 1024:
                    raise ValueError('invalid canary metadata')
                try:
                    metadata = json.loads(base64.b64decode(metadata_lines[0], validate=True))
                    if (not isinstance(metadata, dict) or set(metadata) != {'name', 'tags', 'nonce'} or
                        not isinstance(metadata['nonce'], str) or
                        not re.fullmatch(r'[A-Za-z0-9_-]{8,128}', metadata['nonce'])):
                        raise ValueError('invalid canary metadata')
                    from .lifecycle import LifecycleService
                    LifecycleService._validate_name(metadata['name'])
                    LifecycleService._validate_tags(metadata['tags'])
                    name, tags = metadata['name'], metadata['tags']
                except (ValueError, UnicodeError, LifecycleError) as error:
                    raise ValueError('invalid canary metadata') from None
            records.append({
                'id': peer_id, 'name': name, 'status': status,
                'lastHandshakeAt': stamp, 'lastSeenAt': stamp, 'createdAt': None,
                'expiration': '', 'rxBytes': stats['rx_bytes'] if stats else 0,
                'txBytes': stats['tx_bytes'] if stats else 0, 'notes': '', 'tags': tags,
                'warning': 'Lifecycle state is disabled.' if state == 'disabled' else '',
            })
        return records

    def _rollback_if_changed(self, source: bytes, target: bytes) -> None:
        current = self._read_config()
        if current == source:
            return
        if current != target:
            raise ValueError('canary config drift after write')
        try:
            self._write_config(target, source)
        finally:
            # The rollback replace may itself succeed before a directory fsync fails.
            if self._read_config() == source:
                self._sync_runtime()

    def create(self, name: str, tags: list[str], nonce: str,
               keypair: Callable[[], tuple[str, str]], server_public: Callable[[], str],
               save_config: Callable[[str, str], None] | None = None,
               runtime_header_protection: Callable[[], str] | None = None) -> dict[str, Any]:
        """Prepare the complete client artifact before changing durable state."""
        import json as _json
        from .lifecycle import LifecycleService, _IDEMPOTENCY_RE
        LifecycleService._validate_name(name)
        LifecycleService._validate_tags(tags)
        if not isinstance(nonce, str) or not _IDEMPOTENCY_RE.fullmatch(nonce):
            raise ValueError('invalid request nonce')
        if self._write_config is None or self._sync_runtime is None:
            raise ValueError('persistent writer unavailable')
        before = self.list_clients()
        source = self._read_config()
        config = PersistentCanaryConfig(source)
        if len(config.peers()) >= 64:
            raise ValueError('canary peer capacity exhausted')
        marker = b'# AWG-CITA-NONCE ' + hashlib.sha256(nonce.encode('ascii')).hexdigest().encode() + b'\n'
        if marker in source:
            raise ValueError('request nonce already used')
        routes = []
        for _status, _representation, block in config._entries.values():
            route = next(_ALLOWED.fullmatch(line).group(1).decode('ascii') for line in block.splitlines(keepends=True) if _ALLOWED.fullmatch(line))
            routes.append(ipaddress.ip_network(route))
        interface = source.split(b'\n[Peer]\n', 1)[0].splitlines()
        fields: dict[str, str] = {}
        for line in interface[1:]:
            if b'=' not in line or line.lstrip().startswith(b'#'):
                continue
            key, value = (part.strip().decode('ascii') for part in line.split(b'=', 1))
            # AWG permits multiple hook commands. Preserve them verbatim in
            # the persistent config while keeping all other fields unique.
            if key in {'PostUp', 'PostDown'}:
                continue
            if key in fields:
                raise ValueError('duplicate canary interface field')
            fields[key] = value
        try:
            interface_address = ipaddress.ip_interface(fields['Address'])
            listen_port = int(fields['ListenPort'])
        except (KeyError, ValueError) as error:
            raise ValueError('unexpected canary profile') from error
        if (interface_address.version != 4 or not 24 <= interface_address.network.prefixlen <= 29 or
                not 1 <= listen_port <= 65535 or fields['Address'] != self._expected_interface_address or
                listen_port != self._expected_listen_port):
            raise ValueError('unexpected canary profile')
        address = next((f'{candidate}/32' for candidate in interface_address.network.hosts()
                        if candidate != interface_address.ip and
                        not any(ipaddress.ip_network(f'{candidate}/32').overlaps(route) for route in routes)), None)
        if address is None:
            raise ValueError('canary address capacity exhausted')
        if not valid_endpoint_host(self._endpoint_host):
            raise ValueError('invalid canary endpoint')
        try:
            dns_server = str(ipaddress.ip_address(self._dns_server))
        except ValueError as error:
            raise ValueError('invalid canary DNS') from error
        required_obfuscation = ('S1', 'S2', 'S3', 'S4', 'H1', 'H2', 'H3', 'H4')
        if not isinstance(self._expected_obfuscation, dict) or set(self._expected_obfuscation) not in (frozenset(), frozenset(required_obfuscation)):
            raise ValueError('missing canary obfuscation profile')
        extras = []
        for key in self._expected_obfuscation:
            value = fields.get(key)
            if (value is None or not value.isascii() or not value.isdecimal() or
                    not 0 <= int(value) <= 4294967295 or value != self._expected_obfuscation[key]):
                raise ValueError('unexpected canary obfuscation profile')
            extras.append(f'{key} = {value}')
        if not self._expected_obfuscation and any(key in fields for key in required_obfuscation):
            raise ValueError('unexpected canary obfuscation profile')
        present_j = [key for key in ('Jc', 'Jmin', 'Jmax') if key in fields]
        if present_j and len(present_j) != 3:
            raise ValueError('partial canary obfuscation profile')
        for key in ('Jc', 'Jmin', 'Jmax'):
            value = fields.get(key)
            if value is not None:
                if not value.isascii() or not value.isdecimal() or not 0 <= int(value) <= 65535:
                    raise ValueError('unexpected canary obfuscation profile')
                extras.append(f'{key} = {value}')
        if present_j and int(fields['Jmin']) > int(fields['Jmax']):
            raise ValueError('unexpected canary obfuscation profile')
        if not self._expected_obfuscation and present_j:
            raise ValueError('unexpected canary obfuscation profile')
        header_protection = fields.get('HeaderProtectionKey')
        if header_protection is not None:
            if not self._expected_obfuscation:
                raise ValueError('unexpected canary obfuscation profile')
            _valid_key(header_protection.encode('ascii'))
            if runtime_header_protection is None or runtime_header_protection() != header_protection:
                raise ValueError('canary header protection differs from runtime')
            extras.append(f'HeaderProtectionKey = {header_protection}')
        private, public = keypair()
        _valid_key(private.encode('ascii'))
        _valid_key(public.encode('ascii'))
        _valid_key(server_public_key := server_public().encode('ascii'))
        runtime_fields = self._read_dump().splitlines()[0].split('\t')
        if len(runtime_fields) < 3 or runtime_fields[1] != server_public_key.decode('ascii') or runtime_fields[2] != str(listen_port):
            raise ValueError('canary server key differs from runtime')
        if public in config.peers() or public == server_public_key.decode('ascii'):
            raise ValueError('canary public key collision')
        client_id = 'peer-' + hashlib.sha256(base64.b64decode(public)).hexdigest()[:16]
        if client_id in {item['id'] for item in before}:
            raise ValueError('canary client id collision')
        config_text = '\n'.join(['[Interface]', f'PrivateKey = {private}', f'Address = {address}',
                                 f'DNS = {dns_server}', *([f'MTU = {self._client_mtu}'] if self._client_mtu is not None else []),
                                 *extras, '', '[Peer]', f'PublicKey = {server_public_key.decode("ascii")}',
                                 f'Endpoint = {self._endpoint_host}:{listen_port}', f'AllowedIPs = {self._client_allowed_ips}',
                                 f'PersistentKeepalive = {self._client_keepalive}', ''])
        import segno
        qr_uri = segno.make_qr(config_text).png_data_uri(scale=4)
        if not isinstance(qr_uri, str) or not qr_uri.startswith('data:image/png;base64,') or len(qr_uri) > 65536:
            raise ValueError('canary QR generation failed')
        metadata = base64.b64encode(_json.dumps({'name': name, 'tags': tags, 'nonce': nonce},
                                                 ensure_ascii=True, separators=(',', ':')).encode('ascii'))
        stanza = (b'\n[Peer]\n# AWG-CITA-META ' + metadata + b'\nPublicKey = ' + public.encode('ascii') +
                  b'\nAllowedIPs = ' + address.encode('ascii') + b'\n')
        # The nonce ledger is kept even if the peer is later deleted.
        target = source.replace(b'[Interface]\n', b'[Interface]\n' + marker, 1) + stanza
        PersistentCanaryConfig(target)
        try:
            self._write_config(source, target)
            self._sync_runtime()
            after = self.list_clients()
            if self._read_config() != target or len(after) != len(before) + 1:
                raise ValueError('canary creation readback failed')
            created = next((entry for entry in after if entry['id'] == client_id), None)
            if created is None or created['status'] == 'DISABLED' or {row['id'] for row in after} != {row['id'] for row in before} | {client_id}:
                raise ValueError('canary creation readback failed')
            if save_config is not None:
                save_config(client_id, config_text)
            return {'schema_version': 1, 'client': created, 'configText': config_text,
                    'qrDataUri': qr_uri, 'oneTime': False}
        except Exception:
            self._rollback_if_changed(source, target)
            raise

    def mutate(self, operation: str, client_id: str) -> ClientRecord | dict[str, Any]:
        if operation not in {'disable', 'enable', 'delete'} or not isinstance(client_id, str):
            raise ValueError('invalid operation')
        if self._write_config is None or self._sync_runtime is None:
            raise ValueError('persistent writer unavailable')
        before = self.list_clients()
        by_id = {record['id']: record for record in before}
        source = self._read_config()
        persisted = PersistentCanaryConfig(source)
        matches = [key for key in persisted.peers() if 'peer-' + hashlib.sha256(base64.b64decode(key)).hexdigest()[:16] == client_id]
        if len(matches) != 1 or matches[0] not in self._mutable_keys or client_id not in by_id:
            raise ValueError('peer not authorized')
        key = matches[0]
        target = getattr(persisted, operation)(key)
        if target == source:
            return by_id[client_id]
        try:
            self._write_config(source, target)
            self._sync_runtime()
            after = self.list_clients()
            after_by_id = {record['id']: record for record in after}
            if ({id: entry for id, entry in PersistentCanaryConfig(self._read_config())._entries.items() if id != key}
                    != {id: entry for id, entry in persisted._entries.items() if id != key}
                    or set(after_by_id) - {client_id} != set(by_id) - {client_id}):
                raise ValueError('unrelated peer changed')
            if operation == 'delete':
                if client_id in after_by_id:
                    raise ValueError('delete readback failed')
                return {'schema_version': 1, 'id': client_id, 'deleted': True}
            expected = 'DISABLED' if operation == 'disable' else None
            record = after_by_id.get(client_id)
            if record is None or (record['status'] == 'DISABLED') != (expected == 'DISABLED'):
                raise ValueError('mutation readback failed')
            return record
        except Exception:
            self._rollback_if_changed(source, target)
            raise


class RealAwgLifecycleAdapter:
    """Call only the installed fixed root helper; never expose its raw output."""

    _HELPER = '/usr/local/sbin/awg-cita-peer'
    _ID = re.compile(r'peer-[A-Za-z0-9_-]{1,64}\Z')

    def __init__(self, helper: Callable[[str, str | None], dict[str, Any]] | None = None,
                 *, profile: str | None = None) -> None:
        if profile not in (None, 'awg2', 'wg'):
            raise ValueError('invalid peer profile')
        self._profile = profile
        self._helper = helper or (lambda operation, client_id: self._invoke(operation, client_id, profile))

    @classmethod
    def _invoke(cls, operation: str, client_id: str | dict[str, Any] | None,
                profile: str | None = None) -> dict[str, Any]:
        if operation not in {'list', 'server', 'endpoint-update', 'port-update', 'network-update', 'enable', 'disable', 'delete', 'create', 'config', 'config-update'}:
            raise LifecycleError('invalid_request')
        if profile not in (None, 'awg2', 'wg'):
            raise LifecycleError('invalid_request')
        if operation in {'create', 'config-update', 'endpoint-update', 'port-update', 'network-update'}:
            if operation == 'create':
                valid = (isinstance(client_id, dict) and set(client_id) == {'name', 'tags', 'idempotencyKey'} and
                         isinstance(client_id['name'], str) and isinstance(client_id['tags'], list) and
                         isinstance(client_id['idempotencyKey'], str))
            elif operation == 'endpoint-update':
                from .server_endpoint import validate_request
                try:
                    validate_request(client_id)
                    valid = True
                except (ValueError, TypeError):
                    valid = False
            elif operation == 'port-update':
                from .server_port import validate_request
                try:
                    validate_request(client_id)
                    valid = True
                except (ValueError, TypeError):
                    valid = False
            elif operation == 'network-update':
                from .server_network import validate_request
                try:
                    validate_request(client_id, profile)
                    valid = True
                except (ValueError, TypeError):
                    valid = False
            else:
                from .client_config_edit import validate_revision
                from .client_templates import validate
                try:
                    valid = (isinstance(client_id, dict) and set(client_id) == {'clientId', 'expectedRevision', 'settings'} and
                             isinstance(client_id['clientId'], str) and bool(cls._ID.fullmatch(client_id['clientId'])) and
                             bool(validate_revision(client_id['expectedRevision'])) and bool(validate(client_id['settings'])))
                except (ValueError, KeyError, TypeError):
                    valid = False
            if not valid:
                raise LifecycleError('invalid_request')
            argument = json.dumps(client_id, ensure_ascii=True, separators=(',', ':'))
            if len(argument) > 1024:
                raise LifecycleError('invalid_request')
        elif (client_id is None) != (operation in {'list', 'server'}) or (client_id is not None and not isinstance(client_id, str)) or (isinstance(client_id, str) and not cls._ID.fullmatch(client_id)):
            raise LifecycleError('invalid_request')
        from .app import AwgReader
        argv = ('/usr/bin/sudo', '-n', '--', cls._HELPER, operation) if profile is None else (
            '/usr/bin/sudo', '-n', '--', '/usr/local/sbin/awg-cita-profile', profile, operation)
        if operation in {'create', 'config-update', 'endpoint-update', 'port-update', 'network-update'}:
            if operation == 'config-update':
                argv += (client_id['clientId'],)
                argument = json.dumps({'expectedRevision': client_id['expectedRevision'], 'settings': client_id['settings']},
                                      ensure_ascii=True, separators=(',', ':'))
            elif operation == 'endpoint-update':
                argument = json.dumps(client_id, ensure_ascii=True, separators=(',', ':'))
            elif operation == 'port-update':
                argument = json.dumps(client_id, ensure_ascii=True, separators=(',', ':'))
            elif operation == 'network-update':
                argument = json.dumps(client_id, ensure_ascii=True, separators=(',', ':'))
            out, err = AwgReader._run(argv, ACTION_HELPER_TIMEOUT, argument.encode('ascii'))
        elif client_id is not None:
            argv += (client_id,)
            out, err = AwgReader._run(argv, ACTION_HELPER_TIMEOUT)
        else:
            out, err = AwgReader._run(argv, 15)
        if err or len(out.encode('utf-8')) > (131072 if operation in {'create', 'config', 'config-update'} else 65536):
            raise LifecycleError('awg_command_failed')

        def unique_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
            result: dict[str, Any] = {}
            for key, value in pairs:
                if key in result:
                    raise ValueError('duplicate field')
                result[key] = value
            return result

        try:
            value = json.loads(out, object_pairs_hook=unique_pairs)
        except (ValueError, TypeError):
            value = None
        # Raise outside the JSON exception handler: its .doc can contain private config.
        if not isinstance(value, dict):
            raise LifecycleError('awg_command_failed')
        return value

    def _call(self, operation: str, client_id: str | None = None) -> dict[str, Any]:
        if operation not in {'list', 'enable', 'disable', 'delete'}:
            raise LifecycleError('invalid_request')
        if client_id is not None and not self._ID.fullmatch(client_id):
            raise LifecycleError('invalid_request')
        value = self._helper(operation, client_id)
        if not isinstance(value, dict) or set(value) != ({'schema_version', 'clients'} if operation == 'list' else {'schema_version', 'client'} if operation != 'delete' else {'schema_version', 'deleted', 'id'}):
            raise LifecycleError('awg_command_failed')
        if type(value['schema_version']) is not int or value['schema_version'] != 1:
            raise LifecycleError('awg_command_failed')
        return value

    @staticmethod
    def _record(value: Any) -> ClientRecord:
        if not isinstance(value, dict) or set(value) != set(CLIENT_FIELDS):
            raise LifecycleError('awg_command_failed')
        return value

    def list_clients(self) -> list[ClientRecord]:
        records = self._call('list')['clients']
        if not isinstance(records, list) or len(records) > 64:
            raise LifecycleError('awg_command_failed')
        return [self._record(record) for record in records]

    def server_settings(self) -> dict[str, Any]:
        value = self._helper('server', None)
        return self._validate_server_settings(value)

    @staticmethod
    def _validate_server_settings(value: Any) -> dict[str, Any]:
        keys = {'schema_version', 'profile', 'interface', 'endpoint',
                'address', 'listenPort', 'state', 'clientCount', 'revision'}
        if (not isinstance(value, dict) or set(value) not in (keys, keys | {'obfuscation'}) or
                type(value['schema_version']) is not int or value['schema_version'] != 1 or
                value['profile'] not in {'awg3', 'awg2', 'wg'} or
                value['interface'] != {'awg3': 'awg-canary0', 'awg2': 'awg-cita2', 'wg': 'awg-cita-wg'}[value['profile']] or
                not valid_endpoint_host(value['endpoint']) or value['state'] != 'ACTIVE' or
                type(value['listenPort']) is not int or not 1 <= value['listenPort'] <= 65535 or
                type(value['clientCount']) is not int or not 0 <= value['clientCount'] <= 64 or
                not isinstance(value['revision'], str) or not re.fullmatch(r'[0-9a-f]{64}', value['revision'])):
            raise LifecycleError('awg_command_failed')
        try:
            address = ipaddress.ip_interface(value['address'])
        except (ValueError, TypeError) as error:
            raise LifecycleError('awg_command_failed') from error
        if address.version != 4:
            raise LifecycleError('awg_command_failed')
        if 'obfuscation' in value:
            from .server_network import validate_obfuscation
            try:
                if value['profile'] != 'awg2':
                    raise ValueError('unexpected obfuscation')
                validate_obfuscation(value['obfuscation'])
            except ValueError as error:
                raise LifecycleError('awg_command_failed') from error
        return value

    def update_server_endpoint(self, expected_revision: str, endpoint: str) -> dict[str, Any]:
        from .server_endpoint import validate_request
        validate_request({'expectedRevision': expected_revision, 'endpoint': endpoint})
        value = self._helper('endpoint-update', {'expectedRevision': expected_revision, 'endpoint': endpoint})
        # Reuse the strict projection validation.
        return self._validate_server_settings(value)

    def update_server_port(self, expected_revision: str, listen_port: int) -> dict[str, Any]:
        from .server_port import validate_request
        validate_request({'expectedRevision': expected_revision, 'listenPort': listen_port})
        value = self._helper('port-update', {'expectedRevision': expected_revision, 'listenPort': listen_port})
        return self._validate_server_settings(value)

    def update_server_network(self, expected_revision: str, kind: str, target: object) -> dict[str, Any]:
        from .server_network import validate_request
        request = {'expectedRevision': expected_revision, kind: target}
        validate_request(request, self._profile)
        value = self._helper('network-update', request)
        return self._validate_server_settings(value)

    def get_client(self, client_id: str) -> ClientRecord | None:
        return next((item for item in self.list_clients() if item['id'] == client_id), None)

    def disable_client(self, client_id: str, _reason: str) -> ClientRecord:
        return self._record(self._call('disable', client_id)['client'])

    def enable_client(self, client_id: str) -> ClientRecord:
        return self._record(self._call('enable', client_id)['client'])

    def delete_client(self, client_id: str) -> bool:
        result = self._call('delete', client_id)
        if result['id'] != client_id or result['deleted'] is not True:
            raise LifecycleError('awg_command_failed')
        return True

    def create_client(self, name: str, tags: list[str], nonce: str) -> dict[str, Any]:
        request = {'name': name, 'tags': tags, 'idempotencyKey': nonce}
        value = self._helper('create', request)
        if (not isinstance(value, dict) or set(value) != {'schema_version', 'client', 'configText', 'qrDataUri', 'oneTime'} or
            type(value['schema_version']) is not int or value['schema_version'] != 1 or value['oneTime'] is not False or
            not isinstance(value['configText'], str) or not isinstance(value['qrDataUri'], str) or
            len(value['configText']) > 2400 or len(value['qrDataUri']) > 65536):
            raise LifecycleError('awg_command_failed')
        self._record(value['client'])
        return value

    def update_client(self, _client_id: str, _metadata: ClientUpdate) -> ClientRecord:
        raise LifecycleError('invalid_state')

    def generate_configuration_preview(self, _client_id: str) -> None:
        raise LifecycleError('invalid_state')

    def get_configuration(self, client_id: str) -> dict[str, Any]:
        if not isinstance(client_id, str) or not re.fullmatch(r'peer-[0-9a-f]{16}', client_id):
            raise LifecycleError('invalid_request')
        value = self._helper('config', client_id)
        if (not isinstance(value, dict) or set(value) != {'schema_version', 'client', 'configText', 'qrDataUri', 'revision'} or
                type(value['schema_version']) is not int or value['schema_version'] != 1 or
                not isinstance(value['configText'], str) or not 1 <= len(value['configText']) <= 2400 or
                not isinstance(value['qrDataUri'], str) or not value['qrDataUri'].startswith('data:image/png;base64,') or
                len(value['qrDataUri']) > 65536 or not re.fullmatch(r'[0-9a-f]{64}', value['revision'])):
            raise LifecycleError('awg_command_failed')
        if self._record(value['client'])['id'] != client_id:
            raise LifecycleError('awg_command_failed')
        return value

    def update_configuration(self, client_id: str, expected_revision: str,
                             settings: dict[str, object]) -> dict[str, Any]:
        from .client_config_edit import validate_revision
        from .client_templates import validate
        try:
            validate_revision(expected_revision)
            normalized = validate(settings)
        except (ValueError, TypeError) as error:
            raise LifecycleError('invalid_request') from error
        value = self._helper('config-update', {'clientId': client_id,
                                               'expectedRevision': expected_revision, 'settings': normalized})
        if (not isinstance(value, dict) or value.get('client', {}).get('id') != client_id or
                not re.fullmatch(r'[0-9a-f]{64}', str(value.get('revision', '')))):
            raise LifecycleError('awg_command_failed')
        return value
