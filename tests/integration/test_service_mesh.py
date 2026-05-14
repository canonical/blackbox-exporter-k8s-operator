#!/usr/bin/env python3
# Copyright 2025 Canonical Ltd.
# See LICENSE file for licensing details.

"""Integration tests for service mesh support."""

import json
import logging
from pathlib import Path
from typing import Any, Dict, List

import pytest
import requests
import yaml
from helpers import get_unit_address
from lightkube import Client
from lightkube.generic_resource import create_namespaced_resource
from pytest_operator.plugin import OpsTest
from tenacity import retry, stop_after_attempt, wait_fixed

logger = logging.getLogger(__name__)

METADATA = yaml.safe_load(Path("./charmcraft.yaml").read_text())
APP_NAME = METADATA["name"]
RESOURCES = {
    "blackbox-exporter-image": METADATA["resources"]["blackbox-exporter-image"]["upstream-source"]
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


async def get_prometheus_targets_from_client_pod(
    ops_test: OpsTest,
    source_unit: str,
    prometheus_app: str = "prometheus",
) -> Dict[str, Any]:
    """Get Prometheus scrape targets from inside a pod (within the cluster)."""
    prometheus_url = await get_unit_address(ops_test, prometheus_app, 0)
    url = f"http://{prometheus_url}:9090/api/v1/targets"

    rc, stdout, stderr = await ops_test.juju(
        "ssh",
        "--container",
        source_unit.split("/")[0],
        source_unit,
        "curl",
        "-s",
        url,
    )
    assert rc == 0, f"Failed to curl prometheus: {stderr}"
    response_json = json.loads(stdout)

    assert response_json["status"] == "success"
    return response_json["data"]


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
        channel="latest/edge",
        trust=True,
    )
    await ops_test.model.deploy(
        "istio-beacon-k8s",
        application_name="istio-beacon",
        channel="latest/edge",
        trust=True,
    )
    await ops_test.model.deploy(
        "istio-ingress-k8s",
        application_name="istio-ingress",
        channel="latest/edge",
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
    ingress_address = get_istio_ingress_ip(ops_test, "istio-ingress")
    proxied_endpoint = f"http://{ingress_address}/{ops_test.model_name}-{APP_NAME}"
    response = requests.get(f"{proxied_endpoint}/metrics")
    assert response.status_code == 200


@retry(wait=wait_fixed(10), stop=stop_after_attempt(6))
async def test_metrics_endpoint(ops_test: OpsTest):
    """Check that blackbox appears in the Prometheus scrape targets when mesh is enabled."""
    assert ops_test.model is not None

    # Query from inside the prometheus pod when service mesh is enabled
    source_unit = "prometheus/0"
    targets = await get_prometheus_targets_from_client_pod(ops_test, source_unit)
    blackbox_targets = [
        target
        for target in targets["activeTargets"]
        if target["discoveredLabels"].get("juju_charm") == "blackbox-exporter-k8s"
    ]
    assert blackbox_targets, "Blackbox exporter target not found in Prometheus"
