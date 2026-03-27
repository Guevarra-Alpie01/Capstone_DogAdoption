# Django Load, Stress, and Security Probe Suite

This folder adds a Locust-based test suite for the Bayawan Vet Django backend. It exercises:

- public traffic
- authenticated user browsing
- admin browsing
- CSRF-protected form submissions
- adaptive stress testing
- basic SQL injection and XSS probes

## Files

- `tests/load_test.py`: main Locust suite
- `tests/check_deployment_config.py`: validates `DEBUG=False` and security middleware before benchmarking
- `tests/requirements-load.txt`: minimal Locust dependency file

## Install

```powershell
pip install -r tests/requirements-load.txt
```

## Minimum Environment Variables

Provide at least one normal user account:

```powershell
$env:LOAD_TEST_USER_USERNAME="testuser"
$env:LOAD_TEST_USER_PASSWORD="testpassword"
```

Optional admin account:

```powershell
$env:LOAD_TEST_ADMIN_USERNAME="adminuser"
$env:LOAD_TEST_ADMIN_PASSWORD="adminpassword"
```

Credential pools are also supported:

```powershell
$env:LOAD_TEST_USER_CREDENTIALS="user1:pass1,user2:pass2"
$env:LOAD_TEST_ADMIN_CREDENTIALS="admin1:pass1,admin2:pass2"
```

Fixed concurrent counts are also supported when you want a guaranteed mix of traffic:

```powershell
$env:LOAD_TEST_PUBLIC_FIXED_COUNT="10"
$env:LOAD_TEST_USER_FIXED_COUNT="80"
$env:LOAD_TEST_ADMIN_FIXED_COUNT="7"
```

When fixed counts are set, Locust will keep that many users in each class and distribute any remaining users by weight. Keep the total user count at or above the sum of the fixed counts.

## Important Rate-Limit Note

Your backend rate-limits authentication. A large one-IP login storm can hit that limiter before the Django app itself is the bottleneck.

For realistic staging tests:

- whitelist the load-generator IP at the edge, or
- temporarily raise the auth bucket on staging only, or
- keep session cycling disabled and focus on post-login traffic

## Useful Options

```powershell
$env:LOAD_TEST_PROFILE="steady"                 # steady | stress
$env:LOAD_TEST_OUTPUT_DIR="tests/reports"
$env:LOAD_TEST_REPORT_PREFIX="staging_"
$env:LOAD_TEST_SEARCH_TERM="dog"
$env:LOAD_TEST_BARANGAY_QUERY="ca"
```

Optional write traffic:

```powershell
$env:LOAD_TEST_ENABLE_WRITES="true"
$env:LOAD_TEST_WRITE_USER_SAMPLE_RATE="0.10"
$env:LOAD_TEST_REQUEST_BARANGAY="Caranoche"
$env:LOAD_TEST_REQUEST_CITY="Bayawan City"
$env:LOAD_TEST_REQUEST_PHONE_NUMBER="09171234567"
$env:LOAD_TEST_REQUEST_LATITUDE="9.364300"
$env:LOAD_TEST_REQUEST_LONGITUDE="122.804300"
```

Security probe tuning:

```powershell
$env:LOAD_TEST_ENABLE_SECURITY_PROBES="true"
$env:LOAD_TEST_SECURITY_PROBE_USER_SAMPLE_RATE="0.10"
$env:LOAD_TEST_SECURITY_PROBE_INTERVAL_SECONDS="180"
```

Steady ramp defaults:

- users: `10,50,100,500`
- stage durations: `60,120,180,240` seconds
- spawn rates: `2,5,10,25`

Stress defaults:

- starts at `10` users
- adds `40` users every `60` seconds
- stops when failure ratio goes above `10%` or p95 goes above `5000 ms`

## Check Django Config First

```powershell
python tests/check_deployment_config.py
```

## Run Locally

Interactive UI:

```powershell
locust -f tests/load_test.py --host=http://127.0.0.1:8000
```

Example mixed local run with at least 7 concurrent admins/staff:

```powershell
$env:LOAD_TEST_USER_CREDENTIALS="user1:pass1,user2:pass2,user3:pass3,user4:pass4,user5:pass5"
$env:LOAD_TEST_ADMIN_CREDENTIALS="admin1:pass1,admin2:pass2,admin3:pass3,admin4:pass4,admin5:pass5,admin6:pass6,admin7:pass7"
$env:LOAD_TEST_USER_FIXED_COUNT="60"
$env:LOAD_TEST_ADMIN_FIXED_COUNT="7"
$env:LOAD_TEST_PUBLIC_FIXED_COUNT="10"
locust -f tests/load_test.py --host=http://127.0.0.1:8000
```

Then in the Locust UI, set the total users to at least `77` so all fixed users can spawn.

Headless steady ramp with CSV and HTML reports:

```powershell
$env:LOAD_TEST_PROFILE="steady"
locust -f tests/load_test.py `
  --host=http://127.0.0.1:8000 `
  --headless `
  --html tests/reports/steady.html `
  --csv tests/reports/steady
```

Headless stress run against staging:

```powershell
$env:LOAD_TEST_PROFILE="stress"
locust -f tests/load_test.py `
  --host=https://your-django-app.com `
  --headless `
  --html tests/reports/stress.html `
  --csv tests/reports/stress
```

Example requested command:

```powershell
locust -f tests/load_test.py --host=https://your-django-app.com
```

## Reports

Locust built-ins:

- `--html` gives charts and latency/failure graphs
- `--csv` writes aggregate CSV metrics

Suite-generated outputs in `tests/reports/`:

- `*_summary.json`: fail ratio, p95, RPS, and breaking point if detected
- `*_security_probes.csv`: GET/POST probe findings
- `*_stage_history.csv`: stage-by-stage snapshots

## What the Suite Simulates

Public traffic:

- root redirect
- login page
- signup page
- live/readiness probes

Authenticated user traffic:

- login
- home feed
- announcements
- adoption list
- request page
- claim list
- notification summary
- barangay API
- search endpoint
- optional adoption/comment/request submissions
- logout on session end

Admin traffic:

- login through the shared auth page
- post list
- request board
- registration record
- analytics dashboard
- notification summary
- admin search APIs
- logout on session end

Security probes:

- SQL injection-like query strings on GET endpoints
- XSS payloads on GET search endpoints
- optional XSS comment POST probe when write traffic is enabled

## Practical Staging Advice

- Keep write traffic off unless you are using throwaway data.
- Use multiple test accounts for more realistic sessions.
- For a `7` admin/staff concurrency target, use at least `7` distinct admin credentials to avoid per-account login throttling distorting the run.
- Run one auth-focused test and one post-login scalability test.
- Correlate the Locust charts with PythonAnywhere CPU and memory graphs during stress runs.
