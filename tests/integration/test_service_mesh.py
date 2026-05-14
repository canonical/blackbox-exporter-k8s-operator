#!/usr/bin/env python3
# Copyright 2025 Canonical Ltd.
# See LICENSE file for licensing details.

"""Integration tests for service mesh support."""

import json
import logging
import time
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Set

import pytest
import yaml
from helpers import can_blackbox_probe, get_unit_address
from lightkube import Client
from lightkube.generic_resource import create_namespaced_resource
from pytest_operator.plugin import OpsTest

logger = logging.getLogger(__name__)

METADATA = yaml.safe_load(Path("./charmcraft.yaml").read_text())
APP_NAME = METADATA["name"]
RESOURCES = {
    "blackbox-exporter-image": METADATA["resources"]["blackbox-exporter-image"]["upstream-source"]
}

# Probe configuration to test blackbox probing functionality
BLACKBOX_PROBES = {
    "scrape_configs": [
        {
            "job_name": "prometheus-website",
            "metrics_path": "/probe",
            "params": {"module": ["http_2xx"]},
            "static_configs": [{"targets": ["http://prometheus.io", "https://prometheus.io"]}],
        }
    ]
}


def get_istio_ingress_ip(ops_test: OpsTest, app_name: str = "istio-ingress") -> str:
    """Get the istio-ingress public IP address from Kubernetes."""
    gateway_resource = create_namespaced_resource(
        group="gateway.networking.k8s.io",
        version="v1",
        kind="Gateway",
        plural="gateways",
    )
    client = Client()
    assert ops_test.model_name is not None
    gateway = client.get(gateway_resource, app_name, namespace=ops_test.model_name)
    if gateway.status and gateway.status.get("addresses"):  # type: ignore
        return gateway.status["addresses"][0]["value"]  # type: ignore
    raise ValueError(f"No ingress address found for {app_name}")


async def service_mesh(
    enable: bool,
    ops_test: OpsTest,
    beacon_app_name: str,
    apps_to_be_related_with_beacon: List[str],
):
    """Enable or disable the service-mesh in the model.

    This puts the entire model, that the beacon app is part of, on mesh.
    This integrates the apps_to_be_related_with_beacon with the beacon app
    via the ``service-mesh`` relation.
    """
    assert ops_test.model is not None
    await ops_test.model.applications[beacon_app_name].set_config(
        {"model-on-mesh": str(enable).lower()}
    )
    await ops_test.model.wait_for_idle(status="active", timeout=1000)
    if enable:
        for app in apps_to_be_related_with_beacon:
            await ops_test.model.integrate(
                f"{beacon_app_name}:service-mesh", f"{app}:service-mesh"
            )
    else:
        for app in apps_to_be_related_with_beacon:
            await ops_test.model.applications[beacon_app_name].remove_relation(
                "service-mesh", f"{app}:service-mesh"
            )
    await ops_test.model.wait_for_idle(status="active", timeout=1000)


async def get_prometheus_targets(
    ops_test: OpsTest,
    prometheus_app: str = "prometheus",
    unit_num: int = 0,
) -> Dict[str, Any]:
    """Get Prometheus scrape targets."""
    address = await get_unit_address(ops_test, prometheus_app, unit_num)
    url = f"http://{address}:9090/api/v1/targets"
    response = urllib.request.urlopen(url, data=None, timeout=10.0)
    if response.code != 200:
        raise RuntimeError(f"Failed to get Prometheus targets: {response.code}")
    response_data = response.read().decode("utf-8")
    response_json = json.loads(response_data)
    if response_json.get("status") != "success":
        raise RuntimeError(f"Prometheus API returned error: {response_json}")
    return response_json.get("data", {})


def get_blackbox_targets_from_prometheus(
    targets_data: Dict[str, Any],
) -> List[Dict[str, Any]]:
    """Filter Prometheus targets to get only blackbox-exporter targets."""
    active_targets = targets_data.get("activeTargets", [])
    return [
        target
        for target in active_targets
        if target.get("discoveredLabels", {}).get("juju_charm") == "blackbox-exporter-k8s"
    ]


def get_blackbox_unit_addresses_from_targets(
    blackbox_targets: List[Dict[str, Any]],
) -> Set[str]:
    """Extract the unit addresses from blackbox targets."""
    addresses = set()
    for target in blackbox_targets:
        # The scrapePool contains the target address like "blackbox-exporter-k8s-0.blackbox..."
        # or we can get it from labels
        labels = target.get("labels", {})
        instance = labels.get("instance", "")
        if instance:
            # instance is typically "ip:port", extract just the ip/hostname
            address = instance.split(":")[0]
            addresses.add(address)
    return addresses


async def get_ingress_metrics(ops_test: OpsTest) -> str:
    """Get metrics through the istio-ingress endpoint."""
    ingress_address = get_istio_ingress_ip(ops_test, "istio-ingress")
    proxied_endpoint = f"http://{ingress_address}/{ops_test.model_name}-{APP_NAME}/metrics"
    response = urllib.request.urlopen(proxied_endpoint, data=None, timeout=10.0)
    if response.code != 200:
        raise RuntimeError(f"Failed to get metrics through ingress: {response.code}")
    return response.read().decode("utf-8")


@pytest.mark.setup
@pytest.mark.abort_on_fail
async def test_build_and_deploy(ops_test: OpsTest, charm_under_test):
    """Build and deploy the charm together with Istio service mesh components."""
    assert ops_test.model is not None

    await ops_test.model.deploy(
        charm_under_test,
        application_name=APP_NAME,
        resources=RESOURCES,
        trust=True,
    )
    await ops_test.model.deploy(
        "prometheus-k8s",
        application_name="prometheus",
        channel="1/edge",
        trust=True,
    )
    await ops_test.model.deploy(
        "istio-k8s",
        application_name="istio",
        channel="2/edge",
        trust=True,
    )
    await ops_test.model.deploy(
        "istio-beacon-k8s",
        application_name="istio-beacon",
        channel="2/edge",
        trust=True,
    )
    await ops_test.model.deploy(
        "istio-ingress-k8s",
        application_name="istio-ingress",
        channel="2/edge",
        trust=True,
    )

    await ops_test.model.wait_for_idle(
        apps=[
            APP_NAME,
            "prometheus",
            "istio",
            "istio-beacon",
            "istio-ingress",
        ],
        status="active",
        timeout=1000,
    )

    # Configure blackbox probes
    await ops_test.model.applications[APP_NAME].set_config(
        {"probes_file": yaml.dump(BLACKBOX_PROBES)}
    )
    await ops_test.model.wait_for_idle(apps=[APP_NAME], status="active", timeout=300)


@pytest.mark.setup
@pytest.mark.abort_on_fail
async def test_integrate(ops_test: OpsTest):
    """Integrate apps before enabling service mesh."""
    assert ops_test.model is not None

    await ops_test.model.integrate(f"{APP_NAME}:self-metrics-endpoint", "prometheus")
    await ops_test.model.integrate(f"{APP_NAME}:ingress", "istio-ingress:ingress")

    await ops_test.model.wait_for_idle(
        apps=[
            APP_NAME,
            "prometheus",
            "istio-ingress",
        ],
        status="active",
        timeout=1000,
    )


@pytest.mark.setup
@pytest.mark.abort_on_fail
async def test_scale_up(ops_test: OpsTest):
    """Scale up the blackbox-exporter charm to multiple units."""
    assert ops_test.model is not None

    app = ops_test.model.applications[APP_NAME]
    await app.scale(3)

    await ops_test.model.wait_for_idle(
        apps=[APP_NAME],
        status="active",
        timeout=1000,
        wait_for_exact_units=3,
    )


@pytest.mark.setup
@pytest.mark.abort_on_fail
async def test_enable_service_mesh(ops_test: OpsTest):
    """Enable service mesh.

    This is not done in the previous step for two reasons:
    1. Not all apps are mesh-enabled yet, so we need to let apps establish comms first.
    2. The `service_mesh` helper provides a way to parametrize and run existing tests
       with service mesh enabled.
    """
    await service_mesh(
        enable=True,
        ops_test=ops_test,
        beacon_app_name="istio-beacon",
        apps_to_be_related_with_beacon=[APP_NAME],
    )


async def test_ingress(ops_test: OpsTest):
    """Check the ingress integration by checking if blackbox is reachable through istio-ingress."""
    assert ops_test.model is not None
    metrics = await get_ingress_metrics(ops_test)
    assert "blackbox_exporter_build_info" in metrics, "Expected blackbox metrics not found"


@pytest.mark.abort_on_fail
async def test_metrics_endpoint_all_units(ops_test: OpsTest):
    """Check that all blackbox units appear in Prometheus scrape targets when mesh is enabled."""
    assert ops_test.model is not None

    # Wait for Prometheus to scrape the targets
    time.sleep(60)

    # Get all blackbox unit addresses from the model
    app = ops_test.model.applications[APP_NAME]
    expected_unit_count = len(app.units)
    assert expected_unit_count == 3, f"Expected 3 units, got {expected_unit_count}"

    # Query Prometheus for targets
    targets_data = await get_prometheus_targets(ops_test, "prometheus")
    blackbox_targets = get_blackbox_targets_from_prometheus(targets_data)

    # Check that we have targets for all units
    assert len(blackbox_targets) >= expected_unit_count, (
        f"Expected at least {expected_unit_count} blackbox targets in Prometheus, "
        f"got {len(blackbox_targets)}"
    )

    # Verify all targets are healthy
    unhealthy_targets = [
        target for target in blackbox_targets if target.get("health") != "up"
    ]
    assert not unhealthy_targets, (
        f"Some blackbox targets are not healthy: {unhealthy_targets}"
    )

    logger.info(
        f"All {len(blackbox_targets)} blackbox-exporter targets are healthy in Prometheus"
    )


async def test_probes_all_units(ops_test: OpsTest):
    """Check that blackbox probes work on all units when service mesh is enabled."""
    assert ops_test.model is not None

    app = ops_test.model.applications[APP_NAME]
    expected_unit_count = len(app.units)

    # Test that each unit can execute probes
    for unit_num in range(expected_unit_count):
        # Test probing an external target (prometheus.io)
        result = await can_blackbox_probe(
            ops_test,
            APP_NAME,
            unit_num,
            target="http://prometheus.io",
            module="http_2xx",
        )
        assert result, f"Probe failed on unit {APP_NAME}/{unit_num}"
        logger.info(f"Probe successful on unit {APP_NAME}/{unit_num}")
