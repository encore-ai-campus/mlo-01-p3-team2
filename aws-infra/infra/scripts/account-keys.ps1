#Requires -Version 5.1
[CmdletBinding()]
param(
    [Parameter(Mandatory)]
    [ValidateSet('Prepare','Register')]
    [string]$Action,
    [ValidateSet('all','account1','account2','account3','account4','account5')]
    [string]$Account = 'all',
    [string]$KeyDirectory = (Join-Path $env:USERPROFILE '.ssh/project-key')
)
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
$infraRoot = Split-Path -Parent $PSScriptRoot
$topologyPath = Join-Path $infraRoot 'config/topology.tfvars.json'
$accountKeys = @('account1','account2','account3','account4','account5')
$privateNames = @{ account1 = 'project-bastion.pem'; account2 = 'account2.pem'; account3 = 'account3.pem'; account4 = 'account4.pem'; account5 = 'account5.pem' }
$sshKeygen = (Get-Command ssh-keygen -CommandType Application -ErrorAction Stop).Source

function Write-KeyText {
    param([string]$Path, [string]$Text)
    [IO.File]::WriteAllText($Path, $Text, [Text.UTF8Encoding]::new($false))
}

function Read-KeyMaterial {
    param([string]$Path)
    # 개인키를 화면이나 설정에 저장하지 않고 공개키만 추출한다. 파이프 입력은 사용하지 않는다.
    $lines = & $sshKeygen -y -f $Path
    if ($LASTEXITCODE -ne 0) { throw "개인키 읽기 실패: $Path" }
    $publicKey = ($lines -join '').Trim()
    if ($publicKey -notmatch '^(ssh-rsa|ssh-ed25519) [A-Za-z0-9+/=]+(?:\s.*)?$') {
        throw "OpenSSH 공개키를 추출하지 못했습니다: $Path"
    }
    $parts = $publicKey -split '\s+'
    $null = [Convert]::FromBase64String($parts[1])
    return "$($parts[0]) $($parts[1])"
}

function Protect-KeyFile {
    param([string]$Path)
    # 사용자 소유의 파일 하나만 읽기 권한으로 제한한다. 재실행 때 소유권 변경 권한은 요구하지 않는다.
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent().User
    $owner = (Get-Acl -LiteralPath $Path).GetOwner([Security.Principal.SecurityIdentifier])
    if ($owner.Value -ne $identity.Value) { throw "현재 Windows 사용자가 소유한 개인키 파일이 필요합니다: $Path" }
    $acl = [Security.AccessControl.FileSecurity]::new()
    $acl.SetAccessRuleProtection($true, $false)
    $acl.AddAccessRule([Security.AccessControl.FileSystemAccessRule]::new($identity, 'Read', 'Allow'))
    Set-Acl -LiteralPath $Path -AclObject $acl
}

function Get-KeyInputs {
    param([switch]$Protect)
    $result = @{}
    # 파일이 모두 있는지 먼저 검사한다. 누락된 키가 있으면 공개키·설정을 수정하지 않는다.
    foreach ($key in $accountKeys) {
        $path = Join-Path $KeyDirectory $privateNames[$key]
        if (-not (Test-Path -LiteralPath $path -PathType Leaf)) { throw "개인키 파일이 없습니다: $path" }
        $result[$key] = @{ PrivatePath = [IO.Path]::GetFullPath($path) }
    }
    foreach ($key in $accountKeys) {
        if ($Protect) { Protect-KeyFile $result[$key].PrivatePath }
        $result[$key].PublicKey = Read-KeyMaterial $result[$key].PrivatePath
    }
    if (@($accountKeys | ForEach-Object { $result[$_].PublicKey } | Select-Object -Unique).Count -ne 5) {
        throw '계정별 키는 서로 달라야 합니다. 중복된 개인키 파일을 확인하세요.'
    }
    return $result
}

function Invoke-KeyPrepare {
    if ($Account -ne 'all') { throw 'Prepare는 다섯 계정을 함께 준비합니다. -Account all을 사용하세요.' }
    $keys = Get-KeyInputs -Protect
    $config = Get-Content -Raw -LiteralPath $topologyPath | ConvertFrom-Json
    $publicDirectory = Join-Path $infraRoot 'config/keys'
    $backupDirectory = Join-Path $infraRoot '.local/ssh-keys/previous-public'
    $null = New-Item -ItemType Directory -Path $publicDirectory, $backupDirectory -Force
    # 기존 공개키는 로컬 백업에 남긴다. 개인키는 저장소 안으로 복사하지 않는다.
    foreach ($key in $accountKeys) {
        $oldPath = $config.topology.accounts.$key.ssh_public_key_path
        if (-not [IO.Path]::IsPathRooted($oldPath)) { $oldPath = Join-Path $infraRoot $oldPath }
        $backupPath = Join-Path $backupDirectory "$key.pub"
        if ((Test-Path -LiteralPath $oldPath -PathType Leaf) -and -not (Test-Path -LiteralPath $backupPath)) {
            Copy-Item -LiteralPath $oldPath -Destination $backupPath
        }
    }
    foreach ($key in $accountKeys) {
        $publicPath = Join-Path $publicDirectory "$key.pub"
        Write-KeyText $publicPath ($keys[$key].PublicKey + "`n")
        $config.topology.accounts.$key.ssh_public_key_path = "config/keys/$key.pub"
        Write-Host "$key : $($keys[$key].PrivatePath) -> $publicPath"
        & $sshKeygen -lf $publicPath
        if ($LASTEXITCODE -ne 0) { throw "공개키 식별값 확인 실패: $key" }
    }
    Write-KeyText $topologyPath ($config | ConvertTo-Json -Depth 50)
    Write-Host '공개키 준비 완료. AWS에는 아직 적용하지 않았습니다. 기존 저장 Plan은 다시 만드세요.'
}

function Invoke-KeyAws {
    param([string]$Profile, [string[]]$Arguments)
    $cliArguments = @($Arguments) + @('--profile', $Profile, '--region', $topology.region,
        '--output','json','--no-cli-pager','--no-cli-auto-prompt','--cli-connect-timeout','5','--cli-read-timeout','20')
    $ErrorActionPreference = 'Continue'
    $lines = & $awsCommand @cliArguments 2>&1
    $code = $LASTEXITCODE
    $ErrorActionPreference = 'Stop'
    $text = ($lines | ForEach-Object { $_.ToString() }) -join "`n"
    if ($code -ne 0) { throw "AWS 호출 실패 ($Profile / $($Arguments[0]) $($Arguments[1])): $text" }
    return ($text | ConvertFrom-Json)
}

function Invoke-KeySsh {
    param([string[]]$Arguments)
    & $sshCommand @Arguments
    if ($LASTEXITCODE -ne 0) { throw 'SSH 작업 실패. 앞서 성공한 서버의 새 공개키는 유지됩니다. 오류를 해결한 뒤 같은 Register를 다시 실행하세요.' }
}

function Get-KeyTag {
    param($Instance, [string]$Name)
    return (@($Instance.Tags | Where-Object { $_.Key -eq $Name } | Select-Object -ExpandProperty Value) -join '')
}

function Get-KeyInstallCommand {
    param([string[]]$PublicKeys)
    # 기존 공개키를 보존하면서 새 공개키를 중복 없이 추가한다.
    $commands = @('umask 077', 'mkdir -p ~/.ssh', 'touch ~/.ssh/authorized_keys', 'chmod 700 ~/.ssh', 'chmod 600 ~/.ssh/authorized_keys')
    foreach ($key in $PublicKeys) {
        if ($key -notmatch '^(ssh-rsa|ssh-ed25519) [A-Za-z0-9+/=]+$') { throw '등록할 공개키 형식이 잘못됐습니다.' }
        $commands += "(grep -qxF '$key' ~/.ssh/authorized_keys || printf '%s\n' '$key' >> ~/.ssh/authorized_keys)"
        $commands += "grep -qxF '$key' ~/.ssh/authorized_keys"
    }
    return ($commands -join ' && ')
}

function Invoke-KeyRegister {
    $keys = Get-KeyInputs
    $topology = (Get-Content -Raw -LiteralPath $topologyPath | ConvertFrom-Json).topology
    $selected = if ($Account -eq 'all') { $accountKeys } else { @($Account) }
    $targets = @()
    # 설정·실제 계정·서버 태그·개수를 모두 확인한 뒤 원격 등록을 시작한다.
    foreach ($key in $accountKeys) {
        $publicPath = Join-Path $infraRoot "config/keys/$key.pub"
        if (-not (Test-Path -LiteralPath $publicPath) -or [IO.File]::ReadAllText($publicPath).Trim() -ne $keys[$key].PublicKey -or
            $topology.accounts.$key.ssh_public_key_path -ne "config/keys/$key.pub") { throw "$key 키 설정이 일치하지 않습니다. Prepare부터 실행하세요." }
    }
    foreach ($key in @(@('account1') + $selected | Select-Object -Unique)) {
        $identity = Invoke-KeyAws $topology.accounts.$key.profile @('sts','get-caller-identity')
        if ($identity.Account -ne $topology.accounts.$key.id) { throw "CLI 프로필의 실제 계정이 다릅니다: $key" }
    }
    $bastionResponse = Invoke-KeyAws $topology.accounts.account1.profile @('ec2','describe-instances','--filters',
        "Name=tag:Project,Values=$($topology.project)",'Name=tag:Account,Values=account1',
        'Name=tag:ManagedBy,Values=Terraform','Name=tag:Layout,Values=v2','Name=tag:Stage,Values=bastion',
        'Name=tag:Node,Values=bastion','Name=tag:Role,Values=bastion','Name=instance-state-name,Values=running')
    $bastions = @($bastionResponse.Reservations | ForEach-Object { $_.Instances })
    if ($bastions.Count -ne 1 -or -not $bastions[0].PSObject.Properties['PublicIpAddress']) { throw '실행 중인 새 Bastion 한 대와 공인 IP가 필요합니다. PlanCreate 검토 후 Create부터 완료하세요.' }
    $bastion = $bastions[0]
    foreach ($key in $selected) {
        $nodes = @($topology.nodes.PSObject.Properties | Where-Object { $_.Value.account -eq $key -and $_.Value.role -ne 'bastion' })
        $response = Invoke-KeyAws $topology.accounts.$key.profile @('ec2','describe-instances','--filters',
            "Name=tag:Project,Values=$($topology.project)","Name=tag:Account,Values=$key",
            'Name=tag:ManagedBy,Values=Terraform','Name=tag:Layout,Values=v2',
            "Name=tag:Node,Values=$(($nodes.Name) -join ',')",'Name=instance-state-name,Values=pending,running,stopping,stopped')
        $instances = @($response.Reservations | ForEach-Object { $_.Instances })
        if ($instances.Count -ne $nodes.Count) { throw "$key 서비스 서버 수가 설정과 다릅니다. 예상 $($nodes.Count), 실제 $($instances.Count)" }
        foreach ($node in $nodes) {
            $matches = @($instances | Where-Object { (Get-KeyTag $_ 'Node') -eq $node.Name })
            if ($matches.Count -ne 1 -or (Get-KeyTag $matches[0] 'Role') -ne $node.Value.role -or $matches[0].State.Name -ne 'running') {
                throw "실행 중인 서비스 서버를 하나로 확정하지 못했습니다: $key/$($node.Name)"
            }
            $instance = $matches[0]
            if ($instance.InstanceId -notmatch '^i-[0-9a-f]+$' -or $node.Name -notmatch '^[a-zA-Z0-9_-]+$' -or $instance.PrivateIpAddress -notmatch '^\d+\.\d+\.\d+\.\d+$') { throw '서버 ID·이름·사설 IP 형식 오류' }
            $targets += [pscustomobject]@{ Account = $key; Node = $node.Name; Instance = $instance; Alias = "infra-key-$key-$($node.Name)" }
        }
    }
    $directory = Join-Path $infraRoot '.local/ssh-keys'
    $null = New-Item -ItemType Directory -Path $directory -Force
    $configPath = Join-Path $directory 'ssh-config'
    $sshLines = @()
    foreach ($key in $accountKeys) {
        $privatePath = $keys[$key].PrivatePath.Replace('\','/')
        $sshLines += @("Host infra-key-bastion-$key", "    HostName $($bastion.PublicIpAddress)", '    User ubuntu',
            "    IdentityFile `"$privatePath`"", '    IdentitiesOnly yes', '    StrictHostKeyChecking accept-new', '    ConnectTimeout 10')
    }
    foreach ($target in $targets) {
        $privatePath = $keys[$target.Account].PrivatePath.Replace('\','/')
        $sshLines += @("Host $($target.Alias)","    HostName $($target.Instance.PrivateIpAddress)",'    User ubuntu',
            "    IdentityFile `"$privatePath`"",'    IdentitiesOnly yes','    StrictHostKeyChecking accept-new','    ConnectTimeout 10',
            '    ProxyJump infra-key-bastion-account1')
    }
    Write-KeyText $configPath (($sshLines -join "`n") + "`n")
    # 각 팀원은 자기 계정 키로 Bastion에도 접속할 수 있도록 다섯 공개키를 추가한다.
    Invoke-KeySsh @('-F',$configPath,'-o','BatchMode=yes','infra-key-bastion-account1',
        (Get-KeyInstallCommand @($accountKeys | ForEach-Object { $keys[$_].PublicKey })))
    foreach ($target in $targets) {
        Write-Host "공개키 등록: $($target.Account)/$($target.Node) / $($target.Instance.InstanceId)"
        $key = $target.Account
        $publicPath = (Join-Path $infraRoot "config/keys/$key.pub").Replace('\','/')
        # EIC 임시 키로 접속한 직후 authorized_keys에 영구 등록한다. EC2를 삭제하거나 재생성하지 않는다.
        $sent = Invoke-KeyAws $topology.accounts.$key.profile @('ec2-instance-connect','send-ssh-public-key',
            '--instance-id',$target.Instance.InstanceId,'--availability-zone',$target.Instance.Placement.AvailabilityZone,
            '--instance-os-user','ubuntu','--ssh-public-key',"file://$publicPath")
        if (-not $sent.Success) { throw "EC2 Instance Connect 공개키 전송 실패: $($target.Node)" }
        Invoke-KeySsh @('-F',$configPath,'-o','BatchMode=yes',$target.Alias,(Get-KeyInstallCommand @($keys[$key].PublicKey)))
    }
    # 팀원용 접속 설정은 자기 계정 키로 Bastion을 거치도록 마지막에 갱신한다.
    foreach ($target in $targets) {
        $block = "    ProxyJump infra-key-bastion-account1"
        $start = [Array]::IndexOf($sshLines, "Host $($target.Alias)")
        for ($index = $start + 1; $index -lt $sshLines.Count -and $sshLines[$index] -notlike 'Host *'; $index++) {
            if ($sshLines[$index] -eq $block) { $sshLines[$index] = "    ProxyJump infra-key-bastion-$($target.Account)" }
        }
    }
    Write-KeyText $configPath (($sshLines -join "`n") + "`n")
    Write-Host "새 공개키 등록 완료: 서비스 서버 $($targets.Count)대. 기존 공개키는 보존했습니다."
    Write-Host "접속 설정: $configPath"
    Write-Host '서비스 workload의 새 Plan을 계정별로 검토해야 Terraform 키페어 등록 정보까지 맞출 수 있습니다.'
}

if ($Action -eq 'Prepare') {
    Invoke-KeyPrepare
} else {
    $awsCommand = (Get-Command aws -CommandType Application -ErrorAction Stop).Source
    $sshCommand = (Get-Command ssh -CommandType Application -ErrorAction Stop).Source
    Invoke-KeyRegister
}
