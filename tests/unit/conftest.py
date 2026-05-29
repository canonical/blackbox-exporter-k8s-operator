# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

"""Shared fixtures for blackbox-exporter-k8s unit tests."""

import json
from contextlib import ExitStack
from unittest.mock import MagicMock, patch

import pytest
from helpers import tautology
from ops import testing

from blackbox import BlackboxExporterApi, WorkloadManager
from charm import BlackboxExporterCharm

VERSION_EXEC = testing.Exec(
    command_prefix=["blackbox_exporter", "--version"],
    stdout="blackbox_exporter, version 0.25.0 (branch: HEAD, revision: abc123)",
)


@pytest.fixture
def patch_charm_externalities():
    """Patch external dependencies so scenario tests exercise Python logic in isolation.

    Stubs out the BlackboxExporter HTTP reload, container config push, lightkube
    k8s client, socket.getfqdn, and the KubernetesComputeResourcesPatch lifecycle.
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


@pytest.fixture
def context():
    """A fresh scenario Context for the BlackboxExporterCharm."""
    return testing.Context(BlackboxExporterCharm, charm_root=".")


@pytest.fixture
def container():
    """The blackbox workload container with a stubbed --version exec."""
    return testing.Container("blackbox", can_connect=True, execs={VERSION_EXEC})


@pytest.fixture
def charm_tracing_relation():
    """A charm-tracing relation pointing at a Tempo coordinator over HTTP.

    Named `charm_tracing_relation` (not `tracing_relation`) to distinguish from a
    possible workload-tracing relation; charm vs workload tracing is the fleet split.
    """
    return testing.Relation(
        endpoint="charm-tracing",
        interface="tracing",
        remote_app_name="tempo",
        remote_app_data={
            "receivers": json.dumps(
                [{"protocol": {"name": "otlp_http", "type": "http"}, "url": "http://tempo:4318"}]
            ),
        },
        remote_units_data={0: {}},
    )


@pytest.fixture
def tls_charm_tracing_relation():
    """A charm-tracing relation pointing at a Tempo coordinator over HTTPS."""
    return testing.Relation(
        endpoint="charm-tracing",
        interface="tracing",
        remote_app_name="tempo",
        remote_app_data={
            "receivers": json.dumps(
                [
                    {
                        "protocol": {"name": "otlp_http", "type": "http"},
                        "url": "https://tempo:4318",
                    }
                ]
            ),
        },
        remote_units_data={0: {}},
    )


@pytest.fixture
def ca_cert_relation():
    """A receive-ca-cert relation supplying a CA for TLS validation."""
    return testing.Relation(
        endpoint="receive-ca-cert",
        interface="certificate_transfer",
        remote_app_name="self-signed-certificates",
        remote_app_data={
            "ca": "-----BEGIN CERTIFICATE-----\nMIIBfake\n-----END CERTIFICATE-----",
        },
        remote_units_data={0: {}},
    )
