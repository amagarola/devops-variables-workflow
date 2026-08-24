variable "config_root" {
  type        = string
  default     = ""
  description = "Optional local config root. Defaults to this repository's config directory."
}

variable "projects" {
  type        = list(string)
  default     = []
  description = "Projects to include. Empty discovers all config subdirectories."
}

variable "topics" {
  type        = list(string)
  default     = []
  description = "Resource topics to include. Empty discovers YAML filenames."
}
