$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
$scriptPath = Join-Path $PSScriptRoot '../scripts/deploy.ps1'
$tokens = $null
$errors = $null
$ast = [System.Management.Automation.Language.Parser]::ParseFile($scriptPath, [ref]$tokens, [ref]$errors)
if ($errors) { throw ($errors | Out-String) }
# AWS 호출 없이 실제 인벤토리 생성 코드의 Front 분기만 실행한다.
$branch = $ast.Find({ param($n)
    $n -is [System.Management.Automation.Language.IfStatementAst] -and
    $n.Clauses[0].Item1.Extent.Text -eq '$record.Account -eq ''account1'' -and $record.Role -in @(''game_frontend'', ''ad_frontend'')'
}, $true)
if (-not $branch) { throw 'Front 분기를 찾지 못했습니다.' }
$block = [scriptblock]::Create($branch.Clauses[0].Item2.Extent.Text.Trim().Substring(1).TrimEnd().TrimEnd('}'))
$platform = [pscustomobject]@{
    frontend_domains = [pscustomobject]@{'front-a'='bootcampmetaverse.site'}
    frontend_backend_nodes = [pscustomobject]@{'front-a'='game-server-test'}
}
$traffic = [pscustomobject]@{public_http_cidrs=@('222.112.208.69/32');game_client_cidrs=@('222.112.208.69/32')}
$instance = [pscustomobject]@{PublicIpAddress='43.203.25.153'}
$records = @(
    [pscustomobject]@{Account='account1';Role='game';Name='game-server';Id='old'},
    [pscustomobject]@{Account='account1';Role='game';Name='game-server-test';Id='test'},
    [pscustomobject]@{Account='account1';Role='ad';Name='ad-server';Id='ad'}
)
$live = @{old=[pscustomobject]@{PrivateIpAddress='10.10.10.152'};test=[pscustomobject]@{PrivateIpAddress='10.10.10.166'};ad=[pscustomobject]@{PrivateIpAddress='10.10.10.20'}}
$record = [pscustomobject]@{Account='account1';Role='game_frontend';Name='front-a'}
$hostVars = @{}
. $block
if ($hostVars.edge_domain -ne 'bootcampmetaverse.site' -or $hostVars.edge_game_backend_host -ne '10.10.10.166' -or $hostVars.edge_frontend_upstreams[0].port -ne 8004 -or -not $hostVars.edge_http_redirect) { throw '게임 도메인 매핑 실패' }
$record = [pscustomobject]@{Account='account1';Role='ad_frontend';Name='front-b'}
$hostVars = @{}
. $block
if ($hostVars.ContainsKey('edge_domain') -or $hostVars.edge_frontend_upstreams[0].host -ne '10.10.10.20' -or $hostVars.edge_http_redirect -or $hostVars.edge_client_max_body_size -ne '3m') { throw '광고 Front 회귀' }
$record = [pscustomobject]@{Account='account1';Role='game_frontend';Name='front-a'}
$platform.frontend_domains.'front-a' = 'bad;domain'
$rejected = $false
try { . $block } catch { $rejected = $true }
if (-not $rejected) { throw '잘못된 도메인 거부 실패' }
'PASS: 게임 도메인·선택 Backend·광고 유지·잘못된 도메인 거부'
