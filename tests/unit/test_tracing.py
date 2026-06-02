# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

"""State-transition tests for charm tracing integration."""

import json

import pytest
from ops import testing

pytestmark = pytest.mark.usefixtures("patch_all")


@pytest.mark.parametrize("tls", (True, False))
def test_charm_starts_with_charm_tracing_relation(
    context, container, charm_tracing_relation, tls_charm_tracing_relation, ca_cert_relation, tls
):
    """The charm should reach active status with a tracing relation, with or without TLS."""
    # GIVEN a charm with a charm-tracing relation (and a receive-ca-cert relation if TLS)
    tracing_relation = tls_charm_tracing_relation if tls else charm_tracing_relation
    relations = [tracing_relation] + ([ca_cert_relation] if tls else [])
    state_in = testing.State(leader=True, containers=[container], relations=relations)
    # WHEN pebble_ready fires
    state_out = context.run(context.on.pebble_ready(container), state_in)
    # THEN the charm reaches ActiveStatus
    assert state_out.unit_status == testing.ActiveStatus()


def test_charm_tracing_relation_changed(context, container, charm_tracing_relation):
    """On relation-changed, the charm advertises the protocols it wants in its own databag."""
    # GIVEN a leader charm related over charm-tracing
    state_in = testing.State(
        leader=True,
        containers=[container],
        relations=[charm_tracing_relation],
    )
    # WHEN the tracing relation data changes
    state_out = context.run(
        context.on.relation_changed(charm_tracing_relation, remote_unit=0), state_in
    )
    # THEN the charm has published the protocols it wants to receive traces on
    local_app_data = state_out.get_relation(charm_tracing_relation.id).local_app_data
    assert json.loads(local_app_data["receivers"]) == ["otlp_http"]


def test_charm_tracing_relation_broken(context, container, charm_tracing_relation):
    """On relation-broken, the charm withdraws its tracing request from the databag."""
    # GIVEN a leader charm related over charm-tracing
    state_in = testing.State(
        leader=True,
        containers=[container],
        relations=[charm_tracing_relation],
    )
    # WHEN the tracing relation is broken
    state_out = context.run(context.on.relation_broken(charm_tracing_relation), state_in)
    # THEN the charm no longer advertises any tracing protocols
    assert "receivers" not in state_out.get_relation(charm_tracing_relation.id).local_app_data
