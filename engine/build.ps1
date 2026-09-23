param([ValidateSet('Release', 'Debug')][string]$Configuration = 'Release')
$ErrorActionPreference = 'Stop'
$engineRoot = $PSScriptRoot
$cmakeCommand = Get-Command cmake -ErrorAction SilentlyContinue
$compilerCommand = Get-Command g++ -ErrorAction SilentlyContinue
$ninjaCommand = Get-Command ninja -ErrorAction SilentlyContinue
$cmakePath = if ($cmakeCommand) { $cmakeCommand.Source } else { $null }
$compilerPath = if ($compilerCommand) { $compilerCommand.Source } else { $null }
$ninjaPath = if ($ninjaCommand) { $ninjaCommand.Source } else { $null }
$jetbrainsRoot = Join-Path $env:ProgramFiles 'JetBrains'
if (Test-Path -LiteralPath $jetbrainsRoot) {
    $clionDirectories = Get-ChildItem -LiteralPath $jetbrainsRoot -Directory -Filter 'CLion*' | Sort-Object Name -Descending
    foreach ($directory in $clionDirectories) {
        $candidateCmake = Join-Path $directory.FullName 'bin\cmake\win\x64\bin\cmake.exe'
        $candidateCompiler = Join-Path $directory.FullName 'bin\mingw\bin\g++.exe'
        $candidateNinja = Join-Path $directory.FullName 'bin\ninja\win\x64\ninja.exe'
        if (!$cmakePath -and (Test-Path -LiteralPath $candidateCmake)) { $cmakePath = $candidateCmake }
        if (!$compilerPath -and (Test-Path -LiteralPath $candidateCompiler)) { $compilerPath = $candidateCompiler }
        if (!$ninjaPath -and (Test-Path -LiteralPath $candidateNinja)) { $ninjaPath = $candidateNinja }
    }
}
if (!$cmakePath) { throw 'CMake was not found. Install CMake or open engine/ in CLion.' }
$buildDirectory = Join-Path $engineRoot 'build'
$configureArguments = @('-S', $engineRoot, '-B', $buildDirectory, "-DCMAKE_BUILD_TYPE=$Configuration")
if ($compilerPath -and $ninjaPath) {
    $configureArguments += @('-G', 'Ninja', "-DCMAKE_CXX_COMPILER=$compilerPath", "-DCMAKE_MAKE_PROGRAM=$ninjaPath")
}
$originalPath = $env:PATH
try {
    if ($compilerPath) { $env:PATH = (Split-Path -Parent $compilerPath) + ';' + $env:PATH }
    & $cmakePath @configureArguments
    if ($LASTEXITCODE -ne 0) { throw 'CMake configuration failed.' }
    & $cmakePath --build $buildDirectory --config $Configuration --parallel 2
    if ($LASTEXITCODE -ne 0) { throw 'C++ compilation failed.' }
    Write-Host "Build finished in $buildDirectory"
} finally {
    $env:PATH = $originalPath
}
