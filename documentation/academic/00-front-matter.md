# PetroSmart: A Multi-Tenant Petrol Pump Management System

{{titlepage}}

A project report submitted in partial fulfilment of the requirements for the degree of

**Bachelor of Science (Computer Science)**

Submitted by: **[STUDENT NAME]**

Roll number: **[ROLL NUMBER]**

Under the guidance of: **[GUIDE NAME]**

Department of Computer Science

**[COLLEGE NAME]**

**[UNIVERSITY NAME]**

Academic year **[ACADEMIC YEAR]**

{{pagebreak}}

## Certificate

This is to certify that the project entitled **"PetroSmart: A Multi-Tenant Petrol Pump Management
System"** is a bonafide work carried out by **[STUDENT NAME]** (Roll No. **[ROLL NUMBER]**) of
T.Y. B.Sc. Computer Science, **[COLLEGE NAME]**, in partial fulfilment of the requirements for the
degree of Bachelor of Science (Computer Science) of **[UNIVERSITY NAME]** during the academic year
**[ACADEMIC YEAR]**.

Project Guide: ______________________ Head of Department: ______________________

External Examiner: ______________________ Date: ____________ College seal

{{pagebreak}}

## Declaration

I, **[STUDENT NAME]**, hereby declare that the project entitled **"PetroSmart: A Multi-Tenant
Petrol Pump Management System"** submitted to **[COLLEGE NAME]** is my original work, carried out
under the guidance of **[GUIDE NAME]**, and has not been submitted elsewhere for the award of any
degree or diploma.

Place: [PLACE] Date: [DATE] Signature: ______________________

## Acknowledgement

I thank my project guide **[GUIDE NAME]** for guidance throughout this project, the Head of the
Department of Computer Science and the staff of **[COLLEGE NAME]** for their support, and the petrol
pump dealers and managers whose working practices shaped the design of PetroSmart. I also thank my
family and friends for their encouragement.

[STUDENT NAME]

{{pagebreak}}

## Abstract

Petrol pumps in India still record most of their daily work in paper registers and spreadsheets:
nozzle totalizer readings, testing litres, cash and card collections, credit given to transport
customers, tanker deliveries and the daily dip of every underground tank. Errors in these records
hide fuel losses and cash shortages, and a dealer with several outlets cannot see the business as a
whole.

PetroSmart is a web-based, multi-tenant petrol pump management system built with Python and Django.
One installation serves many independent dealer businesses, and each business's data is isolated on
the server so that one dealer can never read another's records. Inside a business there are exactly
two roles: the Dealer, who owns and configures the business, and the Manager, who records daily
operations at assigned outlets.

The core of the system is the **Shift Card**, modelled on the paper card used at pumps. For each
attendant and dispenser (MPD/DU) per shift it records opening and closing totalizer readings and
testing litres, and calculates total nozzle delivery, net customer sales and sales value. Testing
litres are kept separate and are never counted as sales, but they are counted as fuel leaving the
tank. The card's money details (note counts, coins, bank card, company card, phone wallet, credit
slips, lube sales, customer receipts and expenses) produce the cash to be collected and the
shift's shortage or excess. The system also reconciles tank stock against dip readings, records
fuel purchase invoices with taxes, maintains credit customer ledgers and numbered credit bills,
tracks expenses, lubricant stock, employees and compliance reminders, and provides a dashboard,
charts, and reports exportable to PDF and Excel. Every change is written to an append-only audit
log.

PetroSmart was developed in nine phases with 232 automated tests, all passing at the time of
writing. It records data entered by people; it is not connected to dispensers, payment terminals
or oil-company systems, and it does not calculate GST.

**Keywords:** petrol pump management, fuel station, Django, multi-tenant SaaS, shift card, nozzle
totalizer, testing litres, tank stock reconciliation, credit billing, audit trail.

{{pagebreak}}

{{toc}}
