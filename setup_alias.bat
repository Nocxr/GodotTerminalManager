```bat
@echo off
setlocal

echo.
echo ========================================
echo   Godot Terminal Manager Alias Setup
echo ========================================
echo.

rem Get the folder this BAT file lives in.
set "SCRIPT_DIR=%~dp0"
set "MANAGER=%SCRIPT_DIR%godot_terminal_manager.py"

echo Setup script:
echo   %~f0
echo.
echo Manager:
echo   %MANAGER%
echo.

if not exist "%MANAGER%" (
    echo ERROR:
    echo godot_terminal_manager.py was not found next to this setup script.
    echo.
    goto :end
)

rem Pass the manager path through an environment variable so quoting paths is safe.
set "GODOT_MANAGER_PATH=%MANAGER%"

pwsh.exe -NoProfile -ExecutionPolicy Bypass -Command "$profilePath=$PROFILE; $manager=$env:GODOT_MANAGER_PATH; Write-Host ('PowerShell profile: ' + $profilePath); Write-Host ''; $profileDir=Split-Path -Parent $profilePath; if (!(Test-Path $profileDir)) { Write-Host 'Creating PowerShell profile directory...'; New-Item -ItemType Directory -Path $profileDir -Force | Out-Null }; if (!(Test-Path $profilePath)) { Write-Host 'Creating PowerShell profile...'; New-Item -ItemType File -Path $profilePath -Force | Out-Null }; $content=Get-Content $profilePath -Raw -ErrorAction SilentlyContinue; if ($null -eq $content) { $content='' }; $desired='function godot {'+[Environment]::NewLine+'    python \"'+$manager+'\" @args'+[Environment]::NewLine+'}'; $pattern='(?ms)^function\s+godot\s*\{.*?^\}'; $match=[regex]::Match($content,$pattern); if ($match.Success) { Write-Host 'Existing godot function found:'; Write-Host ''; Write-Host $match.Value; Write-Host ''; if ($match.Value -eq $desired) { Write-Host 'OK: godot already points to the correct location.' } else { Write-Host 'Path/function does not match. Updating...'; $content=[regex]::Replace($content,$pattern,[System.Text.RegularExpressions.MatchEvaluator]{param($m) $desired},1); Set-Content -Path $profilePath -Value $content; Write-Host ''; Write-Host 'Updated godot function:'; Write-Host ''; Write-Host $desired } } else { Write-Host 'No godot function found. Adding it...'; if ($content.Length -gt 0 -and !$content.EndsWith([Environment]::NewLine)) { $content += [Environment]::NewLine }; $content += [Environment]::NewLine+$desired+[Environment]::NewLine; Set-Content -Path $profilePath -Value $content; Write-Host ''; Write-Host 'Added godot function:'; Write-Host ''; Write-Host $desired }; Write-Host ''; Write-Host ('godot -> ' + $manager)"

echo.
if errorlevel 1 (
    echo ERROR: Setup failed.
) else (
    echo ========================================
    echo Setup complete.
    echo ========================================
    echo.
    echo Open a NEW PowerShell window and type:
    echo.
    echo   godot
)

:end
echo.
echo Press any key to close...
pause >nul
```