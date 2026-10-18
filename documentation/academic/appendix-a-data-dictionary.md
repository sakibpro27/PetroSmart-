# Appendix A: Data dictionary

*Generated from the Django models on 18 October 2026 by `documentation/tools/generate_schema_docs.py`. Do not edit by hand: rerun the script after changing a model.*

Every business table has a `business_id` column (the tenant). Views read tenant data only through `for_business(...)`, so one dealer can never see another's rows (see Chapter 4).

Abbreviations: PK primary key, FK foreign key. Decimal(p,s) has p digits in total, s after the decimal point. Litres use Decimal(12,2); money uses Decimal(14,2).

## A.1 Tenants: businesses, outlets and subscriptions

### Table A.1: `tenants_subscriptionplan` (subscription plan)

A plan sold by the SaaS provider (e.g. Starter, Multi-Outlet).

| Field | Type | Constraints | Description |
|---|---|---|---|
| `id` | BigInt (auto) | PK; Not null | ID |
| `name` | Varchar(60) | Unique; Not null | Name |
| `code` | Varchar(30) | Unique; Not null | Code |
| `max_outlets` | PositiveInteger | Not null; Default 1; ≥ 0 | Max outlets |
| `max_users` | PositiveInteger | Not null; Default 3; ≥ 0 | Max users |
| `price_per_year` | Decimal(10,2) | Not null; Default 0 | Price per year |
| `is_active` | Boolean | Not null; Default True | Inactive plans cannot be sold. |

### Table A.2: `tenants_business` (business)

A petrol pump dealer's business account. This is the tenant.

| Field | Type | Constraints | Description |
|---|---|---|---|
| `id` | BigInt (auto) | PK; Not null | ID |
| `name` | Varchar(150) | Not null | Name |
| `legal_name` | Varchar(200) | Not null | Legal name |
| `contact_phone` | Varchar(20) | Not null | Contact phone |
| `contact_email` | Varchar(254) | Not null | Contact email |
| `address` | Text | Not null | Address |
| `plan_id` | FK → tenants_subscriptionplan | Not null; On delete PROTECT | Plan |
| `status` | Varchar(10) | Not null; One of: TRIAL, ACTIVE, SUSPENDED, CANCELLED; Default 'TRIAL' | Status |
| `subscription_starts_on` | Date | Not null | Subscription starts on |
| `subscription_ends_on` | Date | Not null | Subscription ends on |
| `created_at` | DateTime | Not null | Created at |
| `updated_at` | DateTime | Not null | Updated at |

### Table A.3: `tenants_subscriptionrenewal` (subscription renewal)

A record of each renewal or plan change made by the platform administrator. Payment collection happens outside PetroSmart; this keeps the history.

| Field | Type | Constraints | Description |
|---|---|---|---|
| `id` | BigInt (auto) | PK; Not null | ID |
| `business_id` | FK → tenants_business | Not null; On delete PROTECT | Business |
| `plan_id` | FK → tenants_subscriptionplan | Not null; On delete PROTECT | Plan |
| `previous_end` | Date | Not null | Previous end |
| `new_end` | Date | Not null | New end |
| `amount` | Decimal(10,2) | Not null; Default 0 | Amount received (₹), if any. |
| `reference` | Varchar(100) | Not null | Invoice or payment reference. |
| `recorded_by_id` | FK → accounts_user | Not null; On delete PROTECT | Recorded by |
| `created_at` | DateTime | Not null | Created at |

### Table A.4: `tenants_outlet` (outlet)

A single petrol pump site belonging to a business.

| Field | Type | Constraints | Description |
|---|---|---|---|
| `id` | BigInt (auto) | PK; Not null | ID |
| `business_id` | FK → tenants_business | Not null; On delete PROTECT | Business |
| `name` | Varchar(150) | Not null | Name |
| `code` | Varchar(20) | Not null | Short code used on reports, e.g. OUT-01. |
| `address` | Text | Not null | Address |
| `oil_company` | Varchar(60) | Not null | e.g. IOCL, BPCL, HPCL, Nayara, Jio-bp. |
| `gstin` | Varchar(15) | Not null | GSTIN |
| `phone` | Varchar(20) | Not null | Mobile |
| `email` | Varchar(254) | Not null | Email |
| `bill_terms` | Text | Not null | Printed at the bottom of every credit bill. One condition per line. |
| `is_active` | Boolean | Not null; Default True | Is active |
| `created_at` | DateTime | Not null | Created at |

Table rules:
- Unique `unique_outlet_code_per_business` on (business, code)

## A.2 Accounts: users and roles

### Table A.5: `accounts_user` (user)

| Field | Type | Constraints | Description |
|---|---|---|---|
| `id` | BigInt (auto) | PK; Not null | ID |
| `password` | Varchar(128) | Not null | Password |
| `last_login` | DateTime | Null | Last login |
| `is_superuser` | Boolean | Not null; Default False | Designates that this user has all permissions without explicitly assigning them. |
| `username` | Varchar(150) | Unique; Not null | Required. 150 characters or fewer. Letters, digits and @/./+/-/_ only. |
| `first_name` | Varchar(150) | Not null | First name |
| `last_name` | Varchar(150) | Not null | Last name |
| `email` | Varchar(254) | Not null | Email address |
| `is_staff` | Boolean | Not null; Default False | Designates whether the user can log into this admin site. |
| `is_active` | Boolean | Not null; Default True | Designates whether this user should be treated as active. Unselect this instead of deleting accounts. |
| `date_joined` | DateTime | Not null | Date joined |
| `business_id` | FK → tenants_business | Null; On delete PROTECT | Leave empty only for platform administrators. |
| `role` | Varchar(10) | Not null; One of: DEALER, MANAGER | Role |
| `phone` | Varchar(20) | Not null | Phone |
| `groups` | Many-to-many → auth_group (table `accounts_user_groups`) |  | The groups this user belongs to. A user will get all permissions granted to each of their groups. |
| `user_permissions` | Many-to-many → auth_permission (table `accounts_user_user_permissions`) |  | Specific permissions for this user. |
| `assigned_outlets` | Many-to-many → tenants_outlet (table `accounts_user_assigned_outlets`) |  | Outlets a manager may work on. Dealers can access every outlet. |

Table rules:
- Check `business_user_or_platform_admin`

## A.3 Audit log

### Table A.6: `audit_auditlog` (audit log)

| Field | Type | Constraints | Description |
|---|---|---|---|
| `id` | BigInt (auto) | PK; Not null | ID |
| `business_id` | FK → tenants_business | Null; On delete PROTECT | Business |
| `user_id` | FK → accounts_user | Null; On delete SET_NULL | User |
| `action` | Varchar(20) | Not null; One of: LOGIN, LOGOUT, LOGIN_FAILED, CREATE, UPDATE, DELETE, SUBMIT, APPROVE, REJECT, CORRECT | Action |
| `object_type` | Varchar(100) | Not null | Object type |
| `object_id` | Varchar(64) | Not null | Object id |
| `description` | Varchar(255) | Not null | Description |
| `changes` | Text | Not null | Changes |
| `ip_address` | GenericIPAddress | Null | Ip address |
| `created_at` | DateTime | Not null | Created at |

## A.4 Outlet set-up: products, prices, dispensers, tanks, nozzles, shifts

### Table A.7: `station_fuelproduct` (fuel product)

| Field | Type | Constraints | Description |
|---|---|---|---|
| `id` | BigInt (auto) | PK; Not null | ID |
| `business_id` | FK → tenants_business | Not null; On delete PROTECT | Business |
| `category` | Varchar(3) | Not null; One of: MS, HSD | Category |
| `code` | Varchar(10) | Not null | Short code shown on reports, e.g. MS, HSD, XP95. |
| `name` | Varchar(60) | Not null | Name |
| `is_active` | Boolean | Not null; Default True | Is active |

Table rules:
- Unique `unique_product_code_per_business` on (business, code)

### Table A.8: `station_fuelprice` (fuel price)

| Field | Type | Constraints | Description |
|---|---|---|---|
| `id` | BigInt (auto) | PK; Not null | ID |
| `business_id` | FK → tenants_business | Not null; On delete PROTECT | Business |
| `outlet_id` | FK → tenants_outlet | Not null; On delete PROTECT | Outlet |
| `product_id` | FK → station_fuelproduct | Not null; On delete PROTECT | Product |
| `effective_from` | Date | Not null | The price applies from this date until a newer price starts. |
| `price_per_litre` | Decimal(7,2) | Not null; ≥ 0.01 | Selling price in ₹ per litre. |
| `created_at` | DateTime | Not null | Created at |

Table rules:
- Unique `unique_price_per_outlet_product_date` on (outlet, product, effective_from)

### Table A.9: `station_dispenser` (dispenser)

| Field | Type | Constraints | Description |
|---|---|---|---|
| `id` | BigInt (auto) | PK; Not null | ID |
| `business_id` | FK → tenants_business | Not null; On delete PROTECT | Business |
| `outlet_id` | FK → tenants_outlet | Not null; On delete PROTECT | Outlet |
| `code` | Varchar(20) | Not null | e.g. DU-1 |
| `make` | Varchar(60) | Not null | Manufacturer and model (optional). |
| `serial_number` | Varchar(60) | Not null | Serial number |
| `is_active` | Boolean | Not null; Default True | Is active |

Table rules:
- Unique `unique_dispenser_code_per_outlet` on (outlet, code)

### Table A.10: `station_tank` (tank)

| Field | Type | Constraints | Description |
|---|---|---|---|
| `id` | BigInt (auto) | PK; Not null | ID |
| `business_id` | FK → tenants_business | Not null; On delete PROTECT | Business |
| `outlet_id` | FK → tenants_outlet | Not null; On delete PROTECT | Outlet |
| `product_id` | FK → station_fuelproduct | Not null; On delete PROTECT | Product |
| `code` | Varchar(20) | Not null | e.g. T1. Must be unique within the outlet. |
| `capacity_litres` | Decimal(12,2) | Not null; ≥ 1 | Capacity litres |
| `starting_stock` | Decimal(12,2) | Not null; ≥ 0 | Litres in the tank at the end of the day before the first stock sheet. It becomes the first opening stock. |
| `variation_alert_litres` | Decimal(10,2) | Not null; Default Decimal('25.00'); ≥ 0 | A daily stock variation larger than this is flagged for the Dealer and needs an explanation. Set it to suit your tank and dip method. |
| `volume_basis` | Varchar(20) | Not null; One of: OBSERVED; Default 'OBSERVED' | Volume basis |
| `is_active` | Boolean | Not null; Default True | Is active |

Table rules:
- Unique `unique_tank_code_per_outlet` on (outlet, code)

### Table A.11: `station_nozzle` (nozzle)

| Field | Type | Constraints | Description |
|---|---|---|---|
| `id` | BigInt (auto) | PK; Not null | ID |
| `business_id` | FK → tenants_business | Not null; On delete PROTECT | Business |
| `outlet_id` | FK → tenants_outlet | Not null; On delete PROTECT | Outlet |
| `dispenser_id` | FK → station_dispenser | Not null; On delete PROTECT | Dispenser |
| `product_id` | FK → station_fuelproduct | Not null; On delete PROTECT | Product |
| `tank_id` | FK → station_tank | Null; On delete PROTECT | The tank this nozzle draws from. Needed for tank stock reconciliation. |
| `code` | Varchar(20) | Not null | e.g. N1. Must be unique within the outlet. |
| `initial_reading` | Decimal(12,2) | Not null; ≥ 0 | Totalizer reading in litres when this nozzle was set up in PetroSmart. It becomes the first opening reading in Daily Sales. |
| `is_active` | Boolean | Not null; Default True | Is active |

Table rules:
- Unique `unique_nozzle_code_per_outlet` on (outlet, code)

### Table A.12: `station_shift` (shift)

| Field | Type | Constraints | Description |
|---|---|---|---|
| `id` | BigInt (auto) | PK; Not null | ID |
| `business_id` | FK → tenants_business | Not null; On delete PROTECT | Business |
| `outlet_id` | FK → tenants_outlet | Not null; On delete PROTECT | Outlet |
| `name` | Varchar(40) | Not null | e.g. Morning, Evening, Night. |
| `start_time` | Time | Not null | Start time |
| `end_time` | Time | Not null | An end time earlier than the start means the shift runs past midnight. The same start and end time means a 24-hour shift. |
| `sort_order` | PositiveSmallInteger | Not null; Default 1; ≥ 0 | Order within the day; 1 comes first. |
| `is_active` | Boolean | Not null; Default True | Is active |

Table rules:
- Unique `unique_shift_name_per_outlet` on (outlet, name)

## A.5 Shift Cards (Daily Sales)

### Table A.13: `sales_dailysalessheet` (shift card)

| Field | Type | Constraints | Description |
|---|---|---|---|
| `id` | BigInt (auto) | PK; Not null | ID |
| `business_id` | FK → tenants_business | Not null; On delete PROTECT | Business |
| `outlet_id` | FK → tenants_outlet | Not null; On delete PROTECT | Outlet |
| `shift_id` | FK → station_shift | Not null; On delete PROTECT | Shift |
| `business_date` | Date | Not null | Business date |
| `shift_sort_order` | PositiveSmallInteger | Not null; ≥ 0 | Shift sort order |
| `dispenser_id` | FK → station_dispenser | Null; On delete PROTECT | MPD / DU |
| `employee_id` | FK → operations_employee | Null; On delete PROTECT | Employee (DSM) |
| `cashier_name` | Varchar(100) | Not null | Cashier name |
| `helper_name` | Varchar(100) | Not null | Helper name |
| `tanker_card` | Boolean | Not null; Default False | Tick for a tanker / bulk sale card. |
| `time_from` | Time | Null | Time from |
| `time_to` | Time | Null | Time to |
| `notes` | Varchar(255) | Not null | Remark |
| `general_credit` | Decimal(14,2) | Not null; Default Decimal('0'); ≥ 0 | Credit given to someone who is not a registered credit customer. |
| `general_credit_party` | Varchar(100) | Not null | General credit party |
| `bank_card` | Decimal(14,2) | Not null; Default Decimal('0'); ≥ 0 | Bank card |
| `company_card` | Decimal(14,2) | Not null; Default Decimal('0'); ≥ 0 | Oil-company fleet / loyalty cards. |
| `phone_wallet` | Decimal(14,2) | Not null; Default Decimal('0'); ≥ 0 | Phone wallet (UPI) |
| `notes_2000` | PositiveInteger | Not null; Default 0; ≥ 0 | Notes 2000 |
| `notes_500` | PositiveInteger | Not null; Default 0; ≥ 0 | Notes 500 |
| `notes_200` | PositiveInteger | Not null; Default 0; ≥ 0 | Notes 200 |
| `notes_100` | PositiveInteger | Not null; Default 0; ≥ 0 | Notes 100 |
| `notes_50` | PositiveInteger | Not null; Default 0; ≥ 0 | Notes 50 |
| `notes_20` | PositiveInteger | Not null; Default 0; ≥ 0 | Notes 20 |
| `notes_10` | PositiveInteger | Not null; Default 0; ≥ 0 | Notes 10 |
| `coins` | Decimal(14,2) | Not null; Default Decimal('0'); ≥ 0 | Coins |
| `entered_by_id` | FK → accounts_user | Not null; On delete PROTECT | Entered by |
| `updated_by_id` | FK → accounts_user | Null; On delete PROTECT | Updated by |
| `created_at` | DateTime | Not null | Created at |
| `updated_at` | DateTime | Not null | Updated at |

### Table A.14: `sales_dailysalesline` (daily sales line)

| Field | Type | Constraints | Description |
|---|---|---|---|
| `id` | BigInt (auto) | PK; Not null | ID |
| `business_id` | FK → tenants_business | Not null; On delete PROTECT | Business |
| `sheet_id` | FK → sales_dailysalessheet | Not null; On delete CASCADE | Sheet |
| `nozzle_id` | FK → station_nozzle | Not null; On delete PROTECT | Nozzle |
| `product_id` | FK → station_fuelproduct | Not null; On delete PROTECT | Product |
| `tank_id` | FK → station_tank | Null; On delete PROTECT | Tank |
| `opening_reading` | Decimal(12,2) | Not null; ≥ 0 | Opening reading |
| `closing_reading` | Decimal(12,2) | Null; ≥ 0 | Closing reading |
| `testing_litres` | Decimal(10,2) | Not null; Default Decimal('0'); ≥ 0 | Litres dispensed for delivery testing. Not counted as customer sales. |
| `price_per_litre` | Decimal(7,2) | Not null | Price per litre |
| `meter_reset` | Boolean | Not null; Default False | Tick only if the meter rolled over or was replaced during this shift. |
| `reading_before_reset` | Decimal(12,2) | Null; ≥ 0 | Reading before reset |
| `reading_after_reset` | Decimal(12,2) | Null; ≥ 0 | Reading after reset |
| `notes` | Varchar(255) | Not null | Notes |
| `total_delivery` | Decimal(12,2) | Null | Total delivery |
| `net_sales_litres` | Decimal(12,2) | Null | Net sales litres |
| `sales_value` | Decimal(14,2) | Null | Sales value |

Table rules:
- Unique `unique_nozzle_per_sales_sheet` on (sheet, nozzle)

### Table A.15: `sales_salescorrection` (sales correction)

A correction to an older Shift Card. Applied immediately when saved.

| Field | Type | Constraints | Description |
|---|---|---|---|
| `id` | BigInt (auto) | PK; Not null | ID |
| `business_id` | FK → tenants_business | Not null; On delete PROTECT | Business |
| `sheet_id` | FK → sales_dailysalessheet | Not null; On delete CASCADE | Sheet |
| `status` | Varchar(10) | Not null; One of: APPLIED; Default 'APPLIED' | Status |
| `reason` | Text | Not null | Reason |
| `requested_by_id` | FK → accounts_user | Not null; On delete PROTECT | Requested by |
| `requested_at` | DateTime | Not null | Requested at |

### Table A.16: `sales_correctionline` (correction line)

One nozzle's old and new values. Kept permanently as correction history.

| Field | Type | Constraints | Description |
|---|---|---|---|
| `id` | BigInt (auto) | PK; Not null | ID |
| `business_id` | FK → tenants_business | Not null; On delete PROTECT | Business |
| `correction_id` | FK → sales_salescorrection | Not null; On delete CASCADE | Correction |
| `line_id` | FK → sales_dailysalesline | Not null; On delete CASCADE | Line |
| `old_closing_reading` | Decimal(12,2) | Not null | Old closing reading |
| `new_closing_reading` | Decimal(12,2) | Not null | New closing reading |
| `old_testing_litres` | Decimal(10,2) | Not null | Old testing litres |
| `new_testing_litres` | Decimal(10,2) | Not null | New testing litres |
| `old_price_per_litre` | Decimal(7,2) | Not null | Old price per litre |
| `new_price_per_litre` | Decimal(7,2) | Not null | New price per litre |
| `next_line_id` | FK → sales_dailysalesline | Null; On delete SET_NULL | Next line |
| `next_old_opening` | Decimal(12,2) | Null | Next old opening |
| `next_new_opening` | Decimal(12,2) | Null | Next new opening |

## A.6 Tank stock

### Table A.17: `stock_tankreceipt` (tank receipt)

| Field | Type | Constraints | Description |
|---|---|---|---|
| `id` | BigInt (auto) | PK; Not null | ID |
| `business_id` | FK → tenants_business | Not null; On delete PROTECT | Business |
| `outlet_id` | FK → tenants_outlet | Not null; On delete PROTECT | Outlet |
| `tank_id` | FK → station_tank | Not null; On delete PROTECT | Tank |
| `received_on` | Date | Not null | Received on |
| `litres` | Decimal(12,2) | Not null; ≥ 0.01 | Litres unloaded into this tank, as measured at the outlet. |
| `reference` | Varchar(60) | Not null | Challan, invoice or tanker number. |
| `notes` | Varchar(255) | Not null | Notes |
| `volume_basis` | Varchar(20) | Not null; One of: OBSERVED; Default 'OBSERVED' | Volume basis |
| `entered_by_id` | FK → accounts_user | Not null; On delete PROTECT | Entered by |
| `created_at` | DateTime | Not null | Created at |
| `purchase_id` | FK → purchases_fuelpurchase | Null; On delete PROTECT | Purchase |

### Table A.18: `stock_stocksheet` (stock sheet)

Saved in one step with every tank's dip reading. There is no approval step.

| Field | Type | Constraints | Description |
|---|---|---|---|
| `id` | BigInt (auto) | PK; Not null | ID |
| `business_id` | FK → tenants_business | Not null; On delete PROTECT | Business |
| `outlet_id` | FK → tenants_outlet | Not null; On delete PROTECT | Outlet |
| `business_date` | Date | Not null | Business date |
| `notes` | Text | Not null | Notes |
| `entered_by_id` | FK → accounts_user | Not null; On delete PROTECT | Entered by |
| `updated_by_id` | FK → accounts_user | Null; On delete PROTECT | Updated by |
| `created_at` | DateTime | Not null | Created at |
| `updated_at` | DateTime | Not null | Updated at |

Table rules:
- Unique `unique_stock_sheet_per_outlet_date` on (outlet, business_date)

### Table A.19: `stock_stockline` (stock line)

| Field | Type | Constraints | Description |
|---|---|---|---|
| `id` | BigInt (auto) | PK; Not null | ID |
| `business_id` | FK → tenants_business | Not null; On delete PROTECT | Business |
| `sheet_id` | FK → stock_stocksheet | Not null; On delete CASCADE | Sheet |
| `tank_id` | FK → station_tank | Not null; On delete PROTECT | Tank |
| `product_id` | FK → station_fuelproduct | Not null; On delete PROTECT | Product |
| `opening_stock` | Decimal(12,2) | Not null | Opening stock |
| `fuel_received` | Decimal(12,2) | Not null; Default Decimal('0') | Fuel received |
| `total_delivery` | Decimal(12,2) | Not null; Default Decimal('0') | All fuel dispensed from this tank's nozzles, testing litres included. |
| `testing_litres` | Decimal(12,2) | Not null; Default Decimal('0') | Shown for information only. Already part of the total delivery. |
| `calculated_closing` | Decimal(12,2) | Not null | Calculated closing |
| `measured_closing` | Decimal(12,2) | Null; ≥ 0 | Measured closing |
| `variation` | Decimal(12,2) | Null | Variation |
| `notes` | Varchar(255) | Not null | Notes |

Table rules:
- Unique `unique_tank_per_stock_sheet` on (sheet, tank)

## A.7 Fuel purchases

### Table A.20: `purchases_supplier` (supplier)

| Field | Type | Constraints | Description |
|---|---|---|---|
| `id` | BigInt (auto) | PK; Not null | ID |
| `business_id` | FK → tenants_business | Not null; On delete PROTECT | Business |
| `name` | Varchar(150) | Not null | e.g. IOCL Terminal, Loni |
| `contact_person` | Varchar(100) | Not null | Contact person |
| `phone` | Varchar(20) | Not null | Phone |
| `email` | Varchar(254) | Not null | Email |
| `gstin` | Varchar(15) | Not null | Optional. Stored for reference only. |
| `address` | Text | Not null | Address |
| `is_active` | Boolean | Not null; Default True | Is active |

Table rules:
- Unique `unique_supplier_name_per_business` on (business, name)

### Table A.21: `purchases_fuelpurchase` (fuel purchase)

| Field | Type | Constraints | Description |
|---|---|---|---|
| `id` | BigInt (auto) | PK; Not null | ID |
| `business_id` | FK → tenants_business | Not null; On delete PROTECT | Business |
| `outlet_id` | FK → tenants_outlet | Not null; On delete PROTECT | Outlet |
| `supplier_id` | FK → purchases_supplier | Not null; On delete PROTECT | Company name |
| `invoice_number` | Varchar(50) | Not null | Invoice no. |
| `invoice_date` | Date | Not null | Invoice date |
| `delivery_date` | Date | Not null | The day the fuel was unloaded into the tanks. |
| `tanker_number` | Varchar(30) | Not null | Lorry / tanker registration number. |
| `round_up` | Boolean | Not null; Default False | Round the invoice total to the nearest rupee. |
| `round_off` | Decimal(14,2) | Not null; Default Decimal('0') | Round off |
| `invoice_amount` | Decimal(14,2) | Not null; ≥ 0 | Sum of the line totals plus round off (₹). |
| `notes` | Text | Not null | Remark |
| `entered_by_id` | FK → accounts_user | Not null; On delete PROTECT | Entered by |
| `created_at` | DateTime | Not null | Created at |
| `updated_at` | DateTime | Not null | Updated at |

Table rules:
- Unique `unique_invoice_per_supplier` on (business, supplier, invoice_number)

### Table A.22: `purchases_purchaseline` (purchase line)

One row of the invoice, e.g. HSD 12 KL at ₹88,450.00 per KL into tank T1.

| Field | Type | Constraints | Description |
|---|---|---|---|
| `id` | BigInt (auto) | PK; Not null | ID |
| `business_id` | FK → tenants_business | Not null; On delete PROTECT | Business |
| `purchase_id` | FK → purchases_fuelpurchase | Not null; On delete CASCADE | Purchase |
| `product_id` | FK → station_fuelproduct | Not null; On delete PROTECT | Item name |
| `tank_id` | FK → station_tank | Not null; On delete PROTECT | Tank |
| `invoiced_litres` | Decimal(12,2) | Not null; ≥ 0.01 | Quantity printed on the invoice, in litres (KL x 1,000). |
| `rate_per_kl` | Decimal(12,2) | Not null; ≥ 0.01 | Rate (₹ per KL) |
| `delivery_charges` | Decimal(14,2) | Not null; Default Decimal('0'); ≥ 0 | Dly taxable charges |
| `vat` | Decimal(14,2) | Not null; Default Decimal('0'); ≥ 0 | VAT |
| `cess` | Decimal(14,2) | Not null; Default Decimal('0'); ≥ 0 | Cess |
| `tcs` | Decimal(14,2) | Not null; Default Decimal('0'); ≥ 0 | TCS |
| `received_litres` | Decimal(12,2) | Null; ≥ 0.01 | Litres actually unloaded into the tank. Empty means the same as the invoice. |

Table rules:
- Unique `unique_tank_per_purchase` on (purchase, tank)

## A.8 Customer credit, bills and expenses

### Table A.23: `finance_paymentmethod` (payment method)

| Field | Type | Constraints | Description |
|---|---|---|---|
| `id` | BigInt (auto) | PK; Not null | ID |
| `business_id` | FK → tenants_business | Not null; On delete PROTECT | Business |
| `name` | Varchar(60) | Not null | Name |
| `kind` | Varchar(5) | Not null; One of: CASH, UPI, CARD, BANK, OTHER | Kind |
| `sort_order` | PositiveSmallInteger | Not null; Default 10; ≥ 0 | Sort order |
| `is_active` | Boolean | Not null; Default True | Is active |

Table rules:
- Unique `unique_payment_method_per_business` on (business, name)

### Table A.24: `finance_expensecategory` (expense category)

| Field | Type | Constraints | Description |
|---|---|---|---|
| `id` | BigInt (auto) | PK; Not null | ID |
| `business_id` | FK → tenants_business | Not null; On delete PROTECT | Business |
| `name` | Varchar(60) | Not null | Name |
| `is_active` | Boolean | Not null; Default True | Is active |

Table rules:
- Unique `unique_expense_category_per_business` on (business, name)

### Table A.25: `finance_creditcustomer` (credit customer)

| Field | Type | Constraints | Description |
|---|---|---|---|
| `id` | BigInt (auto) | PK; Not null | ID |
| `business_id` | FK → tenants_business | Not null; On delete PROTECT | Business |
| `name` | Varchar(150) | Not null | Name |
| `phone` | Varchar(20) | Not null | Phone |
| `vehicles` | Varchar(255) | Not null | Vehicle numbers, separated by commas. |
| `address` | Text | Not null | Address |
| `credit_limit` | Decimal(14,2) | Null; ≥ 0 | Leave empty for no limit. Exceeding it shows a warning. |
| `opening_balance` | Decimal(14,2) | Not null; Default Decimal('0'); ≥ 0 | Amount the customer already owed when added to PetroSmart. |
| `opening_balance_date` | Date | Not null | The date of the opening balance. |
| `is_active` | Boolean | Not null; Default True | Is active |

Table rules:
- Unique `unique_credit_customer_per_business` on (business, name)

### Table A.26: `finance_creditsale` (credit sale)

Fuel given on credit on a Shift Card. Increases what the customer owes.

| Field | Type | Constraints | Description |
|---|---|---|---|
| `id` | BigInt (auto) | PK; Not null | ID |
| `business_id` | FK → tenants_business | Not null; On delete PROTECT | Business |
| `sheet_id` | FK → sales_dailysalessheet | Not null; On delete PROTECT | Shift card |
| `outlet_id` | FK → tenants_outlet | Not null; On delete PROTECT | Outlet |
| `slip_no` | PositiveInteger | Not null; ≥ 0 | Slip no. |
| `customer_id` | FK → finance_creditcustomer | Not null; On delete PROTECT | Customer |
| `product_id` | FK → station_fuelproduct | Null; On delete PROTECT | Product |
| `rate` | Decimal(7,2) | Null | Rate (₹/L) |
| `litres` | Decimal(12,2) | Null | Qty (L) |
| `amount` | Decimal(14,2) | Not null; ≥ 0.01 | Amount |
| `vehicle_number` | Varchar(20) | Not null | Vehicle number |
| `bill_id` | FK → finance_creditbill | Null; On delete PROTECT | Bill |

Table rules:
- Unique `unique_slip_no_per_outlet` on (outlet, slip_no)

### Table A.27: `finance_customerpayment` (customer payment)

Money received from a credit customer. Reduces what they owe.

| Field | Type | Constraints | Description |
|---|---|---|---|
| `id` | BigInt (auto) | PK; Not null | ID |
| `business_id` | FK → tenants_business | Not null; On delete PROTECT | Business |
| `customer_id` | FK → finance_creditcustomer | Not null; On delete PROTECT | Customer |
| `outlet_id` | FK → tenants_outlet | Not null; On delete PROTECT | Outlet |
| `received_on` | Date | Not null | Received on |
| `amount` | Decimal(14,2) | Not null; ≥ 0.01 | Amount |
| `method_id` | FK → finance_paymentmethod | Not null; On delete PROTECT | Method |
| `reference` | Varchar(100) | Not null | Receipt, cheque or UTR number |
| `notes` | Varchar(255) | Not null | Notes |
| `entered_by_id` | FK → accounts_user | Not null; On delete PROTECT | Entered by |
| `created_at` | DateTime | Not null | Created at |
| `sheet_id` | FK → sales_dailysalessheet | Null; On delete PROTECT | Shift card |

### Table A.28: `finance_creditadjustment` (credit adjustment)

A Dealer's correction to a customer's balance (e.g. a discount or a write-off). Positive increases what the customer owes, negative reduces it.

| Field | Type | Constraints | Description |
|---|---|---|---|
| `id` | BigInt (auto) | PK; Not null | ID |
| `business_id` | FK → tenants_business | Not null; On delete PROTECT | Business |
| `customer_id` | FK → finance_creditcustomer | Not null; On delete PROTECT | Customer |
| `adjusted_on` | Date | Not null | Adjusted on |
| `amount` | Decimal(14,2) | Not null | Positive increases the balance; negative reduces it. |
| `reason` | Varchar(255) | Not null | Reason |
| `entered_by_id` | FK → accounts_user | Not null; On delete PROTECT | Entered by |
| `created_at` | DateTime | Not null | Created at |

### Table A.29: `finance_creditbill` (credit bill)

A bill to a credit customer for one outlet's credit slips, from the day after their previous bill up to the bill date. Bill numbers run in one series per outlet and are never reused, even when a bill is cancelled.

| Field | Type | Constraints | Description |
|---|---|---|---|
| `id` | BigInt (auto) | PK; Not null | ID |
| `business_id` | FK → tenants_business | Not null; On delete PROTECT | Business |
| `outlet_id` | FK → tenants_outlet | Not null; On delete PROTECT | Outlet |
| `customer_id` | FK → finance_creditcustomer | Not null; On delete PROTECT | Customer |
| `bill_no` | PositiveInteger | Not null; ≥ 0 | Bill no. |
| `bill_date` | Date | Not null | Slips up to and including this date are billed. |
| `period_from` | Date | Not null | Period from |
| `status` | Varchar(10) | Not null; One of: ISSUED, CANCELLED; Default 'ISSUED' | Status |
| `slips_total` | Decimal(14,2) | Not null | Slips total |
| `round_off` | Decimal(14,2) | Not null; Default Decimal('0') | Round off |
| `previous_balance` | Decimal(14,2) | Not null | Previous balance |
| `created_by_id` | FK → accounts_user | Not null; On delete PROTECT | Created by |
| `created_at` | DateTime | Not null | Created at |
| `cancelled_by_id` | FK → accounts_user | Null; On delete PROTECT | Cancelled by |
| `cancelled_at` | DateTime | Null | Cancelled at |
| `cancel_reason` | Varchar(255) | Not null | Cancel reason |

Table rules:
- Unique `unique_bill_no_per_outlet` on (outlet, bill_no)

### Table A.30: `finance_expense` (expense)

| Field | Type | Constraints | Description |
|---|---|---|---|
| `id` | BigInt (auto) | PK; Not null | ID |
| `business_id` | FK → tenants_business | Not null; On delete PROTECT | Business |
| `outlet_id` | FK → tenants_outlet | Not null; On delete PROTECT | Outlet |
| `expense_date` | Date | Not null | Expense date |
| `category_id` | FK → finance_expensecategory | Not null; On delete PROTECT | Category |
| `description` | Varchar(200) | Not null | Description |
| `amount` | Decimal(14,2) | Not null; ≥ 0.01 | Amount |
| `method_id` | FK → finance_paymentmethod | Not null; On delete PROTECT | Paid by |
| `paid_to` | Varchar(150) | Not null | Paid to |
| `reference` | Varchar(100) | Not null | Bill, voucher or UTR number |
| `notes` | Varchar(255) | Not null | Notes |
| `entered_by_id` | FK → accounts_user | Not null; On delete PROTECT | Entered by |
| `created_at` | DateTime | Not null | Created at |
| `sheet_id` | FK → sales_dailysalessheet | Null; On delete PROTECT | Shift card |

## A.9 Lubricant inventory, employees, reminders

### Table A.31: `operations_shopitem` (shop item)

| Field | Type | Constraints | Description |
|---|---|---|---|
| `id` | BigInt (auto) | PK; Not null | ID |
| `business_id` | FK → tenants_business | Not null; On delete PROTECT | Business |
| `name` | Varchar(120) | Not null | e.g. 20W-40 engine oil, 1 L can |
| `sku` | Varchar(40) | Not null | SKU / code |
| `category` | Varchar(10) | Not null; One of: LUBRICANT, COOLANT, SHOP, OTHER; Default 'LUBRICANT' | Category |
| `unit` | Varchar(5) | Not null; One of: PIECE, LITRE, PACK; Default 'PIECE' | Unit |
| `selling_price` | Decimal(10,2) | Not null; ≥ 0 | Default selling price per unit (₹). |
| `reorder_level` | Decimal(12,2) | Not null; Default Decimal('0'); ≥ 0 | Show a low-stock alert at or below this quantity. |
| `is_active` | Boolean | Not null; Default True | Is active |

Table rules:
- Unique `unique_shop_item_per_business` on (business, name)

### Table A.32: `operations_stockmovement` (stock movement)

Every change to an item's stock at an outlet. Stock on hand is the sum of the quantities: purchases and openings are positive, sales negative, adjustments either.

| Field | Type | Constraints | Description |
|---|---|---|---|
| `id` | BigInt (auto) | PK; Not null | ID |
| `business_id` | FK → tenants_business | Not null; On delete PROTECT | Business |
| `item_id` | FK → operations_shopitem | Not null; On delete PROTECT | Item |
| `outlet_id` | FK → tenants_outlet | Not null; On delete PROTECT | Outlet |
| `moved_on` | Date | Not null | Moved on |
| `kind` | Varchar(10) | Not null; One of: OPENING, PURCHASE, SALE, ADJUSTMENT | Kind |
| `quantity` | Decimal(12,2) | Not null | Positive adds to stock, negative removes it. |
| `unit_price` | Decimal(10,2) | Null; ≥ 0 | Unit price |
| `reference` | Varchar(60) | Not null | Reference |
| `notes` | Varchar(255) | Not null | Notes |
| `entered_by_id` | FK → accounts_user | Not null; On delete PROTECT | Entered by |
| `created_at` | DateTime | Not null | Created at |
| `sales_sheet_id` | FK → sales_dailysalessheet | Null; On delete PROTECT | Shift card |

### Table A.33: `operations_employee` (employee)

| Field | Type | Constraints | Description |
|---|---|---|---|
| `id` | BigInt (auto) | PK; Not null | ID |
| `business_id` | FK → tenants_business | Not null; On delete PROTECT | Business |
| `outlet_id` | FK → tenants_outlet | Not null; On delete PROTECT | Outlet |
| `name` | Varchar(120) | Not null | Name |
| `phone` | Varchar(20) | Not null | Phone |
| `job_title` | Varchar(60) | Not null; Default 'Pump attendant' | e.g. Pump attendant, Cashier, Helper |
| `joined_on` | Date | Null | Joined on |
| `is_active` | Boolean | Not null; Default True | Is active |
| `notes` | Varchar(255) | Not null | Notes |

### Table A.34: `operations_attendance` (attendance)

| Field | Type | Constraints | Description |
|---|---|---|---|
| `id` | BigInt (auto) | PK; Not null | ID |
| `business_id` | FK → tenants_business | Not null; On delete PROTECT | Business |
| `employee_id` | FK → operations_employee | Not null; On delete PROTECT | Employee |
| `shift_id` | FK → station_shift | Not null; On delete PROTECT | Shift |
| `work_date` | Date | Not null | Work date |
| `status` | Varchar(7) | Not null; One of: PRESENT, ABSENT, LEAVE, HALF; Default 'PRESENT' | Status |
| `duty` | Varchar(60) | Not null | e.g. Nozzles N1–N2, cash counter |
| `entered_by_id` | FK → accounts_user | Not null; On delete PROTECT | Entered by |

Table rules:
- Unique `unique_attendance_per_shift` on (employee, work_date, shift)

### Table A.35: `operations_reminder` (reminder)

| Field | Type | Constraints | Description |
|---|---|---|---|
| `id` | BigInt (auto) | PK; Not null | ID |
| `business_id` | FK → tenants_business | Not null; On delete PROTECT | Business |
| `outlet_id` | FK → tenants_outlet | Null; On delete PROTECT | Leave empty for a reminder that covers the whole business. |
| `title` | Varchar(150) | Not null | Title |
| `category` | Varchar(12) | Not null; One of: LICENCE, CALIBRATION, SAFETY, ENVIRONMENT, MAINTENANCE, TANK, INSURANCE, OTHER; Default 'OTHER' | Category |
| `due_date` | Date | Not null | Due date |
| `repeat_months` | PositiveSmallInteger | Not null; Default 0; ≥ 0 | 0 = does not repeat. Otherwise the next reminder is created this many months after the due date when this one is marked done. |
| `notes` | Text | Not null | Authority, licence number, contact, documents needed, etc. |
| `completed_on` | Date | Null | Completed on |
| `completed_by_id` | FK → accounts_user | Null; On delete PROTECT | Completed by |
| `completion_note` | Varchar(255) | Not null | Completion note |
| `created_at` | DateTime | Not null | Created at |
