variable "topology" {
  description = "계정과 서버 배치의 단일 설정."
  type = object({
    project = string
    region  = string
    az_ids  = map(string)
    accounts = map(object({
      id                  = string
      profile             = string
      vpc_cidr            = string
      public_subnets      = bool
      egress              = string
      ami_id              = string
      ssh_public_key_path = string
      key_pair_name       = string
    }))
    nodes = map(object({
      account       = string
      role          = string
      az            = string
      subnet_tier   = string
      instance_type = string
      root_gib      = number
      public_ip     = bool
      data_disks = map(object({
        size_gib    = number
        type        = string
        device_name = string
      }))
    }))
    peerings = list(string)
    alb = object({
      enabled              = bool
      account              = string
      certificate_arn      = string
      frontend_role        = string
      game_role            = string
      ad_role              = string
      static_path          = string
      ad_path              = string
      frontend_health_path = string
      game_health_path     = string
      ad_health_path       = string
    })
  })
  validation {
    condition = (
      toset(keys(var.topology.accounts)) == toset(["account1", "account2", "account3", "account4", "account5"]) &&
      length(distinct([for a in values(var.topology.accounts) : a.id])) == 5 &&
      length(distinct([for a in values(var.topology.accounts) : a.vpc_cidr])) == 5 &&
      alltrue([for a in values(var.topology.accounts) :
        can(regex("^[0-9]{12}$", a.id)) && trimspace(a.profile) != "" &&
        try(format("%s/%s", cidrhost(a.vpc_cidr, 0), split("/", a.vpc_cidr)[1]), "") == a.vpc_cidr &&
        can(regex("^[0-9]+\\.[0-9]+\\.0\\.0/16$", a.vpc_cidr)) &&
        contains(["proxy", "nat", "none"], a.egress) &&
        (a.egress != "nat" || a.public_subnets)
      ])
    )
    error_message = "5개 계정의 ID·프로필·VPC CIDR·인터넷 송신 설정을 확인하세요. NAT에는 퍼블릭 서브넷이 필요합니다."
  }
  validation {
    condition = (
      toset(keys(var.topology.az_ids)) == toset(["a"]) &&
      length(distinct(values(var.topology.az_ids))) == 1 &&
      alltrue([for id in values(var.topology.az_ids) : can(regex("^apne2-az[0-9]+$", id))]) &&
      var.topology.region == "ap-northeast-2"
    )
    error_message = "테스트 환경은 서울 리전의 물리 AZ ID 하나를 a로 지정하세요."
  }
  validation {
    condition = alltrue([for name, n in var.topology.nodes :
      contains(keys(var.topology.accounts), n.account) &&
      contains(keys(var.topology.az_ids), n.az) &&
      contains(["public", "private"], n.subnet_tier) &&
      (n.subnet_tier != "public" || try(var.topology.accounts[n.account].public_subnets, false)) &&
      (!n.public_ip || n.subnet_tier == "public") &&
      n.root_gib >= 20 && floor(n.root_gib) == n.root_gib &&
      alltrue([for d in values(n.data_disks) : d.type == "gp3" && d.size_gib >= 1 && floor(d.size_gib) == d.size_gib]) &&
      length(distinct([for d in values(n.data_disks) : d.device_name])) == length(n.data_disks)
    ])
    error_message = "서버의 계정·AZ·서브넷·공인 IP·디스크 설정이 올바르지 않습니다."
  }
}

variable "traffic" {
  description = "역할별 TCP 연결과 외부 공개 범위."
  type = object({
    admin_public_cidrs = list(string)
    game_client_cidrs  = list(string)
    public_http_cidrs  = optional(list(string))
    ports              = map(number)
    connections = map(object({
      sources = list(string)
      targets = list(string)
      port    = string
      # 생략하면 기존처럼 포트 하나만 허용한다. 값은 ports의 끝 포트 이름이다.
      port_end = optional(string)
    }))
    internet_https_roles = list(string)
  })
  validation {
    condition     = alltrue([for p in values(var.traffic.ports) : p >= 1 && p <= 65535 && floor(p) == p])
    error_message = "TCP 포트는 1~65535의 정수여야 합니다."
  }
  validation {
    condition = alltrue([for c in concat(var.traffic.admin_public_cidrs, var.traffic.game_client_cidrs, coalesce(var.traffic.public_http_cidrs, [])) :
      can(regex("^[0-9]+\\.[0-9]+\\.[0-9]+\\.[0-9]+/[0-9]+$", c)) &&
      try(format("%s/%s", cidrhost(c, 0), split("/", c)[1]), "") == c
    ]) && !contains(var.traffic.admin_public_cidrs, "0.0.0.0/0")
    error_message = "외부 CIDR은 정규 IPv4 네트워크 주소여야 하며 관리자 SSH에 /0을 허용하지 않습니다."
  }
  validation {
    condition = alltrue([for c in values(var.traffic.connections) :
      try(var.traffic.ports[coalesce(c.port_end, c.port)] >= var.traffic.ports[c.port], false)
    ])
    error_message = "연결의 시작·끝 포트 이름이 ports에 있어야 하며 끝 포트는 시작 포트 이상이어야 합니다."
  }
}

locals {
  roles = { for account in keys(var.topology.accounts) : account => toset(concat(
    [for n in values(var.topology.nodes) : n.role if n.account == account],
    var.topology.alb.enabled && var.topology.alb.account == account ? ["alb"] : []
  )) }
  groups = flatten([for account, roles in local.roles : [
    for role in roles : { account = account, role = role, key = "${account}/${role}" }
  ]])
  # 역할 관계를 실제 계정별 SG 쌍으로 펼친다. 서버 배치를 바꾸면 함께 갱신된다.
  flow_list = flatten([for name, c in var.traffic.connections : [
    for src in local.groups : [
      for dst in local.groups : {
        key            = "${name}/${src.key}/${dst.key}"
        source         = src.key
        target         = dst.key
        source_account = src.account
        target_account = dst.account
        port           = var.traffic.ports[c.port]
        port_end       = try(var.traffic.ports[coalesce(c.port_end, c.port)], var.traffic.ports[c.port])
      } if contains(c.targets, dst.role)
    ] if contains(c.sources, src.role)
  ]])
  flows = { for flow in local.flow_list : flow.key => flow }
}
output "topology" { value = var.topology }
output "traffic" { value = var.traffic }
output "roles" { value = local.roles }
output "flows" { value = local.flows }

# 잘못 쓴 역할명과 연결명을 조용히 무시하지 않도록 설정 관계를 검사한다.
resource "terraform_data" "configuration" {
  lifecycle {
    precondition {
      condition = alltrue([for c in values(var.traffic.connections) :
        alltrue([for role in concat(c.sources, c.targets) : contains(distinct([for g in local.groups : g.role]), role)])
      ])
      error_message = "통신 설정에 어떤 서버에도 존재하지 않는 역할이 있습니다."
    }
    precondition {
      condition = alltrue([for pair in var.topology.peerings : contains(flatten([
        for i, a in keys(var.topology.accounts) : [for j, b in keys(var.topology.accounts) : "${a}-${b}" if i < j]
      ]), pair)]) && length(distinct(var.topology.peerings)) == length(var.topology.peerings)
      error_message = "Peering은 account1-account2처럼 계정 순서대로 중복 없이 지정하세요."
    }
    precondition {
      condition = !var.topology.alb.enabled || try(
        var.topology.accounts[var.topology.alb.account].public_subnets &&
        length([for n in values(var.topology.nodes) : n if n.account == var.topology.alb.account && n.role == var.topology.alb.frontend_role]) > 0 &&
        length([for n in values(var.topology.nodes) : n if n.account == var.topology.alb.account && n.role == var.topology.alb.game_role]) > 0 &&
        length([for n in values(var.topology.nodes) : n if n.account == var.topology.alb.account && n.role == var.topology.alb.ad_role]) > 0, false
      )
      error_message = "ALB에는 같은 계정의 퍼블릭 서브넷과 frontend·game·ad 대상이 필요합니다."
    }
  }
}
