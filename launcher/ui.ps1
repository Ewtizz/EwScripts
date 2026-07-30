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
        # ровно под названием: отступ + пробел + [K] + два пробела
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
function Write-EwStep { param([string]$Text) Write-Host "$script:EwPad ·  $Text" -ForegroundColor DarkCyan }
function Write-EwOk   { param([string]$Text) Write-Host "$script:EwPad ✓  $Text" -ForegroundColor Green }
function Write-EwWarn { param([string]$Text) Write-Host "$script:EwPad !  $Text" -ForegroundColor Yellow }
function Write-EwErr  { param([string]$Text) Write-Host "$script:EwPad ✗  $Text" -ForegroundColor Red }

function Read-EwChoice {
    Write-Host ''
    Write-Host "$script:EwPad Выбор: " -ForegroundColor Cyan -NoNewline
    return (Read-Host).Trim()
}

function Read-EwConfirm {
    param([string]$Question)

    Write-Host ''
    Write-Host "$script:EwPad $Question [д/н]: " -ForegroundColor Yellow -NoNewline
    return ((Read-Host).Trim() -match '^(д|да|y|yes)$')
}

function Wait-EwKey {
    param([string]$Text = 'Нажмите Enter, чтобы вернуться в меню')

    Write-Host ''
    Write-Host "$script:EwPad $Text" -ForegroundColor DarkGray
    $null = Read-Host
}
