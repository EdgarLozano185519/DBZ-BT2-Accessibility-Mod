$ErrorActionPreference = 'Stop'
$workspace = Split-Path -Parent $PSScriptRoot
$compiler = Join-Path $env:WINDIR 'Microsoft.NET\Framework64\v4.0.30319\csc.exe'
$sourceFile = Join-Path $PSScriptRoot 'ui\GuideDesktop.cs'
$outputFile = Join-Path $workspace 'DBZ BT2 Guide.exe'
& $compiler /nologo /target:winexe /optimize+ "/out:$outputFile" /reference:System.dll /reference:System.Core.dll /reference:System.Drawing.dll /reference:System.Windows.Forms.dll /reference:System.Web.Extensions.dll $sourceFile
if ($LASTEXITCODE -ne 0) { throw 'The desktop interface did not compile.' }
Write-Output "Built $outputFile"
