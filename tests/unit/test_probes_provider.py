# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.

import json
import unittest
from typing import List

from charms.blackbox_k8s.v0.blackbox_probes import BlackboxProbesProvider
from cosl import JujuTopology
from ops.charm import CharmBase
from ops.framework import StoredState
from ops.model import (
    ActiveStatus,
    BlockedStatus,
)
from ops.testing import Harness

RELATION_NAME = "probes"

PROVIDER_META = f"""
name: provider-tester
containers:
  blackbox-tester:
provides:
  {RELATION_NAME}:
    interface: blackbox_exporter_probes
"""


PROBES: List[dict] = [
    {
        "job_name": "my-first-job",
        "params": {"module": ["http_2xx"]},
        "static_configs": [
            {
                "targets": ["10.1.238.1"],
                "labels": {"some_key": "some-value"},
            }
        ],
    },
    {
        "job_name": "my-second-job",
        "params": {
            "module": ["icmp"],
        },
        "static_configs": [
            {"targets": ["10.1.238.1"], "labels": {"some_other_key": "some-other-value"}}
        ],
    },
]

PROBES_NOT_VALID_MISSING_STATIC_CONFIG: List[dict] = [
    {
        "job_name": "my-first-job",
        "params": {"module": ["http_2xx"]},
    }
]

PROBES_NOT_VALID_MISSING_MODULE: List[dict] = [
    {
        "job_name": "my-first-job",
        "static_configs": [
            {
                "targets": ["10.1.238.1"],
                "labels": {"some_key": "some-value"},
            }
        ],
    },
]

MODULES: dict = {
    "http_2xx_longer_timeout": {
        "prober": "http",
        "timeout": "30s",
    }
}


class BlackboxProbesProviderCharmWithModules(CharmBase):
    def __init__(self, *args, **kwargs):
        super().__init__(*args)

        self.provider = BlackboxProbesProvider(self, probes=PROBES, modules=MODULES)


class BlackboxProbesProviderTest(unittest.TestCase):
    def setUp(self):
        self.harness = Harness(BlackboxProbesProviderCharmWithModules, meta=PROVIDER_META)
        self.harness.set_model_name("MyUUID")
        self.addCleanup(self.harness.cleanup)
        self.harness.set_leader(True)
        self.harness.begin_with_initial_hooks()

    def test_provider_sets_scrape_metadata(self):
        # GIVEN a charm with a Blackbox Probes provider
        rel_id = self.harness.add_relation(RELATION_NAME, "provider")
        self.harness.add_relation_unit(rel_id, "provider/0")

        # WHEN the provider sets the probe specification
        self.harness.charm.provider._set_probes_spec()

        # THEN the scrape metadata is added to the relation data
        data = self.harness.get_relation_data(rel_id, self.harness.model.app.name)
        scrape_metadata = json.loads(data["scrape_metadata"])
        mandatory_keys = {"model", "unit", "model_uuid", "application"}
        self.assertEqual(mandatory_keys, mandatory_keys.intersection(scrape_metadata.keys()))

    def test_provider_sets_probes_on_relation_joined(self):
        # GIVEN a charm with a Blackbox Probes provider
        rel_id = self.harness.add_relation(RELATION_NAME, "provider")
        self.harness.add_relation_unit(rel_id, "provider/0")

        # WHEN the provider sets the probe specification
        self.harness.charm.provider._set_probes_spec()

        # THEN the probes data is added to the relation data
        data = self.harness.get_relation_data(rel_id, self.harness.model.app.name)
        self.assertIn("scrape_probes", data)
        scrape_data = json.loads(data["scrape_probes"])
        self.assertEqual(scrape_data[0]["static_configs"][0]["targets"], ["10.1.238.1"])
        self.assertEqual(scrape_data[0]["params"]["module"], ["http_2xx"])

    def test_provider_sets_modules_with_prefix_on_relation_joined(self):
        # GIVEN a charm with a Blackbox Probes provider
        rel_id = self.harness.add_relation(RELATION_NAME, "provider")
        self.harness.add_relation_unit(rel_id, "provider/0")

        # WHEN the provider sets the probe specification
        self.harness.charm.provider._set_probes_spec()

        # THEN the probes modules data is added to the relation data
        data = self.harness.get_relation_data(rel_id, self.harness.model.app.name)
        self.assertIn("scrape_modules", data)
        scrape_modules = json.loads(data["scrape_modules"])

        topology = JujuTopology.from_dict(json.loads(data["scrape_metadata"]))
        module_name_prefix = "juju_{}_".format(topology.identifier)

        self.assertIn(f"{module_name_prefix}http_2xx_longer_timeout", scrape_modules)

    def test_provider_prefixes_jobs(self):
        # GIVEN a charm with a Blackbox Probes provider
        rel_id = self.harness.add_relation(RELATION_NAME, "provider")
        self.harness.add_relation_unit(rel_id, "provider/0")

        # WHEN the provider sets the probe specification
        self.harness.charm.provider._set_probes_spec()

        # THEN the probes are added to the relation data with prefixed metadata
        data = self.harness.get_relation_data(rel_id, self.harness.model.app.name)
        scrape_data = json.loads(data["scrape_probes"])
        topology = JujuTopology.from_dict(json.loads(data["scrape_metadata"]))
        module_name_prefix = "juju_{}_".format(topology.identifier)

        self.assertEqual(scrape_data[0]["job_name"], f"{module_name_prefix}my-first-job")

    def test_provider_prefixes_modules(self):
        # GIVEN a charm with a Blackbox Probes provider
        rel_id = self.harness.add_relation(RELATION_NAME, "provider")
        self.harness.add_relation_unit(rel_id, "provider/0")

        # WHEN the provider sets the probe specification
        self.harness.charm.provider._set_probes_spec()

        # THEN the probes modules are added to the relation data with prefixed metadata
        data = self.harness.get_relation_data(rel_id, self.harness.model.app.name)
        scrape_data = json.loads(data["scrape_modules"])
        topology = JujuTopology.from_dict(json.loads(data["scrape_metadata"]))
        module_name_prefix = "juju_{}_".format(topology.identifier)
        actual_key = next(iter(scrape_data.keys()))
        expected_key = f"{module_name_prefix}http_2xx_longer_timeout"
        self.assertEqual(actual_key, expected_key)

    def test_get_active_status(self):
        self.addCleanup(self.harness.cleanup)

        # GIVEN a charm with a Blackbox Probes provider providing valid probes
        rel_id = self.harness.add_relation(RELATION_NAME, "provider")
        self.harness.add_relation_unit(rel_id, "provider/0")

        # WHEN the provider sets the probe specification
        self.harness.charm.provider._set_probes_spec()

        # THEN the status of the charm is set to Active
        status = self.harness.charm.provider.get_status()
        assert status == ActiveStatus()


class BlackboxProbesProviderCharmWithWrongProbe(CharmBase):
    _stored = StoredState()

    def __init__(self, *args, **kwargs):
        super().__init__(*args)
        self._stored.set_default(num_events=0)
        self.provider = BlackboxProbesProvider(
            self, probes=PROBES_NOT_VALID_MISSING_MODULE, modules=MODULES
        )


class BlackboxProbesWrongProviderTest(unittest.TestCase):
    def setUp(self):
        self.harness = Harness(BlackboxProbesProviderCharmWithWrongProbe, meta=PROVIDER_META)
        self.harness.set_model_name("MyUUID")
        self.addCleanup(self.harness.cleanup)
        self.harness.set_leader(True)
        self.harness.begin()

    def test_get_blocked_status_on_invalid_probe(self):
        self.assertEqual(self.harness.charm._stored.num_events, 0)

        # GIVEN a charm with a Blackbox Probes provider providing invalid probes
        rel_id = self.harness.add_relation(RELATION_NAME, "provider")
        self.harness.add_relation_unit(rel_id, "provider/0")

        # WHEN the provider sets the probe specification
        self.harness.charm.provider._set_probes_spec()

        # THEN the status of the charm is set to Blocked
        status = self.harness.charm.provider.get_status()
        assert status == BlockedStatus("Errors occurred in probe configuration")
