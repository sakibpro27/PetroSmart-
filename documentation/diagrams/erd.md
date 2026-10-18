# Entity Relationship Diagrams

*Generated from the Django models on 18 October 2026 by `documentation/tools/generate_schema_docs.py`.*

Mermaid `erDiagram` notation: `||--o{` means one to many. Only primary keys, foreign keys and a few key columns are shown; Appendix A lists every column. The `business` link that every table has is shown only in Figure 3.8a to keep the other diagrams readable.

To turn a diagram into an image for the report: paste it into <https://mermaid.live> and use *Actions → PNG*, or preview it in VS Code with a Mermaid extension.

## Figure 3.8a: Tenants, users and outlet set-up

```mermaid
erDiagram
    accounts_user {
        BigAuto id PK
        bigint business_id FK
    }
    station_dispenser {
        BigAuto id PK
        bigint business_id FK
        bigint outlet_id FK
        Char code
    }
    station_fuelprice {
        BigAuto id PK
        bigint business_id FK
        bigint outlet_id FK
        bigint product_id FK
    }
    station_fuelproduct {
        BigAuto id PK
        bigint business_id FK
        Char code
        Char name
    }
    station_nozzle {
        BigAuto id PK
        bigint business_id FK
        bigint outlet_id FK
        bigint dispenser_id FK
        bigint product_id FK
        bigint tank_id FK
        Char code
    }
    station_shift {
        BigAuto id PK
        bigint business_id FK
        bigint outlet_id FK
        Char name
    }
    station_tank {
        BigAuto id PK
        bigint business_id FK
        bigint outlet_id FK
        bigint product_id FK
        Char code
    }
    tenants_business {
        BigAuto id PK
        Char name
        bigint plan_id FK
        Char status
    }
    tenants_outlet {
        BigAuto id PK
        bigint business_id FK
        Char name
        Char code
    }
    tenants_subscriptionplan {
        BigAuto id PK
        Char name
        Slug code
    }
    tenants_subscriptionrenewal {
        BigAuto id PK
        bigint business_id FK
        bigint plan_id FK
        bigint recorded_by_id FK
    }
    tenants_business o|--o{ accounts_user : "business"
    tenants_business ||--o{ station_dispenser : "business"
    tenants_outlet ||--o{ station_dispenser : "outlet"
    tenants_business ||--o{ station_fuelprice : "business"
    tenants_outlet ||--o{ station_fuelprice : "outlet"
    station_fuelproduct ||--o{ station_fuelprice : "product"
    tenants_business ||--o{ station_fuelproduct : "business"
    tenants_business ||--o{ station_nozzle : "business"
    tenants_outlet ||--o{ station_nozzle : "outlet"
    station_dispenser ||--o{ station_nozzle : "dispenser"
    station_fuelproduct ||--o{ station_nozzle : "product"
    station_tank o|--o{ station_nozzle : "tank"
    tenants_business ||--o{ station_shift : "business"
    tenants_outlet ||--o{ station_shift : "outlet"
    tenants_business ||--o{ station_tank : "business"
    tenants_outlet ||--o{ station_tank : "outlet"
    station_fuelproduct ||--o{ station_tank : "product"
    tenants_subscriptionplan ||--o{ tenants_business : "plan"
    tenants_business ||--o{ tenants_outlet : "business"
    tenants_business ||--o{ tenants_subscriptionrenewal : "business"
    tenants_subscriptionplan ||--o{ tenants_subscriptionrenewal : "plan"
    accounts_user ||--o{ tenants_subscriptionrenewal : "recorded_by"
```

## Figure 3.8b: Shift Cards, stock and purchases

```mermaid
erDiagram
    purchases_fuelpurchase {
        BigAuto id PK
        bigint business_id FK
        bigint outlet_id FK
        bigint supplier_id FK
        Char invoice_number
        bigint entered_by_id FK
    }
    purchases_purchaseline {
        BigAuto id PK
        bigint business_id FK
        bigint purchase_id FK
        bigint product_id FK
        bigint tank_id FK
    }
    purchases_supplier {
        BigAuto id PK
        bigint business_id FK
        Char name
    }
    sales_correctionline {
        BigAuto id PK
        bigint business_id FK
        bigint correction_id FK
        bigint line_id FK
        bigint next_line_id FK
    }
    sales_dailysalesline {
        BigAuto id PK
        bigint business_id FK
        bigint sheet_id FK
        bigint nozzle_id FK
        bigint product_id FK
        bigint tank_id FK
    }
    sales_dailysalessheet {
        BigAuto id PK
        bigint business_id FK
        bigint outlet_id FK
        bigint shift_id FK
        Date business_date
        bigint dispenser_id FK
        bigint employee_id FK
        bigint entered_by_id FK
        bigint updated_by_id FK
    }
    sales_salescorrection {
        BigAuto id PK
        bigint business_id FK
        bigint sheet_id FK
        Char status
        bigint requested_by_id FK
    }
    stock_stockline {
        BigAuto id PK
        bigint business_id FK
        bigint sheet_id FK
        bigint tank_id FK
        bigint product_id FK
    }
    stock_stocksheet {
        BigAuto id PK
        bigint business_id FK
        bigint outlet_id FK
        Date business_date
        bigint entered_by_id FK
        bigint updated_by_id FK
    }
    stock_tankreceipt {
        BigAuto id PK
        bigint business_id FK
        bigint outlet_id FK
        bigint tank_id FK
        bigint entered_by_id FK
        bigint purchase_id FK
    }
    purchases_supplier ||--o{ purchases_fuelpurchase : "supplier"
    purchases_fuelpurchase ||--o{ purchases_purchaseline : "purchase"
    sales_salescorrection ||--o{ sales_correctionline : "correction"
    sales_dailysalesline ||--o{ sales_correctionline : "line"
    sales_dailysalesline o|--o{ sales_correctionline : "next_line"
    sales_dailysalessheet ||--o{ sales_dailysalesline : "sheet"
    sales_dailysalessheet ||--o{ sales_salescorrection : "sheet"
    stock_stocksheet ||--o{ stock_stockline : "sheet"
    purchases_fuelpurchase o|--o{ stock_tankreceipt : "purchase"
```

## Figure 3.8c: Credit, expenses and operations

```mermaid
erDiagram
    finance_creditadjustment {
        BigAuto id PK
        bigint business_id FK
        bigint customer_id FK
        bigint entered_by_id FK
    }
    finance_creditbill {
        BigAuto id PK
        bigint business_id FK
        bigint outlet_id FK
        bigint customer_id FK
        Char status
        bigint created_by_id FK
        bigint cancelled_by_id FK
    }
    finance_creditcustomer {
        BigAuto id PK
        bigint business_id FK
        Char name
    }
    finance_creditsale {
        BigAuto id PK
        bigint business_id FK
        bigint sheet_id FK
        bigint outlet_id FK
        bigint customer_id FK
        bigint product_id FK
        bigint bill_id FK
    }
    finance_customerpayment {
        BigAuto id PK
        bigint business_id FK
        bigint customer_id FK
        bigint outlet_id FK
        bigint method_id FK
        bigint entered_by_id FK
        bigint sheet_id FK
    }
    finance_expense {
        BigAuto id PK
        bigint business_id FK
        bigint outlet_id FK
        bigint category_id FK
        bigint method_id FK
        bigint entered_by_id FK
        bigint sheet_id FK
    }
    finance_expensecategory {
        BigAuto id PK
        bigint business_id FK
        Char name
    }
    finance_paymentmethod {
        BigAuto id PK
        bigint business_id FK
        Char name
    }
    operations_attendance {
        BigAuto id PK
        bigint business_id FK
        bigint employee_id FK
        bigint shift_id FK
        Char status
        bigint entered_by_id FK
    }
    operations_employee {
        BigAuto id PK
        bigint business_id FK
        bigint outlet_id FK
        Char name
    }
    operations_reminder {
        BigAuto id PK
        bigint business_id FK
        bigint outlet_id FK
        bigint completed_by_id FK
    }
    operations_shopitem {
        BigAuto id PK
        bigint business_id FK
        Char name
    }
    operations_stockmovement {
        BigAuto id PK
        bigint business_id FK
        bigint item_id FK
        bigint outlet_id FK
        bigint entered_by_id FK
        bigint sales_sheet_id FK
    }
    finance_creditcustomer ||--o{ finance_creditadjustment : "customer"
    finance_creditcustomer ||--o{ finance_creditbill : "customer"
    finance_creditcustomer ||--o{ finance_creditsale : "customer"
    finance_creditbill o|--o{ finance_creditsale : "bill"
    finance_creditcustomer ||--o{ finance_customerpayment : "customer"
    finance_paymentmethod ||--o{ finance_customerpayment : "method"
    finance_expensecategory ||--o{ finance_expense : "category"
    finance_paymentmethod ||--o{ finance_expense : "method"
    operations_employee ||--o{ operations_attendance : "employee"
    operations_shopitem ||--o{ operations_stockmovement : "item"
```
