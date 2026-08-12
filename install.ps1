[CmdletBinding()]
param(
    [switch]$InstallDev
)

$ErrorActionPreference = "Stop"
$installRoot = (Resolve-Path -LiteralPath $PSScriptRoot).Path
$venvPython = Join-Path $installRoot ".venv\Scripts\python.exe"
$requirements = Join-Path $installRoot "requirements.txt"
$skillSource = Join-Path $installRoot "skills\latexword-word-editing"

if (-not (Test-Path -LiteralPath $venvPython)) {
    $pythonLauncher = Get-Command py -ErrorAction SilentlyContinue
    if ($null -ne $pythonLauncher) {
        & $pythonLauncher.Source -3 -m venv (Join-Path $installRoot ".venv")
    }
    else {
        $pythonCommand = Get-Command python -ErrorAction SilentlyContinue
        if ($null -eq $pythonCommand) {
            throw "Python 3.10 or newer is required; neither 'py' nor 'python' is available."
        }
        & $pythonCommand.Source -m venv (Join-Path $installRoot ".venv")
    }
    if ($LASTEXITCODE -ne 0) {
        throw "Could not create the virtual environment."
    }
}

& $venvPython -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)"
if ($LASTEXITCODE -ne 0) {
    throw "Python 3.10 or newer is required."
}

& $venvPython -m pip install --upgrade pip
if ($LASTEXITCODE -ne 0) {
    throw "Could not upgrade pip."
}
& $venvPython -m pip install -r $requirements
if ($LASTEXITCODE -ne 0) {
    throw "Could not install runtime requirements."
}
if ($InstallDev) {
    & $venvPython -m pip install -r (Join-Path $installRoot "requirements-dev.txt")
    if ($LASTEXITCODE -ne 0) {
        throw "Could not install development requirements."
    }
}

$codexRoot = if ($env:CODEX_HOME) { $env:CODEX_HOME } else { Join-Path $env:USERPROFILE ".codex" }
$skillTarget = Join-Path $codexRoot "skills\latexword-word-editing"
New-Item -ItemType Directory -Force -Path $skillTarget | Out-Null
Copy-Item -Path (Join-Path $skillSource "*") -Destination $skillTarget -Recurse -Force

$installedSkill = Join-Path $skillTarget "SKILL.md"
$skillText = [IO.File]::ReadAllText($installedSkill)
if (-not $skillText.Contains("__LATEXWORD_ROOT__")) {
    throw "The skill template does not contain the installation placeholder."
}
$skillText = $skillText.Replace("__LATEXWORD_ROOT__", $installRoot)
$utf8 = [System.Text.UTF8Encoding]::new($false)
[IO.File]::WriteAllText($installedSkill, $skillText, $utf8)

& $venvPython -c "import docx, lxml"
if ($LASTEXITCODE -ne 0) {
    throw "Runtime dependency verification failed."
}

Write-Output "LaTeXWord installed at: $installRoot"
Write-Output "Python: $venvPython"
Write-Output "Codex skill: $skillTarget"
Write-Output "Restart Codex once if it does not discover the newly installed skill."
