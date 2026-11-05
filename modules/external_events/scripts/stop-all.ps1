param([int]$McpPort = 8878, [int]$WebPort = 8879)
$ErrorActionPreference = 'Stop'
$toolRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
foreach ($port in @($McpPort, $WebPort)) {
    $listener = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue
    if (-not $listener) { continue }
    $owner = Get-CimInstance Win32_Process -Filter "ProcessId = $($listener[0].OwningProcess)"
    $parent = Get-CimInstance Win32_Process -Filter "ProcessId = $($owner.ParentProcessId)"
    $ownedPath = ($owner.CommandLine -and $owner.CommandLine.Contains($toolRoot)) -or ($parent.CommandLine -and $parent.CommandLine.Contains($toolRoot))
    if (-not $ownedPath -or -not $owner.CommandLine.Contains('-m mcp_server')) {
        throw "端口 $port 不属于此目录的事件聚合工具，未停止。"
    }
    Stop-Process -Id $owner.ProcessId -ErrorAction SilentlyContinue
    if ($parent.CommandLine -and $parent.CommandLine.Contains($toolRoot) -and $parent.CommandLine.Contains('-m mcp_server')) {
        Stop-Process -Id $parent.ProcessId -ErrorAction SilentlyContinue
    }
    Write-Output "已停止本工具端口 $port；配置与任务文件保留。"
}
