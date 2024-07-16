#!/usr/bin/env python3
# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

"""Workload manager for Blackbox Exporter."""

import logging
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Optional, cast

import yaml
from ops.framework import Object
from ops.pebble import (  # type: ignore
    ChangeError,
    Layer,
)

logger = logging.getLogger(__name__)


class WorkloadManagerError(Exception):
    """Base class for exceptions raised by WorkloadManager."""


class ConfigUpdateFailure(WorkloadManagerError):
    """Custom exception for failed config updates."""


class ContainerNotReady(WorkloadManagerError):
    """Raised when an operation is run that presumes the container being ready.."""


class WorkloadManager(Object):
    """Workload manager for blackbox exporter."""

    _layer_name = _service_name = "blackbox"
    _exe_name = "blackbox_exporter"

    def __init__(
        self,
        charm,
        *,
        container_name: str,
        port: int,
        web_external_url: str,
        config_path: str,
        log_path: str,
    ):
        # Must inherit from ops 'Object' to be able to register events.
        super().__init__(charm, f"{self.__class__.__name__}-{container_name}")

        self._unit = charm.unit

        self._service_name = self._container_name = container_name
        self._container = charm.unit.get_container(container_name)

        self.api = BlackboxExporterApi(endpoint_url=charm._external_url)

        self._port = port
        self._web_external_url = web_external_url
        self._config_path = config_path
        self._log_path = log_path

        # turn the container name to a valid Python identifier
        snake_case_container_name = self._container_name.replace("-", "_")
        charm.framework.observe(
            charm.on[snake_case_container_name].pebble_ready, self._on_pebble_ready
        )

    @property
    def is_ready(self):
        """Is the workload ready to be interacted with?"""
        return self._container.can_connect()

    def _on_pebble_ready(self, _):
        if version := self._blackbox_exporter_version:
            self._unit.set_workload_version(version)
        else:
            logger.debug(
                "Cannot set workload version at this time: couldn't get Blackbox Exporter version"
            )

    @property
    def _blackbox_exporter_version(self) -> Optional[str]:
        """Returns the version of Blackbox Exporter.

        Returns:
            A string equal to the Blackbox Exporter version.
        """
        if not self.is_ready:
            return None
        version_output, _ = self._container.exec([self._exe_name, "--version"]).wait_output()
        # Output looks like this:
        # blackbox_exporter, version 0.24.0 (branch: HEAD, ...)
        result = re.search(r"version (\d*\.\d*\.\d*)", version_output)
        if result is None:
            return result
        return result.group(1)

    def _blackbox_exporter_layer(self) -> Layer:
        """Returns Pebble configuration layer for Blackbox Exporter."""

        def _command():
            """Returns full command line to start Blackbox Exporter."""
            return (
                f"/bin/sh -c '{self._exe_name} "
                f"--config.file={self._config_path} "
                f"--web.listen-address=:{self._port} "
                f"--web.external-url={self._web_external_url} "
                f"2>&1'"
            )

        return Layer(
            {
                "summary": "blackbox exporter layer",
                "description": "pebble config layer for blackbox exporter",
                "services": {
                    self._service_name: {
                        "override": "replace",
                        "summary": "blackbox exporter service",
                        "command": _command(),
                        "startup": "enabled",
                    }
                },
            }
        )

    def update_layer(self) -> None:
        """Update service layer."""
        if not self.is_ready:
            raise ContainerNotReady("cannot update layer")

        overlay = self._blackbox_exporter_layer()

        self._container.add_layer(self._layer_name, overlay, combine=True)
        try:
            # If a config is invalid then blackbox exporter would exit immediately. #TODO: true?
            self._container.replan()
        except ChangeError as e:
            logger.error(
                "Failed to replan; pebble plan: %s; %s",
                self._container.get_plan().to_dict(),
                str(e),
            )

    def update_config(self) -> None:
        """Update blackbox exporter config file to reflect changes in configuration.

        Raises:
            ConfigUpdateFailure, if failed to update configuration file.
        """
        if not self.is_ready:
            raise ContainerNotReady("cannot update config")
        logger.debug("applying config changes")
        config = cast(str, self.model.config.get("config_file"))
        # Basic config validation: valid yaml
        if config:
            try:
                yaml.safe_load(config)
            except yaml.YAMLError as e:
                logger.error(
                    "Failed to load the configuration; invalid YAML: %s %s", config, str(e)
                )
                raise ConfigUpdateFailure("Failed to load config; invalid YAML")
            self._container.push(self._config_path, config, make_dirs=True)

    def restart_service(self) -> bool:
        """Helper function for restarting the underlying service.

        Returns:
            True if restart succeeded; False otherwise.
        """
        logger.info("Restarting service %s", self._service_name)

        if not self.is_ready:
            logger.error("Cannot (re)start service: container is not ready.")
            return False

        # Check if service exists, to avoid ModelError from being raised when the service does
        # not exist.
        if not self._container.get_plan().services.get(self._service_name):
            logger.error("Cannot (re)start service: service does not (yet) exist.")
            return False

        self._container.restart(self._service_name)

        return True

    def reload(self) -> None:
        """Trigger a hot-reload of the configuration (or service restart).

        Raises:
            ConfigUpdateFailure, if the reload (or restart) fails.
        """
        if not self.is_ready:
            raise ContainerNotReady("cannot reload")

        try:
            self.api.reload()
        except BlackboxExporterBadResponse as e:
            logger.warning("config reload via HTTP POST failed: %s", str(e))
            # hot-reload failed so attempting a service restart
            if not self.restart_service():
                raise ConfigUpdateFailure(
                    "Is config valid? hot reload and service restart failed."
                )


class BlackboxExporterBadResponse(RuntimeError):
    """A catch-all exception type to indicate 'no reply', regardless of the reason."""


class BlackboxExporterApi:
    """Blackbox Exporter HTTP API client."""

    def __init__(
        self,
        endpoint_url: str = "http://localhost:9115",
        timeout=2,
    ):
        self.base_url = endpoint_url.rstrip("/")
        self.timeout = timeout

    def reload(self) -> bool:
        """Send a POST request to hot-reload the config.

        This reduces down-time compared to restarting the service.

        Returns:
            True if reload succeeded (returned 200 OK); False otherwise.
        """
        url = urllib.parse.urljoin(self.base_url, "-/reload")
        # for an empty POST request, the `data` arg must be b"" to tell urlopen it's a POST
        if resp := self._open(url, data=b"", timeout=self.timeout):
            logger.warning("reload: POST returned a non-empty response: %s", resp)
            return False
        return True

    @staticmethod
    def _open(url: str, data: Optional[bytes], timeout: float) -> bytes:
        """Send a request using urlopen.

        Args:
            url: target url for the request
            data: bytes to send to target
            timeout: duration in seconds after which to return, regardless the result

        Raises:
            BlackboxExporterBadResponse: If no response or invalid response, regardless the reason.
        """
        for retry in reversed(range(3)):
            try:
                response = urllib.request.urlopen(url, data, timeout)
                if response.code == 200 and response.reason == "OK":
                    return response.read()
                if retry == 0:
                    raise BlackboxExporterBadResponse(
                        f"Bad response on Blackbox Exporter api (code={response.code}, reason={response.reason})"
                    )

            except (ValueError, urllib.error.HTTPError, urllib.error.URLError) as e:
                if retry == 0:
                    raise BlackboxExporterBadResponse(
                        "Bad response on Blackbox Exporter api"
                    ) from e

            time.sleep(0.2)

        assert False, "unreachable"  # help mypy (https://github.com/python/mypy/issues/8964)
