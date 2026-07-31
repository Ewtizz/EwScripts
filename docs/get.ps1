# EwScripts - one-line installer.
#
#     [Net.ServicePointManager]::SecurityProtocol=3072; irm https://ewtizz.github.io/EwScripts/get.ps1 | iex
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

    # One request for the whole repository. Fast, and what normally happens.
    function Get-EwFromArchive {
        param([string]$Work)

        $zip = Join-Path $Work 'repo.zip'
        Invoke-WebRequest -Uri "https://codeload.github.com/$repo/zip/refs/heads/$branch" `
                          -OutFile $zip -UseBasicParsing
        Expand-Archive -LiteralPath $zip -DestinationPath $Work -Force
        Remove-Item -LiteralPath $zip -Force -ErrorAction SilentlyContinue
        $found = Get-ChildItem -LiteralPath $Work -Directory | Select-Object -First 1
        if (-not $found) { throw 'the downloaded archive is empty' }
        return $found.FullName
    }

    # Fallback for networks where GitHub itself is unreachable: jsDelivr is a
    # CDN that mirrors public repositories. It serves no archives, so files come
    # one by one - slower, but it gets through where codeload does not.
    #
    # Branch refs are cached by the CDN for hours, so a freshly pushed fix can
    # lag here. That is the price of the fallback, not a reason to use it first.
    function Get-EwFromMirror {
        param([string]$Work)

        $root = Join-Path $Work 'EwScripts'
        New-Item -ItemType Directory -Path $root -Force | Out-Null

        $meta = Invoke-RestMethod -Uri "https://data.jsdelivr.com/v1/packages/gh/$repo@$branch" `
                                  -UseBasicParsing
        $paths = New-Object System.Collections.ArrayList
        $stack = New-Object System.Collections.Stack
        foreach ($entry in $meta.files) { [void]$stack.Push(@{ Node = $entry; Path = '' }) }
        while ($stack.Count) {
            $item = $stack.Pop()
            $full = if ($item.Path) { "$($item.Path)/$($item.Node.name)" } else { $item.Node.name }
            if ($item.Node.type -eq 'directory') {
                foreach ($child in $item.Node.files) { [void]$stack.Push(@{ Node = $child; Path = $full }) }
            } else {
                [void]$paths.Add($full)
            }
        }

        # Design documents are not needed to run anything.
        $wanted = @($paths | Where-Object { $_ -notlike 'specs/*' })
        if (-not $wanted.Count) { throw 'the mirror returned no files' }

        # A refused file is skipped rather than fatal. jsDelivr will not serve
        # executable types such as .bat - it does not want to be a malware CDN -
        # and netpulse ships a start.bat that nothing here needs, because the
        # launcher writes its own launch.cmd during install. Skipping keeps that
        # policy from breaking the whole download, today and for whatever type
        # they refuse next. Anything genuinely required is missed loudly later.
        $done = 0
        $skipped = @()
        foreach ($relative in $wanted) {
            $target = Join-Path $root ($relative -replace '/', '\')
            New-Item -ItemType Directory -Path (Split-Path $target -Parent) -Force | Out-Null
            try {
                Invoke-WebRequest -Uri "https://cdn.jsdelivr.net/gh/$repo@$branch/$relative" `
                                  -OutFile $target -UseBasicParsing
            } catch {
                if ($_.Exception.Response.StatusCode.value__ -eq 403) {
                    $skipped += $relative
                    Remove-Item -LiteralPath $target -Force -ErrorAction SilentlyContinue
                } else {
                    throw
                }
            }
            $done++
            Write-Host ("`r   mirror: $done / $($wanted.Count)   ") -NoNewline -ForegroundColor DarkGray
        }
        Write-Host ''
        if ($skipped.Count) {
            Write-Host "   mirror refused (not needed): $($skipped -join ', ')" -ForegroundColor DarkGray
        }
        if (-not (Test-Path -LiteralPath (Join-Path $root 'launcher\EwScripts.psm1'))) {
            throw 'the mirror copy is missing the launcher'
        }
        return $root
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
    # lower by default. Without this the repo download fails on a stock machine.
    #
    # 3072 is TLS 1.2 written as a number on purpose: on .NET 4.0 the name
    # [Net.SecurityProtocolType]::Tls12 does not exist at all, and merely naming
    # it throws before any connection is attempted. The number always works.
    #
    # Note this does NOT help the very first request - the one that fetches this
    # file. That is why the documented install command sets TLS 1.2 itself.
    try {
        [Net.ServicePointManager]::SecurityProtocol =
            [Net.ServicePointManager]::SecurityProtocol -bor 3072
    } catch { }

    # ExecutionPolicy applies to script files, not to code arriving through iex -
    # which is why this file runs fine and the launcher it unpacks does not. On a
    # stock Windows the policy is Restricted, so without this the install fails on
    # its very last step, on a freshly installed machine, with "running scripts is
    # disabled on this system".
    #
    # Process scope covers this console window only, vanishes when it closes and
    # needs no administrator. It also outranks the CurrentUser and LocalMachine
    # settings, so a machine somebody has tightened by hand is handled too.
    try {
        Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass -Force -ErrorAction SilentlyContinue
    } catch { }

    # Only a Group Policy outranks Process scope, and lifting it takes an
    # administrator. Better said now than after a pointless download.
    $policy = Get-ExecutionPolicy
    if ($policy -eq 'Restricted' -or $policy -eq 'AllSigned') {
        Write-Problem "Group Policy blocks scripts here: ExecutionPolicy is $policy."
        Write-Problem 'Only an administrator can lift that. Get-ExecutionPolicy -List shows where it is set.'
        return
    }

    # The menu itself is in Russian; on a default cp866 console it would be
    # unreadable without this.
    $previousEncoding = [Console]::OutputEncoding
    try { [Console]::OutputEncoding = New-Object System.Text.UTF8Encoding $false } catch { }

    # A session closed with the window X never reaches the cleanup below, so old
    # working folders pile up over time. Sweep the stale ones; the age filter is
    # what keeps a concurrently running instance safe.
    try {
        $cutoff = (Get-Date).AddDays(-1)
        Get-ChildItem -LiteralPath $env:TEMP -Directory -Filter 'ewscripts-*' -ErrorAction SilentlyContinue |
            Where-Object { $_.CreationTime -lt $cutoff } |
            ForEach-Object { Remove-Item -LiteralPath $_.FullName -Recurse -Force -ErrorAction SilentlyContinue }
    } catch { }

    $work = Join-Path $env:TEMP ('ewscripts-' + [Guid]::NewGuid().ToString('N'))
    try {
        New-Item -ItemType Directory -Path $work -Force | Out-Null

        Write-Host ''
        Write-Host '   EwScripts' -ForegroundColor Cyan
        Write-Host '   downloading...' -ForegroundColor DarkGray

        $source = $null
        $firstError = ''
        try {
            $source = Get-EwFromArchive $work
        } catch {
            $firstError = $_.Exception.Message
            Write-Host '   GitHub is unreachable, trying the jsDelivr mirror...' -ForegroundColor DarkGray
            try {
                $source = Get-EwFromMirror $work
            } catch {
                Write-Problem 'Cannot reach GitHub or the jsDelivr mirror.'
                Write-Problem "GitHub: $firstError"
                Write-Problem "Mirror: $($_.Exception.Message)"
                return
            }
        }

        Import-Module (Join-Path $source 'launcher\EwScripts.psm1') -Force -DisableNameChecking
        Show-EwMenu -SourceDir $source
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
