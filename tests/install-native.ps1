param([Parameter(Mandatory=$true)][string]$Assets)
$ErrorActionPreference = 'Stop'
$sourceRoot = Split-Path $PSScriptRoot
$Assets = [IO.Path]::GetFullPath($Assets)
$work = Join-Path ([IO.Path]::GetTempPath()) ('pascode-test-' + [Guid]::NewGuid().ToString('N'))
$previousHome = $env:PASCODE_HOME
try {
  New-Item -ItemType Directory -Path $work | Out-Null
  $env:PASCODE_HOME = Join-Path $work 'home with spaces'
  $bin = Join-Path $work 'bin with spaces'
  & (Join-Path $sourceRoot 'install.ps1') -InstallRoot $env:PASCODE_HOME -BinDir $bin -DownloadDirectory $Assets -NoPathUpdate -SkipSetup
  & (Join-Path $sourceRoot 'install.ps1') -InstallRoot $env:PASCODE_HOME -BinDir $bin -DownloadDirectory $Assets -NoPathUpdate -SkipSetup
  $command = Join-Path $bin 'pascodectl.exe'
  if ((Get-Content -Raw -LiteralPath (Join-Path $bin '.pascode-home')).Trim() -ne [IO.Path]::GetFullPath($env:PASCODE_HOME)) { throw 'Installed command lost its custom configuration root' }
  & $command version
  if ($LASTEXITCODE -ne 0) { throw 'Installed version command failed' }
  $help = & $command --help
  if ($LASTEXITCODE -ne 0 -or ($help -join "`n") -notmatch 'No host Bash') { throw 'Installed help failed' }
  $corrupt = Join-Path $work 'corrupt'
  New-Item -ItemType Directory -Path $corrupt | Out-Null
  Copy-Item -LiteralPath (Join-Path $Assets 'SHA256SUMS') -Destination $corrupt
  $arch = [Runtime.InteropServices.RuntimeInformation]::OSArchitecture.ToString().ToLowerInvariant()
  if ($arch -eq 'x64') { $arch = 'amd64' }
  $version = (Get-Content -Raw -LiteralPath (Join-Path $sourceRoot 'NATIVE_VERSION')).Trim()
  'corrupt' | Set-Content -LiteralPath (Join-Path $corrupt "pascodectl_${version}_windows_${arch}.zip")
  $rejected = $false
  try { & (Join-Path $sourceRoot 'install.ps1') -InstallRoot $env:PASCODE_HOME -BinDir $bin -DownloadDirectory $corrupt -NoPathUpdate -SkipSetup }
  catch { if ($_.Exception.Message -match 'integrity check failed') { $rejected = $true } else { throw } }
  if (-not $rejected) { throw 'Installer accepted corrupt bytes' }
  Write-Host 'PASS native PowerShell installer, repeat install, spaced paths and checksum rejection'
} finally {
  $env:PASCODE_HOME = $previousHome
  if (Test-Path -LiteralPath $work) { Remove-Item -LiteralPath $work -Recurse -Force }
}
