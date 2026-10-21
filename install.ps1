param(
  [string]$Version = '0.2.0-rc.1',
  [string]$InstallRoot = '',
  [string]$BinDir = '',
  [string]$DownloadDirectory = '',
  [switch]$NoPathUpdate,
  [switch]$SkipSetup
)
$ErrorActionPreference = 'Stop'
if ($env:OS -ne 'Windows_NT') { throw 'Use install.sh on Linux or macOS' }
if ($Version -notmatch '^\d+\.\d+\.\d+(-[0-9A-Za-z.-]+)?$') { throw 'Invalid release version' }
$architecture = [Runtime.InteropServices.RuntimeInformation]::OSArchitecture.ToString().ToLowerInvariant()
switch ($architecture) { 'x64' { $arch = 'amd64' } 'arm64' { $arch = 'arm64' } default { throw 'Unsupported CPU architecture' } }
if (-not $InstallRoot) { if ($env:PASCODE_HOME) { $InstallRoot = $env:PASCODE_HOME } else { $InstallRoot = Join-Path $env:USERPROFILE '.pascode' } }
$InstallRoot = [IO.Path]::GetFullPath($InstallRoot)
if (-not $BinDir) { $BinDir = Join-Path $InstallRoot 'bin' }
$BinDir = [IO.Path]::GetFullPath($BinDir)
New-Item -ItemType Directory -Force -Path $InstallRoot,$BinDir | Out-Null
$stage = Join-Path $InstallRoot ('.download-' + [Guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $stage | Out-Null
try {
  [Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12
  $base = "https://github.com/tarskisworld/pascode/releases/download/v$Version"
  function Fetch([string]$Name) {
    $target = Join-Path $stage $Name
    if ($DownloadDirectory) { Copy-Item -LiteralPath (Join-Path $DownloadDirectory $Name) -Destination $target }
    else { Invoke-WebRequest -UseBasicParsing -Uri "$base/$Name" -OutFile $target }
  }
  function Verify([string]$Name) {
    $lines = @(Get-Content -LiteralPath (Join-Path $stage 'SHA256SUMS') | Where-Object { $_ -match ('^[a-f0-9]{64}  ' + [Regex]::Escape($Name) + '$') })
    if ($lines.Count -ne 1) { throw 'Missing or duplicate artifact checksum' }
    $expected = $lines[0].Substring(0,64)
    $actual = (Get-FileHash -Algorithm SHA256 -LiteralPath (Join-Path $stage $Name)).Hash.ToLowerInvariant()
    if ($expected -ne $actual) { throw 'Release integrity check failed' }
  }
  $archive = "pascodectl_${Version}_windows_${arch}.zip"
  $engine = "engine_linux_${arch}.tar.gz"
  Fetch 'SHA256SUMS'; Fetch $archive; Verify $archive; Fetch $engine; Verify $engine
  Add-Type -AssemblyName System.IO.Compression.FileSystem
  $zip = [IO.Compression.ZipFile]::OpenRead((Join-Path $stage $archive))
  try { foreach ($entry in $zip.Entries) { if ($entry.FullName -notin @('pascodectl.exe','engine.json','README.md')) { throw 'Unexpected archive member' } } } finally { $zip.Dispose() }
  $package = Join-Path $stage 'package'
  Expand-Archive -LiteralPath (Join-Path $stage $archive) -DestinationPath $package
  foreach ($name in @('pascodectl.exe','engine.json','README.md')) { if (-not (Test-Path -LiteralPath (Join-Path $package $name) -PathType Leaf)) { throw 'Incomplete release contents' } }
  Move-Item -LiteralPath (Join-Path $stage $engine) -Destination (Join-Path $package $engine)
  $destination = Join-Path $InstallRoot "versions\$Version\windows-$arch"
  if (Test-Path -LiteralPath $destination) {
    foreach ($name in @('pascodectl.exe','engine.json',$engine)) {
      if ((Get-FileHash -Algorithm SHA256 -LiteralPath (Join-Path $destination $name)).Hash -ne (Get-FileHash -Algorithm SHA256 -LiteralPath (Join-Path $package $name)).Hash) { throw 'Existing version differs; refusing to replace it' }
    }
  } else { New-Item -ItemType Directory -Force -Path (Split-Path $destination) | Out-Null; Move-Item -LiteralPath $package -Destination $destination }
  $command = Join-Path $BinDir 'pascodectl.exe'
  $record = Join-Path $BinDir '.pascode-managed.json'
  if (Test-Path -LiteralPath $command) {
    if (-not (Test-Path -LiteralPath $record)) { throw 'Custom command exists; choose another BinDir' }
    $previous = Get-Content -Raw -LiteralPath $record | ConvertFrom-Json
    if ((Get-FileHash -Algorithm SHA256 -LiteralPath $command).Hash -ne $previous.sha256) { throw 'Existing command was modified; refusing to overwrite it' }
  }
  $pendingCommand = Join-Path $BinDir ('.pascodectl-' + [Guid]::NewGuid().ToString('N') + '.exe')
  Copy-Item -LiteralPath (Join-Path $destination 'pascodectl.exe') -Destination $pendingCommand
  if (Test-Path -LiteralPath $command) {
    $backupCommand = Join-Path $BinDir ('.pascodectl-backup-' + [Guid]::NewGuid().ToString('N') + '.exe')
    [IO.File]::Replace($pendingCommand,$command,$backupCommand)
    Remove-Item -LiteralPath $backupCommand -Force
  }
  else { [IO.File]::Move($pendingCommand,$command) }
  $config = Get-Content -Raw -LiteralPath (Join-Path $destination 'engine.json') | ConvertFrom-Json
  $config.archive = Join-Path $destination $engine
  [IO.File]::WriteAllText((Join-Path $BinDir 'engine.json'),($config | ConvertTo-Json),[Text.UTF8Encoding]::new($false))
  @{sha256=(Get-FileHash -Algorithm SHA256 -LiteralPath $command).Hash;version=$Version} | ConvertTo-Json | Set-Content -LiteralPath $record -Encoding UTF8
  if (-not $NoPathUpdate) {
    $userPath = [Environment]::GetEnvironmentVariable('Path','User')
    if ($null -eq $userPath) { $userPath = '' }
    if (@($userPath -split ';' | Where-Object { $_.TrimEnd('\') -ieq $BinDir.TrimEnd('\') }).Count -eq 0) { [Environment]::SetEnvironmentVariable('Path',(($userPath.TrimEnd(';') + ';' + $BinDir).TrimStart(';')),'User') }
    $env:Path = $BinDir + ';' + $env:Path
  }
  & $command version
  if ($LASTEXITCODE -ne 0) { throw 'Installed CLI could not start' }
  if (-not $SkipSetup -and (Get-Command docker -ErrorAction SilentlyContinue)) { & $command setup; if ($LASTEXITCODE -ne 0) { throw 'CLI installed; start a Linux-container daemon and run setup' } }
  else { Write-Host "CLI installed. Start a Linux container runtime, then run: `"$command`" setup" }
  Write-Host "Installed Windows/$arch release $Version without changing project declarations or credentials."
} finally { if (Test-Path -LiteralPath $stage) { Remove-Item -LiteralPath $stage -Recurse -Force } }
