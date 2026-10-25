param(
    [string]$PythonExecutable
)

$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$venvPython = Join-Path $projectRoot '.venv\Scripts\python.exe'

if (-not (Test-Path $venvPython)) {
    if (-not $PythonExecutable) {
        $installedPython = Join-Path $env:LocalAppData 'Programs\Python\Python311\python.exe'
        if (Test-Path $installedPython) {
            $PythonExecutable = $installedPython
        } elseif (Get-Command py -ErrorAction SilentlyContinue) {
            $PythonExecutable = 'py'
        } else {
            throw 'Install Python 3.11 or pass -PythonExecutable with its full path.'
        }
    }
    $pythonArgs = @()
    if ($PythonExecutable -eq 'py') {
        $pythonArgs += '-3.11'
    }
    & $PythonExecutable @pythonArgs -m venv (Join-Path $projectRoot '.venv')
    if ($LASTEXITCODE -ne 0) { throw 'Virtual environment creation failed.' }
}

& $venvPython -m pip install --upgrade pip
if ($LASTEXITCODE -ne 0) { throw 'pip upgrade failed.' }
& $venvPython -m pip install -r (Join-Path $projectRoot 'requirements.txt')
if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed.' }
& $venvPython -m pip install -e "${projectRoot}[dev]"
if ($LASTEXITCODE -ne 0) { throw 'Project installation failed.' }

Write-Output "Environment ready: $venvPython"
Write-Output "Activate with: & '$(Join-Path $projectRoot '.venv\Scripts\Activate.ps1')'"
