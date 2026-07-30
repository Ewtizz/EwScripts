# Сборка Python — одна на все модули.
#
# Системный Python сознательно не ищется и не трогается: своя копия означает
# предсказуемую версию на любой машине и полное отсутствие следов после удаления.

function Test-EwRuntime {
    return (Test-Path -LiteralPath $script:EwPyExe)
}

function Install-EwRuntime {
    param([Parameter(Mandatory)] $Spec)

    if (Test-EwRuntime) { return }

    $mb = [Math]::Round($Spec.size / 1MB)
    Write-EwStep "Нужен Python — качаю сборку $($Spec.version), $mb МБ. Это разово."

    $tmp = Join-Path ([IO.Path]::GetTempPath()) ('ewscripts-py-' + [Guid]::NewGuid().ToString('N'))
    New-Item -ItemType Directory -Path $tmp -Force | Out-Null
    $zip = Join-Path $tmp 'python.zip'

    try {
        try {
            Invoke-WebRequest -Uri $Spec.url -OutFile $zip -UseBasicParsing
        } catch {
            throw "не удалось скачать Python с $($Spec.url) — $($_.Exception.Message)"
        }

        Write-EwStep 'Проверяю SHA256.'
        $got = (Get-FileHash -LiteralPath $zip -Algorithm SHA256).Hash.ToLower()
        if ($got -ne $Spec.sha256.ToLower()) {
            throw ("SHA256 не совпал, установка прервана.`n" +
                   "$script:EwPad    ожидался $($Spec.sha256)`n" +
                   "$script:EwPad    получен  $got")
        }

        Write-EwStep 'Распаковываю.'
        $unpack = Join-Path $tmp 'unpack'
        Expand-Archive -LiteralPath $zip -DestinationPath $unpack -Force

        $tools = Join-Path $unpack 'tools'
        if (-not (Test-Path -LiteralPath $tools)) {
            throw 'в пакете Python нет папки tools — формат изменился, нужно обновить runtime.json'
        }

        New-Item -ItemType Directory -Path $script:EwRuntimeDir -Force | Out-Null
        if (Test-Path -LiteralPath $script:EwPyDir) {
            Remove-Item -LiteralPath $script:EwPyDir -Recurse -Force
        }
        Move-Item -LiteralPath $tools -Destination $script:EwPyDir

        Write-EwOk "Python $($Spec.version) установлен."
    }
    finally {
        # В пакете есть файл [Content_Types].xml. Квадратные скобки PowerShell
        # понимает как шаблон, поэтому здесь строго -LiteralPath.
        if (Test-Path -LiteralPath $tmp) {
            Remove-Item -LiteralPath $tmp -Recurse -Force -ErrorAction SilentlyContinue
        }
    }
}

# Шим кладётся рядом с рантаймом: он общий для всех модулей и обновляется вместе
# с лаунчером, а не с каждым модулем по отдельности.
function Install-EwLaunchShim {
    param([Parameter(Mandatory)][string]$SourceDir)

    New-Item -ItemType Directory -Path $script:EwRuntimeDir -Force | Out-Null
    Copy-Item -LiteralPath (Join-Path $SourceDir 'launcher\launch.py') `
              -Destination (Join-Path $script:EwRuntimeDir 'launch.py') -Force
}

function Remove-EwRuntime {
    if (Test-Path -LiteralPath $script:EwRuntimeDir) {
        Remove-Item -LiteralPath $script:EwRuntimeDir -Recurse -Force
    }
}
