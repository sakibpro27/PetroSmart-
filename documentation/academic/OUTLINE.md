# Project report outline

**PetroSmart: A Multi-Tenant Petrol Pump Management System**
T.Y. B.Sc. Computer Science project report

The numbers in brackets, such as (#6), refer to the item numbers in
[`../CHECKLIST.md`](../CHECKLIST.md). Each chapter will be written in its own
file in this folder, e.g. `01-introduction.md`.

---

## Front matter (`00-front-matter.md`)  (#1, #2)

- Title page: project title, `[STUDENT NAME]`, `[ROLL NUMBER]`,
  `[COLLEGE NAME]`, `[UNIVERSITY NAME]`, `[GUIDE NAME]`, `[ACADEMIC YEAR]`
- Certificate (from the college, with signature lines)
- Declaration by the student
- Acknowledgement
- Abstract (around 250 words) and keywords
- Table of contents, list of figures, list of tables

## Chapter 1: Introduction (`01-introduction.md`)  (#3)

1.1 Background: how a petrol pump's daily operation works
1.2 Problem statement
1.3 Motivation
1.4 Objectives
1.5 Scope of the project: what is included and what is not
1.6 Organisation of this report

## Chapter 2: System analysis (`02-system-analysis.md`)  (#4, #5, #6, #7)

2.1 Existing system: manual registers, spreadsheets, standalone software
2.2 Limitations of the existing system
2.3 Proposed system and its advantages
2.4 Feasibility study
  2.4.1 Technical feasibility
  2.4.2 Operational feasibility
  2.4.3 Economic feasibility
2.5 Software Requirements Specification
  2.5.1 Purpose and intended users
  2.5.2 User classes: Dealer, Manager, Platform Administrator
  2.5.3 Functional requirements, numbered FR-01, FR-02, and so on, grouped by module
  2.5.4 Non-functional requirements: security, privacy, performance, usability, maintainability, scalability
2.6 Hardware requirements: development machine, server, client devices
2.7 Software requirements: OS, Python, Django, database, browser, libraries

## Chapter 3: System design (`03-system-design.md`)  (#8 to #12)

3.1 System architecture: multi-tenant SaaS, Django MVT, layers
3.2 Module descriptions: one subsection per Django app or module
3.3 UML diagrams
  3.3.1 Use-case diagram
  3.3.2 Class diagram
  3.3.3 Activity diagram: Daily Sales entry and approval
  3.3.4 Sequence diagrams: login and tenant check; Daily Sales submit and approve
3.4 Data Flow Diagrams
  3.4.1 Level 0 (context diagram)
  3.4.2 Level 1
3.5 Entity Relationship Diagram
3.6 Database schema
3.7 Data dictionary: one table per database table (field, data type, size, constraints, description)

## Chapter 4: Implementation (`04-implementation.md`)  (#13, #14, #16)

4.1 Development environment and project structure
4.2 Algorithms and formulas
  4.2.1 Total nozzle delivery = Closing reading − Opening reading
  4.2.2 Net customer sales = Total nozzle delivery − Testing litres
  4.2.3 Customer sales value = Net customer sales × Selling price per litre
  4.2.4 Calculated closing stock = Opening stock + Fuel received − Total nozzle delivery
  4.2.5 Validation rules, and why testing litres are never subtracted twice
  4.2.6 Worked example: 460 L → 480 L, 2 L testing, ₹100/L
4.3 Security implementation
  4.3.1 Authentication and password hashing
  4.3.2 Authorization: Dealer and Manager permissions
  4.3.3 Multi-tenant data isolation
  4.3.4 CSRF protection, input validation, secret management
  4.3.5 Audit logging and protection of approved records
4.4 User interface: design system and screenshots, with an explanation for each screen

## Chapter 5: Testing (`05-testing.md`)  (#15)

5.1 Testing approach: unit, integration and manual testing
5.2 Test plan
5.3 Test cases table: ID, module, description, input, expected result, actual result, Pass/Fail
5.4 Automated test summary: the command used, run date, number of tests, result
5.5 Defects found and how they were fixed

## Chapter 6: Installation and user manual (`06-installation-and-user-guide.md`)  (#17, #18)

6.1 Installation on Windows
6.2 Configuration: the `.env` settings
6.3 Running the application
6.4 Dealer workflow (summary of `user-manual/`)
6.5 Manager workflow (summary of `user-manual/`)

## Chapter 7: Conclusion (`07-conclusion.md`)  (#19)

7.1 Limitations
7.2 Future enhancements
7.3 Conclusion

## References (`08-references.md`)  (#19)

Official documentation for Django, Python, PostgreSQL, Bootstrap and
Chart.js, plus any books or papers actually consulted. Use one citation style
throughout.

## Appendices (optional)

- A: Sample report outputs (PDF / Excel)
- B: Full automated test listing
