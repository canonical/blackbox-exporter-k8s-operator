# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

"""Shared fixtures for blackbox-exporter-k8s unit tests."""

import json

import pytest
from ops import testing

from charm import BlackboxExporterCharm

VERSION_EXEC = testing.Exec(
    command_prefix=["blackbox_exporter", "--version"],
    stdout="blackbox_exporter, version 0.25.0 (branch: HEAD, revision: abc123)",
)


@pytest.fixture
def context():
    """A fresh scenario Context for the BlackboxExporterCharm."""
    return testing.Context(BlackboxExporterCharm, charm_root=".")


@pytest.fixture
def container():
    """The blackbox workload container with a stubbed --version exec."""
    return testing.Container("blackbox", can_connect=True, execs={VERSION_EXEC})


@pytest.fixture
def tracing_relation():
    """A charm-tracing relation pointing at a Tempo coordinator over HTTP."""
    return testing.Relation(
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


@pytest.fixture
def tls_tracing_relation():
    """A charm-tracing relation pointing at a Tempo coordinator over HTTPS."""
    return testing.Relation(
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
