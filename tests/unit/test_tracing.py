# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

"""State-transition tests for charm tracing integration."""

from unittest.mock import patch

import pytest
from ops import testing

pytestmark = pytest.mark.usefixtures("patch_charm_externalities")


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
    """The charm should configure tracing destination on relation-changed."""
    # GIVEN an active charm with a charm-tracing relation
    state_in = testing.State(
        leader=True,
        containers=[container],
        relations=[charm_tracing_relation],
        unit_status=testing.ActiveStatus(),
    )
    # WHEN the tracing relation data changes
    with patch("ops_tracing.set_destination") as mock_set_dest:
        state_out = context.run(
            context.on.relation_changed(charm_tracing_relation, remote_unit=0), state_in
        )
    # THEN unit status is preserved
    assert state_out.unit_status == testing.ActiveStatus()
    # AND the tracing destination is configured to point at the correct URL
    mock_set_dest.assert_called_with(url="http://tempo:4318/v1/traces", ca=None)


def test_charm_tracing_relation_broken(context, container, charm_tracing_relation):
    """The charm should unconfigure tracing destination when the relation is broken."""
    # GIVEN an active charm with a charm-tracing relation
    state_in = testing.State(
        leader=True,
        containers=[container],
        relations=[charm_tracing_relation],
        unit_status=testing.ActiveStatus(),
    )
    # WHEN the tracing relation is broken
    with patch("ops_tracing.set_destination") as mock_set_dest:
        state_out = context.run(context.on.relation_broken(charm_tracing_relation), state_in)
    # THEN unit status is preserved
    assert state_out.unit_status == testing.ActiveStatus()
    # AND the tracing destination is cleared
    mock_set_dest.assert_called_with(url=None, ca=None)


def test_charm_has_tracing_attribute(context, container):
    """The charm should have a tracing attribute after initialization."""
    # GIVEN a charm with no tracing relation
    state_in = testing.State(leader=True, containers=[container])
    # WHEN pebble_ready fires
    with context(context.on.pebble_ready(container), state_in) as mgr:
        mgr.run()
        # THEN the charm exposes a charm_tracing attribute
        assert mgr.charm.charm_tracing is not None
