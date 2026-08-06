#!/usr/bin/env python3
# Copyright 2021 Canonical Ltd.
# See LICENSE file for licensing details.
import logging
import time
from pathlib import Path

import jubilant
import pytest
import yaml
from helpers import (
    all_prometheus_targets_up,
    can_blackbox_probe,
    is_blackbox_up,
)

logger = logging.getLogger(__name__)

METADATA = yaml.safe_load(Path("./charmcraft.yaml").read_text())
app_name = METADATA["name"]
resources = {
    "blackbox-exporter-image": METADATA["resources"]["blackbox-exporter-image"]["upstream-source"]
}
blackbox_probes = {
    "scrape_configs": [
        {
            "job_name": "prometheus-website",
            "metrics_path": "/probe",
            "params": {"module": ["http_2xx"]},
            "static_configs": [{"targets": ["http://prometheus.io", "https://prometheus.io"]}],
        }
    ]
}


@pytest.mark.juju_setup
@pytest.mark.abort_on_fail
def test_build_and_deploy(juju: jubilant.Juju, charm_under_test: str):
    """Build the charm-under-test and deploy it together with related charms.

    Assert on the unit status before any relations/configurations take place.
    """
    # deploy charm from local source folder
    juju.deploy(charm_under_test, app_name, resources=resources, trust=True)
    juju.deploy(
        "prometheus-k8s",
        "prometheus",
        channel="dev/edge",
        trust=True,
    )
    juju.wait(lambda status: jubilant.all_active(status, app_name), timeout=1000)
    juju.config(app_name, {"probes_file": yaml.dump(blackbox_probes)})
    assert juju.status().apps[app_name].units[f"{app_name}/0"].workload_status.current == "active"
    assert is_blackbox_up(juju, app_name)


@pytest.mark.abort_on_fail
def test_probe_endpoint(juju: jubilant.Juju):
    assert can_blackbox_probe(juju, app_name, 0)


@pytest.mark.abort_on_fail
def test_integrate_prometheus(juju: jubilant.Juju):
    juju.integrate(app_name, "prometheus")
    juju.wait(
        lambda status: jubilant.all_active(status, app_name, "prometheus"),
        timeout=1000,
    )
    time.sleep(60 * 2)  # ensure the 1m scrape interval elapses
    assert all_prometheus_targets_up(juju, "prometheus")
