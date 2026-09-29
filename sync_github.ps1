# Sync arctic/web to the GitHub staging clone.
# Data_Out is always wiped on the GitHub side, then replaced with the current web copy.
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
