"""
Creates demo data for local development:

* Two separate businesses (tenants), so you can check that neither can see
  the other's data.
* A Dealer and a Manager in each business.
* For every outlet: MS/HSD nozzles on two dispensers, three shifts and
  sample selling prices.

Usage:  python manage.py seed_demo
Refuses to run when DEBUG is off, so it can never touch a live database.
"""

from datetime import time, timedelta
from decimal import Decimal

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from accounts.models import User
from operations.models import Employee, ShopItem, StockMovement
from purchases.models import Supplier
from station.models import Dispenser, FuelPrice, FuelProduct, Nozzle, Shift, Tank, create_default_products
from tenants.models import Business, Outlet, SubscriptionPlan

DEMO_PASSWORD = "PetroDemo@2026"


class Command(BaseCommand):
    help = "Create demo businesses, outlets and users for local development."

    @transaction.atomic
    def handle(self, *args, **options):
        if not settings.DEBUG:
            raise CommandError("seed_demo only runs when DJANGO_DEBUG=True.")

        today = timezone.localdate()
        starter, _ = SubscriptionPlan.objects.get_or_create(
            code="starter", defaults={"name": "Starter", "max_outlets": 1, "max_users": 3, "price_per_year": 12000}
        )
        multi, _ = SubscriptionPlan.objects.get_or_create(
            code="multi-outlet",
            defaults={"name": "Multi-Outlet", "max_outlets": 5, "max_users": 15, "price_per_year": 36000},
        )

        tenants = [
            {
                "name": "Shree Ganesh Fuels",
                "plan": multi,
                "outlets": [("Ganesh Fuels - Highway", "SGF-01", "IOCL"), ("Ganesh Fuels - City", "SGF-02", "IOCL")],
                "dealer": "ganesh.dealer",
                "manager": "ganesh.manager",
            },
            {
                "name": "Om Sai Petroleum",
                "plan": starter,
                "outlets": [("Om Sai Petroleum", "OSP-01", "BPCL")],
                "dealer": "omsai.dealer",
                "manager": "omsai.manager",
            },
        ]

        for spec in tenants:
            business, _ = Business.objects.get_or_create(
                name=spec["name"],
                defaults={
                    "plan": spec["plan"],
                    "status": Business.Status.ACTIVE,
                    "subscription_starts_on": today,
                    "subscription_ends_on": today + timedelta(days=365),
                },
            )
            outlets = []
            for name, code, company in spec["outlets"]:
                outlet, _ = Outlet.objects.get_or_create(
                    business=business, code=code, defaults={"name": name, "oil_company": company}
                )
                outlets.append(outlet)

            dealer = self._user(spec["dealer"], business, User.Role.DEALER)
            manager = self._user(spec["manager"], business, User.Role.MANAGER)
            manager.assigned_outlets.set(outlets[:1])

            create_default_products(business)
            Supplier.objects.get_or_create(business=business, name=f"{spec['outlets'][0][2]} Terminal (demo)")
            for outlet in outlets:
                self._outlet_setup(business, outlet, today)
            self.stdout.write(f"  {business.name}: dealer '{dealer.username}', manager '{manager.username}'")

        self.stdout.write(self.style.SUCCESS(f"Demo data ready. Password for all demo users: {DEMO_PASSWORD}"))
        self.stdout.write("Demo prices are sample figures, not real oil-company prices.")

    def _outlet_setup(self, business, outlet, today):
        """Two tanks, two dispensers with an MS and an HSD nozzle each, three shifts, and prices."""
        products = {p.code: p for p in FuelProduct.objects.for_business(business)}
        tanks = {}
        for tank_code, product_code, starting in (("T1", "MS", "12000.00"), ("T2", "HSD", "15000.00")):
            tanks[product_code], _ = Tank.objects.get_or_create(
                business=business, outlet=outlet, code=tank_code,
                defaults={"product": products[product_code], "capacity_litres": Decimal("20000"),
                          "starting_stock": Decimal(starting)},
            )
        layout = [("DU-1", "N1", "MS", "125430.50"), ("DU-1", "N2", "HSD", "248910.00"),
                  ("DU-2", "N3", "MS", "98765.25"), ("DU-2", "N4", "HSD", "187300.75")]
        for dispenser_code, nozzle_code, product_code, reading in layout:
            dispenser, _ = Dispenser.objects.get_or_create(business=business, outlet=outlet, code=dispenser_code)
            nozzle, _ = Nozzle.objects.get_or_create(
                business=business, outlet=outlet, code=nozzle_code,
                defaults={"dispenser": dispenser, "product": products[product_code], "initial_reading": Decimal(reading)},
            )
            if nozzle.tank_id is None:
                nozzle.tank = tanks[product_code]
                nozzle.save(update_fields=["tank"])
        for order, (name, start, end) in enumerate(
            [("Morning", time(6), time(14)), ("Evening", time(14), time(22)), ("Night", time(22), time(6))], start=1
        ):
            Shift.objects.get_or_create(
                business=business, outlet=outlet, name=name,
                defaults={"start_time": start, "end_time": end, "sort_order": order},
            )
        for name, title in (("Ravi Patil", "Pump attendant"), ("Suresh Jadhav", "Pump attendant"),
                            ("Anita More", "Cashier")):
            Employee.objects.get_or_create(business=business, outlet=outlet, name=name, defaults={"job_title": title})
        oil, created = ShopItem.objects.get_or_create(
            business=business, name="20W-40 engine oil 1 L", defaults={"selling_price": Decimal("350"),
                                                                         "reorder_level": Decimal("5")})
        if not oil.movements.filter(outlet=outlet).exists():
            StockMovement.objects.create(business=business, item=oil, outlet=outlet, moved_on=today - timedelta(days=30),
                                         kind=StockMovement.Kind.OPENING, quantity=Decimal("24"),
                                         entered_by=business.users.filter(role=User.Role.DEALER).first())
        for product_code, price in (("MS", "100.00"), ("HSD", "90.00")):
            FuelPrice.objects.get_or_create(
                business=business, outlet=outlet, product=products[product_code],
                effective_from=today - timedelta(days=30), defaults={"price_per_litre": Decimal(price)},
            )

    def _user(self, username, business, role):
        user, created = User.objects.get_or_create(
            username=username, defaults={"business": business, "role": role}
        )
        if created:
            first, last = username.split(".")
            user.first_name, user.last_name = first.title(), last.title()
            user.set_password(DEMO_PASSWORD)
            user.save()
        return user
