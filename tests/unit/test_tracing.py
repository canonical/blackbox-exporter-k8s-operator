# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

"""State-transition tests for charm tracing integration."""

import json
from contextlib import ExitStack
from unittest.mock import MagicMock, patch

import pytest
from helpers import tautology
from ops import testing

from blackbox import BlackboxExporterApi, WorkloadManager


@pytest.fixture(autouse=True)
def patch_all():
    """Patch external dependencies for every test in this module.

    Stubs out the BlackboxExporter HTTP reload, container config push, lightkube
    k8s client, socket.getfqdn, and the KubernetesComputeResourcesPatch lifecycle
    so the scenario tests can exercise the charm's Python logic in isolation.
    """
    with ExitStack() as stack:
        stack.enter_context(patch.object(BlackboxExporterApi, "reload", tautology))
        stack.enter_context(patch.object(WorkloadManager, "push_config", new=MagicMock()))
        stack.enter_context(patch("lightkube.core.client.GenericSyncClient", new=MagicMock()))
        stack.enter_context(patch("socket.getfqdn", new=lambda *args: "fqdn"))
        stack.enter_context(
            patch.multiple(
                "charm.KubernetesComputeResourcesPatch",
                _namespace="test-namespace",
                _patch=tautology,
                is_ready=tautology,
            )
        )
        yield


def test_charm_starts_without_tracing_relation(context, container):
    """The charm should reach active status without a tracing relation."""
    # GIVEN a charm with no tracing relation
    state_in = testing.State(leader=True, containers=[container])
    # WHEN pebble_ready fires
    state_out = context.run(context.on.pebble_ready(container), state_in)
    # THEN the charm reaches ActiveStatus
    assert state_out.unit_status == testing.ActiveStatus()


@pytest.mark.parametrize(
    "tls",
    [pytest.param(False, id="http"), pytest.param(True, id="https")],
)
def test_charm_starts_with_tracing_relation(
    request, context, container, ca_cert_relation, tls
):
    """The charm should reach active status with a tracing relation, with or without TLS."""
    # GIVEN a charm with a charm-tracing relation (and a receive-ca-cert relation if TLS)
    tracing_relation = request.getfixturevalue(
        "tls_tracing_relation" if tls else "tracing_relation"
    )
    relations = [tracing_relation] + ([ca_cert_relation] if tls else [])
    state_in = testing.State(leader=True, containers=[container], relations=relations)
    # WHEN pebble_ready fires
    state_out = context.run(context.on.pebble_ready(container), state_in)
    # THEN the charm reaches ActiveStatus
    assert state_out.unit_status == testing.ActiveStatus()


def test_tracing_relation_changed(context, container):
    """The charm should handle a tracing relation-changed event without disrupting unit status."""
    # GIVEN an active charm with a charm-tracing relation
    # Unit id 1 (not 0) is intentional: ops-scenario's consistency checker uses a
    # falsy check on event.relation_remote_unit_id, which spuriously warns when 0
    # is passed explicitly. Constructed inline rather than via fixture because the
    # unit-id workaround is local to this test.
    tracing_relation = testing.Relation(
        endpoint="charm-tracing",
        interface="tracing",
        remote_app_name="tempo",
        remote_app_data={
            "receivers": json.dumps(
                [{"protocol": {"name": "otlp_http", "type": ""}, "url": "http://tempo:4318"}]
            ),
        },
        remote_units_data={1: {}},
    )
    state_in = testing.State(
        leader=True,
        containers=[container],
        relations=[tracing_relation],
        unit_status=testing.ActiveStatus(),
    )
    # WHEN the tracing relation data changes
    state_out = context.run(
        context.on.relation_changed(tracing_relation, remote_unit=1), state_in
    )
    # THEN unit status is preserved (charm-tracing events are handled by the
    # framework's ops.tracing.Tracing component, not the charm directly)
    assert state_out.unit_status == testing.ActiveStatus()


def test_tracing_relation_broken(context, container, tracing_relation):
    """The charm should handle the tracing relation being broken without disrupting unit status."""
    # GIVEN an active charm with a charm-tracing relation
    state_in = testing.State(
        leader=True,
        containers=[container],
        relations=[tracing_relation],
        unit_status=testing.ActiveStatus(),
    )
    # WHEN the tracing relation is broken
    state_out = context.run(context.on.relation_broken(tracing_relation), state_in)
    # THEN unit status is preserved (charm-tracing events are handled by the
    # framework's ops.tracing.Tracing component, not the charm directly)
    assert state_out.unit_status == testing.ActiveStatus()


def test_charm_has_tracing_attribute(context, container):
    """The charm should have a tracing attribute after initialization."""
    # GIVEN a charm with no tracing relation
    state_in = testing.State(leader=True, containers=[container])
    # WHEN pebble_ready fires
    with context(context.on.pebble_ready(container), state_in) as mgr:
        mgr.run()
        # THEN the charm exposes a charm_tracing attribute
        assert mgr.charm.charm_tracing is not None
