# EwScripts - one-line installer.
#
#     irm https://ewtizz.github.io/EwScripts/get.ps1 | iex
#
# This file is deliberately ASCII-only. It is fetched over HTTP and executed via
# iex, and PowerShell 5.1 infers the charset from the response headers; when a
# server omits it, any non-ASCII byte here arrives mangled. All Russian text
# lives in launcher/*.ps1, which are read from disk as explicit UTF-8.
#
# Everything runs inside a function so a failed check returns instead of calling
# exit, which under iex would close the user's own console window.

function Invoke-EwBootstrap {
    $ErrorActionPreference = 'Stop'
    $ProgressPreference = 'SilentlyContinue'

    $repo = 'Ewtizz/EwScripts'
    $branch = 'main'

    function Write-Problem {
        param([string]$Message)
        Write-Host ''
        Write-Host "   $Message" -ForegroundColor Red
        Write-Host ''
    }

    if ($env:OS -ne 'Windows_NT') {
        Write-Problem 'EwScripts works on Windows only.'
        return
    }
    if ($PSVersionTable.PSVersion.Major -lt 5) {
        Write-Problem 'EwScripts needs PowerShell 5.1 or newer.'
        return
    }
    try {
        $build = [int](Get-CimInstance Win32_OperatingSystem -ErrorAction Stop).BuildNumber
        if ($build -lt 10240) {
            Write-Problem 'EwScripts needs Windows 10 or 11.'
            return
        }
    } catch { }

    # GitHub refuses anything below TLS 1.2 and PowerShell 5.1 still negotiates
    # lower by default. Without this the download fails on a stock Windows 10.
    try {
        [Net.ServicePointManager]::SecurityProtocol =
            [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12
    } catch { }

    # The menu itself is in Russian; on a default cp866 console it would be
    # unreadable without this.
    $previousEncoding = [Console]::OutputEncoding
    try { [Console]::OutputEncoding = New-Object System.Text.UTF8Encoding $false } catch { }

    $work = Join-Path $env:TEMP ('ewscripts-' + [Guid]::NewGuid().ToString('N'))
    try {
        New-Item -ItemType Directory -Path $work -Force | Out-Null
        $zip = Join-Path $work 'repo.zip'
        $url = "https://codeload.github.com/$repo/zip/refs/heads/$branch"

        Write-Host ''
        Write-Host '   EwScripts' -ForegroundColor Cyan
        Write-Host '   downloading...' -ForegroundColor DarkGray

        try {
            Invoke-WebRequest -Uri $url -OutFile $zip -UseBasicParsing
        } catch {
            Write-Problem "Cannot reach $url"
            Write-Problem $_.Exception.Message
            return
        }

        Expand-Archive -LiteralPath $zip -DestinationPath $work -Force
        $src = Get-ChildItem -LiteralPath $work -Directory | Select-Object -First 1
        if (-not $src) {
            Write-Problem 'The downloaded archive looks empty.'
            return
        }

        Import-Module (Join-Path $src.FullName 'launcher\EwScripts.psm1') -Force -DisableNameChecking
        Show-EwMenu -SourceDir $src.FullName
    }
    catch {
        Write-Problem $_.Exception.Message
    }
    finally {
        Remove-Module EwScripts -Force -ErrorAction SilentlyContinue
        try { [Console]::OutputEncoding = $previousEncoding } catch { }
        if (Test-Path -LiteralPath $work) {
            Remove-Item -LiteralPath $work -Recurse -Force -ErrorAction SilentlyContinue
        }
    }
}

Invoke-EwBootstrap
