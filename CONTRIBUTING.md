# Contributing to blackbox-exporter-k8s

![GitHub](https://img.shields.io/github/license/canonical/blackbox-exporter-k8s-operator)
![GitHub commit activity](https://img.shields.io/github/commit-activity/y/canonical/blackbox-exporter-k8s-operator)
![GitHub](https://img.shields.io/tokei/lines/github/canonical/blackbox-exporter-k8s-operator)
![GitHub](https://img.shields.io/github/issues/canonical/blackbox-exporter-k8s-operator)
![GitHub](https://img.shields.io/github/issues-pr/canonical/blackbox-exporter-k8s-operator) ![GitHub](https://img.shields.io/github/contributors/canonical/blackbox-exporter-k8s-operator) ![GitHub](https://img.shields.io/github/watchers/canonical/blackbox-exporter-k8s-operator?style=social)

## Overview

This documents explains the processes and practices recommended for
contributing enhancements or bug fixing to the Blackbox Exporter Charmed Operator.

The intended use case of this operator is to be deployed as part of the
[COS Lite] bundle, although that is not necessary.

## Setup

A typical setup using [snaps](https://snapcraft.io/) can be found in the
[Juju docs](https://juju.is/docs/sdk/dev-setup).

## Developing

- Prior to getting started on a pull request, we first encourage you to open an
  issue explaining the use case or bug.
  This gives other contributors a chance to weigh in early in the process.
- To author PRs you should be familiar with [juju](https://juju.is/#what-is-juju)
  and [how operators are written](https://juju.is/docs/sdk).
- The best way to get a head start is to join the conversation on our
  [Mattermost channel] or [Discourse].
- All enhancements require review before being merged. Besides the
  code quality and test coverage, the review will also take into
  account the resulting user experience for Juju administrators using
  this charm. To be able to merge you would have to rebase
  onto the `main` branch. We do this to avoid merge commits and to have a
  linear Git history.
- We use [`tox`](https://tox.wiki/en/latest/#) to manage all virtualenvs for
  the development lifecycle.

### Testing

Unit tests are written with the Operator Framework [test harness] and
integration tests are written using [pytest-operator] and [python-libjuju].

The default test environments - lint, static and unit - will run if you start
`tox` without arguments.

You can also manually run a specific test environment:

```shell
tox -e fmt              # update your code according to linting rules
tox -e lint             # code style
tox -e static           # static analysis
tox -e unit             # unit tests
tox -e integration      # integration tests
```

`tox` creates a virtual environment for every tox environment defined in
[tox.ini](tox.ini). To activate a tox environment for manual testing,

```shell
source .tox/unit/bin/activate
```

## Build charm

Build the charm in this git repository using

```shell
charmcraft pack
```

which will create a `*.charm` file you can deploy with:

```shell
juju deploy ./blackbox-exporter-k8s.charm \
  --resource blackbox-exporter-image=ubuntu/blackbox-exporter \
  --config config_file='@path/to/blackbox-exporter.yaml'
```

## Design choices

- The `config.yaml` config file is created in its entirety by the charm
  code on startup. This is done to maintain consistency across OCI images.

[gh:Prometheus operator]: https://github.com/canonical/prometheus-k8s-operator
[Prometheus operator]: https://charmhub.io/prometheus-k8s
[COS Lite]: https://charmhub.io/cos-lite
[Mattermost channel]: https://chat.charmhub.io/charmhub/channels/observability
[Discourse]: https://discourse.charmhub.io/tag/blackbox-exporter
[test harness]: https://ops.readthedocs.io/en/latest/#module-ops.testing
[pytest-operator]: https://github.com/charmed-kubernetes/pytest-operator/blob/main/docs/reference.md
[python-libjuju]: https://pythonlibjuju.readthedocs.io/en/latest/
