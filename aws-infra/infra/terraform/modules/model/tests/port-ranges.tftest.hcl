# AWS 없이 연결 입력의 포트 범위와 기존 단일 포트 호환성을 검사한다.
variables {
  topology = jsondecode(file("../../../config/topology.tfvars.json")).topology
  traffic  = jsondecode(file("../../../config/traffic.tfvars.json")).traffic
}

run "spark_ranges" {
  command = plan
  assert {
    condition = (
      length([for key, flow in output.flows : key if startswith(key, "spark_driver/")]) == 9 &&
      alltrue([for key, flow in output.flows : flow.port == 7078 && flow.port_end == 7094 if startswith(key, "spark_driver/")]) &&
      alltrue([for key, flow in output.flows : flow.port == 7079 && flow.port_end == 7095 if startswith(key, "spark_block/")])
    )
    error_message = "Spark 세 계정의 모든 SG 쌍에 Driver·BlockManager 재시도 범위를 전달해야 합니다."
  }
  assert {
    condition = alltrue([for key, flow in output.flows : flow.port_end == flow.port
      if !startswith(key, "spark_driver/") && !startswith(key, "spark_block/")
    ])
    error_message = "나머지 연결은 기존 단일 포트를 유지해야 합니다."
  }
}

run "legacy_single_ports" {
  command = plan
  variables {
    traffic = merge(var.traffic, {
      connections = { for name, connection in var.traffic.connections : name => {
        sources = connection.sources, targets = connection.targets, port = connection.port
      } }
    })
  }
  assert {
    condition     = alltrue([for flow in values(output.flows) : flow.port_end == flow.port])
    error_message = "port_end가 없는 구성은 단일 포트로 해석해야 합니다."
  }
}

run "unknown_end_port" {
  command = plan
  variables {
    traffic = merge(var.traffic, { connections = merge(var.traffic.connections, {
      spark_driver = merge(var.traffic.connections.spark_driver, { port_end = "missing_port" })
    }) })
  }
  expect_failures = [var.traffic]
}

run "reversed_range" {
  command = plan
  variables {
    traffic = merge(var.traffic, { connections = merge(var.traffic.connections, {
      spark_driver = merge(var.traffic.connections.spark_driver, { port_end = "ssh" })
    }) })
  }
  expect_failures = [var.traffic]
}
