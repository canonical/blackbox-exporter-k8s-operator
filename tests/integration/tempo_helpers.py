# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

"""Charm-agnostic helpers for deploying a monolithic Tempo stack and querying ingested traces.

This module intentionally contains no references to any specific charm under test, so it
can be copied to other repos (or eventually extracted into a shared fleet test library)
verbatim. The companion `test_charm_tracing.py` is the charm-specific orchestration.

The S3 backend is `seaweedfs-k8s`, which replaces the older minio + s3-integrator pattern.
See the inline comment on S3_APP for the naming constraint that makes seaweedfs work
across both microk8s and Canonical Kubernetes environments.
"""

from __future__ import annotations

from typing import List, Set, cast

import jubilant
import requests
from jubilant import Juju

TEMPO = "tempo"
TEMPO_WORKER = "tempo-worker"
# Naming this app "s3" collides with Kubernetes auto-injected env vars
# (S3_PORT=tcp://<ip>:<port>), which the seaweedfs `weed` binary then tries to
# parse as its -s3.port flag and dies on startup. Match parca's "s3-app".
S3_APP = "s3-app"
INTEGRATION_TESTERS_CHANNEL = "dev/edge"


def deploy_monolithic_tempo_cluster(juju: Juju) -> None:
    """Deploy a monolithic Tempo cluster (coordinator + worker + S3 backend).

    Uses `seaweedfs-k8s` as a lightweight S3 backend (replaces the older minio +
    s3-integrator pair; minio is no longer maintained upstream).
    """
    juju.deploy(
        "tempo-worker-k8s",
        app=TEMPO_WORKER,
        channel=INTEGRATION_TESTERS_CHANNEL,
        trust=True,
    )
    juju.deploy(
        "tempo-coordinator-k8s",
        app=TEMPO,
        channel=INTEGRATION_TESTERS_CHANNEL,
        trust=True,
    )
    juju.integrate(TEMPO, TEMPO_WORKER)

    juju.deploy("seaweedfs-k8s", S3_APP, channel="latest/edge")
    juju.integrate(f"{TEMPO}:s3", S3_APP)

    juju.wait(
        lambda status: (
            jubilant.all_agents_idle(status, TEMPO, TEMPO_WORKER, S3_APP)
            and jubilant.all_active(status, TEMPO, TEMPO_WORKER, S3_APP)
        ),
        timeout=1000,
    )


def get_app_ip_address(juju: Juju, app_name: str) -> str:
    """Return a juju application's IP address from `juju status`."""
    return juju.status().apps[app_name].address


def get_ingested_traces_tag_values(tempo_host: str, tls: bool, tag: str) -> Set[str]:
    """Fetch all values for a given tag from Tempo's search API.

    Tempo exposes `/api/search/tag/{tag}/values` which returns every value ever seen
    for that tag across ingested spans. Useful for asserting "did this service emit
    *any* spans yet?" via tag=`service.name`.
    """
    url = f"{'https' if tls else 'http'}://{tempo_host}:3200/api/search/tag/{tag}/values"
    resp = requests.get(url, verify=False, timeout=10)
    assert resp.status_code == 200, resp.reason
    tag_values = cast(List[str], resp.json()["tagValues"])
    return set(tag_values)
