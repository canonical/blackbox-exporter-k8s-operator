#!/usr/bin/env python3
# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.

import unittest

import yaml

from scrape_config_builder import ScrapeConfigBuilder


class TestScrapeConfigBuilder(unittest.TestCase):
    def setUp(self):
        """Set up the test case with a common builder instance and test data."""
        self.builder = ScrapeConfigBuilder("http://blackbox-exporter:9115")
        self.file_probes = {
            "scrape_configs": [
                {"job_name": "config_yaml_job", "static_configs": [{"targets": ["target1"]}]}
            ]
        }
        self.relation_probes = [
            {"job_name": "relation_job", "static_configs": [{"targets": ["target2"]}]}
        ]

    def test_merge_scrape_configs(self):
        """Test that file and relation probes are merged correctly."""
        merged = self.builder.merge_scrape_configs(self.file_probes, self.relation_probes)

        self.assertEqual(len(merged), 2)
        self.assertIn("config_yaml_job", [job["job_name"] for job in merged])
        self.assertIn("relation_job", [job["job_name"] for job in merged])

    def test_build_scraping_jobs(self):
        """Test that the scraping jobs are built correctly with relabel_configs."""
        scraping_jobs = self.builder.build_probes_scraping_jobs(
            file_probes=yaml.safe_dump(self.file_probes),
            relation_probes=self.relation_probes,
        )

        for job in scraping_jobs:
            self.assertIn("metrics_path", job)
            self.assertIn("relabel_configs", job)
            self.assertEqual(job["metrics_path"], "/probe")
            self.assertIsInstance(job["relabel_configs"], list)
            self.assertGreater(len(job["relabel_configs"]), 0)


if __name__ == "__main__":
    unittest.main()
