# Start n8n with Laragon's Node.js. Credentials stay in n8n, not in this repository.
# If PowerShell says running scripts is disabled, use scripts\start-n8n.cmd instead.
$nodeDir = "D:\laragon\bin\nodejs\node-v22.23.4-win-x64"
if (-not (Test-Path (Join-Path $nodeDir "node.exe"))) {
    Write-Error "Laragon Node.js was not found at $nodeDir"
    exit 1
}

$env:Path = "$nodeDir;" + $env:Path
if (-not (Get-Command n8n -ErrorAction SilentlyContinue)) {
    npm install -g n8n
}

n8n start
