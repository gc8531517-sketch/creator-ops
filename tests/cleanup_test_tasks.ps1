param([Parameter(Mandatory)][string]$NamesFile)
$ErrorActionPreference = 'Stop'
$names = Get-Content -LiteralPath $NamesFile -Raw -Encoding utf8 | ConvertFrom-Json
foreach ($name in $names) {
    if ($name -notmatch '^CreatorOps-[A-F0-9]{8}-1234567890000000001-(Recover|\d{14})$') { throw 'NOT_A_TEST_TASK' }
    $task = Get-ScheduledTask -TaskName $name -ErrorAction SilentlyContinue
    if ($null -ne $task) { Unregister-ScheduledTask -TaskName $name -Confirm:$false }
    if (Get-ScheduledTask -TaskName $name -ErrorAction SilentlyContinue) { throw 'TEST_TASK_STILL_EXISTS' }
}
