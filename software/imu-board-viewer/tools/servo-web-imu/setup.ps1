param([string]$PythonPath)

$ErrorActionPreference = 'Stop'
$projectDir = $PSScriptRoot
$tempDir = Join-Path $projectDir 'runtime-temp'
$cacheDir = Join-Path $projectDir 'pip-cache'
$venvDir = Join-Path $projectDir '.venv'
$venvPython = Join-Path $venvDir 'Scripts\python.exe'
$requirements = Join-Path $projectDir 'requirements-imu.lock.txt'

function Test-SupportedPython {
    param([string]$Executable, [string[]]$PrefixArgs = @())
    try {
        # No nested quotes: Windows PowerShell 5.1 native argument handling is lossy.
        $result = & $Executable @PrefixArgs -c 'import sys;print(sys.version_info.major,sys.version_info.minor,int(sys.maxsize>2**32));print(sys.executable)' 2>$null
        if ($LASTEXITCODE -ne 0) { return $null }
        $fields = ([string]$result[0]).Split(' ')
        if ($fields[2] -eq '1' -and ([int]$fields[0] -gt 3 -or ([int]$fields[0] -eq 3 -and [int]$fields[1] -ge 11))) {
            return [string]$result[1]
        }
    } catch { }
    return $null
}

try {
    if (-not (Test-Path -LiteralPath $requirements -PathType Leaf)) {
        throw "Missing dependency lock file: $requirements"
    }
    New-Item -ItemType Directory -Path $tempDir, $cacheDir -Force | Out-Null
    $env:TEMP = $tempDir
    $env:TMP = $tempDir
    $env:PIP_CACHE_DIR = $cacheDir
    $env:PYTHONNOUSERSITE = '1'
    $env:PYTHONUTF8 = '1'
    $env:PIP_DISABLE_PIP_VERSION_CHECK = '1'
    $env:PIP_REQUIRE_VIRTUALENV = 'true'

    if ($PythonPath) {
        $pythonExe = Test-SupportedPython -Executable $PythonPath
        if (-not $pythonExe) { throw "PythonPath must point to an installed 64-bit Python 3.11 or later: $PythonPath" }
    } else {
        $pythonExe = $null
        if (Test-Path -LiteralPath $venvPython -PathType Leaf) {
            $pythonExe = Test-SupportedPython -Executable $venvPython
        }
        if (-not $pythonExe) {
            $pyLauncher = Get-Command py.exe -ErrorAction SilentlyContinue
            if ($pyLauncher) { $pythonExe = Test-SupportedPython -Executable $pyLauncher.Source -PrefixArgs @('-3') }
        }
        if (-not $pythonExe) {
            foreach ($commandName in @('python.exe', 'python3.exe')) {
                $candidate = Get-Command $commandName -ErrorAction SilentlyContinue
                if ($candidate -and $candidate.Source -notlike '*\Microsoft\WindowsApps\*') {
                    $pythonExe = Test-SupportedPython -Executable $candidate.Source
                    if ($pythonExe) { break }
                }
            }
        }
        if (-not $pythonExe) {
            foreach ($registryRoot in @('HKCU:\SOFTWARE\Python\PythonCore', 'HKLM:\SOFTWARE\Python\PythonCore')) {
                foreach ($versionKey in @(Get-ChildItem -LiteralPath $registryRoot -ErrorAction SilentlyContinue | Sort-Object PSChildName -Descending)) {
                    $installKey = Get-Item -LiteralPath (Join-Path $versionKey.PSPath 'InstallPath') -ErrorAction SilentlyContinue
                    if ($installKey) {
                        $candidatePath = $installKey.GetValue('ExecutablePath')
                        if (-not $candidatePath -and $installKey.GetValue('')) {
                            $candidatePath = Join-Path $installKey.GetValue('') 'python.exe'
                        }
                        if ($candidatePath) { $pythonExe = Test-SupportedPython -Executable $candidatePath }
                        if ($pythonExe) { break }
                    }
                }
                if ($pythonExe) { break }
            }
        }
        if (-not $pythonExe) {
            throw 'Install 64-bit Python 3.11 or later on your preferred drive first, or run setup.ps1 -PythonPath "E:\Python\python.exe". This script does not install system Python or J-Link.'
        }
    }

    Write-Host "Python: $pythonExe"
    Write-Host "Local environment: $venvDir"
    if (-not (Test-Path -LiteralPath $venvPython -PathType Leaf)) {
        & $pythonExe -m venv $venvDir
        if ($LASTEXITCODE -ne 0) { throw 'Could not create the local virtual environment.' }
    }
    if (-not (Test-SupportedPython -Executable $venvPython)) {
        throw 'The existing .venv is invalid. Rename it and rerun setup; copied virtual environments are not portable.'
    }
    & $venvPython -m pip install --require-virtualenv --cache-dir $cacheDir -r $requirements
    if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed. Check the error above, network access, and free disk space, then rerun setup.' }

    $configPath = Join-Path $projectDir 'config.json'
    if (-not (Test-Path -LiteralPath $configPath)) {
        Copy-Item -LiteralPath (Join-Path $projectDir 'config.example.json') -Destination $configPath
    }
    Write-Host ''
    Write-Host 'Setup complete. Demo mode is ready.'
    Write-Host 'For a real board, edit config.json: enter your probe_serial and installed JLink_x64.dll path.'
    Write-Host 'No system Python or J-Link driver was installed. Dependencies and caches are inside this project.'
    exit 0
} catch {
    Write-Host ("ERROR: " + $_.Exception.Message) -ForegroundColor Red
    exit 1
}
