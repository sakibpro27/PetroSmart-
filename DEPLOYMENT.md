# Deploying PetroSmart

This guide is for whoever hosts PetroSmart for paying dealers. It assumes an
Ubuntu 22.04/24.04 server, PostgreSQL, Nginx and Gunicorn. Development on
Windows is covered in [README.md](README.md). To put a demonstration copy
online for free, see [FREE_HOSTING.md](FREE_HOSTING.md).

> **Status:** the production settings were checked with
> `manage.py check --deploy`, `collectstatic`, and a server run with
> `DEBUG=False`. A full deployment on a real server with PostgreSQL has
> **not** been carried out yet. Follow these steps on a staging server
> first and test the whole workflow before taking on customers.

## 1. Server packages

```bash
sudo apt update
sudo apt install python3 python3-venv postgresql nginx certbot python3-certbot-nginx
```

## 2. Database

```bash
sudo -u postgres psql
CREATE USER petrosmart WITH PASSWORD 'a-long-random-password';
CREATE DATABASE petrosmart OWNER petrosmart;
\q
```

## 3. Application

```bash
sudo adduser --system --group petrosmart
sudo mkdir -p /srv/petrosmart && sudo chown petrosmart: /srv/petrosmart
sudo -u petrosmart git clone <your-repository> /srv/petrosmart/app
cd /srv/petrosmart/app
sudo -u petrosmart python3 -m venv .venv
sudo -u petrosmart .venv/bin/pip install -r requirements.txt gunicorn==23.0.0
```

Create `/srv/petrosmart/app/.env` (readable only by the `petrosmart` user, `chmod 600`):

```ini
DJANGO_SECRET_KEY=<run: python -c "from django.core.management.utils import get_random_secret_key as k; print(k()+k())">
DJANGO_DEBUG=False
DJANGO_ALLOWED_HOSTS=app.example.in
DJANGO_CSRF_TRUSTED_ORIGINS=https://app.example.in
DATABASE_URL=postgres://petrosmart:a-long-random-password@localhost:5432/petrosmart
PETROSMART_ADMIN_PATH=a-hard-to-guess-admin-path/
DJANGO_SECURE_SSL_REDIRECT=True
DJANGO_SECURE_COOKIES=True
DJANGO_HSTS_SECONDS=31536000
DJANGO_BEHIND_PROXY=True
DJANGO_EMAIL_BACKEND=django.core.mail.backends.smtp.EmailBackend
EMAIL_HOST=smtp.your-provider.com
EMAIL_HOST_USER=...
EMAIL_HOST_PASSWORD=...
DEFAULT_FROM_EMAIL=PetroSmart <no-reply@example.in>
```

PetroSmart refuses to start in production with a short secret key or a
missing or `*` value in `DJANGO_ALLOWED_HOSTS`.

```bash
sudo -u petrosmart .venv/bin/python manage.py migrate
sudo -u petrosmart .venv/bin/python manage.py collectstatic --noinput
sudo -u petrosmart .venv/bin/python manage.py createsuperuser   # platform administrator
sudo -u petrosmart .venv/bin/python manage.py check --deploy
```

`seed_demo` refuses to run when `DEBUG` is off, so demo data can never reach
a live database.

## 4. Gunicorn service

`/etc/systemd/system/petrosmart.service`:

```ini
[Unit]
Description=PetroSmart
After=network.target postgresql.service

[Service]
User=petrosmart
WorkingDirectory=/srv/petrosmart/app
ExecStart=/srv/petrosmart/app/.venv/bin/gunicorn config.wsgi:application --bind 127.0.0.1:8001 --workers 3
Restart=on-failure

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload && sudo systemctl enable --now petrosmart
```

## 5. Nginx and HTTPS

`/etc/nginx/sites-available/petrosmart`:

```nginx
server {
    server_name app.example.in;
    client_max_body_size 5m;
    location / {
        proxy_pass http://127.0.0.1:8001;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_set_header X-Real-IP $remote_addr;
    }
}
```

```bash
sudo ln -s /etc/nginx/sites-available/petrosmart /etc/nginx/sites-enabled/
sudo nginx -t && sudo systemctl reload nginx
sudo certbot --nginx -d app.example.in
```

Static files are served by WhiteNoise from inside the application, so Nginx
needs no static-file block.

**Client IP addresses:** PetroSmart records `REMOTE_ADDR` in the audit log
and uses it to limit login attempts. Behind Nginx this is `127.0.0.1` unless
the real address is passed through. Gunicorn does not do this by itself, so
for per-IP limits to work, add a trusted middleware or Gunicorn configuration
that sets `REMOTE_ADDR` from `X-Real-IP` (set only by your own Nginx). The
per-username login limit works either way.

## 6. Onboarding a dealer (platform administrator)

1. Log in at `https://app.example.in/<PETROSMART_ADMIN_PATH>`.
2. **Subscription plans:** create the plans you sell (outlet and user limits, yearly price).
3. **Businesses:** add the dealer's business with a plan, status and end date.
   MS/HSD products, payment methods and expense categories are created automatically.
4. **Users:** create the first Dealer account (business + role *Dealer*).
   The Dealer then adds outlets, tanks, nozzles, managers and everything else.
5. To renew, select the business and run **Renew selected subscriptions for 12 months**.
   The renewal history is kept, and the Dealer sees it on the Subscription page.

## 7. Backups

PostgreSQL holds everything. Back up daily and keep copies **off** the server.

```bash
# /etc/cron.d/petrosmart-backup  (runs at 02:30)
30 2 * * * petrosmart pg_dump -Fc petrosmart > /srv/petrosmart/backups/petrosmart-$(date +\%Y\%m\%d).dump
```

Copy the dump files to separate storage (another server or encrypted cloud
storage) and delete old ones on a schedule.

**Restore (test this regularly on a spare database):**

```bash
createdb petrosmart_restore
pg_restore -d petrosmart_restore /path/to/petrosmart-YYYYMMDD.dump
```

Keep `.env` out of public backups: it contains the secret key and database password.

## 8. Updating

```bash
cd /srv/petrosmart/app
sudo -u petrosmart git pull
sudo -u petrosmart .venv/bin/pip install -r requirements.txt
sudo -u petrosmart .venv/bin/python manage.py migrate
sudo -u petrosmart .venv/bin/python manage.py collectstatic --noinput
sudo -u petrosmart .venv/bin/python manage.py test
sudo systemctl restart petrosmart
```

Take a backup before every update that includes migrations.
