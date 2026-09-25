import unittest
import threading
import typing
from typing import get_type_hints

import awg_cita.lifecycle as lifecycle
from awg_cita.lifecycle import FakeAwgLifecycleAdapter, LifecycleError, LifecycleService


class LifecycleServiceTests(unittest.TestCase):
    def test_domain_error_does_not_expose_transport_status(self):
        error = LifecycleError("invalid_request")

        self.assertEqual(error.code, "invalid_request")
        self.assertFalse(hasattr(error, "status"))

    def test_public_domain_results_have_typed_models(self):
        models = {
            name: getattr(lifecycle, name, None)
            for name in ("ClientRecord", "ClientUpdate", "ConfigurationPreview", "DeleteResult", "AuditEvent")
        }
        for name, model in models.items():
            with self.subTest(model=name):
                self.assertIsNotNone(model, f"missing typed domain model {name}")
                self.assertTrue(typing.is_typeddict(model), f"{name} is not a TypedDict")

        self.assertEqual(set(models["ClientRecord"].__annotations__), set(lifecycle.CLIENT_FIELDS))
        self.assertEqual(get_type_hints(LifecycleService.list_clients)["return"], list[models["ClientRecord"]])
        self.assertEqual(get_type_hints(LifecycleService.update_client)["metadata"], models["ClientUpdate"])
        self.assertEqual(get_type_hints(LifecycleService.delete_client)["return"], models["DeleteResult"])
        self.assertEqual(
            get_type_hints(LifecycleService.generate_configuration_preview)["return"],
            models["ConfigurationPreview"],
        )
        self.assertEqual(get_type_hints(LifecycleService.audit_events)["return"], list[models["AuditEvent"]])

    def test_list_clients_returns_only_the_bounded_safe_projection(self):
        service = LifecycleService(FakeAwgLifecycleAdapter())

        clients = service.list_clients()

        self.assertEqual(len(clients), 10)
        self.assertEqual(
            set(clients[0]),
            {
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
            },
        )
        self.assertEqual(clients[0]["id"], "peer-atlas")
        self.assertNotIn("privateKey", clients[0])
        self.assertNotIn("endpoint", clients[0])

    def test_real_peer_without_creation_metadata_can_be_projected_as_unknown(self):
        client = FakeAwgLifecycleAdapter().list_clients()[0]
        client["createdAt"] = None
        service = LifecycleService(FakeAwgLifecycleAdapter([client]))
        self.assertIsNone(service.get_client(client["id"])["createdAt"])

    def test_list_clients_rejects_adapter_result_over_the_record_bound(self):
        template = FakeAwgLifecycleAdapter().list_clients()[0]
        clients = [dict(template, id=f"peer-test-{index}", name=f"Test Peer {index}") for index in range(65)]
        service = LifecycleService(FakeAwgLifecycleAdapter(clients))

        with self.assertRaisesRegex(LifecycleError, "internal_error"):
            service.list_clients()

    def test_update_client_changes_only_contract_metadata_and_returns_canonical_record(self):
        service = LifecycleService(FakeAwgLifecycleAdapter())

        updated = service.update_client(
            "peer-atlas",
            {
                "name": "Atlas Relay Updated",
                "notes": "Reviewed metadata.",
                "tags": ["review", "office"],
                "expiration": "2027-01-31",
            },
        )

        self.assertEqual(updated["name"], "Atlas Relay Updated")
        self.assertEqual(updated["notes"], "Reviewed metadata.")
        self.assertEqual(updated["tags"], ["review", "office"])
        self.assertEqual(updated["expiration"], "2027-01-31")
        self.assertEqual(updated["status"], "ONLINE")
        self.assertEqual(service.get_client("peer-atlas"), updated)

    def test_update_client_rejects_unknown_fields(self):
        service = LifecycleService(FakeAwgLifecycleAdapter())

        with self.assertRaisesRegex(LifecycleError, "invalid_request"):
            service.update_client(
                "peer-atlas",
                {"name": "Atlas Relay", "private_key": "not-accepted"},
            )

    def test_update_client_rejects_invalid_bounds_and_preserves_current_record(self):
        cases = (
            ("name", "N" * 49),
            ("notes", "x" * 241),
            ("tags", ["valid"] * 6),
            ("tags", ["unsafe tag"]),
            ("expiration", "2026-02-30"),
        )
        for field, value in cases:
            with self.subTest(field=field, value_length=len(value) if isinstance(value, str) else len(value)):
                service = LifecycleService(FakeAwgLifecycleAdapter())
                metadata = {"name": "Atlas Updated", "notes": "", "tags": [], "expiration": ""}
                metadata[field] = value
                with self.assertRaisesRegex(LifecycleError, "invalid_request"):
                    service.update_client("peer-atlas", metadata)
                self.assertEqual(service.get_client("peer-atlas")["name"], "Atlas Relay")
                self.assertEqual(service.audit_events()[-1]["error_code"], "invalid_request")

    def test_update_rejects_adapter_result_for_a_different_client(self):
        class WrongIdentityAdapter(FakeAwgLifecycleAdapter):
            def update_client(self, client_id, metadata):
                updated = super().update_client(client_id, metadata)
                updated["id"] = "peer-echo"
                return updated

        service = LifecycleService(WrongIdentityAdapter())

        with self.assertRaisesRegex(LifecycleError, "internal_error"):
            service.update_client(
                "peer-atlas",
                {"name": "Atlas Updated", "notes": "", "tags": [], "expiration": ""},
            )

        self.assertEqual(service.audit_events()[-1]["error_code"], "internal_error")

    def test_read_and_state_mutations_reject_mismatched_adapter_results(self):
        class MismatchedReadAdapter(FakeAwgLifecycleAdapter):
            def get_client(self, _client_id):
                return super().get_client("peer-echo")

        with self.assertRaisesRegex(LifecycleError, "internal_error"):
            LifecycleService(MismatchedReadAdapter()).get_client("peer-atlas")

        class NoOpDisableAdapter(FakeAwgLifecycleAdapter):
            def disable_client(self, client_id, _reason):
                return super().get_client(client_id)

        disable_service = LifecycleService(NoOpDisableAdapter())
        with self.assertRaisesRegex(LifecycleError, "internal_error"):
            disable_service.disable_client("peer-atlas", "disable-noop-01", "operator_requested")
        self.assertEqual(disable_service.audit_events()[-1]["error_code"], "internal_error")

        class WrongStateEnableAdapter(FakeAwgLifecycleAdapter):
            def enable_client(self, client_id):
                client = super().get_client(client_id)
                client["status"] = "DISABLED"
                return client

        enable_service = LifecycleService(WrongStateEnableAdapter())
        with self.assertRaisesRegex(LifecycleError, "internal_error"):
            enable_service.enable_client("peer-atlas", "enable-noop-01")
        self.assertEqual(enable_service.audit_events()[-1]["error_code"], "internal_error")

    def test_enable_disable_are_idempotent_and_emit_bounded_audit_events(self):
        service = LifecycleService(FakeAwgLifecycleAdapter())

        disabled = service.disable_client("peer-atlas", "disable-test-0001", "operator_requested")
        replay = service.disable_client("peer-atlas", "disable-test-0001", "operator_requested")
        enabled = service.enable_client("peer-atlas", "enable-test-0001")

        self.assertEqual(disabled["status"], "DISABLED")
        self.assertEqual(replay, disabled)
        self.assertEqual(enabled["status"], "ONLINE")
        events = service.audit_events()
        self.assertEqual(len(events), 3)
        self.assertEqual([event["operation"] for event in events], ["disableClient", "disableClient", "enableClient"])
        self.assertNotIn("configuration", repr(events).lower())

    def test_delete_is_confirmed_and_repeated_delete_is_idempotent(self):
        service = LifecycleService(FakeAwgLifecycleAdapter())

        first = service.delete_client("peer-boreal", "delete-test-0001", True)
        repeated = service.delete_client("peer-boreal", "delete-test-0002", True)

        self.assertEqual(first, {"schema_version": 1, "id": "peer-boreal", "deleted": True})
        self.assertEqual(repeated, first)
        self.assertNotIn("peer-boreal", [client["id"] for client in service.list_clients()])

    def test_delete_processes_a_reappeared_client_with_the_same_id(self):
        adapter = FakeAwgLifecycleAdapter()
        service = LifecycleService(adapter)
        replacement = next(client for client in adapter.list_clients() if client["id"] == "peer-boreal")

        service.delete_client("peer-boreal", "delete-reappear-0001", True)
        adapter._clients.append(replacement)

        deleted = service.delete_client("peer-boreal", "delete-reappear-0002", True)

        self.assertEqual(deleted, {"schema_version": 1, "id": "peer-boreal", "deleted": True})
        with self.assertRaisesRegex(LifecycleError, "client_not_found"):
            service.get_client("peer-boreal")

    def test_stale_delete_tombstone_does_not_hide_adapter_failure(self):
        adapter = FakeAwgLifecycleAdapter()
        service = LifecycleService(adapter)
        replacement = next(client for client in adapter.list_clients() if client["id"] == "peer-boreal")

        service.delete_client("peer-boreal", "delete-failure-0001", True)
        adapter._clients.append(replacement)
        adapter.fail_next("delete_client", RuntimeError("synthetic adapter failure"))

        with self.assertRaisesRegex(LifecycleError, "awg_command_failed"):
            service.delete_client("peer-boreal", "delete-failure-0002", True)

        self.assertEqual(service.get_client("peer-boreal")["id"], "peer-boreal")
        self.assertEqual(service.audit_events()[-1]["error_code"], "awg_command_failed")

    def test_delete_replays_same_idempotency_key_without_touching_reappeared_record(self):
        adapter = FakeAwgLifecycleAdapter()
        service = LifecycleService(adapter)
        replacement = next(client for client in adapter.list_clients() if client["id"] == "peer-boreal")

        first = service.delete_client("peer-boreal", "delete-replay-0001", True)
        adapter._clients.append(replacement)
        replay = service.delete_client("peer-boreal", "delete-replay-0001", True)

        self.assertEqual(replay, first)
        self.assertEqual(service.get_client("peer-boreal")["id"], "peer-boreal")
        self.assertEqual(service.audit_events()[-1]["result"], "REPLAY")

    def test_delete_does_not_report_success_when_readback_still_finds_target(self):
        class LyingDeleteAdapter(FakeAwgLifecycleAdapter):
            def delete_client(self, _client_id):
                return True

        service = LifecycleService(LyingDeleteAdapter())

        with self.assertRaisesRegex(LifecycleError, "internal_error"):
            service.delete_client("peer-boreal", "delete-readback-01", True)

        self.assertEqual(service.get_client("peer-boreal")["id"], "peer-boreal")
        self.assertEqual(service.audit_events()[-1]["error_code"], "internal_error")

    def test_configuration_preview_requires_acknowledgement_and_never_audits_body(self):
        service = LifecycleService(FakeAwgLifecycleAdapter())

        with self.assertRaisesRegex(LifecycleError, "invalid_request"):
            service.generate_configuration_preview("peer-atlas", False)
        preview = service.generate_configuration_preview("peer-atlas", True)

        self.assertEqual(preview["schema_version"], 1)
        self.assertEqual(preview["status"], "MOCK_PREVIEW")
        self.assertTrue(preview["configText"].startswith("# MOCK CONFIGURATION"))
        self.assertIn("[NOT_GENERATED]", preview["configText"])
        self.assertNotIn(preview["configText"], repr(service.audit_events()))

    def test_backend_client_projection_rejects_invalid_id_and_ignores_unknown_fields(self):
        original = FakeAwgLifecycleAdapter().list_clients()[0]
        original["unexpected"] = "not-rendered"
        service = LifecycleService(FakeAwgLifecycleAdapter([original]))

        client = service.list_clients()[0]
        self.assertNotIn("unexpected", client)

        for field, value in (("id", "../path"), ("status", "UNKNOWN_STATE"), ("rxBytes", True)):
            with self.subTest(field=field):
                malformed = dict(original)
                malformed[field] = value
                invalid_service = LifecycleService(FakeAwgLifecycleAdapter([malformed]))
                with self.assertRaisesRegex(LifecycleError, "internal_error"):
                    invalid_service.list_clients()

    def test_client_projection_rejects_oversized_timestamps_and_unsafe_counters(self):
        original = FakeAwgLifecycleAdapter().list_clients()[0]
        long_timestamp = f"2026-09-22T10:00:00.{'1' * 20}Z"
        cases = (
            ("lastHandshakeAt", long_timestamp),
            ("lastSeenAt", long_timestamp),
            ("createdAt", long_timestamp),
            ("rxBytes", (1 << 53)),
            ("txBytes", (1 << 53)),
        )
        for field, value in cases:
            with self.subTest(field=field):
                malformed = dict(original)
                malformed[field] = value
                service = LifecycleService(FakeAwgLifecycleAdapter([malformed]))
                with self.assertRaisesRegex(LifecycleError, "internal_error"):
                    service.list_clients()

    def test_adapter_timeout_maps_to_safe_typed_error_and_audits_no_exception_text(self):
        adapter = FakeAwgLifecycleAdapter()
        adapter.fail_next("disable_client", TimeoutError("synthetic timeout detail"))
        service = LifecycleService(adapter)

        with self.assertRaisesRegex(LifecycleError, "awg_timeout"):
            service.disable_client("peer-atlas", "disable-test-0002", "operator_requested")
        events = service.audit_events()
        self.assertEqual(events[-1]["error_code"], "awg_timeout")
        self.assertNotIn("synthetic timeout detail", repr(events))

    def test_configuration_adapter_failure_uses_configuration_error_code(self):
        adapter = FakeAwgLifecycleAdapter()
        adapter.fail_next("generate_configuration_preview", RuntimeError("synthetic config failure"))
        service = LifecycleService(adapter)

        with self.assertRaisesRegex(LifecycleError, "configuration_failed"):
            service.generate_configuration_preview("peer-atlas", True)

        self.assertEqual(service.audit_events()[-1]["error_code"], "configuration_failed")
        self.assertNotIn("synthetic config failure", repr(service.audit_events()))

    def test_configuration_preview_rejects_malformed_or_secret_bearing_adapter_output(self):
        class MalformedPreviewAdapter(FakeAwgLifecycleAdapter):
            def generate_configuration_preview(self, _client_id):
                return {
                    "schema_version": 1,
                    "previewId": "config-preview-test",
                    "clientId": "peer-atlas",
                    "clientName": "Atlas Relay",
                    "expiration": "2026-12-31",
                    "status": "MOCK_PREVIEW",
                    "qrPayload": "AWG-CITA-MOCK-QR|synthetic-private-key",
                    "configText": "# MOCK CONFIGURATION\nprivate_key = synthetic-key",
                    "privateKey": "synthetic-key",
                }

        service = LifecycleService(MalformedPreviewAdapter())

        with self.assertRaisesRegex(LifecycleError, "internal_error"):
            service.generate_configuration_preview("peer-atlas", True)

        self.assertEqual(service.audit_events()[-1]["error_code"], "internal_error")
        self.assertNotIn("synthetic-key", repr(service.audit_events()))

    def test_adapter_not_found_invalid_state_and_generic_failure_are_typed(self):
        service = LifecycleService(FakeAwgLifecycleAdapter())
        with self.assertRaisesRegex(LifecycleError, "client_not_found"):
            service.enable_client("peer-missing", "enable-missing-01")
        self.assertEqual(service.audit_events()[-1]["error_code"], "client_not_found")

        adapter = FakeAwgLifecycleAdapter()
        adapter.fail_next("enable_client", LifecycleError("invalid_state"))
        invalid_state_service = LifecycleService(adapter)
        with self.assertRaisesRegex(LifecycleError, "invalid_state"):
            invalid_state_service.enable_client("peer-atlas", "enable-invalid-01")
        self.assertEqual(invalid_state_service.audit_events()[-1]["error_code"], "invalid_state")

        generic_adapter = FakeAwgLifecycleAdapter()
        generic_adapter.fail_next("disable_client", RuntimeError("synthetic generic detail"))
        generic_service = LifecycleService(generic_adapter)
        with self.assertRaisesRegex(LifecycleError, "awg_command_failed"):
            generic_service.disable_client("peer-atlas", "disable-generic-01", "operator_requested")
        self.assertEqual(generic_service.audit_events()[-1]["error_code"], "awg_command_failed")
        self.assertNotIn("synthetic generic detail", repr(generic_service.audit_events()))

    def test_missing_idempotency_key_is_rejected_and_audited(self):
        service = LifecycleService(FakeAwgLifecycleAdapter())

        with self.assertRaisesRegex(LifecycleError, "invalid_request"):
            service.enable_client("peer-atlas", None)

        self.assertEqual(service.audit_events()[-1]["error_code"], "invalid_request")
        self.assertEqual(service.get_client("peer-atlas")["status"], "ONLINE")

    def test_invalid_disable_reason_is_not_written_to_audit(self):
        service = LifecycleService(FakeAwgLifecycleAdapter())
        supplied_reason = "synthetic-secret-detail"

        with self.assertRaisesRegex(LifecycleError, "invalid_request"):
            service.disable_client("peer-atlas", "disable-reason-01", supplied_reason)

        self.assertEqual(service.audit_events()[-1]["error_code"], "invalid_request")
        self.assertNotIn(supplied_reason, repr(service.audit_events()))

    def test_concurrent_mutation_is_rejected_while_another_mutation_is_in_flight(self):
        entered = threading.Event()
        release = threading.Event()

        class BlockingAdapter(FakeAwgLifecycleAdapter):
            def enable_client(self, client_id):
                entered.set()
                release.wait(timeout=3)
                return super().enable_client(client_id)

        service = LifecycleService(BlockingAdapter())
        first_error = []

        def enable():
            try:
                service.enable_client("peer-atlas", "enable-concurrent-01")
            except Exception as error:  # pragma: no cover - assertion reports the captured failure
                first_error.append(error)

        first = threading.Thread(target=enable)
        first.start()
        self.assertTrue(entered.wait(timeout=2))
        try:
            with self.assertRaisesRegex(LifecycleError, "conflict"):
                service.disable_client("peer-atlas", "disable-concurrent-1", "operator_requested")
        finally:
            release.set()
            first.join(timeout=3)

        self.assertFalse(first.is_alive())
        self.assertEqual(first_error, [])
        self.assertIn("conflict", [event.get("error_code") for event in service.audit_events()])

    def test_audit_history_is_bounded(self):
        service = LifecycleService(FakeAwgLifecycleAdapter())

        for index in range(300):
            service.enable_client("peer-atlas", f"enable-audit-{index:04d}")

        events = service.audit_events()
        self.assertEqual(len(events), 256)
        self.assertTrue(all(set(event) <= {"timestamp", "operation", "client_id", "result", "error_code", "reason"} for event in events))


if __name__ == "__main__":
    unittest.main()
