---
name: latexword-word-editing
description: Edit existing Microsoft Word .docx documents by preparing and applying the repository's managed shadow-LaTeX workspace. Use when a user asks Codex to translate, rewrite, format, add, delete, or otherwise modify a Word document through the local LaTeXWord converter.
---

# LaTeXWord Word Editing

Use this skill when the user asks for a change to an existing `.docx` in the
current folder. Codex is the editor: LaTeXWord only prepares the editable
shadow and applies the completed file edit. Do not launch another Codex or
provider process.

## Fixed installation

The installer replaces `__LATEXWORD_ROOT__` in this skill with the absolute
path of the one permanent LaTeXWord installation. Use these paths exactly:

- Python: `__LATEXWORD_ROOT__\.venv\Scripts\python.exe`
- launcher: `__LATEXWORD_ROOT__\latexword_workspace.py`

Never search for another checkout, use a repository-relative path, or ask the
user to provide a workspace, edit directory, output path, or temporary folder.
The document being edited may be in any directory; only its managed
`<source-stem>.latexword` folder belongs beside the document.
The CLI configures UTF-8 for its own input and output; do not add a
`PYTHONIOENCODING` assignment to the command.
`shadow.tex` is also UTF-8: when using PowerShell, read it with
`Get-Content -Encoding UTF8` and write it with an explicit UTF-8 encoding.
Do not rely on console encoding settings to decode the file.

## Workflow

1. Identify the document named by the user. If the user did not name one and
   exactly one `.docx` is present in the current folder, use it. If there are
   several plausible documents, ask which one.
2. Use the fixed installation paths above. The user's complete
   instruction is already in the active Codex conversation; do not serialize
   it into a file or pass it as a CLI option:

   ```powershell
   "__LATEXWORD_ROOT__\.venv\Scripts\python.exe" "__LATEXWORD_ROOT__\latexword_workspace.py" edit-start SOURCE.docx
   ```

   When the repository or document is elsewhere, use absolute paths for the
   launcher and source. This command creates or reuses the folder named
   `<source-stem>.latexword` beside the document.
3. Read and edit only `<source-stem>.latexword\shadow.tex`. The generated
   `check.cmd` validates the file. Keep every existing `%lw:<kind>:<number>`
   comment with its block; remove a comment only when deleting its block. New
   blocks need no comment.
4. Do not enter or modify `<source-stem>.latexword\.service`. It contains
   `original.docx` (the first imported version), `current.docx` (the latest
   version represented by the shadow), `candidate.docx`, maps, hashes,
   history, extracted assets, `diagnostics.log`, and staging data. Do not edit
   the source `.docx` directly.
5. Inspect targeted shadow ranges and use syntax already demonstrated there.
   Preserve unrelated content. Run `check.cmd` after the first edit and again
   immediately before applying. Fix every error it reports. Warnings must be
   understood and reported, not hidden.
6. Apply the edit with:

   ```powershell
   "__LATEXWORD_ROOT__\.venv\Scripts\python.exe" "__LATEXWORD_ROOT__\latexword_workspace.py" edit-apply SOURCE.docx
   ```

   This publishes atomically when Word is closed. It stores recovery history in
   the managed folder. If the command reports
   `word-live-update-not-implemented`, do not try to close, reopen, or overwrite
   Word; report that the verified candidate remains under `.service` and ask
   the user to close Word before applying it.

The launcher commands must run in the host/user execution context when the
agent runtime provides that mode. This prevents persistent managed-folder
files from being owned by a disposable sandbox identity. Do not compensate
with `takeown`, `icacls`, or any other ACL mutation.

## Repeated requests

For a later correction to the same document, run `edit-start` again for the
same source. It reuses the existing owned `.latexword` folder; never add
`--instruction-text`, `--workspace`, `--edit-dir`, `--output`, `--run`, or a
system-temporary edit directory. Then edit the same root `shadow.tex`, check
it, and run `edit-apply` again.

## Failure handling

If `edit-start` or the checker fails, inspect the named source or shadow line
and correct the root `shadow.tex`. If `edit-apply` fails, do not create a new
workspace or manually patch the DOCX. Report the concise diagnostic and leave
the managed folder available for repair. The program must not publish a
partial or unchecked document.
