# Отрисовка меню. Ширина рассчитана на стандартное окно консоли в 80 колонок.

$script:EwWidth = 58
$script:EwPad = '   '

function Write-EwHeader {
    param([string]$Version)

    Clear-Host
    Write-Host ''
    $left = "$script:EwPad EwScripts"
    $gap = $script:EwWidth + $script:EwPad.Length - $left.Length - $Version.Length
    Write-Host $left -ForegroundColor Cyan -NoNewline
    Write-Host ((' ' * [Math]::Max(1, $gap)) + $Version) -ForegroundColor DarkGray
    Write-EwRule '='
    Write-Host ''
}

function Write-EwRule {
    param([char]$Char = '-')
    Write-Host ($script:EwPad + ([string]$Char * $script:EwWidth)) -ForegroundColor DarkGray
}

# Строка модуля: слева ключ и название, справа выровненный статус.
function Write-EwModule {
    param(
        [string]$Key,
        [string]$Name,
        [string]$Status,
        [ConsoleColor]$StatusColor = 'Gray',
        [string]$Summary
    )

    $left = "$script:EwPad [$Key]  $Name"
    $gap = $script:EwWidth + $script:EwPad.Length - $left.Length - $Status.Length
    Write-Host $left -ForegroundColor White -NoNewline
    Write-Host ((' ' * [Math]::Max(1, $gap)) + $Status) -ForegroundColor $StatusColor
    if ($Summary) {
        # Ровно под названием: отступ + пробел + [K] + два пробела. Длинное
        # описание обрезаем, иначе оно вылезет за рамку и сломает вёрстку.
        $room = $script:EwWidth - 6
        if ($Summary.Length -gt $room) { $Summary = $Summary.Substring(0, $room - 1) + '…' }
        Write-Host "$script:EwPad      $Summary" -ForegroundColor DarkGray
    }
    Write-Host ''
}

function Write-EwAction {
    param([string]$Key, [string]$Text)
    Write-Host "$script:EwPad [$Key]  " -ForegroundColor White -NoNewline
    Write-Host $Text -ForegroundColor Gray
}

function Write-EwInfo { param([string]$Text) Write-Host "$script:EwPad $Text" -ForegroundColor Gray }

# Длинная заметка модуля: переносим по словам, чтобы не расползалась за край окна.
function Write-EwNote {
    param([string]$Text, [ConsoleColor]$Color = 'Yellow')

    if (-not $Text) { return }
    $limit = $script:EwWidth - 3
    $line = ''
    foreach ($word in ($Text -split '\s+')) {
        if ($line -and ($line.Length + 1 + $word.Length) -gt $limit) {
            Write-Host "$script:EwPad $line" -ForegroundColor $Color
            $line = $word
        } else {
            $line = if ($line) { "$line $word" } else { $word }
        }
    }
    if ($line) { Write-Host "$script:EwPad $line" -ForegroundColor $Color }
}
function Write-EwStep { param([string]$Text) Write-Host "$script:EwPad ·  $Text" -ForegroundColor DarkCyan }
function Write-EwOk   { param([string]$Text) Write-Host "$script:EwPad ✓  $Text" -ForegroundColor Green }
function Write-EwWarn { param([string]$Text) Write-Host "$script:EwPad !  $Text" -ForegroundColor Yellow }
function Write-EwErr  { param([string]$Text) Write-Host "$script:EwPad ✗  $Text" -ForegroundColor Red }

# Меню читает одну клавишу, без Enter: это установщик, а не форма ввода.
#
# ReadKey недоступен в неинтерактивном хосте — например, при прогоне тестов или
# запуске из конвейера, — поэтому там мягко откатываемся на построчный ввод,
# вместо того чтобы падать.
function Read-EwKey {
    # Проверку перенаправления делаем ДО вызова ReadKey, а не ловим исключение
    # после: при перенаправлённом вводе консольного буфера клавиш нет, и ReadKey
    # не падает, а виснет навсегда. Ловить тут нечего — надо просто не звать.
    #
    # На «irm ... | iex» это не влияет: там конвейер объектов PowerShell, а не
    # стандартный ввод процесса, консоль остаётся на месте.
    $redirected = $false
    try { $redirected = [Console]::IsInputRedirected } catch { }

    if (-not $redirected) {
        while ($true) {
            $key = $Host.UI.RawUI.ReadKey('NoEcho,IncludeKeyDown')
            # Shift, Ctrl, Alt, CapsLock и Win сами по себе выбором не являются
            if ($key.VirtualKeyCode -notin 16, 17, 18, 20, 91, 92) { break }
        }
        return [pscustomobject]@{
            Char     = [string]$key.Character
            IsEnter  = ($key.VirtualKeyCode -eq 13)
            IsEscape = ($key.VirtualKeyCode -eq 27)
        }
    }

    try {
        $line = (Read-Host).Trim()
    } catch {
        # Ввода нет вовсе: трактуем как выход, чтобы меню закрылось само,
        # а не упало трейсбеком в лицо.
        return [pscustomobject]@{ Char = '0'; IsEnter = $false; IsEscape = $true }
    }
    return [pscustomobject]@{
        Char     = $line
        IsEnter  = ($line -eq '')
        IsEscape = $false
    }
}

function Read-EwChoice {
    # Пунктов больше девяти — одной клавишей уже не обойтись, читаем строкой.
    param([switch]$AllowLongInput)

    Write-Host ''
    Write-Host "$script:EwPad Выбор: " -ForegroundColor Cyan -NoNewline
    if ($AllowLongInput) { return (Read-Host).Trim() }

    $key = Read-EwKey
    if ($key.IsEscape) { Write-Host '0' -ForegroundColor White; return '0' }
    if ($key.IsEnter) { Write-Host ''; return '' }
    Write-Host $key.Char -ForegroundColor White
    return $key.Char
}

function Read-EwConfirm {
    param([string]$Question)

    Write-Host ''
    Write-Host "$script:EwPad $Question [д/н]: " -ForegroundColor Yellow -NoNewline
    $key = Read-EwKey
    # Согласие требует явной клавиши: Enter и Escape означают «нет», чтобы
    # случайное нажатие никогда не запускало удаление.
    $yes = (-not $key.IsEscape) -and (-not $key.IsEnter) -and ($key.Char -match '^(д|y|1)')
    Write-Host $(if ($yes) { 'да' } else { 'нет' }) -ForegroundColor White
    return $yes
}

function Wait-EwKey {
    param([string]$Text = 'Нажмите любую клавишу, чтобы вернуться в меню')

    Write-Host ''
    Write-Host "$script:EwPad $Text" -ForegroundColor DarkGray
    $null = Read-EwKey
}
