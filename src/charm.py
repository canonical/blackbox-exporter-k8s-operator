#!/usr/bin/env python3
# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

"""A Juju charm for Blackbox Exporter."""

import logging
import socket
import typing
from urllib.parse import urlparse

import yaml
from blackbox import ConfigUpdateFailure, WorkloadManager
from charms.catalogue_k8s.v1.catalogue import CatalogueConsumer, CatalogueItem
from charms.grafana_k8s.v0.grafana_dashboard import GrafanaDashboardProvider
from charms.loki_k8s.v1.loki_push_api import LogForwarder
from charms.observability_libs.v0.kubernetes_compute_resources_patch import (
    K8sResourcePatchFailedEvent,
    KubernetesComputeResourcesPatch,
    ResourceRequirements,
    adjust_resource_requirements,
)
from charms.prometheus_k8s.v0.prometheus_scrape import MetricsEndpointProvider
from charms.traefik_k8s.v2.ingress import IngressPerAppRequirer
from ops.charm import ActionEvent, CharmBase
from ops.main import main
from ops.model import (
    ActiveStatus,
    BlockedStatus,
    MaintenanceStatus,
    WaitingStatus,
)
from ops.pebble import PathError, ProtocolError

logger = logging.getLogger(__name__)


class BlackboxExporterCharm(CharmBase):
    """A Juju charm for Blackbox Exporter."""

    # Container name must match metadata.yaml
    # Service name matches charm name for consistency
    _container_name = _service_name = "blackbox"
    _port = 9115

    # path, inside the workload container, to the blackbox exporter configuration files
    _config_path = "/etc/blackbox_exporter/config.yml"
    _log_path = "/var/blackbox.log"

    def __init__(self, *args):
        super().__init__(*args)

        self.container = self.unit.get_container(self._container_name)
        self.unit.set_ports(self._port)
        self.ingress = IngressPerAppRequirer(
            self,
            port=self._port,
            scheme=lambda: urlparse(self._internal_url).scheme,
            strip_prefix=True,
            redirect_https=True,
        )

        # Core lifecycle events
        self.blackbox_workload = WorkloadManager(
            self,
            container_name=self._container_name,
            port=self._port,
            web_external_url=self._external_url,
            config_path=self._config_path,
            log_path=self._log_path,
        )
        self.framework.observe(self.on.config_changed, self._on_config_changed)

        self.framework.observe(
            # The workload manager too observes pebble ready, but still need this here because
            # of the common exit hook (otherwise would need to pass the common exit hook as
            # a callback).
            self.on.blackbox_pebble_ready,  # pyright: ignore
            self._on_pebble_ready,
        )
        self.framework.observe(self.on.update_status, self._on_update_status)
        self.framework.observe(self.on.upgrade_charm, self._on_upgrade_charm)

        # Action events
        self.framework.observe(
            self.on.show_config_action, self._on_show_config_action  # pyright: ignore
        )

        # Libraries
        # - Kubernetes resource patch
        self.resources_patch = KubernetesComputeResourcesPatch(
            self,
            self._container_name,
            resource_reqs_func=self._resource_reqs_from_config,
        )
        self.framework.observe(
            self.resources_patch.on.patch_failed,  # pyright: ignore
            self._on_k8s_patch_failed,
        )

        # - Self monitoring and probes
        self._scraping = MetricsEndpointProvider(
            self,
            relation_name="self-metrics-endpoint",
            jobs=self.self_scraping_job + self.probes_scraping_jobs,
            refresh_event=[
                self.on.config_changed,
                self.on.update_status,
            ],
        )
        self._grafana_dashboard_provider = GrafanaDashboardProvider(charm=self)
        self._log_forwarding = LogForwarder(self, relation_name="logging")

        self.framework.observe(self.ingress.on.ready, self._handle_ingress)
        self.framework.observe(self.ingress.on.revoked, self._handle_ingress)
        self.catalog = CatalogueConsumer(
            charm=self,
            item=CatalogueItem(
                name="Blackbox Exporter",
                url=self._external_url,
                icon="box-variant",
                description=(
                    "Blackbox exporter allows blackbox probing of endpoints over a multitude of "
                    "protocols, including HTTP, HTTPS, DNS, TCP, ICMP and gRPC."
                ),
            ),
        )

    def _resource_reqs_from_config(self) -> ResourceRequirements:
        """Get the resources requirements from the Juju config."""
        limits = {
            "cpu": self.model.config.get("cpu"),
            "memory": self.model.config.get("memory"),
        }
        requests = {"cpu": "0.25", "memory": "200Mi"}
        return adjust_resource_requirements(limits, requests, adhere_to_requests=True)

    def _on_k8s_patch_failed(self, event: K8sResourcePatchFailedEvent):
        self.unit.status = BlockedStatus(str(event.message))

    def _handle_ingress(self, _):
        if url := self.ingress.url:
            logger.info("Ingress is ready: '%s'.", url)
        else:
            logger.info("Ingress revoked.")
        self._common_exit_hook()

    def _on_show_config_action(self, event: ActionEvent):
        """Hook for the show-config action."""
        event.log(f"Fetching {self._config_path}")
        if not self.blackbox_workload.is_ready:
            event.fail("Container not ready")
        try:
            content = self.container.pull(self._config_path)
            event.set_results(
                {
                    "path": self._config_path,
                    "content": str(content.read()),
                }
            )
        except (ProtocolError, PathError) as e:
            event.fail(str(e))

    def _common_exit_hook(self) -> None:
        """Event processing hook that is common to all events to ensure idempotency."""
        if not self.resources_patch.is_ready():
            if isinstance(self.unit.status, ActiveStatus) or self.unit.status.message == "":
                self.unit.status = WaitingStatus("Waiting for resource limit patch to apply")
            return

        if not self.container.can_connect():
            self.unit.status = MaintenanceStatus("Waiting for pod startup to complete")
            return

        # Make sure the external url is valid
        if external_url := self._external_url:
            parsed = urlparse(external_url)
            if not (parsed.scheme in ["http"] and parsed.hostname):
                # This shouldn't happen
                logger.error(
                    "Invalid external url: %s; must include scheme and hostname.",
                    external_url,
                )
                self.unit.status = BlockedStatus(
                    f"Invalid external url: '{external_url}'; must include scheme and hostname."
                )
                return

        # Update config file
        try:
            self.blackbox_workload.update_config()
        except ConfigUpdateFailure as e:
            self.unit.status = BlockedStatus(str(e))
            return

        # Update pebble layer
        self.blackbox_workload.update_layer()

        # Reload or restart the service
        self.blackbox_workload.reload()

        self.unit.status = ActiveStatus()

    @property
    def _internal_url(self) -> str:
        """Return the fqdn dns-based in-cluster (private) address of the blackbox exporter."""
        return f"http://{socket.getfqdn()}:{self._port}"

    @property
    def _external_url(self) -> str:
        """Return the externally-reachable (public) address of the blackbox exporter.

        If not set in the config, return the internal url.
        """
        return self.ingress.url or self._internal_url

    @property
    def self_scraping_job(self):
        """The self-monitoring scrape job."""
        external_url = urlparse(self._external_url)
        metrics_path = f"{external_url.path.rstrip('/')}/metrics"
        target = (
            f"{external_url.hostname}{':'+str(external_url.port) if external_url.port else ''}"
        )
        job = {
            "metrics_path": metrics_path,
            "static_configs": [{"targets": [target]}],
        }

        return [job]

    @property
    def probes_scraping_jobs(self):
        """The scraping jobs to execute probes from Prometheus."""
        jobs = []
        external_url = urlparse(self._external_url)
        f"{external_url.path.rstrip('/')}/probe"
        probes_scrape_jobs = typing.cast(
            typing.Optional[str], self.model.config.get("probes_file")
        )
        if probes_scrape_jobs:
            probes = yaml.safe_load(probes_scrape_jobs)
            # Add the Blackbox Exporter's `relabel_configs` to each job
            for probe in probes["scrape_configs"]:
                # The relabel configs come from the official Blackbox Exporter docs; please refer
                # to that for further information on what they do
                probe["relabel_configs"] = [
                    {"source_labels": ["__address__"], "target_label": "__param_target"},
                    {"source_labels": ["__param_target"], "target_label": "instance"},
                    # Copy the scrape job target to an extra label for dahsboard usage
                    {"source_labels": ["__param_target"], "target_label": "probe_target"},
                    # Set the address to scrape to the blackbox exporter url
                    {
                        "target_label": "__address__",
                        "replacement": self._external_url.replace("http://", ""),
                    },
                ]
                jobs.append(probe)

        return jobs

    def _on_pebble_ready(self, _):
        """Event handler for PebbleReadyEvent."""
        self._common_exit_hook()

    def _on_config_changed(self, _):
        """Event handler for ConfigChangedEvent."""
        self._common_exit_hook()

    def _on_update_status(self, _):
        """Event handler for UpdateStatusEvent."""
        self._common_exit_hook()

    def _on_upgrade_charm(self, _):
        """Event handler for replica's UpgradeCharmEvent."""
        # After upgrade (refresh), the unit ip address is not guaranteed to remain the same, and
        # the config may need update. Calling the common hook to update.
        self._common_exit_hook()


if __name__ == "__main__":
    main(BlackboxExporterCharm)
