# Locust: 50 members + 3 vet staff + 7 admins (0 anonymous) — full-app navigation
# Prereq: pip install -r tests/requirements-load.txt
# Use real accounts: is_staff for STAFF/ADMIN; members must not be staff.

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

# Load optional env file next to this script
$envFile = Join-Path $PSScriptRoot "capstone60user.env"
if (Test-Path $envFile) {
    Get-Content $envFile | ForEach-Object {
        $line = $_.Trim()
        if ($line -eq "" -or $line.StartsWith("#")) { return }
        $eq = $line.IndexOf("=")
        if ($eq -lt 1) { return }
        $name = $line.Substring(0, $eq).Trim()
        $val = $line.Substring($eq + 1).Trim()
        if ($name) { Set-Item -Path "env:$name" -Value $val }
    }
    Write-Host "Loaded: $envFile"
}

# Defaults for 60-user mix (override in capstone60user.env)
if (-not $env:LOAD_TEST_PUBLIC_FIXED_COUNT) { $env:LOAD_TEST_PUBLIC_FIXED_COUNT = "0" }
if (-not $env:LOAD_TEST_USER_FIXED_COUNT) { $env:LOAD_TEST_USER_FIXED_COUNT = "50" }
if (-not $env:LOAD_TEST_STAFF_FIXED_COUNT) { $env:LOAD_TEST_STAFF_FIXED_COUNT = "3" }
if (-not $env:LOAD_TEST_ADMIN_FIXED_COUNT) { $env:LOAD_TEST_ADMIN_FIXED_COUNT = "7" }

$hostUrl = $env:LOADTEST_HOST
if (-not $hostUrl) { $hostUrl = "http://127.0.0.1:8000" }

$locustFile = Join-Path $PSScriptRoot "load_test.py"
Write-Host "Locust file: $locustFile"
Write-Host "Host: $hostUrl"
Write-Host "Mix: public=$($env:LOAD_TEST_PUBLIC_FIXED_COUNT) user=$($env:LOAD_TEST_USER_FIXED_COUNT) staff=$($env:LOAD_TEST_STAFF_FIXED_COUNT) admin=$($env:LOAD_TEST_ADMIN_FIXED_COUNT)"
Write-Host ""
Write-Host "If credentials are missing, set LOAD_TEST_USER_*, LOAD_TEST_STAFF_*, LOAD_TEST_ADMIN_* in capstone60user.env (see capstone60user.env.example)."
Write-Host ""

$extra = $args
& locust -f $locustFile --host $hostUrl @extra
