$ErrorActionPreference = 'Stop'
$workspace = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$python = Join-Path $workspace '.venv\Scripts\python.exe'
if (-not (Test-Path $python)) { throw "No project virtual environment at $python" }

# The NVDA client is loaded at runtime by path, not imported, so PyInstaller
# cannot find it on its own. speech_output.py looks for it beside the bt2
# package, which inside the bundle means the _internal folder -- the same
# layout the shipped guide worker uses.
$nvda = Join-Path $PSScriptRoot 'vendor\nvda\x64\nvdaControllerClient.dll'
if (-not (Test-Path $nvda)) { throw "Missing NVDA client at $nvda" }

# pywin32 and the SAPI fallback are imported inside functions so that a missing
# screen reader cannot stop the module loading. That hides them from static
# analysis, so name them explicitly.
$hidden = @(
    'win32gui', 'win32con', 'win32process', 'win32api',
    'pythoncom', 'win32com', 'win32com.client',
    'bt2.pcsx2'
)

$arguments = @(
    '-m', 'PyInstaller', '--noconfirm', '--clean',
    '--name', 'DBZ-BT2-Menu-Reader',
    '--distpath', (Join-Path $workspace 'dist'),
    '--workpath', (Join-Path $workspace 'build'),
    '--specpath', (Join-Path $workspace 'build'),
    '--add-data', "$nvda;vendor\nvda\x64",
    '--paths', $PSScriptRoot
)
foreach ($module in $hidden) { $arguments += @('--hidden-import', $module) }
$arguments += (Join-Path $PSScriptRoot 'menu_announcer.py')

# PyInstaller writes its progress to stderr. Windows PowerShell turns that into
# a terminating error under ErrorActionPreference 'Stop' even when the build
# succeeds, so judge the run by its exit code instead.
$previous = $ErrorActionPreference
$ErrorActionPreference = 'Continue'
& $python $arguments
$code = $LASTEXITCODE
$ErrorActionPreference = $previous
if ($code -ne 0) { throw "The menu reader did not build (exit $code)." }

$exe = Join-Path $workspace 'dist\DBZ-BT2-Menu-Reader\DBZ-BT2-Menu-Reader.exe'
if (-not (Test-Path $exe)) { throw "Build reported success but $exe is missing." }

# A 64-bit build is required: the bundled NVDA client is the x64 one, and a
# mismatch fails at runtime rather than at build time.
$stream = [System.IO.File]::OpenRead($exe)
$buffer = New-Object byte[] 64
$stream.Read($buffer, 0, 64) | Out-Null
$peOffset = [BitConverter]::ToInt32($buffer, 60)
$stream.Seek($peOffset + 4, 'Begin') | Out-Null
$machineBytes = New-Object byte[] 2
$stream.Read($machineBytes, 0, 2) | Out-Null
$stream.Close()
$machine = [BitConverter]::ToUInt16($machineBytes, 0)
if ($machine -ne 0x8664) {
    throw ("Built a non-x64 executable (machine 0x{0:X4}); the bundled NVDA client is x64." -f $machine)
}

Write-Output "Built $exe (x64 verified)"
