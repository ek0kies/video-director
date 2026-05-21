param(
    [switch] $Help,
    [switch] $SkipVerify,
    [string] $Remote = $(if ($env:VIDEO_DIRECTOR_REMOTE) { $env:VIDEO_DIRECTOR_REMOTE } else { "origin" }),
    [string] $Ref = $(if ($env:VIDEO_DIRECTOR_REMOTE_REF) { $env:VIDEO_DIRECTOR_REMOTE_REF } else { "" })
)

$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$SkillRoot = Split-Path -Parent $ScriptDir

if ($Help) {
    Write-Host @"
usage: scripts\update.ps1 [-SkipVerify] [-Remote NAME] [-Ref REF]

Update an existing Video Director Git checkout and verify the installed Skill.

Options:
  -SkipVerify   update only; do not run install, doctor, or smoke checks
  -Remote NAME  Git remote to fetch from, default: origin
  -Ref REF      optional remote ref to fast-forward to, for example origin/main
  -Help         show this help

This script never overwrites local modifications. If the Skill is not a Git
checkout, the Agent should back it up, clone the latest repository, and repoint
the Agent skill registration to the whole repository.
"@
    exit 0
}

function Write-Info {
    param([string] $Message)
    Write-Host "INFO update: $Message"
}

function Write-Pass {
    param([string] $Message)
    Write-Host "PASS update: $Message"
}

function Write-Fail {
    param([string] $Message)
    [Console]::Error.WriteLine("FAIL update: $Message")
}

if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
    Write-Fail "git is required to update a Git checkout"
    exit 1
}

$GitRoot = (& git -C $SkillRoot rev-parse --show-toplevel 2>$null)
if ($LASTEXITCODE -ne 0 -or -not $GitRoot) {
    [Console]::Error.WriteLine("FAIL update: registered Skill is not a Git checkout: $SkillRoot")
    [Console]::Error.WriteLine("ACTION_REQUIRED non_git_copy")
    [Console]::Error.WriteLine("Backup this directory, clone https://github.com/ek0kies/video-director to a stable local path, and repoint the current Agent's video-director Skill registration to the whole cloned repository.")
    exit 3
}

Set-Location $GitRoot
Write-Info "install path: $GitRoot"
Write-Info "registered skill path: $SkillRoot"

$Status = (& git status --porcelain)
if ($Status) {
    [Console]::Error.WriteLine("FAIL update: local changes are present; refusing to update")
    & git status --short
    [Console]::Error.WriteLine("ACTION_REQUIRED dirty_tree")
    [Console]::Error.WriteLine("Ask whether to back up, commit, or stop. Do not overwrite these changes.")
    exit 4
}

$CurrentBranch = (& git rev-parse --abbrev-ref HEAD).Trim()
if ($CurrentBranch -eq "HEAD" -and -not $Ref) {
    [Console]::Error.WriteLine("FAIL update: checkout is detached; pass -Ref <remote/ref> or update manually")
    exit 5
}

Write-Info "fetching $Remote"
& git fetch --prune $Remote
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

if ($Ref) {
    Write-Info "fast-forwarding to $Ref"
    & git merge --ff-only $Ref
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
} else {
    $Upstream = (& git rev-parse --abbrev-ref --symbolic-full-name '@{u}' 2>$null)
    if ($LASTEXITCODE -eq 0 -and $Upstream) {
        Write-Info "fast-forwarding from $Upstream"
        & git merge --ff-only $Upstream
        if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    } else {
        $RemoteBranch = "$Remote/$CurrentBranch"
        Write-Info "fast-forwarding from $RemoteBranch"
        & git merge --ff-only $RemoteBranch
        if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    }
}

Write-Pass "repository updated"

if ($SkipVerify -or $env:VIDEO_DIRECTOR_SKIP_VERIFY -eq "1") {
    Write-Pass "verification skipped by request"
    exit 0
}

& (Join-Path $ScriptDir "install.ps1") -SkipSystemInstall
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

& (Join-Path $ScriptDir "doctor.ps1") (Join-Path $GitRoot "runtime\templates\video.template.json")
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

& (Join-Path $GitRoot "tests\smoke.ps1")
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Write-Pass "Video Director update verified"
