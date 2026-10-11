#Requires -Version 5.1
# 전체 삭제의 범위와 원격 상태를 검사한다. 이 파일은 AWS 삭제 API를 호출하지 않는다.
function Get-InfraDestroyTargets {
    [pscustomobject]@{ account = 'account1'; stage = 'bastion' }
    foreach ($account in 1..5) { [pscustomobject]@{ account = "account$account"; stage = 'workload' } }
    [pscustomobject]@{ account = 'shared'; stage = 'connectivity' }
    foreach ($account in 1..5) { [pscustomobject]@{ account = "account$account"; stage = 'foundation' } }
}

function Assert-InfraDestroyInvocation {
    param([string]$Root, [string]$RunId, [string]$Account, [string]$Stage, [string]$Action)
    # 단계 실행기를 직접 호출해 전체 삭제의 검토·순서를 건너뛰지 못하게 한다.
    $run = Read-InfraJson (Join-Path $Root ".local/destroy-all/$RunId/run.json")
    $targets = @(Get-InfraDestroyTargets)
    if ($run.run_id -ne $RunId -or $run.version -ne 1 -or -not $run.delete_data_volumes -or
        $run.fingerprint -ne (Get-InfraFingerprint $Root $null) -or @($run.steps).Count -ne $targets.Count) {
        throw '전체 삭제 실행 정보가 일치하지 않습니다.'
    }
    $selected = -1
    for ($i = 0; $i -lt $targets.Count; $i++) {
        if ($run.steps[$i].account -ne $targets[$i].account -or $run.steps[$i].stage -ne $targets[$i].stage) { throw '전체 삭제 순서가 변경됐습니다.' }
        if ($targets[$i].account -eq $Account -and $targets[$i].stage -eq $Stage) { $selected = $i }
    }
    if ($selected -lt 0) { throw '전체 삭제 대상이 아닙니다.' }
    if ($Action -eq 'Plan') {
        if ($run.status -ne 'Planning' -or $run.steps[$selected].status -ne 'Pending') { throw '전체 Plan 준비 단계가 아닙니다.' }
    } else {
        if ($run.status -ne 'Applying' -or $run.steps[$selected].status -ne 'Applying') { throw '검토한 전체 삭제 적용 단계가 아닙니다.' }
        for ($i = 0; $i -lt $selected; $i++) {
            if ($run.steps[$i].status -notin @('Deleted','Skipped')) { throw '선행 삭제 단계가 완료되지 않았습니다.' }
        }
    }
}

function Invoke-InfraDestroyAws {
    param([string]$Command, [string[]]$Arguments, [string[]]$AbsentErrors = @())
    # PowerShell 5.1에서도 stderr를 수집한 뒤 명시적인 AWS 오류 코드로만 없음 여부를 판단한다.
    $ErrorActionPreference = 'Continue'
    $lines = & $Command @Arguments --output json --no-cli-pager --no-cli-auto-prompt --cli-connect-timeout 10 --cli-read-timeout 30 2>&1
    $code = $LASTEXITCODE
    $ErrorActionPreference = 'Stop'
    $text = ($lines | ForEach-Object { $_.ToString() }) -join "`n"
    if ($code -ne 0) {
        foreach ($absent in $AbsentErrors) {
            if ($text -match ('\(' + [regex]::Escape($absent) + '\)')) { return $null }
        }
        throw "AWS 조회 실패 ($($Arguments[0]) $($Arguments[1])): $text"
    }
    return ($text | ConvertFrom-Json)
}

function Get-InfraDestroyState {
    param([string]$Command, $Backend, [string]$Account, [string]$Stage, [string]$Directory)
    $null = New-Item -ItemType Directory -Path $Directory -Force
    $path = Join-Path $Directory 'remote-state.json'
    $key = "$($Backend.key_prefix)/$Account/$Stage/terraform.tfstate"
    $result = Invoke-InfraDestroyAws $Command @('s3api','get-object','--bucket',$Backend.bucket,
        '--key',$key,'--profile',$Backend.profile,'--region',$Backend.region,$path) @('NoSuchKey')
    if ($null -eq $result) {
        return [pscustomobject]@{ exists = $false; sha256 = ''; managed_count = 0; key = $key; edge_bootstrap_only = $false }
    }
    $state = Read-InfraJson $path
    if (-not $state.PSObject.Properties['version'] -or $state.version -ne 4 -or
        -not $state.PSObject.Properties['resources'] -or -not $state.PSObject.Properties['lineage']) {
        throw "$Account/$Stage 상태 형식을 확인할 수 없습니다."
    }
    $count = 0
    foreach ($resource in @($state.resources)) {
        if ($resource.mode -eq 'managed') { $count += @($resource.instances).Count }
    }
    # 초기 구축에서만 존재하는 표식을 읽어 삭제 Plan에서도 같은 원격 상태 범위를 쓴다.
    $edgeBootstrap = $Account -eq 'account1' -and $Stage -eq 'workload' -and @($state.resources | Where-Object {
        $_.mode -eq 'managed' -and $_.type -eq 'terraform_data' -and $_.name -eq 'edge_bootstrap_guard' -and @($_.instances).Count -gt 0
    }).Count -gt 0
    return [pscustomobject]@{ exists = $true; sha256 = (Get-InfraFileHash $path); managed_count = $count; key = $key; edge_bootstrap_only = [bool]$edgeBootstrap }
}

function Assert-InfraDeletePlan {
    param($Plan, [string]$Stage, [string]$Account, $Topology, [switch]$DeleteDataVolumes)
    if (-not $Plan.PSObject.Properties['planned_values']) { throw '삭제 계획에 planned_values가 없습니다.' }
    if ($Plan.PSObject.Properties['errored'] -and $Plan.errored) { throw '오류가 있는 삭제 계획입니다.' }
    if ($Plan.PSObject.Properties['complete'] -and -not $Plan.complete) { throw '미완성 삭제 계획입니다.' }
    if ($Plan.PSObject.Properties['deferred_changes'] -and @($Plan.deferred_changes).Count) { throw '확정되지 않은 삭제 변경이 있습니다.' }
    $patterns = @{
        bastion = '^module\.(?:model\.terraform_data\.configuration|bastion\.aws_(?:instance|key_pair)\.this)$'
        foundation = '^(?:module\.model\.terraform_data\.configuration|module\.groups\.aws_security_group\.this\[.+\]|module\.network\.aws_(?:(?:vpc|subnet|internet_gateway|route_table|route_table_association|nat_gateway)\.this|eip\.nat|route\.(?:public|private_nat))(?:\[.+\])?)$'
        connectivity = '^(?:module\.model\.terraform_data\.configuration|module\.account[1-5]_account[1-5]\[0\]\.aws_(?:vpc_peering_connection(?:_accepter)?\.this|vpc_peering_connection_options\.(?:requester|accepter)|route\.(?:requester|accepter)\[.+\]))$'
        # workload가 소유한 역할별 콘솔 SSH 규칙만 기존 삭제 허용 목록에 추가한다.
        workload = '^(?:module\.model\.terraform_data\.configuration|terraform_data\.connectivity_ready|terraform_data\.edge_bootstrap_guard\[0\]|aws_vpc_security_group_ingress_rule\.bastion_console_ssh\[0\]|aws_vpc_security_group_ingress_rule\.service_console_ssh\["[^"]+"\]|module\.compute\.aws_(?:(?:key_pair|instance|eip|eip_association)\.this|(?:ebs_volume|volume_attachment)\.data)(?:\[.+\])?|module\.rules\.aws_vpc_security_group_(?:ingress|egress)_rule\.(?:peer|public)\[.+\]|module\.alb\[0\]\.aws_(?:lb\.this|lb_target_group\.this\[.+\]|lb_target_group_attachment\.(?:frontend|game|ad)\[.+\]|lb_listener\.http|lb_listener_rule\.(?:static|ad)))$'
    }
    if (-not $patterns.ContainsKey($Stage)) { throw '지원하지 않는 삭제 단계입니다.' }
    # 삭제 후 managed 자원이 남는 계획을 전체 삭제로 오인하지 않는다.
    $modules = @()
    if ($Plan.PSObject.Properties['planned_values'] -and $Plan.planned_values.PSObject.Properties['root_module']) {
        $modules += $Plan.planned_values.root_module
    }
    while ($modules.Count) {
        $current = $modules[0]
        $modules = @($modules | Select-Object -Skip 1)
        if ($current.PSObject.Properties['child_modules']) { $modules += @($current.child_modules) }
        if ($current.PSObject.Properties['resources'] -and @($current.resources | Where-Object { $_.mode -eq 'managed' }).Count) {
            throw '삭제 계획 적용 후 관리 자원이 남습니다.'
        }
    }
    $changes = if ($Plan.PSObject.Properties['resource_changes']) { @($Plan.resource_changes) } else { @() }
    foreach ($resource in $changes) {
        if ($resource.mode -ne 'managed') { continue }
        if ($resource.address -notmatch $patterns[$Stage]) { throw "삭제 단계 밖의 자원입니다: $($resource.address)" }
        $actions = @($resource.change.actions)
        if ($actions.Count -ne 1 -or $actions[0] -notin @('delete','no-op') -or
            ($resource.change.PSObject.Properties['importing'] -and $resource.change.importing)) {
            throw "삭제 계획에 생성·수정·교체·import가 포함됐습니다: $($resource.address)"
        }
        if ($actions[0] -ne 'delete') { continue }
        if ($resource.type -eq 'aws_ebs_volume' -and -not $DeleteDataVolumes) { throw '데이터 EBS 삭제 선택이 필요합니다.' }
        $before = $resource.change.before
        if (-not $before) { throw '삭제 대상의 기존 값이 없습니다.' }
        $owner = $Account
        if ($Account -eq 'shared') {
            if ($resource.address -match '^module\.(account[1-5])_(account[1-5])\[0\]') {
                $owner = $Matches[1]
                $accepter = $Matches[2]
                if ($resource.address -match '(?:_accepter\.this|\.accepter(?:\[|$))') { $owner = $accepter }
            } else { $owner = 'account1' }
        }
        # 태그를 제공하는 자원은 기존 프로젝트·계정·관리 주체까지 대조한다.
        if ($before.PSObject.Properties['tags_all']) {
            $tags = $before.tags_all
            if (-not $tags -or -not $tags.PSObject.Properties['Project'] -or $tags.Project -ne $Topology.project -or
                -not $tags.PSObject.Properties['Account'] -or $tags.Account -ne $owner -or
                -not $tags.PSObject.Properties['ManagedBy'] -or $tags.ManagedBy -ne 'Terraform' -or
                -not $tags.PSObject.Properties['Layout'] -or $tags.Layout -ne 'v2') {
                throw "삭제 대상의 프로젝트·계정·관리 태그가 다릅니다: $($resource.address)"
            }
        }
        $id = if ($before.PSObject.Properties['id']) { [string]$before.id } else { '' }
        [pscustomobject]@{ address = $resource.address; type = $resource.type; id = $id; account = $owner }
        # EC2 루트 볼륨은 별도 Terraform 자원이 아니므로 결과 검증 목록에 추가한다.
        if ($resource.type -eq 'aws_instance' -and $before.PSObject.Properties['root_block_device']) {
            foreach ($disk in @($before.root_block_device)) {
                if (-not $disk.delete_on_termination) { throw "자동 삭제되지 않는 OS 디스크가 있습니다: $($resource.address)" }
                if ($disk.volume_id) {
                    [pscustomobject]@{ address = "$($resource.address).root_block_device"; type = 'aws_ebs_volume'; id = $disk.volume_id; account = $owner }
                }
            }
        }
    }
}

function Assert-InfraDestroyArtifacts {
    param([string]$Root, [string]$RunId, $Run, $Backend)
    if ($Run.version -ne 1 -or $Run.run_id -ne $RunId -or -not $Run.delete_data_volumes -or
        $Run.fingerprint -ne (Get-InfraFingerprint $Root $null)) { throw '전체 삭제 코드·설정·실행 ID가 변경됐습니다. 새 Plan이 필요합니다.' }
    $targets = @(Get-InfraDestroyTargets)
    if (@($Run.steps).Count -ne $targets.Count) { throw '전체 삭제 단계가 누락됐습니다.' }
    for ($i = 0; $i -lt $targets.Count; $i++) {
        $step = $Run.steps[$i]
        if ($step.account -ne $targets[$i].account -or $step.stage -ne $targets[$i].stage -or
            $step.state_key -ne "$($Backend.key_prefix)/$($step.account)/$($step.stage)/terraform.tfstate" -or
            $step.status -notin @('Planned','Skipped')) { throw '삭제 순서·대상·단계 상태가 올바르지 않습니다.' }
        if ($step.status -eq 'Skipped') { continue }
        $directory = Join-Path $Root ".local/destroy-all/$RunId/$($step.account)/$($step.stage)"
        foreach ($entry in @(@('saved.tfplan','plan_sha256'), @('saved-plan.json','manifest_sha256'), @('delete-summary.json','summary_sha256'))) {
            $file = Join-Path $directory $entry[0]
            if (-not (Test-Path -LiteralPath $file -PathType Leaf) -or (Get-InfraFileHash $file) -ne $step.($entry[1])) {
                throw "저장된 삭제 계획 또는 요약이 변경됐습니다: $($step.account)/$($step.stage)"
            }
        }
        $manifest = Read-InfraJson (Join-Path $directory 'saved-plan.json')
        $topology = (Read-InfraJson (Join-Path $Root 'config/topology.tfvars.json')).topology
        $keyPath = $null
        if ($step.stage -in @('workload','bastion')) {
            $keyPath = $topology.accounts.($step.account).ssh_public_key_path
            if ($keyPath -and -not [IO.Path]::IsPathRooted($keyPath)) { $keyPath = Join-Path $Root $keyPath }
        }
        # 예전 실행 기록에 없는 필드는 일반 모드(false)로 읽는다.
        $stepEdgeMode = $step.PSObject.Properties['edge_bootstrap_only'] -and [bool]$step.edge_bootstrap_only
        $manifestEdgeMode = $manifest.PSObject.Properties['edge_bootstrap_only'] -and [bool]$manifest.edge_bootstrap_only
        if ([bool]$stepEdgeMode -ne [bool]$manifestEdgeMode) { throw '전체 삭제 단계의 초기 구축 모드가 저장 계획과 다릅니다.' }
        if ($manifest.account -ne $step.account -or $manifest.stage -ne $step.stage -or
            $manifest.state_key -ne $step.state_key -or $manifest.plan_mode -ne 'Delete' -or
            $manifest.destroy_run_id -ne $RunId -or -not $manifest.delete_data_volumes -or
            $manifest.plan_sha256 -ne $step.plan_sha256 -or
            $manifest.fingerprint -ne (Get-InfraFingerprint $Root $keyPath)) { throw '단계별 삭제 manifest 또는 공개키가 일치하지 않습니다.' }
    }
}

function Test-InfraDeletedResources {
    param([string]$Command, $Topology, [object[]]$Resources)
    # 삭제 API가 아니라 계획에 있던 주요 독립 자원의 ID 조회다. 권한 오류는 그대로 실패시킨다.
    $checks = @{
        aws_instance = @('ec2','describe-instances','--instance-ids','Reservations','InvalidInstanceID.NotFound')
        aws_ebs_volume = @('ec2','describe-volumes','--volume-ids','Volumes','InvalidVolume.NotFound')
        aws_eip = @('ec2','describe-addresses','--allocation-ids','Addresses','InvalidAllocationID.NotFound')
        aws_vpc = @('ec2','describe-vpcs','--vpc-ids','Vpcs','InvalidVpcID.NotFound')
        aws_subnet = @('ec2','describe-subnets','--subnet-ids','Subnets','InvalidSubnetID.NotFound')
        aws_security_group = @('ec2','describe-security-groups','--group-ids','SecurityGroups','InvalidGroup.NotFound')
        aws_internet_gateway = @('ec2','describe-internet-gateways','--internet-gateway-ids','InternetGateways','InvalidInternetGatewayID.NotFound')
        aws_route_table = @('ec2','describe-route-tables','--route-table-ids','RouteTables','InvalidRouteTableID.NotFound')
        aws_nat_gateway = @('ec2','describe-nat-gateways','--nat-gateway-ids','NatGateways','NatGatewayNotFound')
        aws_vpc_peering_connection = @('ec2','describe-vpc-peering-connections','--vpc-peering-connection-ids','VpcPeeringConnections','InvalidVpcPeeringConnectionID.NotFound')
        aws_key_pair = @('ec2','describe-key-pairs','--key-names','KeyPairs','InvalidKeyPair.NotFound')
        aws_lb = @('elbv2','describe-load-balancers','--load-balancer-arns','LoadBalancers','LoadBalancerNotFound')
        aws_lb_target_group = @('elbv2','describe-target-groups','--target-group-arns','TargetGroups','TargetGroupNotFound')
    }
    foreach ($resource in @($Resources | Sort-Object account,type,id -Unique)) {
        if (-not $checks.ContainsKey($resource.type) -or -not $resource.id) { continue }
        $check = $checks[$resource.type]
        $profile = $Topology.accounts.($resource.account).profile
        $result = Invoke-InfraDestroyAws $Command @($check[0],$check[1],$check[2],$resource.id,
            '--profile',$profile,'--region',$Topology.region) @($check[4])
        if ($null -eq $result) { continue }
        $remaining = @($result.($check[3]))
        if ($resource.type -eq 'aws_instance') { $remaining = @($remaining | ForEach-Object { $_.Instances } | Where-Object { $_.State.Name -ne 'terminated' }) }
        if ($resource.type -eq 'aws_nat_gateway') { $remaining = @($remaining | Where-Object { $_.State -ne 'deleted' }) }
        if ($resource.type -eq 'aws_vpc_peering_connection') { $remaining = @($remaining | Where-Object { $_.Status.Code -ne 'deleted' }) }
        if ($remaining.Count) { $resource }
    }
}
