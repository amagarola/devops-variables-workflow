locals {
  config_root = var.config_root != "" ? abspath(var.config_root) : abspath("${path.module}/config")

  discovered_files    = fileset(local.config_root, "*/*.yaml")
  discovered_projects = sort(distinct([for file in local.discovered_files : split("/", file)[0]]))
  discovered_topics   = sort(distinct([for file in local.discovered_files : trimsuffix(basename(file), ".yaml")]))

  projects = length(var.projects) > 0 ? var.projects : local.discovered_projects
  topics   = length(var.topics) > 0 ? var.topics : local.discovered_topics

  loaded = {
    for pair in setproduct(local.projects, local.topics) :
    "${pair[0]}/${pair[1]}" => yamldecode(file("${local.config_root}/${pair[0]}/${pair[1]}.yaml"))
    if fileexists("${local.config_root}/${pair[0]}/${pair[1]}.yaml")
  }

  config = {
    for topic in local.topics :
    topic => {
      for project in local.projects :
      project => local.loaded["${project}/${topic}"][topic]
      if try(local.loaded["${project}/${topic}"][topic], null) != null
    }
  }
}
