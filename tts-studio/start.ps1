param([int]$Port = 8765)
$ErrorActionPreference = 'Stop'
python "$PSScriptRoot/server.py" --port $Port
