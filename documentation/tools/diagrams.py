"""
The report's diagrams, defined once. build_report.py draws them into the PDF,
and `python documentation/tools/diagrams.py` writes the same diagrams as
editable Mermaid text to documentation/diagrams/uml-and-dfd.md.

Coordinates are in points (1/72 inch), with (0, 0) at the bottom-left; a
node's (x, y) is its bottom-left corner. The PDF builder fits each drawing to
the page, so only the relative positions matter.
"""

from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class Node:
    id: str
    label: str
    x: float
    y: float
    w: float = 120
    h: float = 36
    shape: str = "box"  # box, round, ellipse, actor, store, diamond, circle, terminal, class, boundary


@dataclass
class Edge:
    src: str
    dst: str
    label: str = ""
    dashed: bool = False
    arrow: bool = True
    via: list = field(default_factory=list)  # bend points [(x, y), ...]
    hollow: bool = False  # UML generalisation (hollow triangle)
    label_at: float = 0.5  # position of the label along the (longest) segment


@dataclass
class Diagram:
    name: str
    figure: str
    title: str
    width: float
    height: float
    nodes: list = field(default_factory=list)
    edges: list = field(default_factory=list)
    kind: str = "graph"  # graph or sequence
    participants: list = field(default_factory=list)  # sequence diagrams
    messages: list = field(default_factory=list)  # (from, to, label, dashed)
    note: str = ""


DIAGRAMS = {}


def add(diagram):
    DIAGRAMS[diagram.name] = diagram
    return diagram


def at(id, label, cx, cy, w, h, shape="box"):
    """A node given by its centre."""
    return Node(id, label, cx - w / 2, cy - h / 2, w, h, shape)


# --- Figure 3.1: system architecture ------------------------------------------------

add(Diagram(
    "architecture", "3.1", "System architecture (Django MVT, multi-tenant)", 470, 340,
    nodes=[
        at("browser", "Web browser\n(Dealer / Manager / Platform admin)", 140, 318, 190, 34, "round"),
        at("server", "Gunicorn (Linux) or runserver (Windows)\n+ WhiteNoise static files", 140, 265, 250, 34),
        at("mw", "Middleware: security, sessions, CSRF,\nlogin required, TenantMiddleware", 140, 212, 250, 34),
        at("urls", "URL routing (config/urls.py)", 140, 165, 250, 26),
        at("views", "Views (screens) + permission mixins\nBusinessMember / Dealer required", 140, 117, 250, 34),
        at("services", "Services (business rules, transactions,\naudit log) + calculations.py", 140, 64, 250, 34),
        at("orm", "Models + Django ORM\nfor_business(tenant) query filter", 140, 17, 250, 34),
        at("tpl", "Templates + Bootstrap 5\n+ Chart.js", 395, 165, 130, 34),
        at("exp", "Exports: openpyxl (Excel),\nReportLab (PDF)", 395, 64, 130, 34),
        at("db", "Database\nSQLite (development)\nPostgreSQL (production)", 395, 17, 130, 40, "store"),
    ],
    edges=[
        Edge("browser", "server", "HTTPS request"), Edge("server", "mw"), Edge("mw", "urls"), Edge("urls", "views"),
        Edge("views", "services"), Edge("services", "orm"), Edge("orm", "db", "SQL"),
        Edge("views", "tpl", "render", via=[(295, 125), (295, 165)]),
        Edge("views", "exp", "download", via=[(295, 109), (295, 64)]),
    ],
))

# --- Figure 3.2: use cases ------------------------------------------------------------

_UC = [
    ("uc_login", "Log in / reset password"),
    ("uc_card", "Fill shift card\n(readings, testing, money)"),
    ("uc_correct", "Correct an older shift card"),
    ("uc_stock", "Save daily tank stock (dip)"),
    ("uc_purchase", "Record fuel purchase invoice"),
    ("uc_credit", "Record credit payments,\nissue credit bills"),
    ("uc_expense", "Record expenses, lube stock,\nattendance"),
    ("uc_reports", "View dashboard, reports,\nexport PDF / Excel"),
    ("uc_setup", "Set up outlets, tanks, nozzles,\nshifts, prices"),
    ("uc_users", "Manage managers, employees,\ncredit customers, suppliers"),
    ("uc_audit", "View audit log, operational summary,\ncancel bills, adjust balances"),
    ("uc_tenants", "Manage businesses, plans,\nrenew subscriptions"),
]
_UC_Y = {uc: 488 - n * 42 for n, (uc, _) in enumerate(_UC)}

add(Diagram(
    "usecase", "3.2", "Use-case diagram", 470, 530,
    nodes=[Node("system", "PetroSmart", 135, 0, 200, 528, "boundary"),
           at("manager", "Manager", 45, 341, 50, 72, "actor"),
           at("dealer", "Dealer", 45, 110, 50, 72, "actor"),
           at("admin", "Platform\nadministrator", 425, 26, 70, 72, "actor")]
          + [at(uc, label, 235, _UC_Y[uc], 186, 34, "ellipse") for uc, label in _UC],
    edges=[Edge("manager", uc, arrow=False, via=[(141, _UC_Y[uc])]) for uc, _ in _UC[:8]]
          + [Edge("dealer", uc, arrow=False, via=[(141, _UC_Y[uc])]) for uc in ("uc_setup", "uc_users", "uc_audit")]
          + [Edge("dealer", "manager", hollow=True), Edge("admin", "uc_tenants", arrow=False)],
    note="The hollow arrow means the Dealer can do everything a Manager can, plus the set-up and control tasks. "
         "A Manager works only at the outlets the Dealer assigns. The platform administrator manages tenants "
         "only, on a separate admin site.",
))

# --- Figure 3.3: class diagram ---------------------------------------------------------


def _cls(id, label, cx, top, w=136):
    lines = label.split("\n")
    h = 8 + sum(5.4 if line == "—" else 8.9 for line in lines)
    return Node(id, label, cx - w / 2, top - h, w, h, "class")


_C0, _C1, _C2 = 70, 235, 400
_R1, _R2, _R3, _R4 = 470, 350, 230, 110

add(Diagram(
    "classes", "3.3", "Class diagram (main classes)", 470, 480,
    nodes=[
        _cls("FuelPrice", "FuelPrice\n—\nproduct, effective_from\nprice_per_litre\n—\nprice_on(date)", _C0, _R1),
        _cls("Outlet", "Outlet\n—\nname, code\noil_company, gstin", _C1, _R1),
        _cls("Business", "Business\n—\nname, plan, status\nsubscription_ends_on\n—\nhas_access()", _C2, _R1),
        _cls("Nozzle", "Nozzle\n—\ncode, initial_reading\ndispenser, product, tank", _C0, _R2),
        _cls("Tank", "Tank\n—\ncode, product, capacity\nstarting_stock\nvariation_alert_litres", _C1, _R2),
        _cls("User", "User\n—\nusername, role\n(DEALER / MANAGER)\nassigned_outlets\n—\naccessible_outlets()", _C2, _R2),
        _cls("Line", "DailySalesLine\n—\nopening, closing\ntesting_litres, rate\n—\nfigures(): delivery,\nnet sales, value", _C0, _R3),
        _cls("StockLine", "StockLine\n—\nopening, received\ndelivery, measured\n—\nvariation", _C1, _R3),
        _cls("Purchase", "FuelPurchase, PurchaseLine\n—\ninvoice, KL, rate per KL\ntaxes, received litres\n—\ntotal", _C2, _R3),
        _cls("Sheet", "DailySalesSheet (Shift Card)\n—\ndate, shift, MPD/DU, employee\nnote counts, cards, wallet\n—\ncash_collection", _C0, _R4),
        _cls("Credit", "CreditSale, CreditBill\n—\nslip no, amount, litres\nbill no, round off", _C1, _R4),
        _cls("Customer", "CreditCustomer\n—\ncredit_limit\nopening_balance\n—\nbalance()", _C2, _R4),
    ],
    edges=[
        Edge("Business", "Outlet", "1 .. *", arrow=False), Edge("Business", "User", "1 .. *", arrow=False),
        Edge("Outlet", "FuelPrice", "1 .. *", arrow=False), Edge("Outlet", "Tank", "1 .. *", arrow=False),
        Edge("Tank", "Nozzle", "1 .. *", arrow=False), Edge("Tank", "StockLine", "1 .. *", arrow=False),
        Edge("Tank", "Purchase", "1 .. *", arrow=False), Edge("Nozzle", "Line", "1 .. *", arrow=False),
        Edge("Sheet", "Line", "1 .. *", arrow=False), Edge("Sheet", "Credit", "1 .. *", arrow=False),
        Edge("Customer", "Credit", "1 .. *", arrow=False),
    ],
    note="Every class except User and Business inherits TenantOwnedModel, which adds the business (tenant) link "
         "and the for_business() query filter.",
))

# --- Figure 3.4: activity diagram -------------------------------------------------------

add(Diagram(
    "activity", "3.4", "Activity diagram: filling and saving a Shift Card", 470, 560,
    nodes=[
        Node("start", "", 225, 535, 20, 20, "circle"),
        Node("a1", "Manager chooses date, shift and MPD / DU", 135, 488, 200, 30, "round"),
        Node("a2", "System loads pump rows: opening = previous\nclosing, rate = price in force on the date", 125, 432, 220, 38, "round"),
        Node("d1", "Readings in\norder and\nprice set?", 185, 362, 100, 56, "diamond"),
        Node("e1", "Show reason;\ncard cannot\nstart", 360, 368, 100, 44, "round"),
        Node("a3", "Enter closing readings, testing litres,\nnote counts, cards, wallet, credit slips,\nlube, receipts, expenses", 125, 296, 220, 46, "round"),
        Node("a4", "Live totals on screen: Sale Ltr, Net Ltr,\nSale Rs, cash to collect, balance / short", 125, 238, 220, 38, "round"),
        Node("d2", "Server\nchecks\npass?", 185, 166, 100, 56, "diamond"),
        Node("e2", "Show errors;\nnothing saved", 360, 172, 100, 40, "round"),
        Node("a5", "Save in one transaction: card, lines, slips,\nreceipts, lube sales, expenses + audit log", 125, 100, 220, 40, "round"),
        Node("a6", "Tank 'stock now' drops by total delivery", 135, 50, 200, 28, "round"),
        Node("end", "", 225, 8, 20, 20, "terminal"),
    ],
    edges=[
        Edge("start", "a1"), Edge("a1", "a2"), Edge("a2", "d1"), Edge("d1", "e1", "no"), Edge("d1", "a3", "yes"),
        Edge("a3", "a4"), Edge("a4", "d2", "Save"), Edge("d2", "e2", "no"),
        Edge("e2", "a3", "correct and save again", dashed=True, via=[(410, 319)]),
        Edge("d2", "a5", "yes"), Edge("a5", "a6"), Edge("a6", "end"),
    ],
    note="Server checks: closing ≥ opening (unless a documented meter reset), 0 ≤ testing ≤ delivery, pump rows "
         "match the MPD / DU, enough lube in stock, the date's tank stock not yet saved.",
))

# --- Figure 3.5: sequence diagram -------------------------------------------------------

add(Diagram(
    "sequence", "3.5", "Sequence diagram: saving a Shift Card", 470, 400, kind="sequence",
    participants=["Manager", "Browser", "CardFormView", "services.save_card", "Database", "AuditLog"],
    messages=[
        ("Manager", "Browser", "Click Save", False),
        ("Browser", "CardFormView", "POST /sales/new/ (+ CSRF token)", False),
        ("CardFormView", "CardFormView", "Check login, role, outlet; validate forms", False),
        ("CardFormView", "services.save_card", "save_card(user, header, rows, ...)", False),
        ("services.save_card", "Database", "BEGIN; check order, stock lock, rows", False),
        ("services.save_card", "Database", "INSERT card, lines, slips, receipts ...", False),
        ("services.save_card", "AuditLog", "record(CREATE, figures)", False),
        ("services.save_card", "Database", "COMMIT", False),
        ("services.save_card", "CardFormView", "sheet, warnings", True),
        ("CardFormView", "Browser", "302 redirect to card + messages", True),
        ("Browser", "Manager", "Card page: totals, balance / short, stock now", True),
    ],
))

# --- Figures 3.6 and 3.7: data flow diagrams --------------------------------------------

add(Diagram(
    "dfd0", "3.6", "Data flow diagram, Level 0 (context diagram)", 470, 330,
    nodes=[
        at("p0", "0\nPetroSmart\nPetrol Pump\nManagement\nSystem", 235, 160, 130, 104, "circle"),
        at("manager", "Manager", 50, 290, 100, 36),
        at("customer", "Credit customer", 50, 160, 100, 36),
        at("supplier", "Oil company /\nsupplier", 50, 30, 100, 40),
        at("dealer", "Dealer", 420, 290, 100, 36),
        at("admin", "Platform\nadministrator", 420, 30, 100, 40),
    ],
    edges=[
        Edge("manager", "p0", "readings, testing, cash,\ncredit slips, dips", label_at=0.3),
        Edge("p0", "manager", "card totals,\nstock now", dashed=True, label_at=0.3),
        Edge("dealer", "p0", "set-up, prices,\nusers", label_at=0.3),
        Edge("p0", "dealer", "dashboard, reports,\nPDF / Excel, audit log", dashed=True, label_at=0.3),
        Edge("supplier", "p0", "invoice details", label_at=0.35),
        Edge("p0", "customer", "credit bills", label_at=0.3),
        Edge("customer", "p0", "payments", dashed=True, label_at=0.3),
        Edge("admin", "p0", "plans, businesses,\nrenewals", label_at=0.35),
    ],
))

_X0, _X1, _X2, _X3 = 55, 185, 315, 440
_YA, _YB, _YC, _YD, _YE, _YF = 480, 390, 300, 210, 120, 35

add(Diagram(
    "dfd1", "3.7", "Data flow diagram, Level 1", 500, 510,
    nodes=[
        at("user", "Dealer /\nManager", _X0, _YA, 90, 40),
        at("p1", "1.0\nAuthenticate,\nfind tenant", _X1, _YA, 96, 56, "circle"),
        at("d1", "D1 Users, businesses", _X2 + 45, _YA, 130, 26, "store"),
        at("p2", "2.0\nOutlet\nset-up", _X0, _YB, 96, 56, "circle"),
        at("d2", "D2 Outlets, tanks,\nnozzles, prices", _X1, _YB, 112, 34, "store"),
        at("p3", "3.0\nShift card\nentry", _X2, _YB, 96, 56, "circle"),
        at("p4", "4.0\nTank stock\nreconciliation", _X0, _YC, 100, 58, "circle"),
        at("d3", "D3 Shift cards\n+ lines", _X2, _YC, 112, 34, "store"),
        at("d5", "D5 Credit ledger,\nbills", _X3, _YC, 112, 34, "store"),
        at("d4", "D4 Stock sheets,\nfuel receipts", _X0, _YD, 112, 34, "store"),
        at("p5", "5.0\nFuel\npurchases", _X1, _YD, 96, 56, "circle"),
        at("p6", "6.0\nCredit and\nbilling", _X3, _YD, 96, 56, "circle"),
        at("supplier", "Supplier", _X1, _YE, 80, 30),
        at("p7", "7.0\nDashboard,\nreports", _X0, _YF, 96, 56, "circle"),
        at("d6", "D6 Audit log", _X1, _YF, 112, 26, "store"),
    ],
    edges=[
        Edge("user", "p1", "login"), Edge("d1", "p1", "user, role,\nbusiness"), Edge("p1", "p2", "Dealer"),
        Edge("p1", "p3", "Dealer /\nManager"), Edge("p2", "d2", "save"), Edge("d2", "p3", "opening,\nrate"),
        Edge("p3", "d3", "save card"), Edge("p3", "d5", "credit slips,\nreceipts"),
        Edge("d3", "p4", "total delivery"), Edge("p4", "d4", "dip, variation"), Edge("supplier", "p5", "invoice"),
        Edge("p5", "d4", "tank receipts"), Edge("d5", "p6", "unbilled slips"), Edge("p6", "d5", "bill"),
        Edge("d4", "p7", "stock"), Edge("d3", "p7", "sales", via=[(_X2, 75), (100, 75)], label_at=0.4), Edge("p7", "d6", "export logged"),
    ],
    note="Every process also writes to D6 (Audit log) when it changes data; only one such arrow is drawn.",
))

# --- Figure 3.8: simplified ERD --------------------------------------------------------

_E = [55, 180, 305, 430]
_ER = [300, 245, 190, 135, 80, 25]


def _ent(id, label, col, row):
    return at(id, label, _E[col], _ER[row], 108, 26)


add(Diagram(
    "erd", "3.8", "Entity relationship diagram (simplified; full ERDs in documentation/diagrams/erd.md)", 490, 320,
    nodes=[
        _ent("plan", "SubscriptionPlan", 0, 0), _ent("business", "Business (tenant)", 1, 0), _ent("user", "User", 2, 0),
        _ent("product", "FuelProduct", 0, 1), _ent("outlet", "Outlet", 1, 1),
        _ent("price", "FuelPrice", 0, 2), _ent("tank", "Tank", 1, 2), _ent("nozzle", "Nozzle", 2, 2),
        _ent("receipt", "TankReceipt", 0, 3), _ent("stock", "StockSheet /\nStockLine", 1, 3),
        _ent("line", "DailySalesLine", 2, 3), _ent("sheet", "DailySalesSheet", 3, 3),
        _ent("purchase", "FuelPurchase /\nPurchaseLine", 0, 4), _ent("customer", "CreditCustomer", 2, 4),
        _ent("credit", "CreditSale", 3, 4), _ent("bill", "CreditBill", 3, 5),
    ],
    edges=[
        Edge("plan", "business", "1:N", arrow=False), Edge("business", "user", "1:N", arrow=False),
        Edge("business", "outlet", "1:N", arrow=False), Edge("outlet", "tank", "1:N", arrow=False),
        Edge("product", "tank", "1:N", arrow=False), Edge("product", "price", "1:N", arrow=False),
        Edge("tank", "nozzle", "1:N", arrow=False), Edge("tank", "stock", "1:N", arrow=False),
        Edge("tank", "receipt", "1:N", arrow=False), Edge("purchase", "receipt", "1:N", arrow=False),
        Edge("nozzle", "line", "1:N", arrow=False), Edge("sheet", "line", "1:N", arrow=False),
        Edge("sheet", "credit", "1:N", arrow=False), Edge("customer", "credit", "1:N", arrow=False),
        Edge("bill", "credit", "1:N", arrow=False),
    ],
    note="1:N means one row on the first side has many rows on the other. Every entity except SubscriptionPlan "
         "also belongs to one Business; those links are left out for clarity.",
))


# --- Mermaid export ----------------------------------------------------------------------

def _mermaid_label(text):
    return text.replace("\n", "<br/>").replace('"', "'")


def to_mermaid(diagram):
    if diagram.kind == "sequence":
        lines = ["sequenceDiagram"]
        for p in diagram.participants:
            lines.append(f"    participant {p.replace('.', '_')} as {p}")
        for src, dst, label, dashed in diagram.messages:
            lines.append(f"    {src.replace('.', '_')}{'-->>' if dashed else '->>'}{dst.replace('.', '_')}: {label}")
        return "\n".join(lines)
    lines = ["flowchart TB"]
    shapes = {"box": ('["', '"]'), "round": ('("', '")'), "ellipse": ('(["', '"])'), "actor": ('[/"', '"/]'),
              "store": ('[("', '")]'), "diamond": ('{"', '"}'), "circle": ('(("', '"))'), "terminal": ('(("', '"))'),
              "class": ('["', '"]')}
    for node in diagram.nodes:
        if node.shape == "boundary":
            continue
        left, right = shapes[node.shape]
        label = node.label or ("start" if node.id == "start" else "end")
        lines.append(f"    {node.id}{left}{_mermaid_label(label)}{right}")
    for edge in diagram.edges:
        link = "-.->" if edge.dashed else ("-->" if edge.arrow else "---")
        text = edge.label or ("is a kind of" if edge.hollow else "")
        label = f'|"{_mermaid_label(text)}"|' if text else ""
        lines.append(f"    {edge.src} {link}{label} {edge.dst}")
    return "\n".join(lines)


def write_mermaid():
    out = Path(__file__).resolve().parents[1] / "diagrams" / "uml-and-dfd.md"
    parts = ["# UML diagrams and data flow diagrams (editable Mermaid)", "",
             "*Generated by `documentation/tools/diagrams.py`, which also draws these figures in the PDF report. "
             "Edit the diagrams in that file, then rerun it and `build_report.py`.*", ""]
    for d in DIAGRAMS.values():
        parts += [f"## Figure {d.figure}: {d.title}", "", "```mermaid", to_mermaid(d), "```", ""]
        if d.note:
            parts += [d.note, ""]
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(parts), encoding="utf-8")
    print(f"Wrote {len(DIAGRAMS)} diagrams to {out}")


if __name__ == "__main__":
    write_mermaid()
