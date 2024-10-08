# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.

import json
import unittest
from typing import List

from charms.blackbox_k8s.v0.blackbox_probes import BlackboxProbesRequirer
from ops.charm import CharmBase
from ops.framework import StoredState
from ops.testing import Harness

RELATION_NAME = "blackbox-probes"

REQUIRER_META = f"""
name: requirer-tester
containers:
  blackbox-tester:
requires:
  {RELATION_NAME}:
    interface: blackbox_probes
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

MODULES: dict = {
    "http_2xx_longer_timeout": {
        "prober": "http",
        "timeout": "30s",
    }
}

SCRAPE_METADATA = {
    "model": "consumer-model",
    "model_uuid": "12de4fae-06cc-4ceb-9089-567be09fec78",
    "application": "consumer",
    "charm_name": "test-charm",
    "unit": "test-unit",
}


class BlackboxProbesRequirerCharm(CharmBase):
    _stored = StoredState()

    def __init__(self, *args, **kwargs):
        super().__init__(*args)
        self._stored.set_default(num_events=0)
        self.probes_consumer = BlackboxProbesRequirer(self, RELATION_NAME)
        self.framework.observe(self.probes_consumer.on.targets_changed, self.record_events)

    def record_events(self, event):
        self._stored.num_events += 1

    @property
    def version(self):
        return "1.0.0"


class BlackboxProbesRequirerTest(unittest.TestCase):
    def setUp(self):
        self.harness = Harness(BlackboxProbesRequirerCharm, meta=REQUIRER_META)

        self.addCleanup(self.harness.cleanup)
        self.harness.begin()

    def setup_charm_relations(self):
        """Create relations used by test cases."""
        rel_ids = []
        self.assertEqual(self.harness.charm._stored.num_events, 0)
        rel_id = self.harness.add_relation(RELATION_NAME, "consumer")
        rel_ids.append(rel_id)
        self.harness.update_relation_data(
            rel_id,
            "consumer",
            {
                "scrape_metadata": json.dumps(SCRAPE_METADATA),
                "scrape_probes": json.dumps(PROBES),
                "scrape_modules": json.dumps(MODULES),
            },
        )
        self.assertEqual(self.harness.charm._stored.num_events, 1)

        return rel_ids

    def test_consumer_notifies_on_new_scrape_metadata_relation(self):
        self.assertEqual(self.harness.charm._stored.num_events, 0)

        rel_id = self.harness.add_relation(RELATION_NAME, "consumer")
        self.harness.update_relation_data(
            rel_id, "consumer", {"scrape_metadata": json.dumps(SCRAPE_METADATA)}
        )
        self.assertEqual(self.harness.charm._stored.num_events, 1)

    def test_consumer_notifies_on_new_probes_target(self):
        self.assertEqual(self.harness.charm._stored.num_events, 0)
        rel_id = self.harness.add_relation(RELATION_NAME, "consumer")
        self.harness.add_relation_unit(rel_id, "consumer/0")
        self.harness.update_relation_data(
            rel_id, "consumer/0", {"scrape_probes": json.dumps(PROBES)}
        )
        self.assertEqual(self.harness.charm._stored.num_events, 1)

    def test_consumer_notifies_on_new_modules_target(self):
        self.assertEqual(self.harness.charm._stored.num_events, 0)
        rel_id = self.harness.add_relation(RELATION_NAME, "consumer")
        self.harness.add_relation_unit(rel_id, "consumer/0")
        self.harness.update_relation_data(
            rel_id, "consumer/0", {"scrape_modules": json.dumps(MODULES)}
        )
        self.assertEqual(self.harness.charm._stored.num_events, 1)

    def test_consumer_returns_all_probes_targets(self):
        self.setup_charm_relations()

        probes = self.harness.charm.probes_consumer.probes()
        self.assertEqual(len(probes), 2)
        self.assertEqual(type(probes), list)
