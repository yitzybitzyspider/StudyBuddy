# run-cheap.ps1 — start StudyBuddy live on the cheapest model (testing config).
#
# Usage (from the repo root, with the venv created):
#   .\run-cheap.ps1                       # prompts for your key, runs the web UI on Haiku 4.5
#   .\run-cheap.ps1 -Key "sk-ant-..."     # pass the key inline instead of being prompted
#   .\run-cheap.ps1 -WebSearch            # also allow the harvest-web step (uses Opus 4.6+)
#   .\run-cheap.ps1 -Port 5050            # serve on a different port
#
# The key is set for THIS shell session only — it is never written to a file.
# If execution policy blocks the script, run once:
#   Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass

param(
    [string]$Key,
    [switch]$WebSearch,
    [int]$Port = 5000,
    [string]$Model = "claude-haiku-4-5-20251001"
)

$ErrorActionPreference = "Stop"

# --- API key (session-only) ---------------------------------------------------------
if (-not $Key) { $Key = $env:ANTHROPIC_API_KEY }
if (-not $Key) {
    $secure = Read-Host "Paste your ANTHROPIC_API_KEY" -AsSecureString
    $Key = [System.Net.NetworkCredential]::new("", $secure).Password
}
if (-not $Key) { Write-Error "No API key provided."; exit 1 }
$env:ANTHROPIC_API_KEY = $Key

# --- model config -------------------------------------------------------------------
$env:STUDYBUDDY_MODEL = $Model
Remove-Item Env:STUDYBUDDY_OFFLINE -ErrorAction SilentlyContinue   # make sure live, not offline

if ($WebSearch) {
    $env:STUDYBUDDY_WEBSEARCH_MODEL = "claude-opus-4-6"
    Write-Host "Web search ENABLED for harvest-web (Opus 4.6+, bills per search)." -ForegroundColor Yellow
} else {
    Remove-Item Env:STUDYBUDDY_WEBSEARCH_MODEL -ErrorAction SilentlyContinue
}

# --- python from the local venv if present ------------------------------------------
$py = if (Test-Path ".\.venv\Scripts\python.exe") { ".\.venv\Scripts\python.exe" } else { "python" }

Write-Host "Model: $env:STUDYBUDDY_MODEL  (cheap testing config)" -ForegroundColor Cyan
Write-Host "Watch calls live in another window: Get-Content .\runs\runlog.jsonl -Wait -Tail 20" -ForegroundColor DarkGray
& $py -m studybuddy serve --port $Port
