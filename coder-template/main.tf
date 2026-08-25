// Coder workspace template: "Contract Analysis Workspace" (enclave edition)
//
// Workspaces are confined to a pre-existing *internal* Docker network. They
// have no route to the outside world; the only things they can reach are the
// Coder server and the model endpoint, which are attached to that network
// (directly on a server install, via single-port gateways on a laptop).
// Nothing is downloaded at runtime -- see build/Dockerfile.

terraform {
  required_providers {
    coder = {
      source = "coder/coder"
    }
    docker = {
      source = "kreuzwerker/docker"
    }
  }
}

variable "model_base_url" {
  description = "OpenAI-compatible endpoint reachable from inside the enclave"
  default     = "http://model:11434/v1"
}

variable "model_name" {
  description = "Model name to request at the endpoint"
  # NOTE: the bare qwen3-vl:8b Ollama tag is the *thinking* variant, which
  # returns empty content on JSON-extraction prompts. Use -instruct.
  default = "qwen3-vl:8b-instruct"
}

variable "repo_host_path" {
  description = "Host path of the contract-enclave repo to mount into workspaces"
  default     = "/opt/contract-enclave"
}

variable "enclave_network" {
  description = "Name of the pre-existing internal Docker network workspaces are confined to"
  default     = "enclave"
}

variable "agent_coder_url" {
  description = "How the workspace agent reaches the Coder server from inside the enclave"
  default     = "http://coder:3000"
}

provider "docker" {}

data "coder_provisioner" "me" {}
data "coder_workspace" "me" {}
data "coder_workspace_owner" "me" {}

data "docker_network" "enclave" {
  name = var.enclave_network
}

resource "coder_agent" "main" {
  os   = "linux"
  arch = data.coder_provisioner.me.arch

  env = {
    MODEL_BASE_URL = var.model_base_url
    MODEL_NAME     = var.model_name
    MODEL_API_KEY  = "local"
    # Python env is baked into the image; uv must never try the network.
    UV_PROJECT_ENVIRONMENT = "/opt/venv"
    UV_OFFLINE             = "1"
    UV_FROZEN              = "1"
  }

  startup_script = <<-EOT
    set -e
    mkdir -p /home/coder/contract-enclave/reports
    cd /home/coder/contract-enclave/pipeline
    uv sync   # offline + frozen: fails loudly if the image is stale
    echo "Enclave workspace ready. Try:"
    echo "  cd ~/contract-enclave/pipeline"
    echo "  uv run -m contract_pipeline.cli analyze ../sample-contracts/*.pdf --out ../reports"
  EOT

  metadata {
    display_name = "CPU"
    key          = "cpu"
    script       = "coder stat cpu"
    interval     = 10
    timeout      = 1
  }
  metadata {
    display_name = "RAM"
    key          = "ram"
    script       = "coder stat mem"
    interval     = 10
    timeout      = 1
  }
}

module "code_server" {
  source         = "registry.coder.com/coder/code-server/coder"
  version        = "~> 1.0"
  agent_id       = coder_agent.main.id
  folder         = "/home/coder/contract-enclave"
  offline        = true
  install_prefix = "/opt/code-server"
}

// Serves the generated HTML reports inside the workspace (no downloads needed).
resource "coder_script" "reports" {
  agent_id     = coder_agent.main.id
  display_name = "Reports server"
  run_on_start = true
  script       = <<-EOT
    mkdir -p /home/coder/contract-enclave/reports
    cd /home/coder/contract-enclave/reports
    nohup python3 -m http.server 8088 --bind 127.0.0.1 > /tmp/reports-server.log 2>&1 &
  EOT
}

resource "coder_app" "reports" {
  agent_id     = coder_agent.main.id
  slug         = "reports"
  display_name = "Reports"
  url          = "http://localhost:8088"
  icon         = "/icon/folder.svg"
  share        = "owner"
  subdomain    = false
}

resource "docker_image" "workspace" {
  name = "contract-enclave-workspace:latest"
  build {
    context = "./build"
  }
  triggers = {
    dockerfile = filesha1("${path.module}/build/Dockerfile")
    lock       = filesha1("${path.module}/build/uv.lock")
    pyproject  = filesha1("${path.module}/build/pyproject.toml")
  }
}

resource "docker_volume" "home" {
  name = "coder-${data.coder_workspace.me.id}-home"
  lifecycle {
    ignore_changes = all
  }
}

resource "docker_container" "workspace" {
  count = data.coder_workspace.me.start_count
  image = docker_image.workspace.image_id
  name  = "coder-${data.coder_workspace_owner.me.name}-${lower(data.coder_workspace.me.name)}"

  hostname = data.coder_workspace.me.name

  # The agent's init script embeds the public access URL. Rewrite it to the
  # in-enclave route so the agent downloads itself and connects only through
  # the allowlisted path.
  entrypoint = ["sh", "-c", replace(coder_agent.main.init_script, data.coder_workspace.me.access_url, var.agent_coder_url)]
  env        = ["CODER_AGENT_TOKEN=${coder_agent.main.token}"]

  # The whole point: this is the container's ONLY network, and it is internal.
  network_mode = data.docker_network.enclave.name

  volumes {
    container_path = "/home/coder"
    volume_name    = docker_volume.home.name
    read_only      = false
  }
  volumes {
    container_path = "/home/coder/contract-enclave"
    host_path      = var.repo_host_path
    read_only      = false
  }
}
