$ErrorActionPreference = "Stop"
$RunArgs = $args
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$SkillRoot = Split-Path -Parent $ScriptDir
$VenvDir = if ($env:VIDEO_DIRECTOR_VENV) { $env:VIDEO_DIRECTOR_VENV } else { Join-Path $SkillRoot ".venv" }

if ($RunArgs.Count -gt 0 -and $RunArgs[0] -eq "update") {
    $UpdateArgs = @()
    if ($RunArgs.Count -gt 1) {
        $UpdateArgs = $RunArgs[1..($RunArgs.Count - 1)]
    }
    & (Join-Path $ScriptDir "update.ps1") @UpdateArgs
    exit $LASTEXITCODE
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

function Get-VenvPython {
    $Candidates = @(
        (Join-Path $VenvDir "Scripts\python.exe"),
        (Join-Path $VenvDir "bin/python")
    )

    foreach ($Candidate in $Candidates) {
        if (Test-PythonCompatible $Candidate) {
            return $Candidate
        }
    }
    return $null
}

if (-not $env:VIDEO_DIRECTOR_PYTHON) {
    $ResolvedPython = Get-VenvPython
    if ($ResolvedPython) {
        $env:VIDEO_DIRECTOR_PYTHON = $ResolvedPython
    } elseif ($env:VIDEO_DIRECTOR_NO_AUTO_INSTALL -ne "1") {
        & (Join-Path $ScriptDir "install.ps1") -SkipSystemInstall
        $ResolvedPython = Get-VenvPython
        if ($ResolvedPython) {
            $env:VIDEO_DIRECTOR_PYTHON = $ResolvedPython
        }
    }
}

& (Join-Path $ScriptDir "video-director.cmd") @RunArgs
exit $LASTEXITCODE
