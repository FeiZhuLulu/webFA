param(
  [ValidateSet("onedir", "onefile")]
  [string]$Mode = "onefile",
  [string]$PythonExecutable = "python"
)

$ErrorActionPreference = "Stop"
$Root = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot ".."))
$ReleaseRoot = Join-Path $Root ".release"
$VenvRoot = Join-Path $ReleaseRoot "sidecar-venv"
$WheelRoot = Join-Path $ReleaseRoot "wheels"
$WorkRoot = Join-Path $ReleaseRoot "pyinstaller-work"
$DistRoot = Join-Path $ReleaseRoot "pyinstaller-dist"
$FreezeCwd = Join-Path $ReleaseRoot "freeze-cwd"
$SidecarRoot = Join-Path $ReleaseRoot "sidecar"
$SourceBuildRoot = Join-Path $Root "build"
$EggInfoRoot = Join-Path $Root "webfa_desktop_runtime.egg-info"
$ReleaseLock = Join-Path $Root "packaging\python-windows-release-lock.txt"
$Spec = Join-Path $Root "packaging\webfa-sidecar.spec"
$VersionSource = Join-Path $Root "apps\runtime\version.py"
$ExpectedSeededPipVersion = "25.0.1"

$VersionMatch = [regex]::Match(
  (Get-Content -LiteralPath $VersionSource -Raw),
  '__version__\s*=\s*["'']([^"'']+)["'']'
)
if (-not $VersionMatch.Success) {
  throw "Could not read the WebFA release version from $VersionSource"
}
$ReleaseVersion = $VersionMatch.Groups[1].Value

function Assert-WorkspaceChild([string]$Target) {
  $Full = [IO.Path]::GetFullPath($Target)
  $Prefix = $Root.TrimEnd([IO.Path]::DirectorySeparatorChar) + [IO.Path]::DirectorySeparatorChar
  if (-not $Full.StartsWith($Prefix, [StringComparison]::OrdinalIgnoreCase)) {
    throw "Refusing to mutate a path outside the workspace: $Full"
  }
}

function Remove-SafeTree([string]$Target) {
  Assert-WorkspaceChild $Target
  if (Test-Path -LiteralPath $Target) {
    Remove-Item -LiteralPath $Target -Recurse -Force
  }
}

function Invoke-Checked([string]$Program, [string[]]$Arguments) {
  & $Program @Arguments
  if ($LASTEXITCODE -ne 0) {
    throw "Command failed with exit code ${LASTEXITCODE}: $Program $($Arguments -join ' ')"
  }
}

foreach ($Target in @($VenvRoot, $WheelRoot, $WorkRoot, $DistRoot, $FreezeCwd, $SidecarRoot, $SourceBuildRoot, $EggInfoRoot)) {
  Remove-SafeTree $Target
}
New-Item -ItemType Directory -Force -Path $ReleaseRoot, $WheelRoot, $FreezeCwd | Out-Null

# The release interpreter and the fresh venv must not inherit import roots from
# the invoking developer shell. Exact wheel hashes do not protect a shadowed
# `pip` or `build` module that is imported before the lock is evaluated.
Remove-Item Env:PYTHONHOME -ErrorAction SilentlyContinue
Remove-Item Env:PYTHONPATH -ErrorAction SilentlyContinue
Remove-Item Env:VIRTUAL_ENV -ErrorAction SilentlyContinue
$env:PYTHONNOUSERSITE = "1"
$env:PIP_DISABLE_PIP_VERSION_CHECK = "1"
$env:PIP_NO_INPUT = "1"

Push-Location $Root
try {
  $BuildRuntimeJson = & $PythonExecutable -I -c @'
import json, platform, struct, sys
print(json.dumps({
    'implementation': platform.python_implementation(),
    'major': sys.version_info.major,
    'minor': sys.version_info.minor,
    'micro': sys.version_info.micro,
    'bits': struct.calcsize('P') * 8,
    'system': platform.system(),
    'machine': platform.machine(),
}))
'@
  if ($LASTEXITCODE -ne 0) {
    throw "Could not inspect the Python build runtime"
  }
  $BuildRuntime = $BuildRuntimeJson | ConvertFrom-Json
  if (
    $BuildRuntime.implementation -ne "CPython" -or
    $BuildRuntime.major -ne 3 -or
    $BuildRuntime.minor -ne 12 -or
    $BuildRuntime.micro -ne 10 -or
    $BuildRuntime.bits -ne 64 -or
    $BuildRuntime.system -ne "Windows" -or
    $BuildRuntime.machine -notin @("AMD64", "x86_64")
  ) {
    throw "Sidecar releases require Windows x64 CPython 3.12.10; got $BuildRuntimeJson"
  }

  Invoke-Checked $PythonExecutable @("-I", "-m", "venv", $VenvRoot)
  $VenvPython = Join-Path $VenvRoot "Scripts\python.exe"
  $SeededPipVersion = & $VenvPython -I -c @'
from importlib.metadata import version
print(version('pip'))
'@
  if ($LASTEXITCODE -ne 0) {
    throw "Could not inspect the fresh venv seeded pip version"
  }
  $SeededPipVersion = "$SeededPipVersion".Trim()
  if ($SeededPipVersion -ne $ExpectedSeededPipVersion) {
    throw "CPython 3.12.10 must seed pip $ExpectedSeededPipVersion; got $SeededPipVersion"
  }
  Invoke-Checked $VenvPython @(
    "-I", "-m", "pip", "--isolated", "install", "--only-binary=:all:", "--require-hashes", "-r", $ReleaseLock
  )
  Invoke-Checked $VenvPython @("-I", "-m", "build", "--wheel", "--no-isolation", "--outdir", $WheelRoot)
  $Wheels = @(Get-ChildItem -LiteralPath $WheelRoot -Filter "webfa_desktop_runtime-${ReleaseVersion}-*.whl")
  if ($Wheels.Count -ne 1) {
    throw "Expected exactly one WebFA $ReleaseVersion wheel, found $($Wheels.Count)"
  }
  Remove-SafeTree $SourceBuildRoot
  Remove-SafeTree $EggInfoRoot
  Invoke-Checked $VenvPython @(
    "-I", "-m", "pip", "--isolated", "install", "--no-deps", $Wheels[0].FullName
  )
  Invoke-Checked $VenvPython @("-I", "-m", "pip", "--isolated", "check")

  $MetadataMatches = @(
    Get-ChildItem -LiteralPath (Join-Path $VenvRoot "Lib\site-packages") `
      -Directory -Filter "webfa_desktop_runtime-${ReleaseVersion}.dist-info"
  )
  if ($MetadataMatches.Count -ne 1) {
    throw "Expected exactly one installed WebFA metadata directory, found $($MetadataMatches.Count)"
  }
  $MetadataRoot = $MetadataMatches[0].FullName
  Assert-WorkspaceChild $MetadataRoot
  $DirectUrlMetadata = Join-Path $MetadataRoot "direct_url.json"
  if (Test-Path -LiteralPath $DirectUrlMetadata) {
    Remove-Item -LiteralPath $DirectUrlMetadata -Force
  }
  if (Test-Path -LiteralPath $DirectUrlMetadata) {
    throw "Build-local direct_url.json metadata must not enter the frozen sidecar"
  }
  $RecordMetadata = Join-Path $MetadataRoot "RECORD"
  if (Test-Path -LiteralPath $RecordMetadata) {
    $SanitizedRecord = @(
      Get-Content -LiteralPath $RecordMetadata |
        Where-Object { $_ -notmatch '(^|[\\/])direct_url\.json,' }
    )
    [IO.File]::WriteAllLines(
      $RecordMetadata,
      $SanitizedRecord,
      [Text.UTF8Encoding]::new($false)
    )
  }
  if (
    (Test-Path -LiteralPath $RecordMetadata) -and
    (Select-String -LiteralPath $RecordMetadata -Pattern "direct_url.json" -Quiet)
  ) {
    throw "Installed wheel RECORD still references build-local direct_url metadata"
  }

  Push-Location $FreezeCwd
  try {
    $env:WEBFA_PYINSTALLER_MODE = $Mode
    Remove-Item Env:PYTHONPATH -ErrorAction SilentlyContinue
    Invoke-Checked $VenvPython @(
      "-I", "-m", "PyInstaller", "--clean", "--noconfirm", "--distpath", $DistRoot,
      "--workpath", $WorkRoot, $Spec
    )
  }
  finally {
    Pop-Location
    Remove-Item Env:WEBFA_PYINSTALLER_MODE -ErrorAction SilentlyContinue
  }

  if ($Mode -eq "onefile") {
    $Executable = Join-Path $DistRoot "webfa.exe"
    New-Item -ItemType Directory -Force -Path $SidecarRoot | Out-Null
    Copy-Item -LiteralPath $Executable -Destination (Join-Path $SidecarRoot "webfa.exe")
    $Executable = Join-Path $SidecarRoot "webfa.exe"
  }
  else {
    $BundleRoot = Join-Path $DistRoot "webfa"
    Copy-Item -LiteralPath $BundleRoot -Destination $SidecarRoot -Recurse
    $Executable = Join-Path $SidecarRoot "webfa.exe"
  }
  if (-not (Test-Path -LiteralPath $Executable -PathType Leaf)) {
    throw "PyInstaller did not produce the expected executable: $Executable"
  }
  Invoke-Checked $Executable @("--version")
  Invoke-Checked "node" @((Join-Path $Root "scripts\smoke-sidecar.cjs"), $Executable)
  Write-Output "WebFA $Mode sidecar verified: $Executable"
}
finally {
  Pop-Location
}
