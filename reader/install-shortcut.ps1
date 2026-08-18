[CmdletBinding(SupportsShouldProcess = $true)]
param(
    [string]$Pythonw,
    [string]$DesktopPath
)

$ErrorActionPreference = 'Stop'
# Piped stdout uses the console code page (GBK on zh-CN) unless pinned, which
# would break the UTF-8 JSON contract of the -WhatIf preview on such systems.
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$projectRoot = (Resolve-Path -LiteralPath (Split-Path $PSScriptRoot -Parent)).Path

if ([string]::IsNullOrWhiteSpace($Pythonw)) {
    $python = (Get-Command python.exe -ErrorAction Stop).Source
    $Pythonw = Join-Path (Split-Path $python) 'pythonw.exe'
}
if (-not (Test-Path -LiteralPath $Pythonw -PathType Leaf)) {
    throw "pythonw.exe was not found: $Pythonw"
}
$resolvedPythonw = (Resolve-Path -LiteralPath $Pythonw).Path
if ([IO.Path]::GetFileName($resolvedPythonw) -ine 'pythonw.exe') {
    throw "The reader shortcut must use pythonw.exe: $resolvedPythonw"
}

if ([string]::IsNullOrWhiteSpace($DesktopPath)) {
    $DesktopPath = [Environment]::GetFolderPath('Desktop')
}
if (-not (Test-Path -LiteralPath $DesktopPath -PathType Container)) {
    throw "The desktop directory was not found: $DesktopPath"
}
$resolvedDesktop = (Resolve-Path -LiteralPath $DesktopPath).Path
$readerName = -join [char[]](0x9605, 0x8BFB, 0x5668)
$shortcutPath = Join-Path $resolvedDesktop "JLPT iPad $readerName.lnk"
$arguments = "-m jlpt_notes reader --root `"$projectRoot\jlpt-notes`" --config `"$projectRoot\reader\mkdocs.yml`" --port 8765"
$manualStart = -join [char[]](0x624B, 0x52A8, 0x542F, 0x52A8)
$lanReadOnlyReader = -join [char[]](0x5C40, 0x57DF, 0x7F51, 0x53EA, 0x8BFB, 0x9605, 0x8BFB, 0x5668)
$preview = [ordered]@{
    ShortcutPath = $shortcutPath
    TargetPath = $resolvedPythonw
    Arguments = $arguments
    WorkingDirectory = $projectRoot
    Description = "$manualStart JLPT iPad $lanReadOnlyReader"
}

# Preview resolves every path and exact argument before any COM object exists.
if ($WhatIfPreference) {
    [pscustomobject]$preview | ConvertTo-Json -Compress
    return
}

if ($PSCmdlet.ShouldProcess($shortcutPath, 'create manual JLPT iPad reader shortcut')) {
    $shell = New-Object -ComObject WScript.Shell
    $shortcut = $shell.CreateShortcut($shortcutPath)
    $shortcut.TargetPath = $preview.TargetPath
    $shortcut.Arguments = $preview.Arguments
    $shortcut.WorkingDirectory = $preview.WorkingDirectory
    $shortcut.Description = $preview.Description
    $shortcut.Save()
    Write-Host "Created: $shortcutPath"
}
