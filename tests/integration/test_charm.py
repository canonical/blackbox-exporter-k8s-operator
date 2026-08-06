#!/usr/bin/env python3
# Copyright 2021 Canonical Ltd.
# See LICENSE file for licensing details.

"""This test module tests rescaling.

1. Deploys multiple units of the charm under test and waits for them to become active
2. Reset and repeat the above until the leader unit is not the zero unit
3. Scales up the application by a few units and waits for them to become active
4. Scales down the application to below the leader unit, to trigger a leadership change event
"""

import logging
from pathlib import Path

import jubilant
import pytest
import requests
import yaml
from helpers import can_blackbox_probe, get_traefik_proxied_endpoints, is_blackbox_up

logger = logging.getLogger(__name__)

METADATA = yaml.safe_load(Path("./charmcraft.yaml").read_text())
app_name = METADATA["name"]
resources = {
    "blackbox-exporter-image": METADATA["resources"]["blackbox-exporter-image"]["upstream-source"]
}


@pytest.mark.juju_setup
@pytest.mark.abort_on_fail
def test_build_and_deploy(juju: jubilant.Juju, charm_under_test: str):
    """Build the charm-under-test and deploy it together with related charms.

    Assert on the unit status before any relations/configurations take place.
    """
    # deploy charm from local source folder
    juju.deploy(charm_under_test, app=app_name, resources=resources, trust=True)
    juju.deploy("traefik-k8s", "traefik", channel="latest/candidate", trust=True)
    juju.wait(jubilant.all_active, timeout=1000)
    assert juju.status().apps[app_name].units[f"{app_name}/0"].workload_status.current == "active"
    assert is_blackbox_up(juju, app_name)


@pytest.mark.abort_on_fail
def test_probe_endpoint(juju: jubilant.Juju):
    assert can_blackbox_probe(juju, app_name, 0)


@pytest.mark.juju_setup
@pytest.mark.abort_on_fail
def test_integrate_traefik(juju: jubilant.Juju):
    juju.integrate(f"{app_name}:ingress", "traefik")
    juju.wait(
        lambda status: jubilant.all_active(status, app_name, "traefik"),
        delay=15,
        successes=3,
    )


@pytest.mark.abort_on_fail
def test_traefik(juju: jubilant.Juju):
    """Check the ingress integration, by checking if blackbox is reachable through Traefik."""
    proxied_endpoints = get_traefik_proxied_endpoints(juju)
    assert app_name in proxied_endpoints

    response = requests.get(f"{proxied_endpoints[app_name]['url']}/metrics")
    assert response.status_code == 200
