# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

"""State-transition tests for charm tracing integration."""

import json
from unittest.mock import patch

from helpers import tautology
from ops import testing

from blackbox import BlackboxExporterApi, WorkloadManager
from charm import BlackboxExporterCharm

k8s_resource_multipatch = patch.multiple(
    "charm.KubernetesComputeResourcesPatch",
    _namespace="test-namespace",
    _patch=tautology,
    is_ready=tautology,
)

VERSION_EXEC = testing.Exec(
    command_prefix=["blackbox_exporter", "--version"],
    stdout="blackbox_exporter, version 0.25.0 (branch: HEAD, revision: abc123)",
)


@patch.object(BlackboxExporterApi, "reload", tautology)
@patch.object(WorkloadManager, "push_config")
@patch("lightkube.core.client.GenericSyncClient")
@patch("socket.getfqdn", new=lambda *args: "fqdn")
@k8s_resource_multipatch
def test_charm_starts_without_tracing_relation(*_):
    """The charm should reach active status without a tracing relation."""
    ctx = testing.Context(BlackboxExporterCharm, charm_root=".")
    container = testing.Container("blackbox", can_connect=True, execs={VERSION_EXEC})
    state = testing.State(leader=True, containers=[container])
    out = ctx.run(ctx.on.pebble_ready(container), state)
    assert out.unit_status == testing.ActiveStatus()


@patch.object(BlackboxExporterApi, "reload", tautology)
@patch.object(WorkloadManager, "push_config")
@patch("lightkube.core.client.GenericSyncClient")
@patch("socket.getfqdn", new=lambda *args: "fqdn")
@k8s_resource_multipatch
def test_charm_starts_with_tracing_relation(*_):
    """The charm should handle a tracing relation being present."""
    ctx = testing.Context(BlackboxExporterCharm, charm_root=".")
    container = testing.Container("blackbox", can_connect=True, execs={VERSION_EXEC})
    tracing_relation = testing.Relation(
        endpoint="charm-tracing",
        interface="tracing",
        remote_app_name="tempo",
        remote_app_data={
            "receivers": json.dumps(
                [{"protocol": {"name": "otlp_http", "type": ""}, "url": "http://tempo:4318"}]
            ),
        },
        remote_units_data={0: {}},
    )
    state = testing.State(leader=True, containers=[container], relations=[tracing_relation])
    out = ctx.run(ctx.on.pebble_ready(container), state)
    assert out.unit_status == testing.ActiveStatus()


@patch.object(BlackboxExporterApi, "reload", tautology)
@patch.object(WorkloadManager, "push_config")
@patch("lightkube.core.client.GenericSyncClient")
@patch("socket.getfqdn", new=lambda *args: "fqdn")
@k8s_resource_multipatch
def test_tracing_relation_changed(*_):
    """The charm should handle a tracing relation-changed event without disrupting unit status."""
    ctx = testing.Context(BlackboxExporterCharm, charm_root=".")
    container = testing.Container("blackbox", can_connect=True, execs={VERSION_EXEC})
    # Unit id 1 (not 0) is intentional: ops-scenario's consistency checker uses a
    # falsy check on event.relation_remote_unit_id, which spuriously warns when 0
    # is passed explicitly.
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
    state = testing.State(
        leader=True,
        containers=[container],
        relations=[tracing_relation],
        unit_status=testing.ActiveStatus(),
    )
    out = ctx.run(ctx.on.relation_changed(tracing_relation, remote_unit=1), state)
    # charm-tracing relation events are observed by the framework's ops.tracing.Tracing
    # component, not by the charm directly, so the charm's unit status is preserved.
    assert out.unit_status == testing.ActiveStatus()


@patch.object(BlackboxExporterApi, "reload", tautology)
@patch.object(WorkloadManager, "push_config")
@patch("lightkube.core.client.GenericSyncClient")
@patch("socket.getfqdn", new=lambda *args: "fqdn")
@k8s_resource_multipatch
def test_tracing_relation_broken(*_):
    """The charm should handle the tracing relation being broken without disrupting unit status."""
    ctx = testing.Context(BlackboxExporterCharm, charm_root=".")
    container = testing.Container("blackbox", can_connect=True, execs={VERSION_EXEC})
    tracing_relation = testing.Relation(
        endpoint="charm-tracing",
        interface="tracing",
        remote_app_name="tempo",
        remote_units_data={0: {}},
    )
    state = testing.State(
        leader=True,
        containers=[container],
        relations=[tracing_relation],
        unit_status=testing.ActiveStatus(),
    )
    out = ctx.run(ctx.on.relation_broken(tracing_relation), state)
    # charm-tracing relation events are observed by the framework's ops.tracing.Tracing
    # component, not by the charm directly, so the charm's unit status is preserved.
    assert out.unit_status == testing.ActiveStatus()


@patch.object(BlackboxExporterApi, "reload", tautology)
@patch.object(WorkloadManager, "push_config")
@patch("lightkube.core.client.GenericSyncClient")
@patch("socket.getfqdn", new=lambda *args: "fqdn")
@k8s_resource_multipatch
def test_tracing_with_ca_cert_relation(*_):
    """The charm should handle both tracing and CA cert relations."""
    ctx = testing.Context(BlackboxExporterCharm, charm_root=".")
    container = testing.Container("blackbox", can_connect=True, execs={VERSION_EXEC})
    tracing_relation = testing.Relation(
        endpoint="charm-tracing",
        interface="tracing",
        remote_app_name="tempo",
        remote_app_data={
            "receivers": json.dumps(
                [{"protocol": {"name": "otlp_http", "type": ""}, "url": "https://tempo:4318"}]
            ),
        },
        remote_units_data={0: {}},
    )
    ca_cert_relation = testing.Relation(
        endpoint="receive-ca-cert",
        interface="certificate_transfer",
        remote_app_name="self-signed-certificates",
        remote_app_data={
            "ca": "-----BEGIN CERTIFICATE-----\nMIIBfake\n-----END CERTIFICATE-----",
        },
        remote_units_data={0: {}},
    )
    state = testing.State(
        leader=True, containers=[container], relations=[tracing_relation, ca_cert_relation]
    )
    out = ctx.run(ctx.on.pebble_ready(container), state)
    assert out.unit_status == testing.ActiveStatus()


@patch.object(BlackboxExporterApi, "reload", tautology)
@patch.object(WorkloadManager, "push_config")
@patch("lightkube.core.client.GenericSyncClient")
@patch("socket.getfqdn", new=lambda *args: "fqdn")
@k8s_resource_multipatch
def test_charm_has_tracing_attribute(*_):
    """The charm should have a tracing attribute after initialization."""
    ctx = testing.Context(BlackboxExporterCharm, charm_root=".")
    container = testing.Container("blackbox", can_connect=True, execs={VERSION_EXEC})
    state = testing.State(leader=True, containers=[container])

    with ctx(ctx.on.pebble_ready(container), state) as mgr:
        assert hasattr(mgr.charm, "charm_tracing")
        assert mgr.charm.charm_tracing is not None
