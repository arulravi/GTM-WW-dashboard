$ErrorActionPreference = "Stop"
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Push-Location $repoRoot
try {
    Write-Host "[1/3] Running Python regression suite..."
    python -m unittest discover -s tests -v
    if ($LASTEXITCODE -ne 0) {
        throw "Python regression suite failed with exit code $LASTEXITCODE. Deployment must stop."
    }

    $node = Get-Command node -ErrorAction SilentlyContinue
    if (-not $node) {
        throw "Node.js is required for the dashboard JavaScript syntax check. Deployment must stop."
    }
    $dashboard = Join-Path $repoRoot "dashboard.html"
    $temporaryScript = Join-Path ([System.IO.Path]::GetTempPath()) (
        "gtm-dashboard-inline-{0}.js" -f [guid]::NewGuid().ToString("N")
    )
    try {
        Write-Host "[2/3] Checking inline dashboard JavaScript syntax..."
        @'
from pathlib import Path
import re
import sys

source = Path(sys.argv[1]).read_text(encoding="utf-8")
scripts = re.findall(r"<script\b[^>]*>(.*?)</script\s*>", source, re.I | re.S)
Path(sys.argv[2]).write_text("\n".join(scripts), encoding="utf-8")
'@ | python - $dashboard $temporaryScript
        if ($LASTEXITCODE -ne 0) {
            throw "Could not extract inline JavaScript (exit code $LASTEXITCODE). Deployment must stop."
        }
        & $node.Source --check $temporaryScript
        if ($LASTEXITCODE -ne 0) {
            throw "Inline dashboard JavaScript syntax check failed (exit code $LASTEXITCODE). Deployment must stop."
        }
    }
    finally {
        if (Test-Path -LiteralPath $temporaryScript) {
            Remove-Item -LiteralPath $temporaryScript -Force
        }
    }

    Write-Host "[3/3] Checking patch whitespace..."
    git diff --check
    if ($LASTEXITCODE -ne 0) {
        throw "git diff --check failed (exit code $LASTEXITCODE). Deployment must stop."
    }

    Write-Host "Automated pre-deployment checks passed."
    Write-Host "Browser end-to-end and real cross-device OneDrive tests are not run by this script; see docs/REGRESSION_CHECKLIST.md."
}
finally {
    Pop-Location
}
