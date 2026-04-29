resource "juju_application" "blackbox_exporter" {
  name        = var.app_name
  config      = var.config
  constraints = var.constraints
  model_uuid  = var.model_uuid
  trust       = true
  units       = var.units

  charm {
    name     = "blackbox-exporter-k8s"
    channel  = var.channel
    revision = var.revision
  }
}
