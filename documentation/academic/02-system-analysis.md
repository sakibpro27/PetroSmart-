# Chapter 2: System Analysis

## 2.1 Existing system

At a typical outlet the daily work is recorded by hand:

- a **shift card** or register page per attendant with each nozzle's opening and closing readings,
  testing litres and the money handed over;
- a **dip register** with each tank's measured stock;
- a **credit register** of slips signed by transport customers, from which monthly bills are written;
- invoice files from the oil company, and expense vouchers;
- spreadsheets that the dealer or accountant fills in later from these papers.

## 2.2 Limitations of the existing system

| Problem | Effect |
|---|---|
| Sales are calculated by hand for every nozzle and shift | Arithmetic mistakes; testing litres are sometimes counted as sales, or subtracted twice from stock |
| Readings are not linked from shift to shift | A wrong opening reading goes unnoticed and shifts sales between shifts |
| Cash shortages are worked out at the end of the day | It is hard to tell which attendant or shift was short |
| Tank stock is known only at the daily dip | Losses and leaks are noticed late |
| Credit balances live in a separate register | Bills are slow to prepare and balances disagree |
| Papers can be corrected without a trace | Figures cannot be audited |
| Each outlet keeps its own papers | A dealer with several outlets has no combined view |

## 2.3 Proposed system

PetroSmart replaces the registers with one web application:

- The **Shift Card** screen looks like the paper card. Opening readings and rates are filled in by
  the system; the attendant's closing readings, testing litres and money details are entered once,
  and every total is calculated.
- Each tank's **stock now** updates as soon as a card or a fuel receipt is saved, and the **daily
  stock sheet** compares it with the dip.
- **Credit slips** entered on cards feed the customer's **ledger**, and **credit bills** are numbered
  and printed from them.
- **Purchases** record each invoice line (product, tank, KL, rate, taxes as printed) and the litres
  actually received.
- The **dashboard** and **reports** show all outlets together, with PDF and Excel export.
- An **audit log** records who changed what and when, and records can never be silently altered.
- One online installation serves many dealers, each seeing only their own data.

## 2.4 Feasibility study

### 2.4.1 Technical feasibility

The system uses mature, free and widely documented tools: Python 3.13, Django 5.2, Bootstrap 5,
Chart.js, openpyxl and ReportLab. It runs on an ordinary Windows PC for development (with SQLite) and
on a small Linux server with PostgreSQL for production. No special hardware is needed at the pump: a
phone, tablet or PC with a browser is enough. Technical feasibility is therefore high.

### 2.4.2 Operational feasibility

The screens follow the existing paper workflow (Shift Card, dip sheet, credit slips and bills), so
pump staff do not have to learn a new way of working. The system has only two business roles, and
the Manager sees only their assigned outlets. Operational feasibility is high, provided staff are
trained to enter the cards at the end of every shift.

### 2.4.3 Economic feasibility

The software stack has no licence cost. The running costs are hosting and a domain. For a
demonstration, free hosting plans are enough (see `FREE_HOSTING.md` and `render.yaml`). For paying
dealers, a small paid server with PostgreSQL and backups is needed; its cost depends on the provider
and is shared by every dealer on the installation, which is the advantage of the multi-tenant
design. The figures below are assumptions for planning, not measured costs:

| Item | Assumption |
|---|---|
| Development | Student project time; open-source tools only |
| Hosting for production | One small virtual server and a managed or self-hosted PostgreSQL, shared by all dealers |
| Price to a dealer | A yearly subscription per business (plans and renewals are built in, Chapter 4) |

Because one server serves many businesses, the cost per dealer falls as more dealers subscribe.

## 2.5 Software Requirements Specification (SRS)

### 2.5.1 Purpose and users

The SRS describes what PetroSmart must do. It has three kinds of user:

| User class | Description |
|---|---|
| **Dealer** | Owner of a petrol pump business. Sets up outlets, users, prices and settings; sees everything in the business; also does daily entry if needed. |
| **Manager** | Works at one or more outlets assigned by the Dealer. Fills Shift Cards and daily stock, records purchases, payments, expenses, lube stock and attendance. |
| **Platform administrator** | The software provider. Creates businesses, plans and Dealer accounts, and renews subscriptions. Uses a separate admin site and never sees the business screens. |

### 2.5.2 Functional requirements

Status column: **Implemented** means the feature exists in the code and is covered by the automated
tests listed in Appendix B.

| ID | Requirement | Status |
|---|---|---|
| FR-01 | Users log in with a username and password, log out, and reset a forgotten password by email. | Implemented |
| FR-02 | Each user belongs to exactly one business, as Dealer or Manager. Platform administrators belong to no business. | Implemented |
| FR-03 | A user can only read or change data of their own business; a Manager only of assigned outlets. | Implemented |
| FR-04 | The Dealer manages the business profile, outlets (within the plan's limit), users (within the plan's limit), fuel products and selling prices with effective dates. | Implemented |
| FR-05 | The Dealer manages dispensers (MPD/DU), tanks, nozzles (each linked to a tank) and shifts per outlet. | Implemented |
| FR-06 | A Shift Card is created per date, shift and MPD/DU, with the employee (DSM), cashier, helper and times. | Implemented |
| FR-07 | The card's opening readings come from each nozzle's previous closing reading, and the rate from the price in force on the card's date. Neither can be typed over. | Implemented |
| FR-08 | For each nozzle: Sale Ltr = closing − opening; Net Ltr = Sale Ltr − testing; Sale Rs = Net Ltr × rate. Testing litres must be between 0 and Sale Ltr. | Implemented |
| FR-09 | A meter rollover or replacement can be recorded with the readings before and after the reset and a written reason. | Implemented |
| FR-10 | The card records note counts, coins, bank card, company card, phone wallet, general credit, credit slips, lube sales, customer receipts and DSM expenses, and calculates cash to be collected and the balance (short or excess). | Implemented |
| FR-11 | Saving a card updates customer ledgers (credit slips, receipts), lube stock and expenses at once. | Implemented |
| FR-12 | Only the latest card for its nozzles can be edited or deleted; an older card is fixed by a correction that keeps the old values and updates the next card's opening reading. | Implemented |
| FR-13 | Each tank's stock now = last dip (or starting stock) + fuel received − total nozzle delivery since then. | Implemented |
| FR-14 | A daily stock sheet records each tank's dip reading; variation = measured − calculated; a variation beyond the tank's alert limit needs a note. | Implemented |
| FR-15 | A fuel purchase invoice records lines (product, tank, KL, rate per KL, delivery charges, VAT, cess, TCS as printed, litres received) and an optional round off. | Implemented |
| FR-16 | Credit customers have a credit limit, opening balance and a running ledger; the Dealer can make adjustments with a reason. | Implemented |
| FR-17 | Credit bills are numbered per outlet, cover unbilled slips up to the bill date, show the previous balance and net amount, and can be cancelled (Dealer only) with a reason. | Implemented |
| FR-18 | Expenses are recorded with category, payment method, outlet and date. | Implemented |
| FR-19 | The dashboard shows today's MS and HSD sales, testing litres, money received, tank stock, recent deliveries, exceptions and reminders, with charts. | Implemented |
| FR-20 | Reports (sales summary, nozzle readings, tank stock, purchases, shift card cash, expenses, credit outstanding) can be viewed and exported as PDF and Excel. | Implemented |
| FR-21 | Lubricant and shop items have stock per outlet; sales cannot exceed stock. | Implemented |
| FR-22 | Employees and their attendance per shift are recorded (employees do not log in). | Implemented |
| FR-23 | Compliance and maintenance reminders have due dates and optional repetition. | Implemented |
| FR-24 | Every important change and every export is recorded in an append-only audit log, which the Dealer can view and filter. | Implemented |
| FR-25 | The platform administrator manages plans and businesses, renews subscriptions, and a business whose subscription has lapsed cannot use the system. | Implemented |

### 2.5.3 Non-functional requirements

| ID | Category | Requirement |
|---|---|---|
| NFR-01 | Security | Passwords are stored as salted PBKDF2 hashes, never in plain text; minimum 10 characters, not common or entirely numeric. |
| NFR-02 | Security | Repeated failed logins lock that username (5 failures in 15 minutes) or address (20 failures). |
| NFR-03 | Security | All forms use CSRF protection; all input is validated on the server; the database is accessed only through the Django ORM. |
| NFR-04 | Privacy | Tenant isolation is enforced on the server and in database queries, not by hiding buttons. |
| NFR-05 | Integrity | Saving a card, stock sheet, purchase or bill happens in one database transaction: all or nothing. |
| NFR-06 | Accuracy | Litres and money use exact decimal numbers (two decimal places), never floating point; values are rounded half up to the paisa. |
| NFR-07 | Usability | Screens work on desktop, tablet and phone; figures use Indian grouping (₹1,23,456.78); colour is never the only signal of a status. |
| NFR-08 | Maintainability | Business rules live in service modules, formulas in one calculation module, and every rule has automated tests. |
| NFR-09 | Deployability | Secrets and settings come from environment variables; the app refuses to start in production with an unsafe secret key or host list. |

## 2.6 Hardware requirements

| Use | Minimum |
|---|---|
| Development PC | Windows 10/11, dual-core processor, 4 GB RAM, 2 GB free disk |
| Production server | Linux virtual server with 1 vCPU and 1 GB RAM, plus PostgreSQL |
| Users at the pump | Any phone, tablet or PC with a modern web browser and internet access; a printer for bills and Shift Cards |

## 2.7 Software requirements

| Software | Version used |
|---|---|
| Operating system (development) | Windows 10 Pro |
| Python | 3.13 |
| Django | 5.2.18 |
| Database | SQLite (development), PostgreSQL 17 (production; driver psycopg 3.2.13) |
| Front end | HTML5, CSS3, JavaScript, Bootstrap 5.3.3, Bootstrap Icons, Chart.js 4.4.4 |
| Reports | openpyxl 3.1.5 (Excel), ReportLab 4.2.5 (PDF) |
| Production server | Gunicorn 23.0.0, WhiteNoise 6.7.0 |
| Other libraries | dj-database-url, python-dotenv (see `requirements.txt`) |
| Version control | Git, GitHub |
| Browser | Current Chrome, Edge or Firefox |
