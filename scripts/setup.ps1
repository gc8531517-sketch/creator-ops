param([string]$Python = 'python')
$ErrorActionPreference = 'Stop'
$project = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).Path
Push-Location -LiteralPath $project
try {
    & $Python -c 'import sys; sys.exit(0 if sys.version_info >= (3,11) else 1)'
    if ($LASTEXITCODE -ne 0) { throw 'Python 3.11+ required' }
    if (-not (Test-Path -LiteralPath '.venv/Scripts/python.exe')) {
        & $Python -m venv .venv
        if ($LASTEXITCODE -ne 0) { throw 'VENV_CREATE_FAILED' }
    }
    & ./.venv/Scripts/python.exe -m pip install -r requirements.txt
    if ($LASTEXITCODE -ne 0) { throw 'DEPENDENCY_INSTALL_FAILED' }
    if (-not (Test-Path -LiteralPath 'config.local.json')) {
        & ./.venv/Scripts/python.exe tools/creator.py init-config
        if ($LASTEXITCODE -ne 0) { throw 'CONFIG_INIT_FAILED' }
    }
    Write-Output 'Installed. Configure Chrome extension and lark-cli, then run tools/creator.py doctor.'
} finally { Pop-Location }
