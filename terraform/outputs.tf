output "app_name" {
  value       = juju_application.blackbox_exporter.name
  description = "The name of the deployed application"
}

output "requires" {
  value = {
    catalogue = "catalogue"
    ingress   = "ingress"
    logging   = "logging"
    probes    = "probes"
  }
  description = "Map of the integration endpoints required by the application"
}

output "provides" {
  value = {
    self_metrics_endpoint = "self-metrics-endpoint"
    grafana_dashboard     = "grafana-dashboard"
  }
  description = "Map of the integration endpoints provided by the application"
}
