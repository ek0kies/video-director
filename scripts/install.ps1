param(
    [switch] $NoSystemInstall,
    [switch] $SkipSystemInstall,
    [switch] $SkipDoctor,
    [string] $Venv
)

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$SkillRoot = Split-Path -Parent $ScriptDir
$VenvDir = if ($Venv) { $Venv } elseif ($env:VIDEO_DIRECTOR_VENV) { $env:VIDEO_DIRECTOR_VENV } else { Join-Path $SkillRoot ".venv" }
$RequirementsFile = Join-Path $SkillRoot "requirements.txt"
$PipCacheDir = if ($env:VIDEO_DIRECTOR_PIP_CACHE_DIR) { $env:VIDEO_DIRECTOR_PIP_CACHE_DIR } else { Join-Path $SkillRoot ".cache\pip" }
$AllowSystemInstall = -not ($NoSystemInstall -or $SkipSystemInstall)

function Write-Pass { param([string] $Message) Write-Host "PASS $Message" }
function Write-Info { param([string] $Message) Write-Host "INFO $Message" }
function Write-Fail { param([string] $Message) Write-Host "FAIL $Message" }

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

function Get-VenvPython {
    $Candidates = @(
        (Join-Path $VenvDir "Scripts\python.exe"),
        (Join-Path $VenvDir "bin/python")
    )
    foreach ($Candidate in $Candidates) {
        if (Test-Path -LiteralPath $Candidate) {
            return $Candidate
        }
    }
    return $null
}

function Write-PythonFix {
    Write-Host "FIX python:"
    Write-Host "  Windows: winget install Python.Python.3.11"
    Write-Host "  Windows Store disabled: install Python 3.11+ from python.org, then rerun scripts\install.ps1"
}

function Write-FfmpegFix {
    Write-Host "FIX ffmpeg:"
    Write-Host "  Windows winget: winget install Gyan.FFmpeg"
    Write-Host "  Windows Chocolatey: choco install ffmpeg -y"
    Write-Host "  Windows Scoop: scoop install ffmpeg"
}

function Try-InstallFfmpeg {
    if (-not $AllowSystemInstall) {
        return $false
    }
    if ((Get-Command ffmpeg -ErrorAction SilentlyContinue) -and (Get-Command ffprobe -ErrorAction SilentlyContinue)) {
        return $true
    }

    if (Get-Command winget -ErrorAction SilentlyContinue) {
        Write-Info "attempting ffmpeg install with winget"
        & winget install Gyan.FFmpeg --accept-package-agreements --accept-source-agreements
        return $LASTEXITCODE -eq 0
    }
    if (Get-Command choco -ErrorAction SilentlyContinue) {
        Write-Info "attempting ffmpeg install with Chocolatey"
        & choco install ffmpeg -y
        return $LASTEXITCODE -eq 0
    }
    if (Get-Command scoop -ErrorAction SilentlyContinue) {
        Write-Info "attempting ffmpeg install with Scoop"
        & scoop install ffmpeg
        return $LASTEXITCODE -eq 0
    }
    return $false
}

if (-not (Test-Path -LiteralPath $RequirementsFile)) {
    Write-Fail "requirements file not found: $RequirementsFile"
    exit 1
}

try {
    $ProbePath = Join-Path $SkillRoot ".write-test"
    Set-Content -LiteralPath $ProbePath -Value "ok" -Encoding UTF8
    Remove-Item -LiteralPath $ProbePath -Force
    Write-Pass "skill directory writable: $SkillRoot"
} catch {
    Write-Fail "skill directory is not writable: $SkillRoot"
    Write-Host "FIX permissions:"
    Write-Host "  Move the Skill to a user-writable directory or grant write permission to this directory."
    exit 1
}

New-Item -ItemType Directory -Force -Path $PipCacheDir | Out-Null
$env:PIP_CACHE_DIR = $PipCacheDir
Write-Pass "pip cache directory: $PipCacheDir"

$PythonCmd = Resolve-Python
if (-not $PythonCmd) {
    Write-Fail "Python 3.10+ not found"
    Write-PythonFix
    exit 1
}
Write-Pass "python: $(Get-PythonVersion $PythonCmd)"

if (-not (Test-Path -LiteralPath $VenvDir)) {
    Write-Info "creating virtual environment: $VenvDir"
    Invoke-PythonCandidate $PythonCmd @("-m", "venv", $VenvDir)
    if ($LASTEXITCODE -ne 0) {
        Write-Fail "failed to create virtual environment"
        Write-Host "FIX venv:"
        Write-Host "  $PythonCmd -m ensurepip --upgrade"
        Write-Host "  $PythonCmd -m venv `"$VenvDir`""
        exit 1
    }
} else {
    Write-Info "reusing virtual environment: $VenvDir"
}

$VenvPython = Get-VenvPython
if (-not $VenvPython) {
    Write-Fail "virtual environment python not found under $VenvDir"
    exit 1
}
Write-Pass "venv python: $VenvPython"

& $VenvPython -m pip --version *> $null
if ($LASTEXITCODE -ne 0) {
    Write-Fail "pip is unavailable in virtual environment"
    Write-Host "FIX pip:"
    Write-Host "  `"$VenvPython`" -m ensurepip --upgrade"
    exit 1
}
Write-Pass "pip available"

Write-Info "installing baseline Python requirements"
& $VenvPython -m pip install -r $RequirementsFile
if ($LASTEXITCODE -ne 0) {
    Write-Fail "pip install failed"
    Write-Host "FIX python dependency:"
    Write-Host "  `"$VenvPython`" -m pip install -r `"$RequirementsFile`""
    exit 1
}
Write-Pass "requirements installed: $RequirementsFile"

& $VenvPython -c "import importlib; importlib.import_module('PIL')" *> $null
if ($LASTEXITCODE -ne 0) {
    Write-Fail "PIL import failed after install"
    Write-Host "FIX python dependency:"
    Write-Host "  `"$VenvPython`" -m pip install -r `"$RequirementsFile`""
    exit 1
}
Write-Pass "python dependency importable: PIL"

if ((Get-Command ffmpeg -ErrorAction SilentlyContinue) -and (Get-Command ffprobe -ErrorAction SilentlyContinue)) {
    Write-Pass "ffmpeg/ffprobe available"
} elseif ((Try-InstallFfmpeg) -and (Get-Command ffmpeg -ErrorAction SilentlyContinue) -and (Get-Command ffprobe -ErrorAction SilentlyContinue)) {
    Write-Pass "ffmpeg/ffprobe installed"
} else {
    Write-Fail "ffmpeg/ffprobe unavailable"
    Write-FfmpegFix
    exit 1
}

$env:VIDEO_DIRECTOR_PYTHON = $VenvPython
if (-not $SkipDoctor) {
    & (Join-Path $ScriptDir "doctor.ps1") (Join-Path $SkillRoot "runtime\templates\video.template.json")
    if ($LASTEXITCODE -ne 0) {
        exit $LASTEXITCODE
    }
}

Write-Pass "Video Director install complete"
