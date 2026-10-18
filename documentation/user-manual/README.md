# PetroSmart User Manual

This manual is for the people who use PetroSmart at the petrol pump: the **Dealer** (owner) and the
**Manager**. It explains each job step by step. No technical knowledge is needed.

## 1. Logging in

1. Open the PetroSmart address in Chrome, Edge or Firefox.
2. Type your **username** and **password** and click **Log in**.
3. Forgot your password? Click **Forgot your password?** and follow the email. A Dealer can also set a new
   password for a Manager under **Users**.

After 5 wrong passwords your account is blocked for 15 minutes. Wait, then try again.

Click your name at the top, then **Log out**, when you finish, especially on a shared computer.

## 2. What you see

The menu on the left is grouped:

| Group | Items | Who |
|---|---|---|
| Operations | Overview, Shift cards, Tank stock, Fuel purchases, Fuel received, Sales summary, Reports | Dealer and Manager |
| Money | Credit customers, Credit bills, Expenses, Operational summary (Dealer only) | Dealer and Manager |
| Outlet | Lubricants and shop, Employees, Reminders, Audit log (Dealer only) | Dealer and Manager |
| Set-up | Outlets, Fuel products, Payments and expenses, Suppliers, Users | Dealer only |
| Business | Business profile, Subscription | Dealer only |

A Manager only sees the outlets the Dealer gave them.

## 3. Manager: daily work

### 3.1 Shift Card (after every shift, for each DSM and MPD / DU)

1. Click **Shift cards → New shift card**.
2. Choose the **date**, **shift** and **MPD / DU**. The pumps appear with their **opening** reading
   and **rate**. You cannot change these: the opening is the last card's closing reading, and the
   rate is the price the Dealer set for that date.
3. Choose the **employee (DSM)**; type the cashier, helper and times.
4. For each pump type the **Closing** reading and the **Testing** litres.
   - **Sale Ltr** = Closing − Opening
   - **Net Ltr** = Sale Ltr − Testing
   - **Sale Rs** = Net Ltr × Rate
5. **Money Details:** type how many notes of ₹2000, 500, 200, 100, 50, 20 and 10, and the coins. Type
   the amounts of **Bank Card**, **Company Card**, **Phone Wallet** (UPI) and **Gen. Credit Sale**.
6. Click **More** to add:
   - **Credit Sale** slips: customer, product, amount, vehicle number;
   - **Lube / Oil Sale**: item, quantity, rate;
   - **Customer Receipt**: money a credit customer paid at the pump;
   - **Exp / Cash by DSM**: money the attendant spent from the cash.
7. Look at **Balance / Short**. ₹0.00 means it matches; a minus amount means the cash is short.
8. Click **Save**, or **Save & Print** for a paper copy.

**Testing litres** are fuel drawn to check the pump. They are not counted as a sale, but they are
taken out of the tank stock.

**Meter rolled over or replaced?** Open the pump's extra details, tick the meter reset box, type the
reading before and after the reset, and write what happened.

### 3.2 Fixing a mistake on a Shift Card

- **Latest card:** open it and click **Edit** or **Delete**.
- **Older card** (a later card already exists): click **Correct readings**, type the right numbers and
  the reason. PetroSmart moves the next card's opening reading for you and keeps the old figures in
  the history.
- **Locked card:** if the day's tank stock is already saved, edit or delete that stock sheet first.

### 3.3 Tank stock (end of the day)

1. **Tank stock → New stock sheet**, choose the outlet and date, click **Load tanks**.
2. For each tank type the **dip** (measured) stock in litres.
3. PetroSmart shows the **calculated** stock and the **variation** (dip − calculated).
4. If the variation is more than the tank's limit, write a note explaining it.
5. Save. Stock sheets are entered in date order.

The **stock now** figure on the Overview and Tank stock pages changes as soon as a card or a fuel
delivery is saved.

### 3.4 Fuel purchase (when a tanker arrives)

1. **Fuel purchases → Record purchase.**
2. Choose the supplier and type the invoice number and date.
3. Add one line per tank: product (MS or HSD), quantity in KL, rate per KL, delivery charges, VAT,
   cess and TCS **exactly as printed on the invoice**, and the litres actually unloaded.
4. Tick round up if the invoice rounds to the nearest rupee. Save.

The received litres are added to the tank stock.

### 3.5 Other jobs

- **Fuel received:** fuel unloaded that is not on a purchase invoice.
- **Expenses → Record expense:** date, category, amount, how it was paid.
- **Credit customers → Record payment:** money a customer paid at the office.
- **Lubricants and shop → Record movement:** stock in and stock adjustments. A sale cannot be more than the stock.
- **Employees → Shift attendance:** mark attendance for each shift.
- **Reminders:** licence renewals, calibration, maintenance; mark them done.

## 4. Dealer: set-up and control

The Dealer can do every Manager job at every outlet, plus the following.

### 4.1 First set-up

1. **Business profile:** name and contact details.
2. **Outlets → Add outlet:** name, code, oil company, address. For credit bills add the GSTIN, phone,
   email and bill terms.
3. Open the outlet and add:
   - **Tanks:** code, product, capacity, starting stock, variation alert limit;
   - **MPD / DU** (dispensers);
   - **Nozzles:** dispenser, product, tank and the current totalizer reading;
   - **Shifts:** name, start and end time, order in the day.
4. **Set price** for MS and HSD with the date from which the price starts.
5. **Payments and expenses:** payment methods and expense categories.
6. **Suppliers** and **Credit customers** (credit limit and opening balance).
7. **Users → Add user:** create Managers and tick their outlets.

### 4.2 Changing the MS or HSD price

Open the outlet, click **Set price**, choose the product, type the new price and the date it starts,
and save. Cards from that date use the new rate; older cards keep the old one.

### 4.3 Credit bills

1. **Credit bills → New bill.** Choose the customer, outlet and bill date.
2. Check the slips shown (all unbilled slips up to the bill date) and save.
3. Click **Print / Save as PDF** to give the bill to the customer.
4. A wrong bill can be cancelled with a reason; its slips become unbilled again.

### 4.4 Checking the business

- **Overview:** today's sales by product (testing shown separately), money received, tank stock,
  deliveries, things that need attention and reminders.
- **Reports:** sales summary, nozzle readings, tank stock, purchases, shift card cash, expenses, credit
  outstanding. Choose dates and click PDF or Excel.
- **Operational summary:** totals for a period.
- **Audit log:** who saved, changed or deleted what, and when.
- **Subscription:** plan and end date. A reminder appears when 15 days are left.

## 5. Good habits

- Enter every Shift Card at the end of the shift, and the tank stock at the end of the day.
- Never share your password. Each Manager should have their own login.
- Use **Correct readings** instead of deleting and re-entering old cards, so the history is kept.
- Explain every large stock variation in the note.
