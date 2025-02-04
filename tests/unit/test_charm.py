#!/usr/bin/env python3
# Copyright 2021 Canonical Ltd.
# See LICENSE file for licensing details.

import unittest
from unittest.mock import patch

import ops
import yaml
from helpers import k8s_resource_multipatch, tautology
from ops.model import ActiveStatus, BlockedStatus
from ops.testing import Harness

from blackbox import BlackboxExporterApi, WorkloadManager
from charm import BlackboxExporterCharm

ops.testing.SIMULATE_CAN_CONNECT = True


class TestWithInitialHooks(unittest.TestCase):
    container_name: str = "blackbox"

    @patch.object(BlackboxExporterApi, "reload", tautology)
    @patch("socket.getfqdn", new=lambda *args: "fqdn")
    @patch("charm.BlackboxExporterCharm._external_url", new="http://0.0.0.0/")
    @k8s_resource_multipatch
    @patch("lightkube.core.client.GenericSyncClient")
    @patch.object(WorkloadManager, "_blackbox_exporter_version", property(lambda *_: "0.0.0"))
    @patch.object(WorkloadManager, "push_config")
    def setUp(self, *unused):
        self.harness = Harness(BlackboxExporterCharm)
        self.addCleanup(self.harness.cleanup)

        self.harness.set_leader(True)

        self.harness.begin_with_initial_hooks()

    @patch("socket.getfqdn", new=lambda *args: "fqdn")
    def test_pebble_layer_added(self, *unused):
        plan = self.harness.get_container_pebble_plan(self.container_name)

        # Check we've got the plan as expected
        self.assertIsNotNone(plan.services)
        self.assertIsNotNone(service := plan.services.get(self.harness.charm._service_name))
        self.assertIsNotNone(command := service.command)

        # Check command is as expected
        self.assertEqual(
            plan.services, self.harness.charm.blackbox_workload._blackbox_exporter_layer().services
        )

        # Check command contains key arguments
        self.assertIn("--config.file", command)
        self.assertIn("--web.listen-address", command)

        # Check the service was started
        service = self.harness.model.unit.get_container("blackbox").get_service("blackbox")
        self.assertTrue(service.is_running())

    @k8s_resource_multipatch
    @patch.object(WorkloadManager, "push_config")
    def test_charm_blocks_if_user_provided_config_with_templates(self, *unused):
        new_config = "some: -   malformed yaml"
        self.harness.update_config({"config_file": new_config})
        self.assertIsInstance(self.harness.charm.unit.status, BlockedStatus)

        new_config = yaml.dump({"some": "good-yaml"})
        self.harness.update_config({"config_file": new_config})
        self.assertIsInstance(self.harness.charm.unit.status, ActiveStatus)


class TestWithoutInitialHooks(unittest.TestCase):
    container_name: str = "blackbox"

    @patch.object(BlackboxExporterApi, "reload", tautology)
    @k8s_resource_multipatch
    @patch("lightkube.core.client.GenericSyncClient")
    @patch("charm.BlackboxExporterCharm._external_url", new="http://0.0.0.0/")
    def setUp(self, *unused):
        self.harness = Harness(BlackboxExporterCharm)
        self.addCleanup(self.harness.cleanup)

        self.harness.set_leader(True)

        self.harness.begin()

    @k8s_resource_multipatch
    @patch.object(WorkloadManager, "_blackbox_exporter_version", property(lambda *_: "0.0.0"))
    @patch.object(WorkloadManager, "push_config")
    def test_unit_status_around_pebble_ready(self, *unused):
        # before pebble_ready, status should be "maintenance"
        self.assertIsInstance(self.harness.charm.unit.status, ops.model.MaintenanceStatus)

        # after pebble_ready, status should be "active"
        self.harness.container_pebble_ready(self.container_name)
        self.assertIsInstance(self.harness.charm.unit.status, ops.model.ActiveStatus)

        self.assertEqual(self.harness.model.unit.name, "blackbox-exporter-k8s/0")
