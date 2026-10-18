# PetroSmart documentation

This folder holds the project's documentation, kept in three separate parts:

| Folder | Audience | Contents |
|---|---|---|
| `academic/` | College examiners and project guide | The T.Y. B.Sc. Computer Science project report, one Markdown file per chapter, plus the built `PetroSmart-Project-Report.pdf`. |
| `user-manual/` | Dealers and managers using PetroSmart | Step-by-step workflows, written without technical terms (`README.md` and a PDF copy). |
| `screenshots/` | Used by the report | Screen images shown in Chapter 4. |
| `tools/` | Whoever updates the report | Scripts that generate the data dictionary, the test results, the diagrams and the PDFs (see `CHECKLIST.md`). |
| `diagrams/` | Used by the report | Editable Mermaid text of the UML, DFD and ER diagrams. The PDF draws the same diagrams from `tools/diagrams.py`. |

Developer documentation (setup, code rules, backup) is in the main
[`README.md`](../README.md) at the project root, not here.

Progress is tracked in [`CHECKLIST.md`](CHECKLIST.md). The planned report
structure is in [`academic/OUTLINE.md`](academic/OUTLINE.md).

## Rules for every document

1. **Match the code.** Every model, field, screen and formula described here
   must exist in the source code at the time it is written. If the code
   changes, update the documentation in the same phase.
2. **No claims ahead of the code.** Features that are not built yet go in the
   "Future enhancements" chapter, or are clearly marked *Planned*.
3. **Only real test results.** A test case is marked *Pass* only after it has
   actually been run. Record the date and the command used.
4. **Placeholders for personal details.** Write them as `[STUDENT NAME]`,
   `[ROLL NUMBER]` and so on, until the real details are provided.
5. **Diagrams as editable text.** Each diagram has a text source in
   `tools/diagrams.py` (exported as Mermaid to `diagrams/`) so it can be changed later.
   Every diagram gets a figure number and caption, e.g. *Figure 3.1: Level 0 DFD*.
6. **Screenshots come from the running application**, never from mock-ups.
