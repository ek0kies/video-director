$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$SkillRoot = Split-Path -Parent $ScriptDir
$SmokeBase = if ($env:VIDEO_DIRECTOR_SMOKE_ROOT) {
    $env:VIDEO_DIRECTOR_SMOKE_ROOT
} else {
    Join-Path ([System.IO.Path]::GetTempPath()) ("video-director-smoke-" + [System.Guid]::NewGuid().ToString("N"))
}
$DemoRoot = Join-Path $SmokeBase "demo\contest"
$ConfigPath = Join-Path $DemoRoot "video-director.contest-demo.local.json"
$SummaryPath = Join-Path $DemoRoot "output\contest-demo\latest_run.json"

try {
    Write-Host "INFO smoke root: $SmokeBase"

    & (Join-Path $SkillRoot "scripts\install.ps1") -NoSystemInstall
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

    & (Join-Path $SkillRoot "scripts\doctor.ps1") (Join-Path $SkillRoot "runtime\templates\video.template.json")
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

    $env:VIDEO_DIRECTOR_DEMO_ROOT = $DemoRoot
    & (Join-Path $SkillRoot "scripts\run.ps1") demo
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

    & (Join-Path $SkillRoot "scripts\doctor.ps1") $ConfigPath
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

    & (Join-Path $SkillRoot "scripts\run.ps1") run $ConfigPath --dry-run
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

    & (Join-Path $SkillRoot "scripts\run.ps1") run $ConfigPath
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

    & (Join-Path $SkillRoot "scripts\run.ps1") summarize $SummaryPath
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

    Write-Host "STATUS PASS video-director smoke completed"
} finally {
    if ($env:VIDEO_DIRECTOR_KEEP_SMOKE -ne "1" -and (Test-Path -LiteralPath $SmokeBase)) {
        Remove-Item -LiteralPath $SmokeBase -Recurse -Force
    }
}
