# Deployment Prep (Django + PythonAnywhere)

This project now supports environment-based production settings.

## 1. Create and fill `.env`

Copy `.env.example` to `.env`, then set at least:

- `DJANGO_SECRET_KEY` to a long random value
- `DJANGO_DEBUG=False`
- `DJANGO_ALLOWED_HOSTS=<your-username>.pythonanywhere.com`
- `DJANGO_CSRF_TRUSTED_ORIGINS=https://<your-username>.pythonanywhere.com`
- DB settings (`DB_*`) to your PythonAnywhere MySQL database

You can also set:

- `PYTHONANYWHERE_DOMAIN=<your-username>.pythonanywhere.com`

For a quick local test in PowerShell without editing `.env`, you can set the Facebook variables only for the current terminal session:

```powershell
$env:FACEBOOK_APP_ID="your_app_id_here"
$env:FACEBOOK_APP_SECRET="your_app_secret_here"
$env:FACEBOOK_GRAPH_API_VERSION="v20.0"
python manage.py runserver
```

These values disappear when you close that terminal window.

If `DJANGO_CSRF_TRUSTED_ORIGINS` is left blank, it is auto-derived from `ALLOWED_HOSTS` (HTTPS origins only, excluding localhost).

## 2. Cache choice

- Default is `CACHE_BACKEND=locmem` (works without Redis).
- If you use external Redis, set:
  - `CACHE_BACKEND=redis`
  - `REDIS_URL=redis://...`
- For production, prefer Redis over `locmem` so cache state stays consistent across workers.

## 3. Install dependencies

```bash
pip install -r requirements.txt
```

## 4. Apply database and static setup

```bash
python manage.py migrate
python manage.py collectstatic --noinput
```

## 5. Validate deployment configuration

```bash
python manage.py check --deploy
```

## 6. PythonAnywhere WSGI config

In the WSGI file, ensure:

- project path is on `sys.path`
- `DJANGO_SETTINGS_MODULE` is `pet_adoption.settings`
- virtualenv is selected in Web tab

Then reload the web app.

## 7. PythonAnywhere static/media mapping

In the Web tab, add:

- URL: `/static/` -> Directory: `<project-path>/staticfiles`
- URL: `/media/` -> Directory: `<project-path>/media`

Facebook preview images need `/media/` to be publicly reachable.

## 8. Facebook Share Preview Checklist

1. Share URL must be public:
   - `/user/announcements/share/<id>/` should return `200` without login.
2. Confirm OG tags exist:
   - `og:title`
   - `og:description`
   - `og:image` (absolute HTTPS URL)
   - `og:url`
3. Ensure uploaded image URL opens in browser:
   - `https://<your-domain>/media/...`
4. Use Facebook Sharing Debugger:
   - https://developers.facebook.com/tools/debug/
   - Click `Scrape Again` after each content change.
5. If preview is old, clear cache by scraping again.

## Notes

- Media files are served by Django only when `DEBUG=True`.
- Automatic default admin creation is disabled unless `CREATE_DEFAULT_ADMIN=True` and admin credentials are set.
- Health probes are available at `/health/live/` and `/health/ready/`.
- Route metrics are exposed at `/health/metrics/` for staff users; keep that endpoint internal-only in production.
- Apply rate limits at the edge for notification, reaction, face-auth, and autocomplete endpoints.
- Certificate exports, analytics cache warming, and face-image processing are better handled by background jobs if traffic grows.
