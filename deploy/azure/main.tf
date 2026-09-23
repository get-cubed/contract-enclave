// Hosted demo environment: one Azure VM that plays the role of the client's
// server. It runs the same stack as the laptop demo (scripts/dev-up.sh), with
// Caddy terminating HTTPS in front of Coder.
//
// Drive it with scripts/azure-demo.sh rather than calling terraform directly:
// the script keeps state, the SSH key, and variables outside the repo and runs
// the on-VM setup after apply.
//
// Inbound (NSG): SSH and HTTPS only from the allowlisted CIDRs, plus HTTP from
// anywhere so Let's Encrypt can validate the certificate (Caddy answers port 80
// with the ACME challenge or a redirect, nothing else). Ollama (11434) and the
// raw Coder port (3000) are never reachable from outside the VM. The VM has no
// managed identity, so nothing on it holds Azure credentials.

terraform {
  required_version = ">= 1.9.0"

  required_providers {
    azurerm = {
      source  = "hashicorp/azurerm"
      version = "4.81.0"
    }
  }

  // Path is supplied by scripts/azure-demo.sh (-backend-config) so state lives
  // in the user's state directory, not in the checkout.
  backend "local" {}
}

variable "subscription_id" {
  description = "Azure subscription to deploy into"
  type        = string
}

variable "location" {
  description = "Azure region. It needs quota for vm_size's family."
  type        = string
  default     = "southcentralus"
}

variable "vm_size" {
  description = "VM size. The T4 GPU size is the demo target; a CPU size works but OCR takes minutes per page."
  type        = string
  default     = "Standard_NC4as_T4_v3"
}

variable "name" {
  description = "Name prefix for every resource"
  type        = string
  default     = "contract-enclave-demo"
}

variable "admin_username" {
  description = "Admin user on the VM (owns the synced repo and runs Coder)"
  type        = string
  default     = "azureuser"
}

variable "ssh_public_key" {
  description = "OpenSSH public key for the admin user"
  type        = string
}

variable "operator_cidrs" {
  description = "CIDRs allowed SSH and HTTPS (the operator's public IP)"
  type        = list(string)

  validation {
    condition     = length(var.operator_cidrs) > 0
    error_message = "At least one operator CIDR is required."
  }
}

variable "extra_https_cidrs" {
  description = "Additional CIDRs allowed HTTPS only (co-presenters, the client's office)"
  type        = list(string)
  default     = []
}

variable "os_disk_gb" {
  description = "OS disk size: model weights, Docker images, Coder's database"
  type        = number
  default     = 128
}

variable "auto_shutdown_time" {
  description = "Daily deallocation time (HHMM, 24h) in auto_shutdown_timezone; null disables it"
  type        = string
  default     = "2200"
  nullable    = true
}

variable "auto_shutdown_timezone" {
  description = "Windows time zone ID for auto_shutdown_time"
  type        = string
  default     = "Central Standard Time"
}

provider "azurerm" {
  features {}
  subscription_id = var.subscription_id
  // Never register resource providers as a side effect of apply. Compute,
  // Network, and DevTestLab (auto-shutdown) must already be registered.
  resource_provider_registrations = "none"
}

locals {
  // Stable per subscription, so the hostname survives a destroy/re-create.
  dns_label = "${var.name}-${substr(sha1(var.subscription_id), 0, 6)}"
  tags = {
    project    = "contract-enclave"
    purpose    = "client demo"
    managed-by = "terraform via scripts/azure-demo.sh"
  }
}

resource "azurerm_resource_group" "demo" {
  name     = "rg-${var.name}"
  location = var.location
  tags     = local.tags
}

resource "azurerm_virtual_network" "demo" {
  name                = "${var.name}-vnet"
  resource_group_name = azurerm_resource_group.demo.name
  location            = azurerm_resource_group.demo.location
  address_space       = ["10.42.0.0/24"]
  tags                = local.tags
}

resource "azurerm_subnet" "demo" {
  name                 = "demo"
  resource_group_name  = azurerm_resource_group.demo.name
  virtual_network_name = azurerm_virtual_network.demo.name
  address_prefixes     = ["10.42.0.0/26"]
}

resource "azurerm_network_security_group" "demo" {
  name                = "${var.name}-nsg"
  resource_group_name = azurerm_resource_group.demo.name
  location            = azurerm_resource_group.demo.location
  tags                = local.tags

  security_rule {
    name                       = "ssh-operator"
    priority                   = 100
    direction                  = "Inbound"
    access                     = "Allow"
    protocol                   = "Tcp"
    source_port_range          = "*"
    destination_port_range     = "22"
    source_address_prefixes    = var.operator_cidrs
    destination_address_prefix = "*"
  }

  security_rule {
    name                       = "https-allowlist"
    priority                   = 110
    direction                  = "Inbound"
    access                     = "Allow"
    protocol                   = "Tcp"
    source_port_range          = "*"
    destination_port_range     = "443"
    source_address_prefixes    = distinct(concat(var.operator_cidrs, var.extra_https_cidrs))
    destination_address_prefix = "*"
  }

  // Let's Encrypt validates from undisclosed addresses, so port 80 is open.
  // Caddy serves only the HTTP-01 challenge and an HTTPS redirect there.
  security_rule {
    name                       = "http-acme"
    priority                   = 120
    direction                  = "Inbound"
    access                     = "Allow"
    protocol                   = "Tcp"
    source_port_range          = "*"
    destination_port_range     = "80"
    source_address_prefix      = "Internet"
    destination_address_prefix = "*"
  }
}

resource "azurerm_public_ip" "demo" {
  name                = "${var.name}-ip"
  resource_group_name = azurerm_resource_group.demo.name
  location            = azurerm_resource_group.demo.location
  allocation_method   = "Static"
  sku                 = "Standard"
  domain_name_label   = local.dns_label
  tags                = local.tags
}

resource "azurerm_network_interface" "demo" {
  name                = "${var.name}-nic"
  resource_group_name = azurerm_resource_group.demo.name
  location            = azurerm_resource_group.demo.location
  tags                = local.tags

  ip_configuration {
    name                          = "primary"
    subnet_id                     = azurerm_subnet.demo.id
    private_ip_address_allocation = "Dynamic"
    public_ip_address_id          = azurerm_public_ip.demo.id
  }
}

resource "azurerm_network_interface_security_group_association" "demo" {
  network_interface_id      = azurerm_network_interface.demo.id
  network_security_group_id = azurerm_network_security_group.demo.id
}

resource "azurerm_linux_virtual_machine" "demo" {
  name                = var.name
  resource_group_name = azurerm_resource_group.demo.name
  location            = azurerm_resource_group.demo.location
  // Changing the size resizes in place (deallocating first when required), so
  // a CPU-sized VM can move to the GPU size once quota is granted. Both sizes
  // must use the SCSI disk controller (v5-and-older families do).
  size                            = var.vm_size
  admin_username                  = var.admin_username
  disable_password_authentication = true
  network_interface_ids           = [azurerm_network_interface.demo.id]
  tags                            = local.tags

  admin_ssh_key {
    username   = var.admin_username
    public_key = var.ssh_public_key
  }

  os_disk {
    caching              = "ReadWrite"
    storage_account_type = "Premium_LRS"
    disk_size_gb         = var.os_disk_gb
  }

  source_image_reference {
    publisher = "Canonical"
    offer     = "ubuntu-24_04-lts"
    sku       = "server"
    version   = "latest"
  }

  // Serial console and boot screenshots, for when SSH will not come up.
  boot_diagnostics {}
}

resource "azurerm_dev_test_global_vm_shutdown_schedule" "demo" {
  count                 = var.auto_shutdown_time == null ? 0 : 1
  virtual_machine_id    = azurerm_linux_virtual_machine.demo.id
  location              = azurerm_resource_group.demo.location
  enabled               = true
  daily_recurrence_time = var.auto_shutdown_time
  timezone              = var.auto_shutdown_timezone
  tags                  = local.tags

  notification_settings {
    enabled = false
  }
}

output "fqdn" {
  value = azurerm_public_ip.demo.fqdn
}

output "public_ip" {
  value = azurerm_public_ip.demo.ip_address
}

output "admin_username" {
  value = var.admin_username
}

output "resource_group" {
  value = azurerm_resource_group.demo.name
}

output "vm_name" {
  value = azurerm_linux_virtual_machine.demo.name
}

output "vm_size" {
  value = azurerm_linux_virtual_machine.demo.size
}

output "auto_shutdown" {
  value = var.auto_shutdown_time == null ? "disabled" : "${var.auto_shutdown_time} ${var.auto_shutdown_timezone}"
}
