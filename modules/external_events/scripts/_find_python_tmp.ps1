$ErrorActionPreference = 'SilentlyContinue'
$paths = @(
    "$env:LOCALAPPDATA\Programs\Python",
    'C:\Python313', 'C:\Python312', 'C:\Python311',
    'C:\ProgramData\miniconda3', 'C:\ProgramData\anaconda3',
    "$env:USERPROFILE\miniconda3", "$env:USERPROFILE\anaconda3",
    'D:\Python313', 'D:\Python312', 'D:\ProgramData\miniconda3'
)
foreach ($p in $paths) {
    if (Test-Path $p) {
        Write-Output "EXISTS: $p"
        Get-ChildItem $p | Select-Object -First 10 -ExpandProperty Name
    }
}
$uv = Get-Command uv -ErrorAction SilentlyContinue
if ($uv) { Write-Output "UV: $($uv.Source)" }
$python = Get-Command python -ErrorAction SilentlyContinue
if ($python) { Write-Output "PYTHON: $($python.Source)" }
