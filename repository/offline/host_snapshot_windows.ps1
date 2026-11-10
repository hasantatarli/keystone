# =============================================================================
# Keystone offline evidence: host script for Windows
#
# Prints the same sections as the Linux host collector (host_snapshot.sh), so
# Keystone reads both the same way. Read-only: Get-* cmdlets only; it installs,
# creates and changes nothing.
#
# Run in PowerShell on the database server and save the output:
#   powershell -ExecutionPolicy Bypass -File host_snapshot_windows.ps1 > host.txt
# =============================================================================

$ErrorActionPreference = "Continue"
$os = Get-CimInstance Win32_OperatingSystem
$cs = Get-CimInstance Win32_ComputerSystem

"===CAPTURED_AT==="
(Get-Date).ToUniversalTime().ToString("yyyy-MM-ddTHH:mm:ssZ")

"===OS_FAMILY==="
"WINDOWS"

"===HOSTNAME==="
$env:COMPUTERNAME

"===OS_RELEASE==="
"PRETTY_NAME=""$($os.Caption)"""
"VERSION_ID=""$($os.Version)"""

"===UPTIME==="
[int]((Get-Date) - $os.LastBootUpTime).TotalSeconds

"===CPU==="
[Environment]::ProcessorCount

# Same lines as /proc/meminfo, in kB.
"===MEMORY==="
"MemTotal: $($os.TotalVisibleMemorySize) kB"
"MemAvailable: $($os.FreePhysicalMemory) kB"
$swapTotal = 0; $swapUsed = 0
Get-CimInstance Win32_PageFileUsage -ErrorAction SilentlyContinue | ForEach-Object {
    $swapTotal += $_.AllocatedBaseSize; $swapUsed += $_.CurrentUsage }
"SwapTotal: $($swapTotal * 1024) kB"
"SwapFree: $(($swapTotal - $swapUsed) * 1024) kB"

# Like df -B1 -P: device, size, used, available, use%, mount point (local disks only).
"===FILESYSTEMS==="
"Filesystem 1-blocks Used Available Capacity Mounted on"
Get-CimInstance Win32_LogicalDisk -Filter "DriveType=3" | ForEach-Object {
    $used = $_.Size - $_.FreeSpace
    $pct = if ($_.Size -gt 0) { [int](100 * $used / $_.Size) } else { 0 }
    "$($_.DeviceID) $($_.Size) $used $($_.FreeSpace) $pct% $($_.DeviceID)\"
}

# Like lsblk ROTA: 1 rotating (HDD), 0 not (SSD); unknown media types are left out.
"===BLOCK_DEVICES==="
try {
    Get-Partition -ErrorAction Stop | Where-Object { $_.DriveLetter } | ForEach-Object {
        $disk = $_
        $media = (Get-PhysicalDisk -ErrorAction SilentlyContinue |
                  Where-Object { $_.DeviceId -eq [string]$disk.DiskNumber } | Select-Object -First 1).MediaType
        if ($media -eq "HDD") { "$($disk.DriveLetter): 1" }
        elseif ($media -eq "SSD") { "$($disk.DriveLetter): 0" }
    }
} catch { }

# Like systemd-detect-virt --vm: the hypervisor, or none.
"===VIRTUALIZATION==="
$model = "$($cs.Manufacturer) $($cs.Model)"
if ($model -match "VMware") { "vmware" }
elseif ($model -match "VirtualBox|innotek") { "oracle" }
elseif ($model -match "Microsoft Corporation Virtual Machine") { "microsoft" }
elseif ($model -match "QEMU|KVM") { "kvm" }
elseif ($model -match "Xen") { "xen" }
elseif ($model -match "Amazon EC2") { "amazon" }
elseif ($model -match "Google") { "google" }
elseif ($model -match "Virtual") { "unknown" }
else { "none" }    # HypervisorPresent is also true on physical hosts with Hyper-V, WSL or VBS
