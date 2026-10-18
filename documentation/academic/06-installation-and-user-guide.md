# Chapter 6: Installation and User Guide

## 6.1 Installing on Windows (development)

**Requirements:** Windows 10 or 11, Python 3.13 (tick *Add python.exe to PATH* during set-up) and Git.

Open **Windows PowerShell** and run:

```
git clone https://github.com/[GITHUB USER]/[REPOSITORY].git PetroSmart
cd PetroSmart
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
copy .env.example .env
```

If PowerShell refuses to run `Activate.ps1`, run this once and try again:

```
Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
```

Create a secret key and paste it after `DJANGO_SECRET_KEY=` in the `.env` file (open it with Notepad).
For your own computer, set `DJANGO_DEBUG=True` and leave `DATABASE_URL` empty to use SQLite:

```
python -c "from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())"
```

Create the database, optional demo data and the platform administrator:

```
python manage.py migrate
python manage.py seed_demo
python manage.py createsuperuser
```

## 6.2 Running the application

```
.\.venv\Scripts\Activate.ps1
python manage.py runserver
```

| Address | Who uses it |
|---|---|
| http://127.0.0.1:8000/ | Dealers and Managers (business app) |
| http://127.0.0.1:8000/platform-admin/ | Platform administrator (address set by `PETROSMART_ADMIN_PATH`) |

`seed_demo` creates two demo businesses with the users `ganesh.dealer`, `ganesh.manager`,
`omsai.dealer` and `omsai.manager` (password `PetroDemo@2026`). It works only while `DEBUG` is on,
and the demo password must never be used on a live server. Stop the server with **Ctrl + C**.

To run the automated tests: `python manage.py test`.

## 6.3 Putting the system online

- **Free demonstration:** the repository contains `render.yaml`, a Render Blueprint that creates the
  web service and a free PostgreSQL database and sets the environment variables
  (see `FREE_HOSTING.md`).
- **Paying dealers:** `DEPLOYMENT.md` describes an Ubuntu server with PostgreSQL, Gunicorn, Nginx,
  HTTPS and daily backups. The production settings have been checked with
  `manage.py check --deploy`; a full production deployment for paying customers has not yet been
  carried out.

In production `DJANGO_DEBUG` must be `False`, the secret key must be long and random, and
`DJANGO_ALLOWED_HOSTS` must name the real domain. The application refuses to start otherwise.

## 6.4 First set-up by the platform administrator

1. Log in at `/platform-admin/`.
2. Under **Subscription plans**, add a plan (for example "Starter": 1 outlet, 3 users).
3. Under **Businesses**, add the dealer's business, choose the plan and set the subscription end date.
4. Under **Users**, add the Dealer: username, a password of at least 10 characters, role **Dealer**,
   and the business.
5. Give the Dealer the web address and their username. The Dealer should change the password after
   the first login.

## 6.5 User guide: Dealer

The Dealer sees every menu. The **Set-up** and **Business** menus appear only for the Dealer.

**Setting up an outlet (once)**

1. **Outlets → Add outlet:** name, code, oil company, address; for bills also GSTIN, phone, email and
   bill terms.
2. **Fuel products:** MS and HSD are created for the business; add others if needed.
3. Open the outlet and add, in this order: **tanks** (product, capacity, starting stock, variation
   alert limit), **MPD / DU** (dispensers), **nozzles** (dispenser, product, tank, initial totalizer
   reading) and **shifts** (name, times, order in the day).
4. **Set price** for MS and HSD with the date from which each price applies. To change a price later,
   add a new price with a new effective date; old cards keep their old rate.
5. **Payments and expenses:** payment methods and expense categories.
6. **Suppliers** and **Credit customers** (credit limit, opening balance).
7. **Users → Add user:** create each Manager and tick the outlets they may work at.

**Daily control**

- **Overview:** today's MS and HSD sales (testing shown separately), money received, tank stock,
  recent deliveries, items needing attention and reminders. Choose an outlet or a date to filter.
- **Credit bills → New bill:** choose the customer, outlet and bill date, check the slips, and save.
  Use **Print / Save as PDF** for the customer. A wrong bill can be cancelled with a reason.
- **Credit customers:** each customer's ledger and balance; record payments or an adjustment with a
  reason.
- **Reports:** choose a report and period, then download it as PDF or Excel.
- **Operational summary** and **Audit log:** totals for a period, and who changed what and when.
- **Subscription:** the plan and its end date. A reminder appears 15 days before it ends.

## 6.6 User guide: Manager

The Manager sees only the outlets the Dealer assigned.

**Filling a Shift Card (end of each shift, for each DSM and MPD / DU)**

1. **Shift cards → New shift card.**
2. Choose the **date**, **shift** and **MPD / DU**. The pump rows load with the **opening** readings
   and **rates**, which cannot be changed.
3. Choose the **employee (DSM)** and type the cashier and helper names and times.
4. For each pump, type the **closing** reading and the **testing** litres. **Sale Ltr**, **Net Ltr**
   and **Sale Rs** are calculated at once.
5. In **Money Details**, type the number of notes of each value and the coins, and the amounts for
   bank card, company card, phone wallet and general credit.
6. Under **More**, add credit slips (customer, product, amount, vehicle number), lube or oil sales,
   customer receipts and expenses paid in cash by the DSM.
7. Check **Balance / Short** on the right, then click **Save** (or **Save & Print**).

If the meter rolled over or was replaced, tick *meter reset* on that pump and enter the readings before
and after the reset with a note.

**Fixing a card**

- The latest card can be edited or deleted.
- An older card shows **Correct readings**: type the right values and the reason. The next card's
  opening reading is updated automatically, and the old values stay in the history.
- After the day's tank stock is saved, that day's cards are locked; edit or delete the stock sheet
  first.

**Other daily work**

- **Tank stock → New stock sheet:** at the end of the day choose the date, click **Load tanks**, type each tank's dip
  reading and save. A large variation needs a note.
- **Fuel purchases → Record purchase:** type the invoice number and date and one line per tank
  (product, KL, rate per KL, delivery charges, VAT, cess, TCS as printed, and the litres actually
  received). One invoice can have MS and HSD lines. Saving adds the fuel to the tanks.
- **Fuel received:** fuel unloaded without an invoice entry.
- **Expenses → Record expense**, **Lubricants and shop**, **Employees** (attendance) and **Reminders**.
