param(
    [Parameter(Mandatory)][string]$ConfigPath,
    [Parameter(Mandatory)][string]$PlanPath,
    [Parameter(Mandatory)][string]$PythonPath,
    [switch]$Apply
)
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
$resolvedConfig = (Resolve-Path -LiteralPath $ConfigPath).Path
$resolvedPlan = (Resolve-Path -LiteralPath $PlanPath).Path
$plan = Get-Content -LiteralPath $resolvedPlan -Raw -Encoding utf8 | ConvertFrom-Json
if (-not $plan.registration_complete -or [string]$plan.work_id -notmatch '^\d{10,25}$') { throw 'INVALID_REGISTERED_PLAN' }
$expected = @('12小时','24小时','48小时','72小时','7天')
if (@($plan.nodes).Count -ne 5 -or (Compare-Object $expected @($plan.nodes.node))) { throw 'INVALID_NODES' }
$pythonw = Join-Path (Split-Path -Parent $PythonPath) 'pythonw.exe'
if (-not (Test-Path -LiteralPath $pythonw)) { throw 'PYTHONW_REQUIRED' }
$launcher = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '../tools/task_launcher.py')).Path
$sid = [System.Security.Principal.WindowsIdentity]::GetCurrent().User.Value
$hasher = [System.Security.Cryptography.SHA256]::Create()
try { $installation = ([BitConverter]::ToString($hasher.ComputeHash([System.Text.Encoding]::UTF8.GetBytes($resolvedConfig)))).Replace('-','').Substring(0,8) }
finally { $hasher.Dispose() }
$prefix = "CreatorOps-$installation-$($plan.work_id)"
$entries = @()
foreach ($node in $plan.nodes) {
    $planned = [DateTimeOffset]::Parse($node.planned_at)
    if ($planned -le [DateTimeOffset]::Now -or $node.status -notin @('pending','failed')) { continue }
    $name = "$prefix-$($planned.ToString('yyyyMMddHHmmss'))"
    $arguments = '"{0}" "{1}" "{2}" "{3}"' -f $launcher,$resolvedConfig,$plan.work_id,$node.node
    if ($Apply) {
        $action = New-ScheduledTaskAction -Execute $pythonw -Argument $arguments
        $trigger = New-ScheduledTaskTrigger -Once -At $planned.LocalDateTime
        $settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -ExecutionTimeLimit (New-TimeSpan -Minutes 16) -MultipleInstances IgnoreNew
        $principal = New-ScheduledTaskPrincipal -UserId $sid -LogonType Interactive -RunLevel Limited
        Register-ScheduledTask -TaskName $name -Action $action -Trigger $trigger -Settings $settings -Principal $principal -Force | Out-Null
        $readback = Get-ScheduledTask -TaskName $name
        if ($readback.Settings.WakeToRun -or $readback.Settings.StartWhenAvailable -or $readback.Actions.Execute -ne $pythonw -or $readback.Actions.Arguments -ne $arguments) { throw 'TASK_READBACK_FAILED' }
    }
    $entries += @{task_name=$name; node=$node.node; planned_at=$node.planned_at}
}
$recoveryName = "$prefix-Recover"
$recoveryArgs = '"{0}" "{1}" "{2}"' -f $launcher,$resolvedConfig,$plan.work_id
function Escape-Xml([string]$v) { [System.Security.SecurityElement]::Escape($v) }
$xml = @"
<Task version="1.3" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
<Principals><Principal id="User"><UserId>$(Escape-Xml $sid)</UserId><LogonType>InteractiveToken</LogonType><RunLevel>LeastPrivilege</RunLevel></Principal></Principals>
<Settings><MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy><DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries><StopIfGoingOnBatteries>false</StopIfGoingOnBatteries><StartWhenAvailable>false</StartWhenAvailable><WakeToRun>false</WakeToRun><ExecutionTimeLimit>PT16M</ExecutionTimeLimit></Settings>
<Triggers>
<LogonTrigger><Enabled>true</Enabled><UserId>$(Escape-Xml $sid)</UserId></LogonTrigger>
<SessionStateChangeTrigger><Enabled>true</Enabled><UserId>$(Escape-Xml $sid)</UserId><StateChange>SessionUnlock</StateChange></SessionStateChangeTrigger>
<EventTrigger><Enabled>true</Enabled><Subscription>&lt;QueryList&gt;&lt;Query Id="0" Path="System"&gt;&lt;Select Path="System"&gt;*[System[Provider[@Name='Microsoft-Windows-Power-Troubleshooter'] and EventID=1]]&lt;/Select&gt;&lt;/Query&gt;&lt;/QueryList&gt;</Subscription></EventTrigger>
</Triggers>
<Actions Context="User"><Exec><Command>$(Escape-Xml $pythonw)</Command><Arguments>$(Escape-Xml $recoveryArgs)</Arguments></Exec></Actions>
</Task>
"@
if ($Apply) {
    Register-ScheduledTask -TaskName $recoveryName -Xml $xml -Force | Out-Null
    $readback = Get-ScheduledTask -TaskName $recoveryName
    if ($readback.Settings.WakeToRun -or $readback.Settings.StartWhenAvailable -or $readback.Actions.Arguments -ne $recoveryArgs) { throw 'RECOVERY_READBACK_FAILED' }
}
@{ok=$true; applied=[bool]$Apply; tasks=$entries; recovery_task=$recoveryName; wake_to_run=$false; start_when_available=$false} | ConvertTo-Json -Depth 6
