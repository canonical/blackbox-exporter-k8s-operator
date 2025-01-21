#!/usr/bin/env python3
# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.

"""Helper class to build scrape configurations for Blackbox Exporter."""

from typing import Any, Dict, List
from urllib.parse import urlparse

import yaml


class ScrapeConfigBuilder:
    """Helper class to build scrape configurations for Blackbox Exporter."""

    def __init__(self, external_url: str):
        """Initialize the ScrapeConfigBuilder.

        :param external_url: The external URL to be used for constructing probes' `metrics_path` and `relabel_configs`.
        """
        self.external_url = external_url

    def merge_scrape_configs(
        self, file_probes: Dict[str, Any], relation_probes: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """Merge the scrape_configs from both file and relation.

        The relation probes are hashed to ensure uniquess in the blackbox_probes.py library.
        However, in case of same `job_name` the relation probe takes precedence,
        overriding the corresponding file probe.

        Args:
            file_probes: data parsed from the "probes_file" configuration, loaded as a dictionary.
                Defaults to an empty dictionary if no valid YAML or config entry is found.
            relation_probes: a list of dicts probes extracted from a relation. Relation probes job_names
                are hashed to ensure uniqueness and avoid conflict.

        Returns:
            A list of dicts representing the merged probes from both file and relation data.
        """
        merged_scrape_configs = {
            probe["job_name"]: probe for probe in file_probes.get("scrape_configs", [])
        }

        for probe in relation_probes:
            job_name = probe["job_name"]
            merged_scrape_configs[job_name] = probe

        return list(merged_scrape_configs.values())

    def build_probes_scraping_jobs(
        self,
        file_probes: str,
        relation_probes: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        """Build list of probes scraping jobs.

        Args:
            file_probes: data parsed from the "probes_file" configuration, loaded as a dictionary.
                Defaults to an empty dictionary if no valid YAML or config entry is found.
            relation_probes: a list of dicts probes extracted from a relation.

        Returns:
            A list of scraping jobs with blackbox relabel configs.
        """
        external_url = urlparse(self.external_url)
        probes_path = f"{external_url.path.rstrip('/')}/probe"

        file_probes_scrape_jobs_dict = yaml.safe_load(file_probes) if file_probes else {}

        merged_scrape_configs = self.merge_scrape_configs(
            file_probes_scrape_jobs_dict, relation_probes
        )

        # Add the Blackbox Exporter's `relabel_configs` to each job
        for probe in merged_scrape_configs:
            probe["metrics_path"] = probes_path
            probe["relabel_configs"] = [
                {"source_labels": ["__address__"], "target_label": "__param_target"},
                {"source_labels": ["__param_target"], "target_label": "instance"},
                {"source_labels": ["__param_target"], "target_label": "probe_target"},
                {"target_label": "__address__", "replacement": external_url.hostname},
            ]

        return merged_scrape_configs
