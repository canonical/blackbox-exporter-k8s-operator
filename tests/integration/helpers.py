# Copyright 2021 Canonical Ltd.
# See LICENSE file for licensing details.

"""Helper functions for writing tests."""

import json
import logging
import urllib.request
from typing import Any, Dict, Optional, Tuple

from juju.unit import Unit
from pytest_operator.plugin import OpsTest

logger = logging.getLogger(__name__)


async def get_unit_address(ops_test: OpsTest, app_name: str, unit_num: int) -> str:
    """Get private address of a unit."""
    status = await ops_test.model.get_status()  # noqa: F821
    return status["applications"][app_name]["units"][f"{app_name}/{unit_num}"]["address"]


async def is_blackbox_unit_up(ops_test: OpsTest, app_name: str, unit_num: int):
    address = await get_unit_address(ops_test, app_name, unit_num)
    url = f"http://{address}:9115"
    logger.info("blackbox exporter public address: %s", url)

    response = urllib.request.urlopen(f"{url}", data=None, timeout=2.0)
    return response.code == 200


async def is_blackbox_up(ops_test: OpsTest, app_name: str):
    return all(
        [
            await is_blackbox_unit_up(ops_test, app_name, unit_num)
            for unit_num in range(len(ops_test.model.applications[app_name].units))
        ]
    )


async def can_blackbox_probe(
    ops_test: OpsTest,
    app_name: str,
    unit_num: int,
    target: Optional[str] = None,
    module: str = "http_2xx",
):
    address = await get_unit_address(ops_test, app_name, unit_num)
    url = f"http://{address}:9115"
    if not target:
        target = f"{address}:9115"

    response = urllib.request.urlopen(
        f"{url}/probe?target={target}&module={module}", data=None, timeout=2.0
    )
    return response.code == 200 and "probe_success 1" in str(response.read())


async def get_blackbox_config_from_file(
    ops_test: OpsTest, app_name: str, container_name: str, config_file_path: str
) -> Tuple[Optional[int], str, str]:
    rc, stdout, stderr = await ops_test.juju(
        "ssh", "--container", f"{container_name}", f"{app_name}/0", "cat", f"{config_file_path}"
    )
    return rc, stdout, stderr


async def deploy_literal_bundle(ops_test: OpsTest, bundle: str):
    run_args = [
        "juju",
        "deploy",
        "--trust",
        "-m",
        ops_test.model_name,
        str(ops_test.render_bundle(bundle)),
    ]

    retcode, stdout, stderr = await ops_test.run(*run_args)
    assert retcode == 0, f"Deploy failed: {(stderr or stdout).strip()}"
    logger.info(stdout)


async def get_traefik_proxied_endpoints(
    ops_test: OpsTest, traefik_app: str = "traefik"
) -> Dict[str, Any]:
    assert ops_test.model is not None
    traefik_leader: Unit = ops_test.model.applications[traefik_app].units[0]  # type: ignore
    action = await traefik_leader.run_action("show-proxied-endpoints")
    action_result = await action.wait()
    return json.loads(action_result.results["proxied-endpoints"])
