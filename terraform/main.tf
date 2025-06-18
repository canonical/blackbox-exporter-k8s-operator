# -------------- # Model --------------

data "juju_model" "model" {
  name = var.model
}

# -------------- # Application --------------

resource "juju_application" "blackbox_exporter" {
  name  = var.app_name
  model = data.juju_model.model.name
  # We always need this variable to be true in order
  # to be able to apply resources limits.
  trust = true
  charm {
    name     = "blackbox-exporter-k8s"
    channel  = var.channel
    revision = var.revision
  }
  units       = var.units
  config      = var.config
  constraints = var.constraints
  resources   = var.resources
}
