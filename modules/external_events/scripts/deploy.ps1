param([int]$McpPort = 8878, [int]$WebPort = 8879, [switch]$NoBrowser)
$ErrorActionPreference = 'Stop'
$toolRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
if ($McpPort -eq $WebPort -or $McpPort -lt 1024 -or $McpPort -gt 65535 -or $WebPort -lt 1024 -or $WebPort -gt 65535) {
    throw '网页和MCP须使用不同的1024至65535端口。'
}
$pythonPath = Join-Path $toolRoot '.venv\Scripts\python.exe'
$runtimeDir = Join-Path $toolRoot '.local'
Push-Location $toolRoot
try {
    if (-not (Test-Path -LiteralPath $pythonPath)) {
        $launcher = Get-Command py -ErrorAction SilentlyContinue
        if ($launcher) { $pythonCommand = $launcher.Source; $pythonArgs = @('-3') }
        else {
            $launcher = Get-Command python -ErrorAction SilentlyContinue
            if (-not $launcher) { throw '请先安装Python 3.11或以上版本，并启用PATH，然后重新双击deploy.cmd。' }
            $pythonCommand = $launcher.Source; $pythonArgs = @()
        }
        & $pythonCommand @pythonArgs -c 'import sys; sys.exit(0 if sys.version_info >= (3,11) else 1)'
        if ($LASTEXITCODE -ne 0) { throw '需要Python 3.11或以上版本。' }
        Write-Output '创建独立Python环境…'
        & $pythonCommand @pythonArgs -m venv (Join-Path $toolRoot '.venv')
        if ($LASTEXITCODE -ne 0) { throw '创建虚拟环境失败。' }
    }
    New-Item -ItemType Directory -Path $runtimeDir -Force | Out-Null
    $lockFile = Join-Path $toolRoot 'requirements-lock.txt'
    $dependencyHash = (Get-FileHash -LiteralPath $lockFile -Algorithm SHA256).Hash
    $marker = Join-Path $runtimeDir 'dependencies.sha256'
    $previous = if (Test-Path -LiteralPath $marker) { (Get-Content -LiteralPath $marker -Raw).Trim() } else { '' }
    if ($previous -ne $dependencyHash) {
        Write-Output '安装已验证的依赖版本（首次需联网）…'
        & $pythonPath -X utf8 -m pip install --disable-pip-version-check -r $lockFile
        if ($LASTEXITCODE -ne 0) { throw '依赖安装失败；检查网络，重新运行即可继续安装。' }
        & $pythonPath -X utf8 -m pip check
        if ($LASTEXITCODE -ne 0) { throw '依赖一致性检查失败。' }
        [IO.File]::WriteAllText($marker, $dependencyHash, [Text.UTF8Encoding]::new($false))
    }
    $envFile = Join-Path $toolRoot '.env'
    if (-not (Test-Path -LiteralPath $envFile)) { Copy-Item -LiteralPath (Join-Path $toolRoot '.env.example') -Destination $envFile }
    & (Join-Path $PSScriptRoot 'start-all.ps1') -McpPort $McpPort -WebPort $WebPort
    $ready = $false
    for ($attempt = 0; $attempt -lt 30; $attempt++) {
        try {
            $config = Invoke-RestMethod -Uri "http://127.0.0.1:$WebPort/api/config" -TimeoutSec 2
            $ready = $true
            break
        } catch { Start-Sleep -Milliseconds 500 }
    }
    if (-not $ready) { throw '网页未能就绪；查看.local/web.stderr.log。' }
    & $pythonPath -X utf8 (Join-Path $PSScriptRoot 'check-local.py') --web-port $WebPort --mcp-port $McpPort
    if ($LASTEXITCODE -ne 0) { throw '本地服务协议检查未通过；查看.local日志。' }
    if (-not $config.search) {
        Write-Warning "网页已部署，但搜索凭据未配置。请在 $envFile 填入VOLCENGINE_SEARCH_API_KEY，再重启服务。已有环境变量ASK_ECHO_SEARCH_INFINITY_API_KEY也可复用。"
    }
    Write-Output "部署完成：http://127.0.0.1:$WebPort/"
    if (-not $NoBrowser) { Start-Process "http://127.0.0.1:$WebPort/" }
} finally { Pop-Location }
