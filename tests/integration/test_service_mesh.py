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

import jubilant
import pytest
import yaml
from helpers import can_blackbox_probe, get_unit_address
from lightkube import Client
from lightkube.generic_resource import create_namespaced_resource

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


def get_istio_ingress_ip(juju: jubilant.Juju, app_name: str = "istio-ingress") -> str:
    """Get the istio-ingress public IP address from Kubernetes."""
    gateway_resource = create_namespaced_resource(
        group="gateway.networking.k8s.io",
        version="v1",
        kind="Gateway",
        plural="gateways",
    )
    client = Client()
    model_name = juju.status().model.name
    gateway = client.get(gateway_resource, app_name, namespace=model_name)
    if gateway.status and gateway.status.get("addresses"):  # type: ignore
        return gateway.status["addresses"][0]["value"]  # type: ignore
    raise ValueError(f"No ingress address found for {app_name}")


def resolve_units_in_error(juju: jubilant.Juju):
    """Resolve any units in error state with retry."""
    status = juju.status()
    for app in status.apps.values():
        for unit_name, unit in app.units.items():
            if unit.workload_status.current == "error":
                logger.info(f"Resolving error on {unit_name}")
                juju.cli("resolved", unit_name)


def service_mesh(
    enable: bool,
    juju: jubilant.Juju,
    beacon_app_name: str,
    apps_to_be_related_with_beacon: List[str],
):
    """Enable or disable the service-mesh in the model.

    This puts the entire model, that the beacon app is part of, on mesh.
    This integrates the apps_to_be_related_with_beacon with the beacon app
    via the ``service-mesh`` relation.

    Note: Enabling the mesh causes Istio to intercept all traffic in the namespace,
    which can temporarily disrupt Juju agent connections to the controller. We use
    raise_on_error=False and resolve any units that enter error state.
    """
    juju.config(beacon_app_name, {"model-on-mesh": str(enable).lower()})
    # Allow errors during mesh reconfiguration - network disruption is expected
    try:
        juju.wait(jubilant.all_active, timeout=600, delay=5.0)
    except TimeoutError:
        pass
    resolve_units_in_error(juju)

    if enable:
        for app in apps_to_be_related_with_beacon:
            juju.integrate(f"{beacon_app_name}:service-mesh", f"{app}:service-mesh")
    else:
        for app in apps_to_be_related_with_beacon:
            juju.remove_relation(f"{beacon_app_name}:service-mesh", f"{app}:service-mesh")

    # Allow errors during integration - mesh traffic interception may cause transient failures
    try:
        juju.wait(jubilant.all_active, timeout=600, delay=5.0)
    except TimeoutError:
        pass
    resolve_units_in_error(juju)

    # Final wait to confirm all units are stable
    juju.wait(jubilant.all_active, timeout=600)


def get_prometheus_targets(
    juju: jubilant.Juju,
    prometheus_app: str = "prometheus",
    unit_num: int = 0,
) -> Dict[str, Any]:
    """Get Prometheus scrape targets."""
    address = get_unit_address(juju, prometheus_app, unit_num)
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


def get_ingress_metrics(juju: jubilant.Juju) -> str:
    """Get metrics through the istio-ingress endpoint."""
    ingress_address = get_istio_ingress_ip(juju, "istio-ingress")
    model_name = juju.status().model.name
    proxied_endpoint = f"http://{ingress_address}/{model_name}-{APP_NAME}/metrics"
    response = urllib.request.urlopen(proxied_endpoint, data=None, timeout=10.0)
    if response.code != 200:
        raise RuntimeError(f"Failed to get metrics through ingress: {response.code}")
    return response.read().decode("utf-8")


@pytest.mark.juju_setup
@pytest.mark.abort_on_fail
def test_build_and_deploy(juju: jubilant.Juju, charm_under_test: str):
    """Build and deploy the charm together with Istio service mesh components."""
    # Deploy non-istio apps
    juju.deploy(
        str(charm_under_test),
        app=APP_NAME,
        resources=RESOURCES,
        trust=True,
    )
    juju.deploy(
        "prometheus-k8s",
        "prometheus",
        channel="dev/edge",
        trust=True,
    )

    # Deploy istio-k8s first and wait for it to be ready before deploying
    # istio-beacon and istio-ingress which depend on it
    model_info = juju.show_model()
    istio_config = {} if model_info.cloud == "microk8s" else {"platform": ""}

    juju.deploy(
        "istio-k8s",
        "istio",
        channel="dev/edge",
        trust=True,
        config=istio_config,
    )

    # Wait for istio to be active before deploying dependent charms
    juju.wait(
        lambda status: status.apps["istio"].is_active,
        timeout=600,
        delay=5.0,
    )

    # Now deploy the charms that depend on istio control plane
    juju.deploy(
        "istio-beacon-k8s",
        "istio-beacon",
        channel="dev/edge",
        trust=True,
    )
    juju.deploy(
        "istio-ingress-k8s",
        "istio-ingress",
        channel="dev/edge",
        trust=True,
    )

    # First attempt - allow errors since istio components may need retries
    juju.wait(
        jubilant.all_agents_idle,
        timeout=600,
        delay=15.0,
    )

    # Resolve any units in error state and retry
    resolve_units_in_error(juju)

    # Final wait for all apps to be active
    juju.wait(
        lambda status: jubilant.all_active(
            status,
            APP_NAME,
            "prometheus",
            "istio",
            "istio-beacon",
            "istio-ingress",
        ),
        error=jubilant.any_error,
        timeout=600,
        delay=15.0,
    )

    # Configure blackbox probes
    juju.config(APP_NAME, {"probes_file": yaml.dump(BLACKBOX_PROBES)})
    juju.wait(lambda status: jubilant.all_active(status, APP_NAME), timeout=300)


@pytest.mark.juju_setup
@pytest.mark.abort_on_fail
def test_integrate(juju: jubilant.Juju):
    """Integrate apps before enabling service mesh."""
    juju.integrate(f"{APP_NAME}:self-metrics-endpoint", "prometheus")
    juju.integrate(f"{APP_NAME}:ingress", "istio-ingress:ingress")

    juju.wait(
        lambda status: jubilant.all_active(
            status,
            APP_NAME,
            "prometheus",
            "istio-ingress",
        ),
        timeout=1000,
    )


@pytest.mark.juju_setup
@pytest.mark.abort_on_fail
def test_scale_up(juju: jubilant.Juju):
    """Scale up the blackbox-exporter charm to multiple units."""
    juju.add_unit(APP_NAME, num_units=2)

    juju.wait(
        lambda status: (
            jubilant.all_active(status, APP_NAME) and len(status.apps[APP_NAME].units) == 3
        ),
        timeout=1000,
    )


@pytest.mark.juju_setup
@pytest.mark.abort_on_fail
def test_enable_service_mesh(juju: jubilant.Juju):
    """Enable service mesh.

    This is not done in the previous step for two reasons:
    1. Not all apps are mesh-enabled yet, so we need to let apps establish comms first.
    2. The `service_mesh` helper provides a way to parametrize and run existing tests
       with service mesh enabled.
    """
    service_mesh(
        enable=True,
        juju=juju,
        beacon_app_name="istio-beacon",
        apps_to_be_related_with_beacon=[APP_NAME],
    )


def test_ingress(juju: jubilant.Juju):
    """Check the ingress integration by checking if blackbox is reachable through istio-ingress."""
    metrics = get_ingress_metrics(juju)
    assert "blackbox_exporter_build_info" in metrics, "Expected blackbox metrics not found"


@pytest.mark.abort_on_fail
def test_metrics_endpoint_all_units(juju: jubilant.Juju):
    """Check that all blackbox units appear in Prometheus scrape targets when mesh is enabled."""
    # Wait for Prometheus to scrape the targets
    time.sleep(60)

    # Get all blackbox unit addresses from the model
    status = juju.status()
    expected_unit_count = len(status.apps[APP_NAME].units)
    assert expected_unit_count == 3, f"Expected 3 units, got {expected_unit_count}"

    # Query Prometheus for targets
    targets_data = get_prometheus_targets(juju, "prometheus")
    blackbox_targets = get_blackbox_targets_from_prometheus(targets_data)

    # Check that we have targets for all units
    assert len(blackbox_targets) >= expected_unit_count, (
        f"Expected at least {expected_unit_count} blackbox targets in Prometheus, "
        f"got {len(blackbox_targets)}"
    )

    # Verify all targets are healthy
    unhealthy_targets = [target for target in blackbox_targets if target.get("health") != "up"]
    assert not unhealthy_targets, f"Some blackbox targets are not healthy: {unhealthy_targets}"

    logger.info(f"All {len(blackbox_targets)} blackbox-exporter targets are healthy in Prometheus")


def test_probes_all_units(juju: jubilant.Juju):
    """Check that blackbox probes work on all units when service mesh is enabled."""
    status = juju.status()
    expected_unit_count = len(status.apps[APP_NAME].units)

    # Test that each unit can execute probes
    for unit_num in range(expected_unit_count):
        # Test probing an external target (prometheus.io)
        result = can_blackbox_probe(
            juju,
            APP_NAME,
            unit_num,
            target="http://prometheus.io",
            module="http_2xx",
        )
        assert result, f"Probe failed on unit {APP_NAME}/{unit_num}"
        logger.info(f"Probe successful on unit {APP_NAME}/{unit_num}")
