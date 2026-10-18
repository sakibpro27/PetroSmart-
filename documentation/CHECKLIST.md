# Documentation checklist

Last updated: 19 October 2026. **All nine development phases are built, and the academic report is
written and built as a PDF.**
Automated tests: 232 run, 232 passed (`python documentation/tools/generate_test_report.py`, 19 Oct 2026).
Production check: `manage.py check --deploy` reports only the optional HSTS preload warning. A free
demonstration copy runs on Render with PostgreSQL; a production server for paying dealers has not
been set up yet.

**Still to do by the student:** fill in the placeholders in `academic/00-front-matter.md`
([STUDENT NAME], [ROLL NUMBER], [GUIDE NAME], [COLLEGE NAME], [UNIVERSITY NAME], [ACADEMIC YEAR],
[PLACE], [DATE]), the GitHub address in Chapter 6 and any extra references in `08-references.md`,
then rebuild the PDF.

**Status key**

| Status | Meaning |
|---|---|
| ✅ Final | Complete and checked against the code |
| ✏️ Needs student input | Written; placeholders to fill in |

## Academic report (`academic/`)

| # | Item | File | Status |
|---|---|---|---|
| 1 | Title page, certificate, declaration, acknowledgement | `00-front-matter.md` | ✏️ Needs student input |
| 2 | Abstract and keywords | `00-front-matter.md` | ✅ Final |
| 3 | Introduction, problem statement, motivation, objectives, scope | `01-introduction.md` | ✅ Final |
| 4 | Existing system, its limitations, proposed system | `02-system-analysis.md` | ✅ Final |
| 5 | Feasibility study | `02-system-analysis.md` | ✅ Final |
| 6 | SRS: functional and non-functional requirements | `02-system-analysis.md` | ✅ Final |
| 7 | Hardware and software requirements | `02-system-analysis.md` | ✅ Final |
| 8 | System architecture and modules | `03-system-design.md` | ✅ Final |
| 9 | UML: use-case, class, activity, sequence | `03-system-design.md`, `tools/diagrams.py` | ✅ Final |
| 10 | DFD Level 0 and Level 1 | `03-system-design.md`, `tools/diagrams.py` | ✅ Final |
| 11 | ERD and database schema | `03-system-design.md`, `diagrams/erd.md` | ✅ Final |
| 12 | Data dictionary (35 tables) | `appendix-a-data-dictionary.md` (generated) | ✅ Final |
| 13 | UI screenshots | `04-implementation.md`, `screenshots/` | ✅ Final |
| 14 | Algorithms and formulas | `04-implementation.md` | ✅ Final |
| 15 | Test plan, test cases, results | `05-testing.md`, `appendix-b-test-results.md` (generated) | ✅ Final |
| 16 | Security and multi-tenant isolation | `04-implementation.md` | ✅ Final |
| 17 | Installation on Windows | `06-installation-and-user-guide.md` | ✏️ Needs student input (GitHub address) |
| 18 | User manual (Dealer and Manager) | `06-installation-and-user-guide.md`, `user-manual/` | ✅ Final |
| 19 | Limitations, future enhancements, conclusion, references | `07-conclusion.md`, `08-references.md` | ✏️ Needs student input (extra references) |

## Final deliverables

| Item | File |
|---|---|
| Project report (PDF) | `academic/PetroSmart-Project-Report.pdf` |
| User manual (PDF) | `user-manual/PetroSmart-User-Manual.pdf` |
| Editable diagrams (Mermaid) | `diagrams/uml-and-dfd.md`, `diagrams/erd.md` |

## Rebuilding after a change

```powershell
.\.venv\Scripts\Activate.ps1
python documentation/tools/generate_schema_docs.py   # after changing a model
python documentation/tools/generate_test_report.py   # after changing code or tests
python documentation/tools/diagrams.py               # after changing a diagram
python documentation/tools/build_report.py           # always last: writes both PDFs
```

## Update log

| Date | What changed |
|---|---|
| 18 Oct 2026 | Phases 1–9 built; checklist and outline created and kept up to date |
| 18 Oct 2026 | Invoice-style purchases, MS/HSD split on shift cards, credit slips and bills; 231 tests pass |
| 19 Oct 2026 | Report chapters 1–7, references, appendices, diagrams, screenshots and user manual written; PDF builder added. Fixed: stock sheet failing on SQLite with decimal litres, menu background on large screens, phone menu not scrolling. 232 tests pass |
