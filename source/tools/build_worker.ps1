$ErrorActionPreference = 'Stop'
$workspace = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$python = Join-Path $workspace '.venv\Scripts\python.exe'
if (-not (Test-Path $python)) { throw "No project virtual environment at $python" }

# The NVDA client is loaded at runtime by path rather than imported, so
# PyInstaller cannot find it. speech_output.py looks for it beside the bt2
# package, which inside the bundle means the _internal folder.
$nvda = Join-Path $PSScriptRoot 'vendor\nvda\x64\nvdaControllerClient.dll'
if (-not (Test-Path $nvda)) { throw "Missing NVDA client at $nvda" }

# Imported inside functions so a missing screen reader or controller cannot stop
# the module loading, which also hides them from static analysis.
$hidden = @(
    'win32gui', 'win32con', 'win32process', 'win32api', 'win32ui',
    'pythoncom', 'win32com', 'win32com.client',
    'hid', 'scipy.ndimage', 'PIL.Image', 'PIL.ImageGrab',
    'bt2.pcsx2', 'bt2.menus'
)

$arguments = @(
    '-m', 'PyInstaller', '--noconfirm', '--clean',
    '--name', 'guide-worker',
    '--distpath', (Join-Path $workspace 'dist'),
    '--workpath', (Join-Path $workspace 'build'),
    '--specpath', (Join-Path $workspace 'build'),
    '--add-data', "$nvda;vendor\nvda\x64",
    '--paths', $PSScriptRoot
)
foreach ($module in $hidden) { $arguments += @('--hidden-import', $module) }
$arguments += (Join-Path $PSScriptRoot 'guide_host.py')

# PyInstaller writes progress to stderr, which Windows PowerShell turns into a
# terminating error under ErrorActionPreference 'Stop' even on success.
$previous = $ErrorActionPreference
$ErrorActionPreference = 'Continue'
& $python $arguments
$code = $LASTEXITCODE
$ErrorActionPreference = $previous
if ($code -ne 0) { throw "The guide worker did not build (exit $code)." }

$exe = Join-Path $workspace 'dist\guide-worker\guide-worker.exe'
if (-not (Test-Path $exe)) { throw "Build reported success but $exe is missing." }

# x64 is required: the bundled NVDA client is the 64-bit one, and a mismatch
# fails at runtime rather than at build time.
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
    throw ("Built a non-x64 executable (machine 0x{0:X4})." -f $machine)
}

Write-Output "Built $exe (x64 verified)"
Write-Output "Copy dist\guide-worker over the release worker folder to deploy it."
