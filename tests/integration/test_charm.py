#!/usr/bin/env python3
# Copyright 2021 Canonical Ltd.
# See LICENSE file for licensing details.

"""This test module tests rescaling.

1. Deploys multiple units of the charm under test and waits for them to become active
2. Reset and repeat the above until the leader unit is not the zero unit
3. Scales up the application by a few units and waits for them to become active
4. Scales down the application to below the leader unit, to trigger a leadership change event
"""

import asyncio
import logging
from pathlib import Path

import pytest
import requests
import yaml
from helpers import can_blackbox_probe, get_traefik_proxied_endpoints, is_blackbox_up
from pytest_operator.plugin import OpsTest

logger = logging.getLogger(__name__)

METADATA = yaml.safe_load(Path("./metadata.yaml").read_text())
app_name = METADATA["name"]
resources = {
    "blackbox-exporter-image": METADATA["resources"]["blackbox-exporter-image"]["upstream-source"]
}


@pytest.mark.setup
@pytest.mark.abort_on_fail
async def test_build_and_deploy(ops_test: OpsTest, charm_under_test):
    """Build the charm-under-test and deploy it together with related charms.

    Assert on the unit status before any relations/configurations take place.
    """
    # deploy charm from local source folder
    await asyncio.gather(
        ops_test.model.deploy(
            charm_under_test, resources=resources, application_name=app_name, trust=True
        ),
        ops_test.model.deploy("traefik-k8s", "traefik", channel="latest/edge", trust=True),
    )
    await ops_test.model.wait_for_idle(apps=[app_name], status="active", timeout=1000)
    assert ops_test.model.applications[app_name].units[0].workload_status == "active"
    assert await is_blackbox_up(ops_test, app_name)


@pytest.mark.abort_on_fail
async def test_probe_endpoint(ops_test: OpsTest):
    assert await can_blackbox_probe(ops_test, app_name, 0)


@pytest.mark.setup
@pytest.mark.abort_on_fail
async def test_integrate_traefik(ops_test: OpsTest):
    assert ops_test.model is not None
    await ops_test.model.integrate(f"{app_name}:ingress", "traefik")

    await ops_test.model.wait_for_idle(
        apps=[
            app_name,
            "traefik",
        ],
        status="active",
    )


@pytest.mark.abort_on_fail
async def test_traefik(ops_test: OpsTest):
    """Check the ingress integration, by checking if blackbox is reachable through Traefik."""
    assert ops_test.model is not None
    proxied_endpoints = await get_traefik_proxied_endpoints(ops_test)
    assert app_name in proxied_endpoints

    response = requests.get(f"{proxied_endpoints[app_name]['url']}/metrics")
    assert response.status_code == 200
