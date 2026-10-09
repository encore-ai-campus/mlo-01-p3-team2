#Requires -Version 5.1
<#
.SYNOPSIS
Windows 노트북에 Terraform과 AWS CLI v2를 설치합니다.
.DESCRIPTION
현재 사용자에게 설치하고 사용자 PATH를 등록합니다. 기존 설치는 유지합니다.
AWS 로그인이나 AWS 자원 생성은 별도로 진행합니다.
.EXAMPLE
.\infra\setup-windows\install-tools.ps1
.EXAMPLE
.\infra\setup-windows\install-tools.ps1 -CheckOnly
#>
[CmdletBinding()]
param(
    # 설치와 PATH 변경 없이 현재 설치 상태만 확인한다.
    [switch]$CheckOnly
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

if ([Environment]::OSVersion.Platform -ne [PlatformID]::Win32NT) {
    throw '이 스크립트는 Windows용입니다. Windows PowerShell에서 실행하세요.'
}
if (-not [Environment]::Is64BitProcess -or $env:PROCESSOR_ARCHITECTURE -ne 'AMD64') {
    throw 'Intel/AMD 64비트 Windows의 64비트 PowerShell에서 실행하세요. ARM은 이 스크립트의 지원 대상이 아닙니다.'
}

$toolsDirectory = Join-Path $env:USERPROFILE 'tools'
$terraformDirectory = Join-Path $toolsDirectory 'terraform'
$awsUserDirectory = Join-Path $env:LOCALAPPDATA 'Programs\Amazon\AWSCLIV2'
$awsMachineDirectory = Join-Path $env:ProgramFiles 'Amazon\AWSCLIV2'

function Find-Tool {
    param([string]$Name, [string[]]$FallbackDirectories)

    # 기존 PATH를 우선 확인하고, 터미널을 다시 열지 않은 설치도 찾는다.
    $command = Get-Command $Name -CommandType Application -ErrorAction SilentlyContinue |
        Select-Object -First 1
    if ($command) { return $command.Source }
    foreach ($directory in $FallbackDirectories) {
        $candidate = Join-Path $directory "$Name.exe"
        if (Test-Path -LiteralPath $candidate -PathType Leaf) { return $candidate }
    }
    return $null
}

function Get-ToolVersion {
    param([string]$Executable, [string]$Name)

    # stderr로 버전을 출력하는 구버전도 읽은 뒤 실제 종료 코드로 판단한다.
    $startInfo = New-Object System.Diagnostics.ProcessStartInfo
    $startInfo.FileName = $Executable
    $startInfo.Arguments = '--version'
    $startInfo.UseShellExecute = $false
    $startInfo.CreateNoWindow = $true
    $startInfo.RedirectStandardOutput = $true
    $startInfo.RedirectStandardError = $true
    # 상태 확인 중 Terraform의 업데이트 조회가 발생하지 않도록 한다.
    $startInfo.EnvironmentVariables['CHECKPOINT_DISABLE'] = '1'
    $process = New-Object System.Diagnostics.Process
    $process.StartInfo = $startInfo
    try {
        $null = $process.Start()
        $stdout = $process.StandardOutput.ReadToEndAsync()
        $stderr = $process.StandardError.ReadToEndAsync()
        if (-not $process.WaitForExit(30000)) {
            $process.Kill()
            throw "$Name 버전 확인 시간이 초과됐습니다: $Executable"
        }
        $output = ($stdout.Result + "`n" + $stderr.Result).Trim()
        if ($process.ExitCode -ne 0) { throw "$Name 실행 실패: $output" }
        $pattern = if ($Name -eq 'Terraform') { '(?m)^Terraform v(\d+\.\d+\.\d+)' } else { '^aws-cli/(\d+\.\d+\.\d+)' }
        if ($output -notmatch $pattern) { throw "$Name 버전을 확인할 수 없습니다: $output" }
        return [version]$Matches[1]
    } finally {
        $process.Dispose()
    }
}

function Add-UserPath {
    param([string]$Directory)

    # 시스템 PATH는 유지하고 사용자 PATH에 중복 없이 폴더를 등록한다.
    $userPath = [Environment]::GetEnvironmentVariable('Path', 'User')
    $userEntries = @($userPath -split ';' | Where-Object { -not [string]::IsNullOrWhiteSpace($_) })
    $normalized = @($userEntries | ForEach-Object {
        [Environment]::ExpandEnvironmentVariables($_).Trim('"').TrimEnd('\')
    })
    if ($normalized -notcontains $Directory.TrimEnd('\')) {
        $updatedPath = if ([string]::IsNullOrEmpty($userPath)) { $Directory } else { $userPath.TrimEnd(';') + ';' + $Directory }
        [Environment]::SetEnvironmentVariable('Path', $updatedPath, 'User')
    }
    $processEntries = @($env:Path -split ';' | ForEach-Object { $_.Trim('"').TrimEnd('\') })
    if ($processEntries -notcontains $Directory.TrimEnd('\')) {
        $env:Path = $env:Path.TrimEnd(';') + ';' + $Directory
    }
}

function Save-Download {
    param([string]$Uri, [string]$Destination)
    Write-Host "다운로드: $Uri"
    Invoke-WebRequest -Uri $Uri -OutFile $Destination -UseBasicParsing -TimeoutSec 600
}

function Assert-TerraformChecksum {
    param([string]$ArchivePath, [string]$ChecksumsPath)

    # 공식 SHA256 목록의 정확한 파일명과 비교한 뒤에만 압축을 해제한다.
    $fileName = Split-Path -Leaf $ArchivePath
    $pattern = '^([a-fA-F0-9]{64})\s+\*?' + [regex]::Escape($fileName) + '$'
    $expectedHash = $null
    foreach ($line in Get-Content -LiteralPath $ChecksumsPath) {
        if ($line -match $pattern) { $expectedHash = $Matches[1]; break }
    }
    if (-not $expectedHash) { throw "공식 체크섬 목록에서 $fileName 항목을 찾지 못했습니다." }
    $actualHash = (Get-FileHash -LiteralPath $ArchivePath -Algorithm SHA256).Hash
    if ($actualHash -ne $expectedHash) { throw 'Terraform 다운로드 파일의 SHA256이 일치하지 않습니다. 설치를 중단합니다.' }
}

# 수동으로 tools 바로 아래나 공식 ZIP 이름의 폴더에 압축을 푼 설치도 재사용한다.
$terraformFallbacks = @($terraformDirectory, $toolsDirectory)
if (Test-Path -LiteralPath $toolsDirectory -PathType Container) {
    $versionDirectories = @(Get-ChildItem -LiteralPath $toolsDirectory -Directory |
        Where-Object { $_.Name -match '^terraform_(1\.\d+\.\d+)_windows_amd64$' } |
        Sort-Object -Property @{ Expression = { [version]($_.Name -replace '^terraform_|_windows_amd64$', '') }; Descending = $true })
    $terraformFallbacks += @($versionDirectories | ForEach-Object { $_.FullName })
}
$terraformPath = Find-Tool -Name 'terraform' -FallbackDirectories $terraformFallbacks
$awsPath = Find-Tool -Name 'aws' -FallbackDirectories @($awsUserDirectory, $awsMachineDirectory)

# 기존 버전의 충돌은 설치하기 전에 알리고 자동 삭제·업그레이드는 하지 않는다.
if ($terraformPath) {
    $terraformVersion = Get-ToolVersion -Executable $terraformPath -Name 'Terraform'
    if ($terraformVersion -lt [version]'1.6.0' -or $terraformVersion -ge [version]'2.0.0') {
        throw "기존 Terraform $terraformVersion 은 프로젝트 범위(1.6 이상, 2.0 미만) 밖입니다. 기존 설치를 먼저 확인하세요: $terraformPath"
    }
    Write-Host "Terraform $terraformVersion 사용: $terraformPath"
} else { Write-Host 'Terraform: 설치 필요' }
if ($awsPath) {
    $awsVersion = Get-ToolVersion -Executable $awsPath -Name 'AWS CLI'
    if ($awsVersion.Major -ne 2) {
        throw "기존 AWS CLI $awsVersion 이 감지됐습니다. v1과의 명령 충돌을 정리한 뒤 다시 실행하세요: $awsPath"
    }
    if ($awsVersion -lt [version]'2.32.0') {
        throw "기존 AWS CLI $awsVersion 은 aws login에 필요한 2.32.0 이상이 아닙니다. 공식 설치 파일로 업데이트한 뒤 다시 실행하세요: $awsPath"
    }
    Write-Host "AWS CLI $awsVersion 사용: $awsPath"
} else { Write-Host 'AWS CLI v2: 설치 필요' }

if ($CheckOnly) {
    if (-not $terraformPath -or -not $awsPath) { exit 1 }
    exit 0
}

$downloadDirectory = $null
$previousTls = [Net.ServicePointManager]::SecurityProtocol
$previousProgress = $ProgressPreference
try {
    # Windows PowerShell 5.1에서도 HTTPS 다운로드에 TLS 1.2를 사용할 수 있게 한다.
    [Net.ServicePointManager]::SecurityProtocol = $previousTls -bor [Net.SecurityProtocolType]::Tls12
    $ProgressPreference = 'SilentlyContinue'
    if (-not $terraformPath -or -not $awsPath) {
        $downloadDirectory = Join-Path ([IO.Path]::GetTempPath()) ('aws-infra-tools-' + [guid]::NewGuid().ToString('N'))
        New-Item -ItemType Directory -Path $downloadDirectory | Out-Null
    }

    if (-not $terraformPath) {
        $release = Invoke-RestMethod -Uri 'https://checkpoint-api.hashicorp.com/v1/check/terraform' -TimeoutSec 60
        $releaseVersion = [string]$release.current_version
        if ($releaseVersion -notmatch '^1\.\d+\.\d+$' -or [version]$releaseVersion -lt [version]'1.6.0') {
            throw "공식 Terraform 버전 응답이 프로젝트 범위와 맞지 않습니다: $releaseVersion"
        }
        $releaseUrl = "https://releases.hashicorp.com/terraform/$releaseVersion"
        $archiveName = "terraform_${releaseVersion}_windows_amd64.zip"
        $archivePath = Join-Path $downloadDirectory $archiveName
        $checksumsPath = Join-Path $downloadDirectory 'SHA256SUMS'
        Save-Download -Uri "$releaseUrl/$archiveName" -Destination $archivePath
        Save-Download -Uri "$releaseUrl/terraform_${releaseVersion}_SHA256SUMS" -Destination $checksumsPath
        Assert-TerraformChecksum -ArchivePath $archivePath -ChecksumsPath $checksumsPath
        $extractDirectory = Join-Path $downloadDirectory 'terraform'
        Expand-Archive -LiteralPath $archivePath -DestinationPath $extractDirectory
        $extractedExecutable = Join-Path $extractDirectory 'terraform.exe'
        $extractedVersion = Get-ToolVersion -Executable $extractedExecutable -Name 'Terraform'
        if ($extractedVersion -ne [version]$releaseVersion) { throw 'Terraform 실행 파일의 버전이 다운로드한 버전과 다릅니다.' }
        New-Item -ItemType Directory -Path $terraformDirectory -Force | Out-Null
        $terraformPath = Join-Path $terraformDirectory 'terraform.exe'
        Copy-Item -LiteralPath $extractedExecutable -Destination $terraformPath
        $licensePath = Join-Path $extractDirectory 'LICENSE.txt'
        if (Test-Path -LiteralPath $licensePath -PathType Leaf) {
            Copy-Item -LiteralPath $licensePath -Destination $terraformDirectory
        }
    }
    # 뒤의 AWS 설치가 실패해도 재실행하면 설치된 Terraform을 그대로 사용할 수 있다.
    Add-UserPath -Directory (Split-Path -Parent $terraformPath)

    if (-not $awsPath) {
        $msiPath = Join-Path $downloadDirectory 'AWSCLIV2-User.msi'
        $msiLogPath = Join-Path $downloadDirectory 'aws-cli-install.log'
        Save-Download -Uri 'https://awscli.amazonaws.com/AWSCLIV2-User.msi' -Destination $msiPath
        $signature = Get-AuthenticodeSignature -LiteralPath $msiPath
        if ($signature.Status -ne 'Valid') { throw "AWS 설치 파일의 디지털 서명이 유효하지 않습니다: $($signature.Status)" }
        Write-Host 'AWS CLI v2를 현재 사용자에게 설치합니다. 완료까지 잠시 기다려 주세요.'
        $msiArguments = '/i "{0}" /qn /norestart /L*v "{1}"' -f $msiPath, $msiLogPath
        $installer = Start-Process -FilePath (Join-Path $env:SystemRoot 'System32\msiexec.exe') -ArgumentList $msiArguments -WindowStyle Hidden -Wait -PassThru
        if ($installer.ExitCode -notin @(0, 3010)) {
            throw "AWS CLI 설치 실패: 종료 코드 $($installer.ExitCode). 설치 로그: $msiLogPath"
        }
        if ($installer.ExitCode -eq 3010) { Write-Warning 'Windows Installer가 재부팅을 요청했습니다. 작업을 저장한 뒤 재부팅하세요.' }
        $awsPath = Find-Tool -Name 'aws' -FallbackDirectories @($awsUserDirectory, $awsMachineDirectory)
        if (-not $awsPath) { throw "설치 후 aws.exe를 찾지 못했습니다. 설치 로그: $msiLogPath" }
    }
    Add-UserPath -Directory (Split-Path -Parent $awsPath)

    # 전체 경로뿐 아니라 사용자가 실제 입력할 명령 이름으로도 확인한다.
    $activeTerraform = Find-Tool -Name 'terraform' -FallbackDirectories @()
    $activeAws = Find-Tool -Name 'aws' -FallbackDirectories @()
    $verifiedTerraform = Get-ToolVersion -Executable $activeTerraform -Name 'Terraform'
    $verifiedAws = Get-ToolVersion -Executable $activeAws -Name 'AWS CLI'
    if ($verifiedTerraform -lt [version]'1.6.0' -or $verifiedTerraform -ge [version]'2.0.0') {
        throw "PATH에서 프로젝트 범위 밖의 Terraform이 실행됩니다: $activeTerraform"
    }
    if ($verifiedAws.Major -ne 2 -or $verifiedAws -lt [version]'2.32.0') {
        throw "PATH에서 실행되는 AWS CLI는 v2 2.32.0 이상이어야 합니다: $activeAws"
    }
    Write-Host "설치 확인 완료: Terraform $verifiedTerraform / AWS CLI $verifiedAws"
    Write-Host '새 PowerShell 창에서 terraform --version 과 aws --version 을 확인하세요. VS Code를 사용한다면 VS Code도 다시 실행하세요.'
    Write-Host '다음 단계는 AWS 로그인 및 프로필 설정입니다.'

    # 성공한 다운로드만 정리한다. 실패 시 파일과 MSI 로그를 남겨 원인을 확인한다.
    if ($downloadDirectory) {
        $resolvedDownload = [IO.Path]::GetFullPath($downloadDirectory)
        $resolvedTemp = [IO.Path]::GetFullPath([IO.Path]::GetTempPath()).TrimEnd('\') + '\'
        if (-not $resolvedDownload.StartsWith($resolvedTemp, [StringComparison]::OrdinalIgnoreCase) -or
            (Split-Path -Leaf $resolvedDownload) -notmatch '^aws-infra-tools-[a-f0-9]{32}$') {
            throw "임시 폴더 범위 확인 실패: $resolvedDownload"
        }
        Remove-Item -LiteralPath $resolvedDownload -Recurse -Force
    }
} catch {
    if ($downloadDirectory) { Write-Warning "설치 파일과 로그 보관 위치: $downloadDirectory" }
    throw
} finally {
    [Net.ServicePointManager]::SecurityProtocol = $previousTls
    $ProgressPreference = $previousProgress
}
