@echo off
rem ---------------------------------------------------------------------------
rem Keep this file ASCII-only and do NOT add "chcp".
rem cmd.exe tracks its position in a .bat by byte offset: switching the codepage
rem in a file that also contains multi-byte characters makes the parser lose
rem alignment and try to execute fragments of text lines as commands.
rem All Russian text is printed by Python, which writes to the Windows console
rem through the UTF-16 API and renders Cyrillic correctly on any codepage.
rem ---------------------------------------------------------------------------

title NetPulse
cd /d "%~dp0"

where py >nul 2>nul
if %errorlevel%==0 (
    py run.py %*
) else (
    where python >nul 2>nul
    if errorlevel 1 (
        echo.
        echo Python not found. NetPulse needs Python 3.10 or newer:
        echo https://www.python.org/downloads/
        echo.
        pause
        exit /b 1
    )
    python run.py %*
)

echo.
pause
