# Blackbox Exporter Operator (k8s)
[![Charmhub Badge](https://charmhub.io/blackbox-exporter-k8s/badge.svg)](https://charmhub.io/blackbox-exporter-k8s)
[![Release](https://github.com/canonical/blackbox-exporter-k8s-operator/actions/workflows/release.yaml/badge.svg)](https://github.com/canonical/blackbox-exporter-k8s-operator/actions/workflows/release.yaml)
[![Discourse Status](https://img.shields.io/discourse/status?server=https%3A%2F%2Fdiscourse.charmhub.io&style=flat&label=CharmHub%20Discourse)](https://discourse.charmhub.io)

[Charmed Blackbox Exporter (blackbox-exporter-k8s)][Blackbox Exporter operator] is a charm for
[Blackbox Exporter].

The charm imposes configurable resource limits on the workload, can be readily
integrated with [prometheus][Prometheus operator], [grafana][Grafana operator]
and [loki][Loki operator], and it comes with built-in alert rules and dashboards for
self-monitoring.

[Blackbox Exporter]: https://github.com/prometheus/blackbox_exporter
[Grafana operator]: https://charmhub.io/grafana-k8s
[Loki operator]: https://charmhub.io/loki-k8s
[Prometheus operator]: https://charmhub.io/prometheus-k8s
[Blackbox Exporter operator]: https://charmhub.io/blackbox-exporter-k8s


## Getting started

### Basic deployment

Once you have a controller and model ready, you can deploy the blackbox exporter
using the Juju CLI:

```shell
juju deploy --channel=beta blackbox-exporter-k8s
```

The available [channels](https://snapcraft.io/docs/channels) are listed at the top
of [the page](https://charmhub.io/blackbox-exporter-k8s) and can also be retrieved with
Charmcraft CLI:

```shell
$ charmcraft status blackbox-exporter-k8s

Track    Base                  Channel    Version    Revision    Resources
latest   ubuntu 22.04 (amd64)  stable     -          -           -
                               candidate  -          -           -
                               beta       1          1           blackbox-exporter-image (r1)
                               edge       1          1           blackbox-exporter-image (r1)
```

Once the Charmed Operator is deployed, the status can be checked by running:

```shell
juju status --relations --storage --color
```


### Configuration

In order to configure the Blackbox Exporter, a [configuration file](https://github.com/prometheus/blackbox_exporter/blob/master/CONFIGURATION.md)
should be provided using the
[`config_file`](https://charmhub.io/blackbox-exporter-k8s/configure#config_file) option:

```shell
juju config blackbox-exporter-k8s \
  config_file='@path/to/blackbox.yml'
```

To verify Blackbox Exporter is using the expected configuration you can use the
[`show-config`](https://charmhub.io/blackbox-exporter-k8s/actions#show-config) action:

```shell
juju run-action blackbox-exporter-k8s/0 show-config --wait
```

To configure the actual probes, there first needs to be a Prometheus relation:

```shell
juju relate blackbox-exporter-k8s prometheus
```

Then, the probes configuration should be written to a file (following the 
[Blackbox Exporter docs](https://github.com/prometheus/blackbox_exporter#prometheus-configuration)
) and passed via `juju config`:

```shell
juju config blackbox-exporter-k8s \
  probes_file='@path/to/probes.yml'
```

Note that the `relabel_configs` of each scrape job doesn't need to be specified, and will be
overridden by the charm with the needed labels and the correct Blackbox Exporter url.

#### Dynamic Configuration

The list of probes and the list of modules for probing can also be changed dynamically from other charms.
This charm offers a relation to allow charms to forward custom probes spec to Blackbox Exporter. Those are exported over the probes relation using the blackbox_exporter_probes interface:

```shell
requires:
  probes:
    interface: blackbox_exporter_probes
```

The custom probes provided via relation data are merged with the probes defined in the juju config `probes_file` parameter.
The modules custom defined modules are instead integrated with the modules defined in the juju config `blackbox-config` parameter.
In order for the charm defined probes to be probed via this charm all that is required is to relate the two charms with:

```shell
juju relate <charm> blackbox:probes
```

Charms that seek to provide probes for Blackbox Exporter, can do so using the provided blackbox_exporter_probes charm library. This library ensures that probes and modules defined by a charm are forwarded correctly to Prometheus, and the metrics displayed in the associated Grafana Dashboard.

## OCI Images
This charm is published on Charmhub with blackbox exporter images from
the official [quay.io/prometheus/blackbox-exporter].

[quay.io/prometheus/blackbox-exporter]: https://quay.io/repository/prometheus/blackbox-exporter?tab=tags

## Additional Information
- [Blackbox Exporter README](https://github.com/prometheus/blackbox-exporter)
