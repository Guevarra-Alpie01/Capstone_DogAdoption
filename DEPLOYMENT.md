# Deployment Prep (Django + PythonAnywhere)

This project now supports environment-based production settings.

## 1. Create and fill `.env`

Copy `.env.example` to `.env`, then set at least:

- `DJANGO_SECRET_KEY` to a long random value
- `DJANGO_DEBUG=False`
- `DJANGO_ALLOWED_HOSTS=<your-username>.pythonanywhere.com`
- `DJANGO_CSRF_TRUSTED_ORIGINS=https://<your-username>.pythonanywhere.com`
- DB settings (`DB_*`) to your PythonAnywhere MySQL database

## 2. Cache choice

- Default is `CACHE_BACKEND=locmem` (works without Redis).
- If you use external Redis, set:
  - `CACHE_BACKEND=redis`
  - `REDIS_URL=redis://...`

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

## Notes

- Media files are served by Django only when `DEBUG=True`.
- Automatic default admin creation is disabled unless `CREATE_DEFAULT_ADMIN=True` and admin credentials are set.
