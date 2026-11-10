# =============================================================================
# Keystone offline evidence collector (Windows)
#
# Runs the read-only Keystone scripts on one or more PostgreSQL servers with
# psql (from pgAdmin or a PostgreSQL installation): the node script once per
# server, the database script in every database it finds, and the host script
# when run on the server itself. Everything goes into one zip to send. The
# password is asked, never written to disk, and removed at the end.
#
#   powershell -ExecutionPolicy Bypass -File keystone_collect.ps1
# Unattended: -Servers db-1,db-2 -Port 5432 -User postgres -OutDir C:\out
# (and the password in PGPASSWORD); anything not given is asked.
# =============================================================================

param([string]$Servers, [string]$Port, [string]$User, [string]$OutDir, [switch]$NoHost)

$ErrorActionPreference = "Continue"
$Here = Split-Path -Parent $MyInvocation.MyCommand.Path
$Stamp = Get-Date -Format "yyyyMMdd-HHmmss"

function Ask($Prompt, $Default) {
    $answer = Read-Host "$Prompt [$Default]"
    if ([string]::IsNullOrWhiteSpace($answer)) { return $Default } else { return $answer.Trim() }
}

function Find-Psql {
    $command = Get-Command psql.exe -ErrorAction SilentlyContinue
    if ($command) { return $command.Source }
    $patterns = @("$env:ProgramFiles\PostgreSQL\*\bin\psql.exe",
                  "$env:ProgramFiles\pgAdmin 4\runtime\psql.exe",
                  "$env:ProgramFiles\pgAdmin 4\*\runtime\psql.exe",
                  "${env:ProgramFiles(x86)}\pgAdmin 4\*\runtime\psql.exe",
                  "$env:LOCALAPPDATA\Programs\pgAdmin 4\runtime\psql.exe")
    $found = Get-ChildItem -Path $patterns -ErrorAction SilentlyContinue | Sort-Object FullName -Descending
    if ($found) { return $found[0].FullName }
    return (Read-Host "psql.exe bulunamadi. Tam yolunu girin")
}

function Safe($Text) { return ($Text -replace '[^A-Za-z0-9._-]', '_') }

$Psql = Find-Psql
if (-not (Test-Path $Psql)) { Write-Error "psql.exe bulunamadi: $Psql"; exit 1 }
Write-Host "Keystone offline kanit toplama (salt okunur). psql: $Psql"

$Hosts = if ($Servers) { $Servers } else { Ask "Sunucu(lar), virgulle" "localhost" }
if (-not $Port) { $Port = Ask "Port" "5432" }
if (-not $User) { $User = Ask "Kullanici" "postgres" }
$PresetPassword = [bool]$env:PGPASSWORD
if (-not $PresetPassword) {
    $Secure = Read-Host "Sifre" -AsSecureString
    $bstr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($Secure)
    $env:PGPASSWORD = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($bstr)
    [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($bstr)
}
$Out = if ($OutDir) { $OutDir } else { Ask "Cikti klasoru" (Join-Path $Here "keystone_evidence_$Stamp") }
New-Item -ItemType Directory -Force -Path $Out | Out-Null
$env:PGCLIENTENCODING = "UTF8"
$env:PGCONNECT_TIMEOUT = "10"

try {
    foreach ($HostName in ($Hosts -split ",") | ForEach-Object { $_.Trim() } | Where-Object { $_ }) {
        # Files are named after the server as typed (this computer's name for localhost); Keystone matches them.
        $Label = if ($HostName -in @("localhost", "127.0.0.1", "::1")) { [Environment]::MachineName } else { $HostName }
        $Name = Safe $Label
        $Conn = @("-X", "-q", "-At", "-v", "ON_ERROR_STOP=1", "-h", $HostName, "-p", $Port, "-U", $User)

        # Every name this server is reached by, so Keystone knows it however it is typed next time.
        $Resolved = @()
        try { $Resolved = @([System.Net.Dns]::GetHostAddresses($Label) | ForEach-Object { $_.IPAddressToString }) } catch { }
        @{ typed = $HostName; label = $Label; port = [int]$Port; resolved = $Resolved } |
            ConvertTo-Json -Compress | Out-File -Encoding utf8 (Join-Path $Out "${Name}_server.json")

        Write-Host "[$Label] node script..."
        & $Psql @Conn -d postgres -f (Join-Path $Here "keystone_node.sql") -o (Join-Path $Out "${Name}_node.json")
        if ($LASTEXITCODE -ne 0) {
            Write-Warning "[$Label] baglanilamadi ya da script hata verdi; bu sunucu atlandi."
            Remove-Item (Join-Path $Out "${Name}_node.json") -ErrorAction SilentlyContinue
            continue
        }

        $Databases = & $Psql @Conn -d postgres -c "SELECT datname FROM pg_database WHERE datallowconn AND NOT datistemplate ORDER BY 1"
        foreach ($Db in $Databases | Where-Object { $_ }) {
            Write-Host "[$Label] veritabani: $Db"
            $File = Join-Path $Out ("${Name}_db_" + (Safe $Db) + ".json")
            & $Psql @Conn -d $Db -f (Join-Path $Here "keystone_database.sql") -o $File
            if ($LASTEXITCODE -ne 0) {
                Write-Warning "[$Label] $Db atlandi (hata)."
                Remove-Item $File -ErrorAction SilentlyContinue
            }
        }

        $Local = $HostName -in @("localhost", "127.0.0.1", "::1", [Environment]::MachineName)
        if ($NoHost) { $Local = $false }
        elseif (-not $Local) { $Local = (Ask "$Label bu bilgisayar mi? Sunucu bilgisi de toplansin mi (e/h)" "h") -eq "e" }
        if ($Local) {
            & (Join-Path $Here "host_snapshot_windows.ps1") | Out-File -Encoding utf8 (Join-Path $Out "${Name}_host.txt")
            Write-Host "[$Label] sunucu bilgisi toplandi."
        }
    }
}
finally {
    if (-not $PresetPassword) { Remove-Item Env:PGPASSWORD -ErrorAction SilentlyContinue }
}

$Archive = "$Out.zip"
Compress-Archive -Path (Join-Path $Out "*") -DestinationPath $Archive -Force
Write-Host ""
Write-Host "Tamamlandi: $Archive"
Write-Host "Bu dosyayi gonderin. Icerigi duz metindir; gondermeden once inceleyebilirsiniz."
