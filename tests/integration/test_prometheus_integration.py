#!/usr/bin/env python3
# Copyright 2021 Canonical Ltd.
# See LICENSE file for licensing details.
import logging
import time
from pathlib import Path

import pytest
import sh
import yaml
from helpers import (
    are_prometheus_targets_up,
    can_blackbox_probe,
    is_blackbox_up,
)
from pytest_operator.plugin import OpsTest

# pyright: reportAttributeAccessIssue = false

logger = logging.getLogger(__name__)

METADATA = yaml.safe_load(Path("./charmcraft.yaml").read_text())
app_name = METADATA["name"]
resources = {
    "blackbox-exporter-image": METADATA["resources"]["blackbox-exporter-image"]["upstream-source"]
}
resources_arg = [
    f"blackbox-exporter-image={resources['blackbox-exporter-image']}",
]
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


@pytest.mark.setup
@pytest.mark.abort_on_fail
async def test_build_and_deploy(ops_test: OpsTest, charm_under_test):
    """Build the charm-under-test and deploy it together with related charms.

    Assert on the unit status before any relations/configurations take place.
    """
    assert ops_test.model
    # deploy charm from local source folder
    sh.juju.deploy(
        charm_under_test,
        app_name,
        model=ops_test.model.name,
        resource=resources_arg,
        trust=True,
    )
    sh.juju.deploy(
        "prometheus-k8s",
        "prometheus",
        model=ops_test.model.name,
        channel="latest/edge",
        trust=True,
    )
    await ops_test.model.wait_for_idle(apps=[app_name], status="active", timeout=1000)
    await ops_test.model.applications[app_name].set_config(
        {"probes_file": yaml.dump(blackbox_probes)}
    )
    assert ops_test.model.applications[app_name].units[0].workload_status == "active"
    assert await is_blackbox_up(ops_test, app_name)


@pytest.mark.abort_on_fail
async def test_probe_endpoint(ops_test: OpsTest):
    assert await can_blackbox_probe(ops_test, app_name, 0)


@pytest.mark.abort_on_fail
async def test_integrate_prometheus(ops_test: OpsTest):
    assert ops_test.model
    sh.juju.relate(app_name, "prometheus", model=ops_test.model.name)
    await ops_test.model.wait_for_idle(
        apps=[app_name, "prometheus"], status="active", timeout=1000
    )
    time.sleep(60)  # wait for the 1m scrape time
    assert await are_prometheus_targets_up(ops_test, "prometheus")
