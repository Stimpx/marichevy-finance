# Fixed launcher source. CMD hashes these bytes and executes its captured copy.
# No execution policy, antivirus or operating-system security setting changes.
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
[Console]::OutputEncoding = New-Object Text.UTF8Encoding($false)
$held = New-Object 'System.Collections.Generic.List[System.IDisposable]'
try {
    $root = (Get-Location).ProviderPath
    if (-not [Environment]::Is64BitOperatingSystem -or -not [Environment]::Is64BitProcess -or $root -notmatch '^[A-Za-z]:\\') { throw 'fixed-failure' }
    function Assert-Directory([string]$value) {
        $next = $value
        while ($next) {
            $item = Get-Item -LiteralPath $next -Force -ErrorAction Stop
            if (-not $item.PSIsContainer -or ($item.Attributes -band [IO.FileAttributes]::ReparsePoint)) { throw 'fixed-failure' }
            $parent = [IO.Directory]::GetParent($next)
            if ($null -eq $parent) { break }
            $next = $parent.FullName
        }
    }
    Assert-Directory $root
    function Hold-Verified([string]$relative, [string]$expected, [long]$maximum) {
        $filename = [IO.Path]::Combine($root, $relative)
        Assert-Directory ([IO.Path]::GetDirectoryName($filename))
        $item = Get-Item -LiteralPath $filename -Force -ErrorAction Stop
        if ($item.PSIsContainer -or ($item.Attributes -band [IO.FileAttributes]::ReparsePoint) -or $item.Length -le 0 -or $item.Length -gt $maximum) { throw 'fixed-failure' }
        # Sharing read only prevents concurrent replacement/writing until Node exits.
        $stream = [IO.File]::Open($filename, [IO.FileMode]::Open, [IO.FileAccess]::Read, [IO.FileShare]::Read)
        $held.Add($stream)
        $hash = [Security.Cryptography.SHA256]::Create()
        try { $actual = ([BitConverter]::ToString($hash.ComputeHash($stream))).Replace('-', '').ToLowerInvariant() }
        finally { $hash.Dispose() }
        if ($actual -cne $expected) { throw 'fixed-failure' }
    }
    Hold-Verified 'runtime\node.exe' 'dccc52de28d8df2ee22d2062424f8c563070d95d8ad70c54c4bf01d590dec14f' 87034184
    Hold-Verified 'app\windows-bootstrap.cjs' '__WINDOWS_BOOTSTRAP_SHA256__' 1048576
    Hold-Verified 'MANIFEST.json' '__WINDOWS_MANIFEST_SHA256__' 2097152
    foreach ($name in [Environment]::GetEnvironmentVariables('Process').Keys) {
        if ($name -match '^(NODE_|DYLD_|npm_config_|KOFFI_|CLASSIC_LEVEL_PREBUILD$|LIBC$|ARM_VERSION$|ELECTRON_RUN_AS_NODE$)') { [Environment]::SetEnvironmentVariable($name, $null, 'Process') }
    }
    $env:PREBUILDS_ONLY = '1'
    Write-Output 'Этап: запуск среды программы'
    & ([IO.Path]::Combine($root, 'runtime\node.exe')) '--no-global-search-paths' ([IO.Path]::Combine($root, 'app\windows-bootstrap.cjs'))
    if ($LASTEXITCODE -notin @(0, 1, 2)) {
        Write-Output 'Результат: failed'
        Write-Output 'Коды: verification-process-unexpected-exit'
    }
} catch {
    Write-Output 'Результат: failed'
    Write-Output 'Коды: verification-launch-integrity-failed'
} finally {
    foreach ($item in $held) { try { $item.Dispose() } catch {} }
}
