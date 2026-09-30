# Sync arctic/web to the GitHub staging clone, then commit & push.
# Data_Out is always wiped on the GitHub side, then replaced with the current web copy.
# Usage (via sync_github.bat):
#   sync_github.bat                     -> commit "web sync YYYY-MM-DD HHMM" + push
#   sync_github.bat "my message"        -> commit with custom message + push
#   sync_github.bat -NoPush             -> commit only (push later by hand)
#   sync_github.bat -NoCommit           -> copy + stage only (old behaviour)
param(
    [string]$Message = '',
    [switch]$NoPush,
    [switch]$NoCommit
)
$ErrorActionPreference = 'Stop'

$src = 'D:\workspace2026\arctic\web'
$dst = 'D:\workspace2026\_kiost_arctic_push'
$srcData = Join-Path $src 'Data_Out'
$dstData = Join-Path $dst 'Data_Out'

if (-not (Test-Path (Join-Path $dst '.git'))) {
    throw "GitHub staging repo not found: $dst"
}
if (-not (Test-Path $srcData)) {
    throw "Source Data_Out not found: $srcData"
}

Write-Host '==== wipe GitHub Data_Out ===='
git -C $dst rm -r --ignore-unmatch -f -- Data_Out
if (Test-Path $dstData) {
    Remove-Item -LiteralPath $dstData -Recurse -Force
}

Write-Host '==== copy current web Data_Out ===='
New-Item -ItemType Directory -Force -Path $dstData | Out-Null
$rc = (Start-Process -FilePath robocopy -ArgumentList @(
    $srcData, $dstData, '/E', '/NFL', '/NDL', '/NJH', '/NJS', '/nc', '/ns', '/np'
) -Wait -PassThru).ExitCode
if ($rc -ge 8) { throw "robocopy Data_Out failed: $rc" }

Write-Host '==== copy other web files ===='
$rc2 = (Start-Process -FilePath robocopy -ArgumentList @(
    $src, $dst, '/E', '/XD', '.git', 'Data_Out', '__pycache__',
    '/XF', '*.pyc', '/NFL', '/NDL', '/NJH', '/NJS', '/nc', '/ns', '/np'
) -Wait -PassThru).ExitCode
if ($rc2 -ge 8) { throw "robocopy web files failed: $rc2" }

Write-Host '==== stage Data_Out replacement ===='
git -C $dst add -A -- Data_Out
git -C $dst add -- . ':!Data_Out'

Write-Host '==== Data_Out counts ===='
$nSrc = @(Get-ChildItem $srcData -Recurse -File).Count
$nDst = @(Get-ChildItem $dstData -Recurse -File).Count
$nGit = @(git -C $dst ls-files Data_Out).Count
"web=$nSrc  staging=$nDst  git=$nGit"
git -C $dst status -sb

if ($NoCommit) {
    Write-Host '==== staged only (-NoCommit) — commit/push skipped ===='
    exit 0
}

# ==== commit ====
$staged = git -C $dst diff --cached --name-only
if (-not $staged) {
    Write-Host '==== nothing staged — commit/push skipped ===='
    exit 0
}
if (-not $Message) {
    $Message = 'web sync ' + (Get-Date -Format 'yyyy-MM-dd HHmm')
}
Write-Host "==== commit: $Message ===="
git -C $dst commit -m $Message
if ($LASTEXITCODE -ne 0) { throw "git commit failed: $LASTEXITCODE" }

if ($NoPush) {
    Write-Host '==== committed (-NoPush) — push later by hand ===='
    git -C $dst log --oneline -1
    exit 0
}

# ==== push ====
Write-Host '==== push ===='
git -C $dst push
if ($LASTEXITCODE -ne 0) {
    throw "git push failed: $LASTEXITCODE (commit is kept — retry with: git -C $dst push)"
}
Write-Host '==== done ===='
git -C $dst log --oneline -1
