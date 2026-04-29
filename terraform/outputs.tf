output "app_name" {
  value = juju_application.blackbox_exporter.name
}

output "provides" {
  value = {
    self_metrics_endpoint = "self-metrics-endpoint"
    grafana_dashboard     = "grafana-dashboard"
  }
}

output "requires" {
  value = {
    catalogue = "catalogue"
    ingress   = "ingress"
    logging   = "logging"
    probes    = "probes"
  }
}
