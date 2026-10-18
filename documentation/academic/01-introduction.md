# Chapter 1: Introduction

## 1.1 Background

A petrol pump (retail outlet) sells two main fuels: **MS** (motor spirit, petrol) and **HSD** (high-speed
diesel). Fuel is stored in underground tanks and sold through dispensing units (MPD/DU), each with
one or more **nozzles**. Every nozzle has a **totalizer**, a meter that only counts up. The litres a
nozzle delivered in a shift are therefore the closing reading minus the opening reading.

At regular intervals a small quantity is drawn from a nozzle into a certified measure to check that
it delivers accurately. These **testing litres** physically leave the tank, but they are not sold to
a customer. They must therefore be excluded from sales and revenue while still being counted in tank
stock.

At the end of each shift the attendant (DSM, dispensing sales man) hands over cash and the other
forms of payment: card slips, UPI (phone wallet), oil-company fleet cards and credit slips signed by
transport customers. The difference between what should have been collected and what was handed
over is the shift's shortage or excess. Once a day the manager measures each tank with a dip rod and
compares the result with the stock the records say should be there.

## 1.2 Problem statement

These records are normally kept in paper registers or personal spreadsheets. This makes it hard to:

- calculate every nozzle's sales correctly and consistently, especially keeping testing litres out of
  sales but inside stock;
- find out quickly which shift or attendant was short, and by how much;
- know how much fuel should be in each tank right now, and spot losses early;
- keep accurate running balances and bills for credit customers;
- see several outlets together, or trust that figures have not been changed after the fact.

## 1.3 Motivation

Software for fuel stations exists, but it is often installed on a single computer, built for a
single outlet, or linked to specific dispenser hardware. A small dealer needs something simple that
works in a browser, follows the way pump staff already work (the Shift Card), and can be offered to
many dealers from one online installation. That last requirement makes data privacy between
businesses the first design concern.

## 1.4 Objectives

1. Record each shift's nozzle readings and testing litres, and calculate total delivery, net
   customer sales and sales value with fixed, tested formulas.
2. Record how the shift's money was received, and calculate cash to be collected and the shortage
   or excess.
3. Keep tank stock up to date as sales and deliveries are entered, and reconcile it with daily dip
   readings.
4. Record fuel purchase invoices, including taxes as printed, and the litres actually received into
   each tank.
5. Maintain credit customer ledgers, numbered credit slips and credit bills.
6. Give the Dealer a dashboard, charts and reports exportable as PDF and Excel.
7. Serve many dealer businesses from one installation, with strict server-side data isolation, two
   roles (Dealer and Manager), and an audit log of every change.

## 1.5 Scope

**Included:** everything listed in the objectives, plus lubricant and shop inventory, employees and
shift attendance, compliance and maintenance reminders, subscription plans and renewals for the
software provider, and deployment guidance.

**Not included:** automatic reading of dispensers or tank gauges, connection to payment terminals or
oil-company portals, GST returns or statutory accounting, temperature correction of fuel volumes,
and offline or mobile app use. Chapter 7 lists these as limitations and future enhancements.

## 1.6 Organisation of this report

Chapter 2 analyses the existing system and specifies the requirements. Chapter 3 presents the design
(architecture, UML diagrams, data flow diagrams and database). Chapter 4 describes the implementation,
including the formulas and the security design. Chapter 5 covers testing. Chapter 6 explains
installation and use, and Chapter 7 concludes. Appendix A is the data dictionary, and Appendix B
lists every automated test with its result.
