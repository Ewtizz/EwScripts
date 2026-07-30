# EwScripts — меню установки личных скриптов.
#
# Модуль подгружается из распакованного архива репозитория; get.ps1 вызывает
# Show-EwMenu и передаёт путь к этой распаковке.

$script:EwVersion = '1.3.0'

$script:EwRoot       = Join-Path $env:LOCALAPPDATA 'EwScripts'
$script:EwRuntimeDir = Join-Path $script:EwRoot 'runtime'
$script:EwPyDir      = Join-Path $script:EwRuntimeDir 'python'
$script:EwPyExe      = Join-Path $script:EwPyDir 'python.exe'
$script:EwModulesDir = Join-Path $script:EwRoot 'modules'
$script:EwDataDir    = Join-Path $script:EwRoot 'data'
$script:EwStateFile  = Join-Path $script:EwRoot 'state.json'
$script:EwStartMenu  = Join-Path $env:APPDATA 'Microsoft\Windows\Start Menu\Programs\EwScripts'
$script:EwSource     = $null

. (Join-Path $PSScriptRoot 'ui.ps1')
. (Join-Path $PSScriptRoot 'runtime.ps1')
. (Join-Path $PSScriptRoot 'modules.ps1')

function Show-EwMenu {
    param([Parameter(Mandatory)][string]$SourceDir)

    $script:EwSource = $SourceDir
    $runtimeSpec = Get-Content -LiteralPath (Join-Path $SourceDir 'launcher\runtime.json') `
                               -Raw -Encoding UTF8 | ConvertFrom-Json
    # @() обязательно: из функции массив с одним элементом возвращается скаляром,
    # и тогда .Count пуст — то есть ровно на одном модуле меню бы и сломалось.
    $available = @(Get-EwAvailable -SourceDir $SourceDir)

    while ($true) {
        $state = Get-EwState
        Write-EwHeader -Version "v$script:EwVersion"

        if (-not $available.Count) {
            Write-EwWarn 'В репозитории нет ни одного модуля.'
            Wait-EwKey 'Нажмите Enter для выхода'
            return
        }

        $byKey = @{}
        $index = 0
        $updatable = @()
        $installable = @()
        foreach ($m in $available) {
            $index++
            $byKey["$index"] = $m
            $installed = Get-EwInstalledVersion -State $state -Id $m.id

            if (-not $installed) {
                $status = 'не установлен'; $color = 'DarkGray'
                $installable += $m
            } elseif ($installed -ne $m.version) {
                # сравнение на неравенство, а не «больше»: откат тоже должен работать
                $status = "обновление до $($m.version)"; $color = 'Yellow'
                $updatable += $m
            } else {
                $status = "установлен $installed"; $color = 'Green'
            }
            Write-EwModule -Key "$index" -Name $m.name -Status $status `
                           -StatusColor $color -Summary $m.summary
        }

        Write-EwRule
        if ($installable.Count) { Write-EwAction -Key 'A' -Text "Установить всё ($($installable.Count))" }
        if ($updatable.Count) { Write-EwAction -Key 'R' -Text "Обновить всё ($($updatable.Count))" }
        Write-EwAction -Key 'U' -Text 'Удалить EwScripts полностью'
        Write-EwAction -Key '0' -Text 'Выход'

        # Буквы совпадают с латинскими и русскими на тех же физических клавишах:
        # раскладку ради меню переключать не придётся.
        $choice = Read-EwChoice -AllowLongInput:($available.Count -gt 9)
        if ($choice -eq '0' -or $choice -eq '') { return }
        elseif ($choice -match '^[uUгГ]$') {
            if (Invoke-EwRemoveAll) { return }
        }
        elseif ($choice -match '^[aAфФ]$' -and $installable.Count) {
            Invoke-EwInstallAll -Modules $installable -RuntimeSpec $runtimeSpec
        }
        elseif ($choice -match '^[rRкК]$' -and $updatable.Count) {
            Invoke-EwUpdateAll -Modules $updatable -RuntimeSpec $runtimeSpec
        }
        elseif ($byKey.ContainsKey($choice)) {
            Show-EwModuleMenu -Manifest $byKey[$choice] -RuntimeSpec $runtimeSpec
        }
    }
}

function Show-EwModuleMenu {
    param([Parameter(Mandatory)] $Manifest, [Parameter(Mandatory)] $RuntimeSpec)

    while ($true) {
        $state = Get-EwState
        $installed = Get-EwInstalledVersion -State $state -Id $Manifest.id

        Write-EwHeader -Version "v$script:EwVersion"
        Write-Host "$script:EwPad $($Manifest.name)" -ForegroundColor White
        if ($Manifest.summary) { Write-EwInfo $Manifest.summary }
        if ($Manifest.note) {
            Write-Host ''
            Write-EwNote $Manifest.note
        }
        Write-Host ''

        # Список действий собирается заранее и нумеруется подряд. Раньше номера
        # были прибиты гвоздями, и при скрытом «Обновить» меню шло 1, 3, 4, 0.
        $actions = @()
        if (-not $installed) {
            Write-EwInfo "Версия в репозитории: $($Manifest.version). Не установлен."
            $actions += [pscustomobject]@{ Do = 'install'; Text = 'Установить' }
        } else {
            Write-EwInfo "Установлена версия $installed, в репозитории $($Manifest.version)."
            # «Запустить» — только у модулей с ярлыком. Конвертер изображений
            # живёт в контекстном меню, запускать его отдельно нечем.
            if ($Manifest.shortcut) {
                $actions += [pscustomobject]@{ Do = 'run'; Text = 'Запустить' }
            }
            if ($installed -ne $Manifest.version) {
                $actions += [pscustomobject]@{ Do = 'update'; Text = "Обновить до $($Manifest.version)" }
            }
            $actions += [pscustomobject]@{ Do = 'data'; Text = 'Открыть папку с данными' }
            $actions += [pscustomobject]@{ Do = 'remove'; Text = 'Удалить' }
        }

        Write-Host ''
        Write-EwRule
        $byKey = @{}
        $number = 0
        foreach ($action in $actions) {
            $number++
            $byKey["$number"] = $action.Do
            Write-EwAction -Key "$number" -Text $action.Text
        }
        Write-EwAction -Key '0' -Text 'Назад'

        $choice = Read-EwChoice
        Write-Host ''
        if ($choice -eq '0' -or $choice -eq '') { return }

        $todo = $byKey[$choice]
        if (-not $todo) { continue }

        # Ветки на if/elseif, а не switch: «continue» внутри switch внутри цикла
        # в PowerShell трактуется неочевидно, и это тихо ломает поток управления.
        $pause = $true
        try {
            if ($todo -eq 'install') {
                Install-EwModule -Manifest $Manifest -RuntimeSpec $RuntimeSpec -State $state
                Write-EwOk "$($Manifest.name) установлен."
                if ($Manifest.shortcut) {
                    Write-EwInfo "Ярлык: Пуск → EwScripts → $($Manifest.shortcut)"
                }
                # Заметку показываем именно здесь: человек только что поставил
                # модуль и сейчас пойдёт его искать.
                if ($Manifest.note) {
                    Write-Host ''
                    Write-EwNote $Manifest.note
                }
            }
            elseif ($todo -eq 'run') {
                Start-EwModule -Id $Manifest.id
                Write-EwOk "$($Manifest.name) запущен в отдельном окне."
            }
            elseif ($todo -eq 'update') {
                if (Confirm-EwModuleStopped -Id $Manifest.id -Name $Manifest.name) {
                    Install-EwModule -Manifest $Manifest -RuntimeSpec $RuntimeSpec -State $state
                    Write-EwOk "Обновлён до $($Manifest.version). Данные не тронуты."
                }
            }
            elseif ($todo -eq 'data') {
                $data = Join-Path $script:EwDataDir $Manifest.id
                New-Item -ItemType Directory -Path $data -Force | Out-Null
                Start-Process explorer.exe $data
                $pause = $false
            }
            elseif ($todo -eq 'remove') {
                if (Read-EwConfirm "Удалить $($Manifest.name)?") {
                    if (Confirm-EwModuleStopped -Id $Manifest.id -Name $Manifest.name -Action 'Удаление') {
                        $withData = Read-EwConfirm 'Удалить также его данные и логи?'
                        Remove-EwModule -Id $Manifest.id -State $state -WithData:$withData
                        Write-Host ''
                        Write-EwOk "$($Manifest.name) удалён."
                        if (-not $withData) {
                            Write-EwInfo "Данные остались в $(Join-Path $script:EwDataDir $Manifest.id)"
                        }
                    }
                } else { $pause = $false }
            }
        } catch {
            Write-EwErr $_.Exception.Message
            $pause = $true
        }
        if ($pause) { Wait-EwKey }
    }
}

function Invoke-EwInstallAll {
    param([Parameter(Mandatory)] $Modules, [Parameter(Mandatory)] $RuntimeSpec)

    Write-EwHeader -Version "v$script:EwVersion"
    foreach ($m in $Modules) {
        Write-EwStep "$($m.name) $($m.version)"
        try {
            # Состояние перечитывается на каждом шаге: предыдущая установка уже
            # его изменила, и работать со старым снимком нельзя.
            Install-EwModule -Manifest $m -RuntimeSpec $RuntimeSpec -State (Get-EwState)
            Write-EwOk "$($m.name) установлен."
            if ($m.note) { Write-EwNote $m.note }
        } catch {
            Write-EwErr "$($m.name): $($_.Exception.Message)"
        }
    }
    Wait-EwKey
}

function Invoke-EwUpdateAll {
    param([Parameter(Mandatory)] $Modules, [Parameter(Mandatory)] $RuntimeSpec)

    Write-EwHeader -Version "v$script:EwVersion"
    foreach ($m in $Modules) {
        $state = Get-EwState
        Write-EwStep "$($m.name) → $($m.version)"
        try {
            if (Confirm-EwModuleStopped -Id $m.id -Name $m.name) {
                Install-EwModule -Manifest $m -RuntimeSpec $RuntimeSpec -State $state
                Write-EwOk "$($m.name) обновлён."
            }
        } catch {
            Write-EwErr "$($m.name): $($_.Exception.Message)"
        }
    }
    Wait-EwKey
}

# Возвращает $true, если меню надо закрыть. Через exit нельзя: под iex он
# закрыл бы пользователю его собственное окно PowerShell.
function Invoke-EwRemoveAll {
    Write-EwHeader -Version "v$script:EwVersion"

    if (-not (Test-Path -LiteralPath $script:EwRoot)) {
        Write-EwInfo 'EwScripts на этой машине не установлен.'
        Wait-EwKey
        return $false
    }

    Write-EwWarn 'Будут удалены рантайм Python, все модули и ярлыки в меню Пуск.'
    if (-not (Read-EwConfirm 'Удалить EwScripts полностью?')) { return $false }
    $withData = Read-EwConfirm 'Удалить также данные и логи модулей?'
    Write-Host ''

    # Запущенный модуль держит свою папку: без этой проверки удаление снесло бы
    # часть файлов и упало на середине.
    $state = Get-EwState
    foreach ($id in @($state.modules.PSObject.Properties.Name)) {
        if (-not (Confirm-EwModuleStopped -Id $id -Name $id -Action 'Удаление')) { return $false }
    }

    try {
        if (Test-Path -LiteralPath $script:EwStartMenu) {
            Remove-Item -LiteralPath $script:EwStartMenu -Recurse -Force
        }
        Remove-EwRuntime
        foreach ($p in $script:EwModulesDir, $script:EwStateFile) {
            if (Test-Path -LiteralPath $p) { Remove-Item -LiteralPath $p -Recurse -Force }
        }
        if ($withData) {
            if (Test-Path -LiteralPath $script:EwDataDir) {
                Remove-Item -LiteralPath $script:EwDataDir -Recurse -Force
            }
            Remove-Item -LiteralPath $script:EwRoot -Recurse -Force -ErrorAction SilentlyContinue
            Write-EwOk 'EwScripts удалён полностью.'
        } else {
            Write-EwOk 'EwScripts удалён.'
            Write-EwInfo "Данные модулей остались в $script:EwDataDir"
        }
    } catch {
        Write-EwErr $_.Exception.Message
        Wait-EwKey
        return $false
    }
    Wait-EwKey 'Нажмите Enter для выхода'
    return $true
}

Export-ModuleMember -Function Show-EwMenu
