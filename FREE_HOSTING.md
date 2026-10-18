# Putting PetroSmart online for free (demonstration)

This guide puts PetroSmart on **PythonAnywhere's free "Beginner" plan**, so
examiners, classmates or a dealer can try it at an address like
`https://yourname.pythonanywhere.com`. It needs no credit card and no Git on
your computer.

> **Free hosting is for demonstrations only.** The free plan has a small disk,
> no automatic backups and limited outgoing internet, and the site stops if
> you don't log in to PythonAnywhere about once every three months. Do not
> keep real dealers' business data on it. For paying customers, follow
> [DEPLOYMENT.md](DEPLOYMENT.md) on a paid server with PostgreSQL and backups.
>
> Free plans change. Check PythonAnywhere's current plan page before relying
> on any limit mentioned here.

## Why PythonAnywhere

| Option | Free plan | Fit for PetroSmart |
|---|---|---|
| **PythonAnywhere** | One web app, about 512 MB disk, HTTPS included, files kept between restarts | **Best for a demo.** Django is supported, and the SQLite database file is kept. |
| Render, Railway, Koyeb and similar | Containers that sleep or are rebuilt; disk is wiped on each deploy | SQLite data would be lost. A free PostgreSQL database is needed, and on some hosts it expires. |

## 1. Prepare a zip on your computer (Windows)

Run this in PowerShell from `C:\Users\sony\PetroSmart`. It leaves out the
virtual environment, your database, your secrets and generated files:

```powershell
$files = Get-ChildItem -Force | Where-Object { $_.Name -notin @(".venv", "db.sqlite3", ".env", "staticfiles", "__pycache__") }
Compress-Archive -Path $files.FullName -DestinationPath "$env:USERPROFILE\Desktop\petrosmart.zip" -Force
```

## 2. Create the account and upload

1. Sign up for a free **Beginner** account at <https://www.pythonanywhere.com>.
   Your username becomes the web address, so choose it with care.
2. Open the **Files** tab, upload `petrosmart.zip` into `/home/yourname/`.
3. Open **Consoles → Bash** and run:

```bash
cd ~
unzip -q petrosmart.zip -d petrosmart
cd petrosmart
python3.13 -m venv .venv        # use the newest python3.x the console offers (3.10 or newer)
source .venv/bin/activate
pip install -r requirements.txt
```

## 3. Settings (`.env`)

Still in the Bash console, generate a secret key:

```bash
python -c "from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())"
```

Create the settings file with `nano .env`, paste the following (replace
`yourname` and the key), then save with Ctrl+O, Enter, Ctrl+X:

```ini
DJANGO_SECRET_KEY=paste-the-generated-key-here
DJANGO_DEBUG=False
DJANGO_ALLOWED_HOSTS=yourname.pythonanywhere.com
DJANGO_CSRF_TRUSTED_ORIGINS=https://yourname.pythonanywhere.com
DATABASE_URL=
DJANGO_SECURE_COOKIES=True
DJANGO_SECURE_SSL_REDIRECT=False
DJANGO_BEHIND_PROXY=True
PETROSMART_ADMIN_PATH=platform-admin/
```

`DATABASE_URL` stays empty, so the app uses the SQLite file in the project
folder. PythonAnywhere keeps it between restarts. HTTPS is switched on in
step 5 rather than by Django.

Then prepare the database and static files, and create your platform
administrator account:

```bash
python manage.py migrate
python manage.py collectstatic --noinput
python manage.py check --deploy
python manage.py createsuperuser
```

`seed_demo` refuses to run when `DJANGO_DEBUG=False`. Create the demo dealer,
outlet and plan from the platform admin site in step 6 instead.

## 4. Create the web app

1. Open the **Web** tab and choose **Add a new web app**, then **Manual configuration**
   (not "Django"). Pick the same Python version you used for the virtualenv.
2. **Virtualenv:** enter `/home/yourname/petrosmart/.venv`
3. **Static files:** add URL `/static/` with directory `/home/yourname/petrosmart/staticfiles`
4. **WSGI configuration file:** click the link, delete everything in it, and paste:

```python
import os
import sys

path = "/home/yourname/petrosmart"
if path not in sys.path:
    sys.path.insert(0, path)
os.environ["DJANGO_SETTINGS_MODULE"] = "config.settings"

from django.core.wsgi import get_wsgi_application  # noqa: E402

application = get_wsgi_application()
```

## 5. HTTPS and start

On the **Web** tab, turn on **Force HTTPS**, then click **Reload**. Open
`https://yourname.pythonanywhere.com`. You should see the PetroSmart login page.

If you see an error, open the **error log** link on the Web tab. The most
common causes are a typo in `.env` (wrong `DJANGO_ALLOWED_HOSTS`) or a wrong
virtualenv path.

## 6. First dealer

1. Go to `https://yourname.pythonanywhere.com/platform-admin/` and log in as the
   superuser.
2. Add a **Subscription plan**, then a **Business** with an end date in the
   future, then a **User** with role *Dealer* linked to that business.
3. Log out, log in as the dealer and set up outlets, products, tanks, nozzles,
   shifts and prices from the **Set-up** menu.

## Updating the site later

Make a new zip (step 1), upload it, and in the Bash console:

```bash
cd ~ && unzip -oq petrosmart.zip -d petrosmart && cd petrosmart
source .venv/bin/activate
pip install -r requirements.txt
python manage.py migrate
python manage.py collectstatic --noinput
```

Then click **Reload** on the Web tab. `unzip -o` overwrites program files but
keeps `.env` and `db.sqlite3`, because they are not in the zip.

## Limits to know about

- **Email:** free accounts can only reach an allow-list of websites, so the
  "Forgot password" email may not be delivered. The platform administrator can
  set a new password from the platform admin site instead.
- **Backups:** download `db.sqlite3` from the Files tab now and then. There are
  no automatic backups on the free plan.
- **Staying online:** log in to PythonAnywhere at least once every three months
  and click "Run until 3 months from today" on the Web tab, or the site is
  switched off.
