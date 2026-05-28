# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

"""End-to-end integration test for the blackbox-exporter-k8s charm-tracing relation.

Deploys blackbox alongside a monolithic Tempo cluster, integrates `charm-tracing`,
shortens `update-status-hook-interval` to force charm hooks to fire, and asserts that
spans for the blackbox charm actually reach Tempo.

Pattern adapted from canonical/parca-k8s-operator's test_tracing_integrations.py.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest
import yaml
from jubilant import Juju
from tempo_helpers import (
    S3_APP,
    TEMPO,
    TEMPO_WORKER,
    deploy_monolithic_tempo_cluster,
    get_app_ip_address,
    get_ingested_traces_tag_values,
)
from tenacity import retry, stop_after_attempt, wait_fixed

METADATA = yaml.safe_load(Path("./charmcraft.yaml").read_text())
APP_NAME = METADATA["name"]
RESOURCES = {
    "blackbox-exporter-image": METADATA["resources"]["blackbox-exporter-image"]["upstream-source"]
}


@pytest.fixture(scope="module")
def charm_under_test() -> str:
    """Path to a pre-built local charm, or fail if CHARM_PATH not set.

    The integration runner is expected to set CHARM_PATH (built via `charmcraft pack`)
    so this test doesn't pay the build cost itself.
    """
    charm = os.getenv("CHARM_PATH")
    assert charm, "CHARM_PATH must point to a packed .charm file"
    assert Path(charm).exists(), f"CHARM_PATH={charm!r} does not exist"
    return charm


@pytest.mark.setup
@pytest.mark.abort_on_fail
def test_deploy_blackbox_and_tempo(juju: Juju, charm_under_test: str) -> None:
    """Deploy blackbox + monolithic Tempo cluster, then integrate charm-tracing."""
    # GIVEN a monolithic Tempo stack and the blackbox charm
    juju.deploy(
        charm_under_test,
        APP_NAME,
        resources=RESOURCES,
        trust=True,
    )
    deploy_monolithic_tempo_cluster(juju)

    # WHEN the charm-tracing relation is established
    juju.integrate(f"{APP_NAME}:charm-tracing", f"{TEMPO}:tracing")

    # THEN all apps settle into active
    juju.wait(
        lambda status: all(
            status.apps[app].is_active for app in [APP_NAME, TEMPO, TEMPO_WORKER, S3_APP]
        ),
        timeout=1000,
        successes=3,
        delay=10,
    )


@retry(stop=stop_after_attempt(3), wait=wait_fixed(10))
def test_verify_charm_tracing(juju: Juju) -> None:
    """Assert that the blackbox charm's spans actually reach Tempo."""
    # GIVEN update-status fires every 5s so a charm-tracing span is emitted quickly
    juju.cli("model-config", "update-status-hook-interval=5s")

    try:
        # WHEN we query Tempo for the set of service.name values it has ingested
        services = get_ingested_traces_tag_values(
            get_app_ip_address(juju, TEMPO), tls=False, tag="service.name"
        )
        # THEN our charm appears among them
        assert APP_NAME in services, (
            f"expected {APP_NAME!r} in ingested services, got: {sorted(services)}"
        )
    finally:
        # Reset the update-status interval to a sane default for subsequent tests.
        juju.cli("model-config", "update-status-hook-interval=5m")
