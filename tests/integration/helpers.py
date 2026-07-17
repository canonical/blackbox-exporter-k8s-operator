# Copyright 2021 Canonical Ltd.
# See LICENSE file for licensing details.

"""Helper functions for writing tests."""

import json
import logging
import urllib.request
from pprint import pprint
from typing import Any, Dict, Optional, Tuple

import jubilant

logger = logging.getLogger(__name__)


def get_unit_address(juju: jubilant.Juju, app_name: str, unit_num: int) -> str:
    """Get private address of a unit."""
    status = juju.status()
    return status.apps[app_name].units[f"{app_name}/{unit_num}"].address


def is_blackbox_unit_up(juju: jubilant.Juju, app_name: str, unit_num: int):
    address = get_unit_address(juju, app_name, unit_num)
    url = f"http://{address}:9115"
    logger.info("blackbox exporter public address: %s", url)

    response = urllib.request.urlopen(f"{url}", data=None, timeout=2.0)
    return response.code == 200


def is_blackbox_up(juju: jubilant.Juju, app_name: str):
    status = juju.status()
    application = status.apps[app_name]
    return all(
        is_blackbox_unit_up(juju, app_name, unit_num) for unit_num in range(len(application.units))
    )


def can_blackbox_probe(
    juju: jubilant.Juju,
    app_name: str,
    unit_num: int,
    target: Optional[str] = None,
    module: str = "http_2xx",
):
    address = get_unit_address(juju, app_name, unit_num)
    url = f"http://{address}:9115"
    if not target:
        target = f"{address}:9115"

    response = urllib.request.urlopen(
        f"{url}/probe?target={target}&module={module}", data=None, timeout=2.0
    )
    return response.code == 200 and "probe_success 1" in str(response.read())


def all_prometheus_targets_up(
    juju: jubilant.Juju,
    app_name: str,
    unit_num: int = 0,
):
    address = get_unit_address(juju, app_name, unit_num)
    url = f"http://{address}:9090"
    response = urllib.request.urlopen(f"{url}/api/v1/targets", data=None)
    if response.code != 200:
        return False
    response_data = response.read().decode("utf-8")
    response_json = json.loads(response_data)
    targets = response_json.get("data", {}).get("activeTargets", [])

    if not targets:
        logger.warning("No scrape targets present")
        return False

    # Give some details about the targets that are down
    targets_down = [target for target in targets if target["health"] != "up"]
    logger.info("The following scrape targets are down: %s", pprint(targets_down))

    return all(target["health"] == "up" for target in targets)


def get_blackbox_config_from_file(
    juju: jubilant.Juju, app_name: str, container_name: str, config_file_path: str
) -> Tuple[Optional[int], str, str]:
    stdout = juju.ssh(f"{app_name}/0", "cat", config_file_path, container=container_name)
    return 0, stdout, ""


def deploy_literal_bundle(juju: jubilant.Juju, bundle: str):
    juju.cli("deploy", "--trust", str(bundle))


def get_traefik_proxied_endpoints(
    juju: jubilant.Juju, traefik_app: str = "traefik"
) -> Dict[str, Any]:
    result = juju.run(f"{traefik_app}/0", "show-proxied-endpoints")
    return json.loads(result.results["proxied-endpoints"])
