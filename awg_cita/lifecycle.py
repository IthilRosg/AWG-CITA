"""Local, synthetic AWG client lifecycle domain primitives."""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import re
import threading
import unicodedata
import uuid
from collections import OrderedDict
from copy import deepcopy
from typing import Any, Literal, NotRequired, Protocol, TypedDict, cast
from urllib.parse import quote

CLIENT_FIELDS = (
    "id",
    "name",
    "status",
    "lastHandshakeAt",
    "lastSeenAt",
    "createdAt",
    "expiration",
    "rxBytes",
    "txBytes",
    "notes",
    "tags",
    "warning",
)

ClientStatus = Literal["ONLINE", "IDLE", "STALE", "NEVER", "DISABLED"]
LifecycleOperation = Literal[
    "updateClient", "enableClient", "disableClient", "deleteClient", "generateConfigurationPreview", "updateConfiguration"
]
LifecycleErrorCode = Literal[
    "invalid_request", "client_not_found", "invalid_state", "conflict", "internal_error",
    "awg_timeout", "configuration_failed", "awg_command_failed"
]


class ClientRecord(TypedDict):
    id: str
    name: str
    status: ClientStatus
    lastHandshakeAt: str | None
    lastSeenAt: str | None
    createdAt: str | None
    expiration: str
    rxBytes: int
    txBytes: int
    notes: str
    tags: list[str]
    warning: str


class ClientUpdate(TypedDict):
    name: str
    notes: str
    tags: list[str]
    expiration: str


class ConfigurationPreview(TypedDict):
    schema_version: Literal[1]
    previewId: str
    clientId: str
    clientName: str
    expiration: str
    status: Literal["MOCK_PREVIEW"]
    qrPayload: str
    configText: str


class DeleteResult(TypedDict):
    schema_version: Literal[1]
    id: str
    deleted: Literal[True]


class AuditEvent(TypedDict):
    timestamp: str
    operation: LifecycleOperation
    client_id: str
    result: Literal["OK", "ERROR", "REPLAY"]
    error_code: NotRequired[LifecycleErrorCode]
    reason: NotRequired[Literal["operator_requested"]]

_FAKE_CLIENTS = [
    {"id": "peer-atlas", "name": "Atlas Relay", "status": "ONLINE", "lastHandshakeAt": "2026-09-22T10:00:00Z", "lastSeenAt": "2026-09-22T10:01:10Z", "createdAt": "2026-08-17", "expiration": "2026-12-31", "rxBytes": 8431616, "txBytes": 4923392, "notes": "Primary office relay.", "tags": ["priority", "office"], "warning": ""},
    {"id": "peer-boreal", "name": "Boreal Lab", "status": "IDLE", "lastHandshakeAt": "2026-09-22T09:38:00Z", "lastSeenAt": "2026-09-22T09:38:00Z", "createdAt": "2026-08-21", "expiration": "2027-01-15", "rxBytes": 1572864, "txBytes": 786432, "notes": "Research workstation.", "tags": ["lab"], "warning": ""},
    {"id": "peer-cinder", "name": "Cinder Mobile", "status": "STALE", "lastHandshakeAt": "2026-09-19T10:00:00Z", "lastSeenAt": "2026-09-19T10:00:00Z", "createdAt": "2026-07-02", "expiration": "2026-10-02", "rxBytes": 42467328, "txBytes": 8912896, "notes": "Last seen during the field visit.", "tags": ["mobile", "field"], "warning": "Handshake is older than the operator threshold."},
    {"id": "peer-delta", "name": "Delta New", "status": "NEVER", "lastHandshakeAt": None, "lastSeenAt": None, "createdAt": "2026-09-21", "expiration": "", "rxBytes": 0, "txBytes": 0, "notes": "Provisioned fixture with no handshake yet.", "tags": ["new"], "warning": "Client has never connected."},
    {"id": "peer-echo", "name": "Echo Disabled", "status": "DISABLED", "lastHandshakeAt": "2026-09-08T10:00:00Z", "lastSeenAt": "2026-09-08T10:00:00Z", "createdAt": "2026-06-12", "expiration": "2026-11-30", "rxBytes": 2621440, "txBytes": 1310720, "notes": "Temporarily disabled for review.", "tags": ["hold"], "warning": "Lifecycle state is disabled."},
    {"id": "peer-falkor", "name": "Falkor Heavy", "status": "ONLINE", "lastHandshakeAt": "2026-09-22T10:00:00Z", "lastSeenAt": "2026-09-22T10:00:35Z", "createdAt": "2026-05-03", "expiration": "2027-05-03", "rxBytes": 41523912704, "txBytes": 8013348864, "notes": "High-traffic synthetic peer.", "tags": ["priority", "high-traffic"], "warning": ""},
    {"id": "peer-garnet", "name": "Garnet Remote", "status": "IDLE", "lastHandshakeAt": "2026-09-22T09:12:00Z", "lastSeenAt": "2026-09-22T09:12:00Z", "createdAt": "2026-08-30", "expiration": "2026-12-04", "rxBytes": 28311552, "txBytes": 14155776, "notes": "Remote operator laptop.", "tags": ["remote"], "warning": ""},
    {"id": "peer-harbor", "name": "Harbor Stale", "status": "STALE", "lastHandshakeAt": "2026-09-13T10:00:00Z", "lastSeenAt": "2026-09-13T10:00:00Z", "createdAt": "2026-04-19", "expiration": "2026-10-19", "rxBytes": 5767168, "txBytes": 2883584, "notes": "Keep for archive verification.", "tags": ["archive", "review"], "warning": "Expiration is approaching and handshake is stale."},
    {"id": "peer-ivory", "name": "Ivory Expiring", "status": "ONLINE", "lastHandshakeAt": "2026-09-22T09:57:00Z", "lastSeenAt": "2026-09-22T09:58:00Z", "createdAt": "2026-07-28", "expiration": "2026-10-03", "rxBytes": 734003, "txBytes": 367001, "notes": "Synthetic expiry warning case.", "tags": ["expiring"], "warning": "Expiration date is within the review window."},
    {"id": "peer-juniper", "name": "Juniper Note", "status": "NEVER", "lastHandshakeAt": None, "lastSeenAt": None, "createdAt": "2026-09-10", "expiration": "2027-02-28", "rxBytes": 0, "txBytes": 0, "notes": "Awaiting device enrollment.", "tags": ["onboarding", "new"], "warning": "No session data is available."},
]


_CLIENT_ID_RE = re.compile(r"^peer-[A-Za-z0-9_-]{1,64}$")
_TAG_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,23}$")
_IDEMPOTENCY_RE = re.compile(r"^[A-Za-z0-9_-]{8,128}$")
_UPDATE_FIELDS = frozenset({"name", "notes", "tags", "expiration"})
_CLIENT_STATUSES = frozenset({"ONLINE", "IDLE", "STALE", "NEVER", "DISABLED"})
_LIFECYCLE_ERROR_CODES = frozenset({
    "invalid_request", "client_not_found", "invalid_state", "conflict", "internal_error",
    "awg_timeout", "configuration_failed", "awg_command_failed",
})
_MAX_COUNTER = (1 << 53) - 1
MAX_CLIENT_RECORDS = 64
_MAX_AUDIT_EVENTS = 256
_MAX_IDEMPOTENCY_RESULTS = 256
_CONFIG_PREVIEW_ID_RE = re.compile(r"^config-preview-[A-Za-z0-9_-]{1,96}$")


class LifecycleError(Exception):
    """Finite, safe lifecycle-domain error."""

    def __init__(self, code: LifecycleErrorCode) -> None:
        if code not in _LIFECYCLE_ERROR_CODES:
            raise ValueError("unknown lifecycle error code")
        super().__init__(code)
        self.code = code


class AwgLifecycleAdapter(Protocol):
    """Narrow adapter boundary consumed by the lifecycle domain service."""

    def list_clients(self) -> list[ClientRecord]: ...

    def get_client(self, client_id: str) -> ClientRecord | None: ...

    def update_client(self, client_id: str, metadata: ClientUpdate) -> ClientRecord | None: ...

    def enable_client(self, client_id: str) -> ClientRecord | None: ...

    def disable_client(self, client_id: str, reason: str) -> ClientRecord | None: ...

    def delete_client(self, client_id: str) -> bool: ...

    def generate_configuration_preview(self, client_id: str) -> ConfigurationPreview | None: ...


class FakeAwgLifecycleAdapter:
    """Explicit in-memory fake; it never invokes AWG or persists state."""

    def __init__(self, clients: list[dict[str, Any]] | None = None) -> None:
        self._clients = deepcopy(_FAKE_CLIENTS if clients is None else clients)
        self._failures: dict[str, Exception] = {}

    def fail_next(self, operation: str, error: Exception | None = None) -> None:
        self._failures[operation] = error or RuntimeError("synthetic adapter failure")

    def _maybe_fail(self, operation: str) -> None:
        error = self._failures.pop(operation, None)
        if error is not None:
            raise error

    def list_clients(self) -> list[ClientRecord]:
        self._maybe_fail("list_clients")
        return cast(list[ClientRecord], deepcopy(self._clients))

    def get_client(self, client_id: str) -> ClientRecord | None:
        self._maybe_fail("get_client")
        client = next((item for item in self._clients if item.get("id") == client_id), None)
        return cast(ClientRecord, deepcopy(client)) if client is not None else None

    def update_client(self, client_id: str, metadata: ClientUpdate) -> ClientRecord | None:
        self._maybe_fail("update_client")
        client = next((item for item in self._clients if item.get("id") == client_id), None)
        if client is None:
            return None
        client.update(deepcopy(metadata))
        return cast(ClientRecord, deepcopy(client))

    def enable_client(self, client_id: str) -> ClientRecord | None:
        self._maybe_fail("enable_client")
        client = next((item for item in self._clients if item.get("id") == client_id), None)
        if client is None:
            return None
        if client["status"] == "DISABLED":
            client["status"] = "ONLINE"
            if client["warning"] == "Lifecycle state is disabled.":
                client["warning"] = ""
        return cast(ClientRecord, deepcopy(client))

    def disable_client(self, client_id: str, _reason: str) -> dict[str, Any] | None:
        self._maybe_fail("disable_client")
        client = next((item for item in self._clients if item.get("id") == client_id), None)
        if client is None:
            return None
        client["status"] = "DISABLED"
        client["warning"] = "Lifecycle state is disabled."
        return cast(ClientRecord, deepcopy(client))

    def delete_client(self, client_id: str) -> bool:
        self._maybe_fail("delete_client")
        for index, client in enumerate(self._clients):
            if client.get("id") == client_id:
                del self._clients[index]
                return True
        return False

    def generate_configuration_preview(self, client_id: str) -> ConfigurationPreview | None:
        self._maybe_fail("generate_configuration_preview")
        client = next((item for item in self._clients if item.get("id") == client_id), None)
        if client is None:
            return None
        safe_name = quote(client["name"], safe="")
        config_text = "\n".join(
            (
                "# MOCK CONFIGURATION",
                "# UI READY / BACKEND STUB",
                "[Client]",
                f"Name = {client['name']}",
                f"Record = {client_id}",
                f"Expiration = {client['expiration'] or '[NONE]'}",
                "Address = [NOT_GENERATED]",
                "KeyMaterial = [NOT_GENERATED]",
                "Transport = [MOCK_ONLY]",
            )
        )
        return {
            "schema_version": 1,
            "previewId": f"config-preview-{uuid.uuid4().hex}",
            "clientId": client_id,
            "clientName": client["name"],
            "expiration": client["expiration"],
            "status": "MOCK_PREVIEW",
            "qrPayload": f"AWG-CITA-MOCK-QR|client={client_id}|name={safe_name}|status=MOCK_PREVIEW",
            "configText": config_text,
        }


class LifecycleService:
    """Domain projection and lifecycle operations over a narrow adapter."""

    def __init__(self, adapter: AwgLifecycleAdapter) -> None:
        self.adapter = adapter
        self._mutation_lock = threading.Lock()
        self._audit_lock = threading.Lock()
        self._audit: list[dict[str, Any]] = []
        self._idempotency: OrderedDict[str, tuple[str, dict[str, Any]]] = OrderedDict()
        self._deleted_ids: list[str] = []
        self._create_nonces: set[str] = set()

    def create_client(self, name: str, tags: list[str], idempotency_key: str, acknowledged: object) -> dict[str, Any]:
        """Provisioning response: never cache the secret in this service or audit its content."""
        if acknowledged is not True:
            raise LifecycleError('invalid_request')
        self._validate_name(name)
        self._validate_tags(tags)
        if not isinstance(idempotency_key, str) or not _IDEMPOTENCY_RE.fullmatch(idempotency_key):
            raise LifecycleError('invalid_request')
        if not self._mutation_lock.acquire(timeout=2.0):
            raise LifecycleError('conflict')
        try:
            if idempotency_key in self._create_nonces or idempotency_key in self._idempotency:
                raise LifecycleError('conflict')
            # A failed/ambiguous helper response must not cause automatic replay.
            self._create_nonces.add(idempotency_key)
            try:
                value = self.adapter.create_client(name, tags, idempotency_key)
            except Exception:
                value = None
            # Do not retain the adapter exception: it may have secret-bearing args.
            if value is None:
                raise LifecycleError('awg_command_failed')
            if not isinstance(value, dict) or set(value) != {'schema_version', 'client', 'configText', 'qrDataUri', 'oneTime'} or type(value['schema_version']) is not int or value['schema_version'] != 1 or value['oneTime'] is not False:
                raise LifecycleError('internal_error')
            client = self._safe_client(value['client'])
            if client['name'] != name or client['tags'] != tags or client['status'] == 'DISABLED':
                raise LifecycleError('internal_error')
            if (not isinstance(value['configText'], str) or not 1 <= len(value['configText']) <= 2400 or
                not isinstance(value['qrDataUri'], str) or not value['qrDataUri'].startswith('data:image/png;base64,') or
                len(value['qrDataUri']) > 65536):
                raise LifecycleError('internal_error')
            self._record_audit('createClient', client['id'], 'OK')
            return {'schema_version': 1, 'client': client, 'configText': value['configText'],
                    'qrDataUri': value['qrDataUri'], 'oneTime': False}
        except LifecycleError:
            raise
        except Exception:
            raise LifecycleError('awg_command_failed') from None
        finally:
            self._mutation_lock.release()

    def list_clients(self) -> list[ClientRecord]:
        try:
            records = self.adapter.list_clients()
            if not isinstance(records, list) or len(records) > MAX_CLIENT_RECORDS:
                raise LifecycleError("internal_error")
            clients = [self._safe_client(client) for client in records]
            client_ids = [client["id"] for client in clients]
            if len(set(client_ids)) != len(client_ids):
                raise LifecycleError("internal_error")
            return clients
        except LifecycleError:
            raise
        except Exception as error:
            raise self._adapter_error(error) from error

    def get_client(self, client_id: str) -> ClientRecord:
        self._validate_client_id(client_id)
        try:
            client = self.adapter.get_client(client_id)
        except Exception as error:
            raise self._adapter_error(error) from error
        if client is None:
            raise LifecycleError("client_not_found")
        return self._safe_client(client, expected_id=client_id)

    def update_client(self, client_id: str, metadata: ClientUpdate) -> ClientRecord:
        def update() -> ClientRecord:
            self._validate_client_id(client_id)
            if not isinstance(metadata, dict) or set(metadata) != _UPDATE_FIELDS:
                raise LifecycleError("invalid_request")
            self._validate_name(metadata["name"])
            self._validate_notes(metadata["notes"])
            self._validate_tags(metadata["tags"])
            self._validate_expiration(metadata["expiration"])
            updated = self.adapter.update_client(client_id, metadata)
            if updated is None:
                raise LifecycleError("client_not_found")
            safe = self._safe_client(updated, expected_id=client_id)
            if any(safe[field] != metadata[field] for field in _UPDATE_FIELDS):
                raise LifecycleError("internal_error")
            return safe

        return self._run_mutation("updateClient", client_id, None, metadata, update)

    def enable_client(self, client_id: str, idempotency_key: str | None) -> ClientRecord:
        def enable() -> ClientRecord:
            self._validate_client_id(client_id)
            updated = self.adapter.enable_client(client_id)
            if updated is None:
                raise LifecycleError("client_not_found")
            safe = self._safe_client(updated, expected_id=client_id)
            if safe["status"] == "DISABLED":
                raise LifecycleError("internal_error")
            return safe

        return self._run_mutation("enableClient", client_id, idempotency_key, {}, enable, require_idempotency=True)

    def disable_client(self, client_id: str, idempotency_key: str | None, reason: str) -> ClientRecord:
        def disable() -> ClientRecord:
            self._validate_client_id(client_id)
            if reason != "operator_requested":
                raise LifecycleError("invalid_request")
            updated = self.adapter.disable_client(client_id, reason)
            if updated is None:
                raise LifecycleError("client_not_found")
            safe = self._safe_client(updated, expected_id=client_id)
            if safe["status"] != "DISABLED":
                raise LifecycleError("internal_error")
            return safe

        return self._run_mutation(
            "disableClient", client_id, idempotency_key, {"reason": reason}, disable, reason=reason, require_idempotency=True
        )

    def delete_client(self, client_id: str, idempotency_key: str | None, confirmation: object) -> DeleteResult:
        def delete() -> dict[str, Any]:
            self._validate_client_id(client_id)
            if confirmation is not True:
                raise LifecycleError("invalid_request")
            if client_id in self._deleted_ids and self.adapter.get_client(client_id) is None:
                return {"schema_version": 1, "id": client_id, "deleted": True}
            if not self.adapter.delete_client(client_id):
                raise LifecycleError("client_not_found")
            if self.adapter.get_client(client_id) is not None:
                raise LifecycleError("internal_error")
            self._deleted_ids.append(client_id)
            del self._deleted_ids[:-_MAX_IDEMPOTENCY_RESULTS]
            return {"schema_version": 1, "id": client_id, "deleted": True}

        return self._run_mutation(
            "deleteClient", client_id, idempotency_key, {"confirmation": confirmation}, delete, require_idempotency=True
        )

    def generate_configuration_preview(self, client_id: str, acknowledged: object) -> ConfigurationPreview:
        try:
            self._validate_client_id(client_id)
            if acknowledged is not True:
                raise LifecycleError("invalid_request")
            result = self.adapter.generate_configuration_preview(client_id)
            if result is None:
                raise LifecycleError("client_not_found")
            result = self._safe_configuration_preview(result, client_id)
            self._record_audit("generateConfigurationPreview", client_id, "OK")
            return result
        except LifecycleError as error:
            self._record_audit("generateConfigurationPreview", client_id, "ERROR", error.code)
            raise
        except Exception as error:
            mapped = self._adapter_error(error, operation="configuration")
            self._record_audit("generateConfigurationPreview", client_id, "ERROR", mapped.code)
            raise mapped from error

    def get_configuration(self, client_id: str) -> dict[str, Any]:
        self._validate_client_id(client_id)
        try:
            value = self.adapter.get_configuration(client_id)
            client = self._safe_client(value['client'])
            if (client['id'] != client_id or not isinstance(value['configText'], str) or
                    not 1 <= len(value['configText']) <= 2400 or
                    not isinstance(value['qrDataUri'], str) or
                    not value['qrDataUri'].startswith('data:image/png;base64,') or
                    len(value['qrDataUri']) > 65536 or
                    not isinstance(value.get('revision'), str) or
                    not re.fullmatch(r'[0-9a-f]{64}', value['revision'])):
                raise LifecycleError('configuration_failed')
            self._record_audit('getConfiguration', client_id, 'OK')
            return {'schema_version': 1, 'client': client,
                    'configText': value['configText'], 'qrDataUri': value['qrDataUri'],
                    'revision': value['revision']}
        except LifecycleError:
            raise
        except Exception:
            raise LifecycleError('configuration_failed') from None

    def update_configuration(self, client_id: str, expected_revision: str,
                             settings: dict[str, object], idempotency_key: str) -> dict[str, Any]:
        from .client_config_edit import validate_revision
        from .client_templates import validate
        self._validate_client_id(client_id)
        if not isinstance(idempotency_key, str) or not _IDEMPOTENCY_RE.fullmatch(idempotency_key):
            raise LifecycleError('invalid_request')
        try:
            validate_revision(expected_revision)
            settings = validate(settings)
        except (ValueError, TypeError) as error:
            raise LifecycleError('invalid_request') from error
        if not self._mutation_lock.acquire(timeout=2.0):
            raise LifecycleError('conflict')
        try:
            self.adapter.update_configuration(client_id, expected_revision, settings)
            # Read back from the protected store. Never cache private config in idempotency or audit state.
            result = self.get_configuration(client_id)
            self._record_audit('updateConfiguration', client_id, 'OK')
            return result
        except LifecycleError:
            self._record_audit('updateConfiguration', client_id, 'ERROR', 'configuration_failed')
            raise
        except Exception:
            self._record_audit('updateConfiguration', client_id, 'ERROR', 'configuration_failed')
            raise LifecycleError('configuration_failed') from None
        finally:
            self._mutation_lock.release()

    def audit_events(self) -> list[AuditEvent]:
        with self._audit_lock:
            return deepcopy(self._audit)

    def _run_mutation(
        self,
        operation: LifecycleOperation,
        client_id: str,
        idempotency_key: str | None,
        request: dict[str, Any],
        action: Any,
        *,
        reason: Literal["operator_requested"] | None = None,
        require_idempotency: bool = False,
    ) -> Any:
        locked = self._mutation_lock.acquire(timeout=2.0)
        if not locked:
            self._record_audit(operation, client_id, "ERROR", "conflict", reason)
            raise LifecycleError("conflict")
        try:
            self._validate_client_id(client_id)
            fingerprint = hashlib.sha256(
                json.dumps([operation, client_id, request], sort_keys=True, separators=(",", ":")).encode("utf-8")
            ).hexdigest()
            if require_idempotency or idempotency_key is not None:
                if not isinstance(idempotency_key, str) or not _IDEMPOTENCY_RE.fullmatch(idempotency_key):
                    raise LifecycleError("invalid_request")
                previous = self._idempotency.get(idempotency_key)
                if previous is not None:
                    prior_fingerprint, result = previous
                    if prior_fingerprint != fingerprint:
                        raise LifecycleError("conflict")
                    self._record_audit(operation, client_id, "REPLAY", reason=reason)
                    return deepcopy(result)
            result = action()
            if idempotency_key is not None:
                self._idempotency[idempotency_key] = (fingerprint, deepcopy(result))
                self._idempotency.move_to_end(idempotency_key)
                while len(self._idempotency) > _MAX_IDEMPOTENCY_RESULTS:
                    self._idempotency.popitem(last=False)
            self._record_audit(operation, client_id, "OK", reason=reason)
            return result
        except LifecycleError as error:
            self._record_audit(operation, client_id, "ERROR", error.code, reason)
            raise
        except Exception as error:
            mapped = self._adapter_error(error)
            self._record_audit(operation, client_id, "ERROR", mapped.code, reason)
            raise mapped from error
        finally:
            self._mutation_lock.release()

    def _record_audit(
        self,
        operation: LifecycleOperation,
        client_id: str,
        result: Literal["OK", "ERROR", "REPLAY"],
        error_code: LifecycleErrorCode | None = None,
        reason: Literal["operator_requested"] | None = None,
    ) -> None:
        event: AuditEvent = {
            "timestamp": dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat(),
            "operation": operation,
            "client_id": client_id if isinstance(client_id, str) and _CLIENT_ID_RE.fullmatch(client_id) else "",
            "result": result,
        }
        if error_code:
            event["error_code"] = error_code
        if reason == "operator_requested":
            event["reason"] = reason
        with self._audit_lock:
            self._audit.append(event)
            del self._audit[:-_MAX_AUDIT_EVENTS]

    @staticmethod
    def _adapter_error(error: Exception, *, operation: str = "") -> LifecycleError:
        if isinstance(error, TimeoutError):
            return LifecycleError("awg_timeout")
        if operation == "configuration":
            return LifecycleError("configuration_failed")
        return LifecycleError("awg_command_failed")

    @staticmethod
    def _safe_configuration_preview(value: object, client_id: str) -> ConfigurationPreview:
        if not isinstance(value, dict):
            raise LifecycleError("internal_error")
        preview_id = value.get("previewId")
        client_name = value.get("clientName")
        expiration = value.get("expiration")
        qr_payload = value.get("qrPayload")
        config_text = value.get("configText")
        if (
            type(value.get("schema_version")) is not int
            or value["schema_version"] != 1
            or not isinstance(preview_id, str)
            or not _CONFIG_PREVIEW_ID_RE.fullmatch(preview_id)
            or value.get("clientId") != client_id
            or not isinstance(client_name, str)
            or not isinstance(expiration, str)
            or not isinstance(qr_payload, str)
            or len(qr_payload) > 320
            or not isinstance(config_text, str)
            or len(config_text) > 2400
            or value.get("status") != "MOCK_PREVIEW"
        ):
            raise LifecycleError("internal_error")
        try:
            LifecycleService._validate_name(client_name)
            LifecycleService._validate_expiration(expiration)
        except LifecycleError as error:
            raise LifecycleError("internal_error") from error
        safe_qr = f"AWG-CITA-MOCK-QR|client={client_id}|name={quote(client_name, safe='')}|status=MOCK_PREVIEW"
        safe_config = "\n".join(
            (
                "# MOCK CONFIGURATION",
                "# UI READY / BACKEND STUB",
                "[Client]",
                f"Name = {client_name}",
                f"Record = {client_id}",
                f"Expiration = {expiration or '[NONE]'}",
                "Address = [NOT_GENERATED]",
                "KeyMaterial = [NOT_GENERATED]",
                "Transport = [MOCK_ONLY]",
            )
        )
        if qr_payload != safe_qr or config_text != safe_config:
            raise LifecycleError("internal_error")
        return {
            "schema_version": 1,
            "previewId": preview_id,
            "clientId": client_id,
            "clientName": client_name,
            "expiration": expiration,
            "status": "MOCK_PREVIEW",
            "qrPayload": safe_qr,
            "configText": safe_config,
        }

    @staticmethod
    def _validate_client_id(client_id: object) -> None:
        if not isinstance(client_id, str) or not _CLIENT_ID_RE.fullmatch(client_id):
            raise LifecycleError("invalid_request")

    @staticmethod
    def _validate_name(value: object) -> None:
        if not isinstance(value, str) or not 2 <= len(value) <= 48 or value != value.strip():
            raise LifecycleError("invalid_request")
        if unicodedata.category(value[0])[0] not in {"L", "N"}:
            raise LifecycleError("invalid_request")
        if any(unicodedata.category(char)[0] not in {"L", "N"} and char not in " ._-" for char in value):
            raise LifecycleError("invalid_request")

    @staticmethod
    def _validate_notes(value: object) -> None:
        if not isinstance(value, str) or len(value) > 240:
            raise LifecycleError("invalid_request")
        if any(unicodedata.category(char) == "Cc" and char != "\n" for char in value):
            raise LifecycleError("invalid_request")

    @staticmethod
    def _validate_tags(value: object) -> None:
        if not isinstance(value, list) or len(value) > 5:
            raise LifecycleError("invalid_request")
        if any(not isinstance(tag, str) or not _TAG_RE.fullmatch(tag) for tag in value):
            raise LifecycleError("invalid_request")

    @staticmethod
    def _validate_expiration(value: object) -> None:
        if value == "":
            return
        if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
            raise LifecycleError("invalid_request")
        try:
            date = dt.date.fromisoformat(value)
        except ValueError as error:
            raise LifecycleError("invalid_request") from error
        if not dt.date(2020, 1, 1) <= date <= dt.date(2100, 12, 31):
            raise LifecycleError("invalid_request")

    @staticmethod
    def _safe_client(client: dict[str, Any], *, expected_id: str | None = None) -> ClientRecord:
        if not isinstance(client, dict):
            raise LifecycleError("internal_error")
        try:
            if any(field not in client for field in CLIENT_FIELDS):
                raise LifecycleError("internal_error")
            LifecycleService._validate_client_id(client["id"])
            if expected_id is not None and client["id"] != expected_id:
                raise LifecycleError("internal_error")
            LifecycleService._validate_name(client["name"])
            if client["status"] not in _CLIENT_STATUSES:
                raise LifecycleError("internal_error")
            if client["createdAt"] is not None:
                if not isinstance(client["createdAt"], str) or len(client["createdAt"]) > 40:
                    raise LifecycleError("internal_error")
                try:
                    dt.date.fromisoformat(client["createdAt"])
                except ValueError:
                    created_at = dt.datetime.fromisoformat(client["createdAt"].replace("Z", "+00:00"))
                    if created_at.tzinfo is None:
                        raise LifecycleError("internal_error")
            for field in ("lastHandshakeAt", "lastSeenAt"):
                timestamp = client[field]
                if timestamp is not None:
                    if not isinstance(timestamp, str) or len(timestamp) > 40:
                        raise LifecycleError("internal_error")
                    parsed = dt.datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
                    if parsed.tzinfo is None:
                        raise LifecycleError("internal_error")
            LifecycleService._validate_expiration(client["expiration"])
            if any(
                isinstance(client[field], bool)
                or not isinstance(client[field], int)
                or not 0 <= client[field] <= _MAX_COUNTER
                for field in ("rxBytes", "txBytes")
            ):
                raise LifecycleError("internal_error")
            LifecycleService._validate_notes(client["notes"])
            LifecycleService._validate_tags(client["tags"])
            if not isinstance(client["warning"], str) or len(client["warning"]) > 240:
                raise LifecycleError("internal_error")
            if any(unicodedata.category(char) == "Cc" and char != "\n" for char in client["warning"]):
                raise LifecycleError("internal_error")
        except (LifecycleError, TypeError, ValueError, OverflowError) as error:
            raise LifecycleError("internal_error") from error
        return cast(ClientRecord, {field: deepcopy(client[field]) for field in CLIENT_FIELDS})
