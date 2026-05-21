param(
    [string] $ConfigPath
)

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$SkillRoot = Split-Path -Parent $ScriptDir
$VenvDir = if ($env:VIDEO_DIRECTOR_VENV) { $env:VIDEO_DIRECTOR_VENV } else { Join-Path $SkillRoot ".venv" }
if (-not $ConfigPath) {
    $ConfigPath = Join-Path $SkillRoot "runtime\templates\video.template.json"
}
$FailCount = 0

function Write-Pass { param([string] $Message) Write-Host "PASS $Message" }
function Write-Info { param([string] $Message) Write-Host "INFO $Message" }
function Write-Fail {
    param([string] $Message)
    $script:FailCount += 1
    Write-Host "FAIL $Message"
}

function Invoke-PythonCandidate {
    param(
        [Parameter(Mandatory = $true)][string] $Candidate,
        [Parameter(Mandatory = $true)][string[]] $Arguments
    )

    if (Test-Path -LiteralPath $Candidate) {
        & $Candidate @Arguments
        return
    }

    $Parts = $Candidate -split "\s+"
    $Command = $Parts[0]
    $PrefixArgs = @()
    if ($Parts.Count -gt 1) {
        $PrefixArgs = $Parts[1..($Parts.Count - 1)]
    }
    & $Command @PrefixArgs @Arguments
}

function Test-PythonCompatible {
    param([Parameter(Mandatory = $true)][string] $Candidate)

    if (-not (Test-Path -LiteralPath $Candidate) -and -not (Get-Command (($Candidate -split "\s+")[0]) -ErrorAction SilentlyContinue)) {
        return $false
    }

    try {
        Invoke-PythonCandidate $Candidate @("-c", "import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)") *> $null
        return $LASTEXITCODE -eq 0
    } catch {
        return $false
    }
}

function Get-PythonVersion {
    param([string] $Candidate)
    Invoke-PythonCandidate $Candidate @("-c", "import sys; print(f'{sys.executable} {sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}')")
}

function Resolve-Python {
    $Candidates = @()
    if ($env:VIDEO_DIRECTOR_PYTHON) {
        $Candidates += $env:VIDEO_DIRECTOR_PYTHON
    }
    $Candidates += @(
        (Join-Path $VenvDir "Scripts\python.exe"),
        (Join-Path $VenvDir "bin/python"),
        "python3",
        "python",
        "py -3",
        "py -3.13",
        "py -3.12",
        "py -3.11",
        "py -3.10"
    )

    foreach ($Candidate in $Candidates) {
        if (Test-PythonCompatible $Candidate) {
            return $Candidate
        }
    }
    return $null
}

function Write-FfmpegFix {
    Write-Host "FIX ffmpeg:"
    Write-Host "  Windows winget: winget install Gyan.FFmpeg"
    Write-Host "  Windows Chocolatey: choco install ffmpeg -y"
    Write-Host "  Windows Scoop: scoop install ffmpeg"
}

$PythonCmd = Resolve-Python
if ($PythonCmd) {
    Write-Pass "python: $(Get-PythonVersion $PythonCmd)"
} else {
    Write-Fail "python: Python 3.10+ not found"
    Write-Host "FIX python:"
    Write-Host "  Windows: winget install Python.Python.3.11"
    Write-Host "  Windows Store disabled: install Python 3.11+ from python.org, then rerun scripts\install.ps1"
}

if ($PythonCmd) {
    try {
        Invoke-PythonCandidate $PythonCmd @("-c", "import importlib; importlib.import_module('PIL')") *> $null
        if ($LASTEXITCODE -eq 0) {
            Write-Pass "python dependency: PIL importable"
        } else {
            Write-Fail "python dependency: PIL missing"
            Write-Host "FIX python dependency:"
            Write-Host "  powershell -ExecutionPolicy Bypass -File scripts\install.ps1"
        }
    } catch {
        Write-Fail "python dependency: PIL missing"
        Write-Host "FIX python dependency:"
        Write-Host "  powershell -ExecutionPolicy Bypass -File scripts\install.ps1"
    }
}

$Ffmpeg = Get-Command ffmpeg -ErrorAction SilentlyContinue
if ($Ffmpeg) {
    Write-Pass "ffmpeg: $($Ffmpeg.Source)"
} else {
    Write-Fail "ffmpeg: not found on PATH"
    Write-FfmpegFix
}

$Ffprobe = Get-Command ffprobe -ErrorAction SilentlyContinue
if ($Ffprobe) {
    Write-Pass "ffprobe: $($Ffprobe.Source)"
} else {
    Write-Fail "ffprobe: not found on PATH"
    Write-FfmpegFix
}

try {
    $ProbePath = Join-Path $SkillRoot ".write-test"
    Set-Content -LiteralPath $ProbePath -Value "ok" -Encoding UTF8
    Remove-Item -LiteralPath $ProbePath -Force
    Write-Pass "skill directory writable: $SkillRoot"
} catch {
    Write-Fail "skill directory not writable: $SkillRoot"
    Write-Host "FIX permissions:"
    Write-Host "  Move the Skill to a user-writable directory or grant write permission to this directory."
}

if ($PythonCmd -and (Test-Path -LiteralPath $ConfigPath)) {
    $env:VIDEO_DIRECTOR_PYTHON = $PythonCmd
    $Output = & (Join-Path $ScriptDir "video-director.cmd") doctor $ConfigPath 2>&1
    $OutputText = $Output -join [Environment]::NewLine
    if ($LASTEXITCODE -eq 0) {
        Write-Pass "runtime doctor: $ConfigPath"
        Write-Info $OutputText
    } else {
        Write-Fail "runtime doctor failed: $ConfigPath"
        Write-Info $OutputText
    }
} elseif (-not (Test-Path -LiteralPath $ConfigPath)) {
    Write-Fail "config not found: $ConfigPath"
    Write-Host "FIX config:"
    Write-Host "  powershell -ExecutionPolicy Bypass -File scripts\run.ps1 config local --output-mode video --output video-director.video.local.json --job-id demo --narration-text smoke"
}

if ($FailCount -eq 0) {
    Write-Host "STATUS PASS video-director environment is ready"
    exit 0
}

Write-Host "STATUS FAIL video-director environment has $FailCount failing check(s)"
exit 1
