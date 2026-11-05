param([int]$McpPort = 8878, [int]$WebPort = 8879)
$ErrorActionPreference = 'Stop'
$toolRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
function Ensure-Service([int]$Port, [string]$Module, [string]$Script) {
    $listener = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
    if ($listener) {
        $owner = Get-CimInstance Win32_Process -Filter "ProcessId = $($listener[0].OwningProcess)"
        $parent = Get-CimInstance Win32_Process -Filter "ProcessId = $($owner.ParentProcessId)"
        $ownedPath = ($owner.CommandLine -and $owner.CommandLine.Contains($toolRoot)) -or ($parent.CommandLine -and $parent.CommandLine.Contains($toolRoot))
        if (-not $ownedPath -or -not $owner.CommandLine.Contains($Module)) {
            throw "端口 $Port 被其他服务占用；未停止或替换该服务。"
        }
        Write-Output "端口 $Port 的本工具服务已运行。"
    } else {
        & (Join-Path $PSScriptRoot $Script) -Port $Port
    }
}
Ensure-Service $McpPort '-m mcp_server --http' 'start-local.ps1'
Ensure-Service $WebPort '-m mcp_server.web' 'start-web.ps1'
Write-Output "网页：http://127.0.0.1:$WebPort/；MCP：http://127.0.0.1:$McpPort/mcp"
