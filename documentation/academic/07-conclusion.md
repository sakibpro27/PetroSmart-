# Chapter 7: Limitations, Future Enhancements and Conclusion

## 7.1 Limitations

- **Manual data entry.** Totalizer readings, dip readings and payments are typed in by staff. The
  system checks them, but it cannot detect a reading that is wrong yet plausible.
- **No hardware integration.** It is not connected to dispensers, automatic tank gauges or payment
  terminals.
- **No temperature correction.** Volumes are not converted to a standard temperature, so part of a
  stock variation can come from temperature change.
- **Taxes as printed.** Purchase taxes are entered from the invoice; the system does not calculate
  VAT or GST and does not prepare GST returns or statutory accounts.
- **Online only.** A browser and an internet connection are needed; there is no offline mode or
  mobile app.
- **Employees do not log in.** Attendants (DSMs) appear on cards and attendance but have no accounts.
- **Subscription payments** are recorded by the platform administrator; there is no online payment
  gateway.
- **Production use.** The settings are prepared and checked for production, and a demonstration copy
  runs on free hosting, but the system has not yet been used by a paying dealer.

## 7.2 Future enhancements

1. Reading totalizers and tank levels directly from dispensers and automatic tank gauges.
2. Temperature-corrected volumes and density records at fuel receipt.
3. A mobile app with offline entry that synchronises when the connection returns.
4. Login accounts for attendants, so each DSM can see their own shift balance.
5. GST invoices for lubricant sales and export to accounting software such as Tally.
6. Online subscription payment and automatic renewal.
7. SMS or WhatsApp messages for credit bills, payment reminders and low tank stock.
8. Predicting when each tank needs a new load from its sales history.
9. Two-factor authentication for Dealer accounts.

## 7.3 Conclusion

PetroSmart meets the objectives set in Chapter 1. It records each shift on a Shift Card that follows
the paper card used at pumps, and calculates total nozzle delivery, net customer sales and sales value
with one fixed set of formulas. Testing litres are never counted as sales but are counted as fuel
leaving the tank. The card's money details give the cash to be collected and the shortage or excess
for every attendant and shift. Tank stock is updated as soon as sales and deliveries are saved and is
reconciled with the daily dip. Purchases, credit customers, numbered credit bills, expenses,
lubricants, employees and reminders complete the daily operation, and the dashboard and reports give
the Dealer a view of all outlets, exportable to PDF and Excel.

The most important design concern, keeping each dealer's data private on a shared installation, is
handled on the server: the tenant always comes from the logged-in user, every query is filtered by
business, and records of another tenant return "not found". Together with the two-role model, login
lockout, CSRF protection and the append-only audit log, this makes the system suitable to be offered
to several dealers from one installation.

The project was built in nine phases, and its 232 automated tests, covering formulas, workflows,
permissions and tenant isolation, all pass. Building it gave practical experience of requirement
analysis with real users, relational database design, the Django framework, secure web development,
automated testing and deployment.
