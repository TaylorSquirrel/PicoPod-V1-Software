param(
    [ValidateSet('List', 'Validate', 'Prepare')][string]$Mode = 'List',
    [string]$ExpectedFile,
    [string]$ResultFile
)
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding($false)

function Write-PicoResult($data) {
    # The unelevated app precreates this file. Update it in place to preserve
    # that user's ACL; the caller waits for this process to exit before reading.
    if (-not (Test-Path -LiteralPath $ResultFile -PathType Leaf)) { throw 'Result file must be precreated by the app' }
    $encoding = New-Object System.Text.UTF8Encoding($false)
    [System.IO.File]::WriteAllText($ResultFile, ($data | ConvertTo-Json), $encoding)
}

function Get-CardClearTargets($card) {
    $root = [System.IO.Path]::GetFullPath($card.UniqueId).TrimEnd('\') + '\'
    if ($root -notmatch '^\\\\\?\\Volume\{[0-9a-fA-F-]{36}\}\\$') { throw 'Invalid volume GUID root' }
    foreach ($entry in @(Get-ChildItem -LiteralPath $root -Force)) {
        # Windows recreates these bookkeeping directories; leave them alone.
        if ($entry.Name -in @('System Volume Information', '$RECYCLE.BIN')) { continue }
        if ($entry.Name -in @('.', '..') -or ($entry.Attributes -band [IO.FileAttributes]::ReparsePoint)) {
            throw 'Unsafe filesystem entry on the card'
        }
        $target = [System.IO.Path]::GetFullPath((Join-Path -Path $root -ChildPath $entry.Name))
        if (-not $target.StartsWith($root, [StringComparison]::OrdinalIgnoreCase) -or $target.TrimEnd('\') -eq $root.TrimEnd('\')) {
            throw 'Clear target escapes the confirmed card root'
        }
        $target
    }
}

function Get-PicoCards {
    foreach ($volume in @(Get-Volume | Where-Object { $_.FileSystemLabel -ceq 'PICOPOD' })) {
        if (-not $volume.DriveLetter) { continue }
        $partition = Get-Partition -DriveLetter $volume.DriveLetter
        $disk = $partition | Get-Disk
        $partitionCount = @($disk | Get-Partition).Count
        [pscustomobject]@{
            DriveLetter = [string]$volume.DriveLetter
            UniqueId = [string]$volume.UniqueId
            Label = [string]$volume.FileSystemLabel
            FileSystem = [string]$volume.FileSystem
            DriveType = [string]$volume.DriveType
            DiskNumber = [int]$disk.Number
            DiskUniqueId = [string]$disk.UniqueId
            DiskSerial = ([string]$disk.SerialNumber).Trim()
            BusType = [string]$disk.BusType
            IsBoot = [bool]$disk.IsBoot
            IsSystem = [bool]$disk.IsSystem
            PartitionNumber = [int]$partition.PartitionNumber
            PartitionCount = $partitionCount
            Offset = [long]$partition.Offset
            Size = [long]$partition.Size
            DiskSize = [long]$disk.Size
        }
    }
}

if ($Mode -eq 'List') {
    ConvertTo-Json -InputObject @(Get-PicoCards) -Depth 4 -Compress
    exit 0
}

try {
    if (-not $ExpectedFile -or -not $ResultFile) { throw 'Missing format request files' }
    $expected = Get-Content -LiteralPath $ExpectedFile -Raw | ConvertFrom-Json
    $cards = @(Get-PicoCards)
    if ($cards.Count -ne 1) { throw 'Exactly one card named PICOPOD must be connected' }
    $card = $cards[0]
    foreach ($field in @('DriveLetter','UniqueId','DiskNumber','DiskUniqueId','DiskSerial','PartitionNumber','Offset','Size','DiskSize')) {
        if ([string]$card.$field -cne [string]$expected.$field) { throw "Card identity changed: $field" }
    }
    if ($card.Label -cne 'PICOPOD' -or $card.DriveType -ne 'Removable') { throw 'Target is not a removable PICOPOD volume' }
    if ($card.BusType -notin @('USB','SD','MMC')) { throw 'Only USB/SD/MMC card readers are allowed' }
    if ($card.IsBoot -or $card.IsSystem -or $card.PartitionCount -ne 1) { throw 'System disks and multi-partition disks are not allowed' }
    if ($card.DiskSize -gt 34359738368 -or $card.Size -lt 67108864) { throw 'Use a card between 64 MB and 32 GB' }
    if ($card.DriveLetter -eq $env:SystemDrive.TrimEnd(':')) { throw 'System drive is not allowed' }
    $volumes = @(Get-Volume -UniqueId $card.UniqueId)
    if ($volumes.Count -ne 1 -or $volumes[0].FileSystemLabel -cne 'PICOPOD') { throw 'Volume identity changed before formatting' }
    if ($volumes[0].FileSystem -cne $expected.FileSystem) { throw 'Card filesystem changed after confirmation. Please confirm the target again.' }
    $alreadyFat32 = $volumes[0].FileSystem -eq 'FAT32'
    $clearTargets = @()
    if ($alreadyFat32) { $clearTargets = @(Get-CardClearTargets $card) }
    if ($Mode -eq 'Validate') {
        Write-PicoResult @{ ok = $true; dryRun = $true; action = $(if ($alreadyFat32) { 'clear' } else { 'format' }); targets = $clearTargets.Count }
        exit 0
    }
    # The GUI has confirmed erasing user files on this exact card. Preserve an
    # existing FAT32 filesystem; only other filesystems require Format-Volume.
    if ($alreadyFat32) {
        foreach ($target in $clearTargets) {
            # Recheck the GUID volume immediately before every recursive removal.
            $current = Get-Volume -UniqueId $card.UniqueId
            if ($current.FileSystem -ne 'FAT32' -or $current.FileSystemLabel -cne 'PICOPOD') { throw 'Card changed during clearing' }
            $verifiedRoot = [System.IO.Path]::GetFullPath($card.UniqueId).TrimEnd('\') + '\'
            $verifiedTarget = [System.IO.Path]::GetFullPath($target)
            if (-not $verifiedTarget.StartsWith($verifiedRoot, [StringComparison]::OrdinalIgnoreCase) -or $verifiedTarget.TrimEnd('\') -eq $verifiedRoot.TrimEnd('\')) {
                throw 'Refusing to remove a path outside the confirmed card'
            }
            Remove-Item -LiteralPath $verifiedTarget -Recurse -Force -ErrorAction Stop
        }
    } else {
        $volumes[0] | Format-Volume -FileSystem FAT32 -NewFileSystemLabel PICOPOD -Force -Confirm:$false | Out-Null
    }
    $after = Get-Volume -DriveLetter $card.DriveLetter
    if ($after.FileSystem -ne 'FAT32' -or $after.FileSystemLabel -cne 'PICOPOD') { throw 'FAT32 format verification failed' }
    Write-PicoResult @{ ok = $true; action = $(if ($alreadyFat32) { 'cleared' } else { 'formatted' }) }
} catch {
    if ($ResultFile) {
        Write-PicoResult @{ ok = $false; error = $_.Exception.Message }
    }
    exit 1
}
