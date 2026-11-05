param([int]$Port = 8878)
$ErrorActionPreference = 'Stop'
$toolRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$pythonPath = Join-Path $toolRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $pythonPath)) { throw '请先建立 .venv 并安装 requirements.txt' }
if (Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue) {
    throw "端口 $Port 已有服务，请核对现有进程，避免重复启动。"
}
$runtimeDir = Join-Path $toolRoot '.local'
New-Item -ItemType Directory -Path $runtimeDir -Force | Out-Null
$env:PYTHONPATH = Join-Path $toolRoot 'src'
$env:PYTHONUTF8 = '1'
$env:TIMELINE_OUTPUT_DIR = Join-Path $runtimeDir 'research'
$env:NO_PROXY = '127.0.0.1,localhost'
$process = Start-Process -FilePath $pythonPath -ArgumentList @('-m','mcp_server','--http',"127.0.0.1:$Port") -WorkingDirectory $toolRoot -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $runtimeDir 'server.stdout.log') -RedirectStandardError (Join-Path $runtimeDir 'server.stderr.log')
$process.Id | Set-Content -LiteralPath (Join-Path $runtimeDir 'server.pid')
Write-Output "已启动进程 $($process.Id)，等待客户端验证：http://127.0.0.1:$Port/mcp"
