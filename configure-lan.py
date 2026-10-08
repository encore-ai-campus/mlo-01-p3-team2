"""Allow the selected campus TCP port only on the current default LAN."""
import argparse
import json
from pathlib import Path
import subprocess
import sys

root = Path(__file__).resolve().parent
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--port", type=int, default=8002)
options = parser.parse_args()
if not 1 <= options.port <= 65535:
    parser.error("--port must be between 1 and 65535")
result_path = root / ".lan-firewall-result.json"
python_program = Path(sys._base_executable).resolve()


def ps_quote(value):
    return "'" + str(value).replace("'", "''") + "'"


script = r"""
$ErrorActionPreference = 'Stop'
$taskIdentity = [Security.Principal.WindowsIdentity]::GetCurrent()
$taskPrincipal = [Security.Principal.WindowsPrincipal]::new($taskIdentity)
if (-not $taskPrincipal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    throw 'Windows administrator permission is required to add the campus firewall rule.'
}
$taskNetwork = @(Get-NetIPConfiguration | Where-Object { $_.NetAdapter.Status -eq 'Up' -and $_.IPv4DefaultGateway })
if ($taskNetwork.Count -ne 1) { throw 'Expected one default network interface; choose the campus LAN before retrying.' }
$taskAddress = @($taskNetwork[0].IPv4Address.IPAddress)
if ($taskAddress.Count -ne 1 -or $taskAddress[0] -notmatch '^(10\.|192\.168\.|172\.(1[6-9]|2[0-9]|3[01])\.)') { throw 'Expected one private IPv4 address on the campus LAN.' }
$taskRuleName = 'PLAYDATA-Campus-LAN-TCP-__PORT__'
$taskParameters = @{
    DisplayName = 'PLAYDATA campus - TCP __PORT__ - same LAN only'
    Direction = 'Inbound'; Action = 'Allow'; Enabled = 'True'; Profile = 'Any'
    Protocol = 'TCP'; LocalPort = '__PORT__'; LocalAddress = $taskAddress[0]
    RemoteAddress = 'LocalSubnet4'; InterfaceAlias = $taskNetwork[0].InterfaceAlias
    Program = __PYTHON__; EdgeTraversalPolicy = 'Block'
}
$taskExisting = Get-NetFirewallRule -Name $taskRuleName -ErrorAction SilentlyContinue
if ($taskExisting) {
    $taskParameters.Remove('DisplayName')
    Set-NetFirewallRule -Name $taskRuleName -NewDisplayName 'PLAYDATA campus - TCP __PORT__ - same LAN only' @taskParameters | Out-Null
}
else { New-NetFirewallRule -Name $taskRuleName @taskParameters | Out-Null }
$taskRule = Get-NetFirewallRule -Name $taskRuleName
$taskPort = $taskRule | Get-NetFirewallPortFilter
$taskAddresses = $taskRule | Get-NetFirewallAddressFilter
$taskInterface = $taskRule | Get-NetFirewallInterfaceFilter
$taskApplication = $taskRule | Get-NetFirewallApplicationFilter
[PSCustomObject]@{
    ok = $true; name = $taskRule.Name; enabled = [string]$taskRule.Enabled
    action = [string]$taskRule.Action; direction = [string]$taskRule.Direction
    protocol = $taskPort.Protocol; localPort = $taskPort.LocalPort
    localAddress = $taskAddresses.LocalAddress; remoteAddress = $taskAddresses.RemoteAddress
    interface = $taskInterface.InterfaceAlias; program = $taskApplication.Program
    url = ('http://' + $taskAddress[0] + ':__PORT__/')
} | ConvertTo-Json -Depth 4 -Compress
""".replace("__PYTHON__", ps_quote(python_program)).replace("__PORT__", str(options.port))

process = subprocess.run(["powershell.exe", "-NoProfile", "-Command", script], text=True, capture_output=True)
if process.returncode:
    result = {"ok": False, "error": process.stderr.strip()}
else:
    result = json.loads(process.stdout.strip().lstrip("\ufeff"))
result_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
print(json.dumps(result, ensure_ascii=False))
raise SystemExit(0 if result["ok"] else 1)
