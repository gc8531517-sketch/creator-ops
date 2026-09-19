param(
    [Parameter(Mandatory = $true)]
    [ValidatePattern('^[A-Za-z0-9_-]{8,80}$')]
    [string]$JobId,
    [Parameter(Mandatory = $true)]
    [string]$DownloadDirectory,
    [Parameter(Mandatory = $true)]
    [string]$ChromePath,
    [ValidateRange(10, 180)]
    [int]$TimeoutSeconds = 90,
    [switch]$DryRun
)

$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
$creatorUrl = 'https://creator.douyin.com/creator-micro/content/manage'
$encodedJob = [Uri]::EscapeDataString($JobId)
$targetUrl = "${creatorUrl}?codex_douyin_export_job=${encodedJob}"
$startedAt = [DateTimeOffset]::Now

if (-not (Test-Path -LiteralPath $chromePath)) {
    throw "CHROME_NOT_FOUND:$chromePath"
}
if (-not (Test-Path -LiteralPath $DownloadDirectory -PathType Container)) {
    throw "DOWNLOAD_DIRECTORY_NOT_FOUND:$DownloadDirectory"
}

function Get-XlsxSnapshot {
    param([string]$Directory)
    $snapshot = @{}
    Get-ChildItem -LiteralPath $Directory -Filter '作品列表*.xlsx' -File -ErrorAction SilentlyContinue | ForEach-Object {
        $snapshot[$_.FullName] = [long]$_.LastWriteTimeUtc.Ticks
    }
    return $snapshot
}

function Test-ZipHeader {
    param([string]$Path)
    try {
        $stream = [System.IO.File]::Open($Path, 'Open', 'Read', 'ReadWrite')
        try {
            if ($stream.Length -lt 2) { return $false }
            return ($stream.ReadByte() -eq 0x50 -and $stream.ReadByte() -eq 0x4B)
        } finally {
            $stream.Dispose()
        }
    } catch {
        return $false
    }
}

$baseline = Get-XlsxSnapshot -Directory $DownloadDirectory
$result = [ordered]@{
    ok = $false
    phase = if ($DryRun) { 'dry_run' } else { 'waiting_for_new_excel' }
    job_id = $JobId
    target_url = $targetUrl
    download_directory = $DownloadDirectory
    baseline_file_count = $baseline.Count
    started_at = $startedAt.ToString('o')
    new_excel = $null
    error = $null
}

if ($DryRun) {
    $result.ok = $true
    $result | ConvertTo-Json -Depth 5
    exit 0
}

Start-Process -FilePath $ChromePath -ArgumentList @('--new-tab', $targetUrl) -WindowStyle Hidden
$deadline = [DateTimeOffset]::Now.AddSeconds($TimeoutSeconds)
$candidate = $null
$lastLength = -1L
$stableChecks = 0

while ([DateTimeOffset]::Now -lt $deadline) {
    Start-Sleep -Milliseconds 500
    $previousCandidatePath = if ($null -eq $candidate) { '' } else { $candidate.FullName }
    $candidate = $null
    $files = Get-ChildItem -LiteralPath $DownloadDirectory -Filter '作品列表*.xlsx' -File -ErrorAction SilentlyContinue |
        Sort-Object LastWriteTimeUtc -Descending
    foreach ($file in $files) {
        $previousTicks = $baseline[$file.FullName]
        $isNewPath = -not $baseline.ContainsKey($file.FullName)
        $isNewVersion = $null -ne $previousTicks -and $file.LastWriteTimeUtc.Ticks -gt $previousTicks
        if (($isNewPath -or $isNewVersion) -and $file.LastWriteTimeUtc -ge $startedAt.UtcDateTime.AddSeconds(-2)) {
            $candidate = $file
            break
        }
    }
    if ($null -eq $candidate) { continue }
    if ($candidate.FullName -ne $previousCandidatePath) { $stableChecks = 0; $lastLength = -1L }

    if ($candidate.Length -gt 0 -and $candidate.Length -eq $lastLength) {
        $stableChecks += 1
    } else {
        $lastLength = $candidate.Length
        $stableChecks = 0
    }
    if ($stableChecks -ge 2 -and (Test-ZipHeader -Path $candidate.FullName)) {
        $result.ok = $true
        $result.phase = 'download_complete'
        $result.new_excel = $candidate.FullName
        $result.completed_at = [DateTimeOffset]::Now.ToString('o')
        $result | ConvertTo-Json -Depth 5
        exit 0
    }
}

$result.phase = 'failed'
$result.error = 'NO_NEW_VALID_EXCEL_WITHIN_TIMEOUT'
$result.completed_at = [DateTimeOffset]::Now.ToString('o')
$result | ConvertTo-Json -Depth 5
exit 1
