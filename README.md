# latex-to-word

Bidirectional LaTeX and Microsoft Word conversion. Mathematical content is
emitted as native, editable Word Equation objects (OMML), not images or plain
text.

## Installation

The normal installation is done once in a permanent user directory. It is not
repeated in every document folder. Open Codex CLI or Codex Desktop in any
folder and paste the prompt below. The agent performs the clone, Python check,
virtual-environment setup, dependency installation, and skill installation
itself.

```text
Set up LaTeXWord completely on this machine. Do everything from start to
finish yourself and do not ask me to run shell commands manually.

1. Install the program exactly once at %USERPROFILE%\LaTeXWord. If that
   directory does not contain the repository, clone
   https://github.com/Lappland-the-Decadenza/latex-to-word-test.git there. If
   it is already installed, reuse that installation.
2. Check that Python 3.10 or newer is available. If it is missing, install it
   using the available system package manager if possible; otherwise stop and
   tell me the exact prerequisite that blocks you.
3. Run the repository's install.ps1 from that permanent installation. It must
   create or reuse .venv, install requirements.txt, install the local
   latexword-word-editing skill, and replace the skill's installation-path
   placeholder with the absolute path %USERPROFILE%\LaTeXWord.
4. Verify the production imports, the launcher, and the installed skill. The
   installed skill must invoke this exact permanent installation; it must not
   search for the program in the document folder.

Do not modify source code, README files, or any user documents. Do not install
development-only dependencies unless I ask for tests or linting. If Codex
needs to restart or reopen to discover the newly installed skill, finish all
other setup first and tell me only that one restart is required. At the end,
report the permanent installation path, virtual-environment path, and whether
the skill was installed successfully.
```

The repository is [Lappland-the-Decadenza/latex-to-word-test](https://github.com/Lappland-the-Decadenza/latex-to-word-test), and the normal
installation path is `%USERPROFILE%\LaTeXWord`.
The runtime requires Python 3.10 or newer. Microsoft Word is needed only to
inspect or edit the resulting `.docx`; the converters themselves do not need
Word to start.

The production requirements contain only libraries used by the current
converter and workspace paths. `Pillow`, `pytest`, and `ruff` are development
dependencies listed separately in `requirements-dev.txt`.
The old MathML/XSL compatibility oracle is optional and is not required by the
production converter or by normal Word editing.

## Quick start

```powershell
.venv\Scripts\python.exe latex2word.py SOURCE.tex [OUTPUT.docx]
.venv\Scripts\python.exe word2latex.py SOURCE.docx [OUTPUT.tex]
```

The CLI configures UTF-8 for its own input and output automatically, so no
PowerShell encoding variable is required. This is process-local and does not
change Windows or PowerShell settings.

The output path defaults to the input path with the other extension. A failed
formula is preserved as literal LaTeX and reported in the warning summary;
callers should treat any warning as something to inspect.

The first command converts LaTeX to Word; the second converts Word back to
LaTeX. Use explicit output paths when the source document should be preserved.

## Manual installation

If automatic setup through Codex is not desired, install the program once in
PowerShell:

```powershell
$installRoot = Join-Path $env:USERPROFILE 'LaTeXWord'
if (-not (Test-Path $installRoot)) {
    git clone https://github.com/Lappland-the-Decadenza/latex-to-word-test.git $installRoot
}
Set-Location $installRoot
.\install.ps1
```

The installer creates `.venv`, installs the runtime requirements, and installs
the skill with the exact absolute path of this program. For tests and linting,
use `.\install.ps1 -InstallDev`.

To install the skill manually after the program is already installed, copy the
repository skill to the Codex skills directory and replace
`__LATEXWORD_ROOT__` in the copied `SKILL.md` with the exact value of
`$installRoot`:

```powershell
$codexRoot = if ($env:CODEX_HOME) { $env:CODEX_HOME } else { Join-Path $env:USERPROFILE '.codex' }
$skillRoot = Join-Path $codexRoot 'skills\latexword-word-editing'
New-Item -ItemType Directory -Force -Path $skillRoot | Out-Null
Copy-Item -Path (Join-Path $installRoot 'skills\latexword-word-editing\*') -Destination $skillRoot -Recurse -Force
$skillFile = Join-Path $skillRoot 'SKILL.md'
$skillText = [IO.File]::ReadAllText($skillFile).Replace('__LATEXWORD_ROOT__', $installRoot)
[IO.File]::WriteAllText($skillFile, $skillText, [System.Text.UTF8Encoding]::new($false))
```

Restart Codex once after a manual skill installation so it reloads the skill
list.

## AI Word editing

After the installation prompt has completed, put the `.docx` to be edited in
a folder, open Codex CLI or Codex Desktop in that folder, and write only what
you want changed. For example:

```text
In this folder, edit SOURCE.docx. Translate the introduction into English,
improve the headings, highlight the key formulas, and add a section about
thermal stability. Preserve the rest of the document.
```

The person does not run any LaTeXWord commands. The installed skill contains
the absolute path to the one permanent installation and tells the agent how to
prepare or reuse the document workspace,
edit the shadow LaTeX, validate the edit, and apply the result back to Word.
The user's request stays in the Codex conversation; no task file or second
agent is created.

`check.cmd` runs the same shadow validator used by the apply path. It checks
the document envelope, approved packages and environments, commands/options,
block metadata, and math syntax. The apply path additionally checks resource
ownership. Unknown LaTeX commands, environments, packages, or math constructs
are reported as errors; the document class is treated as envelope metadata and
is not restricted to `article`.

The program derives one managed folder from the source stem, reuses it on
later turns, refreshes stale derived files, and adds a numeric suffix only when
an unrelated folder already occupies the expected path. All persistent state
is below that folder's `.service/` directory; the agent-facing root contains
only the shadow, checker, answer, and optional user assets.

Inside `.service`, `original.docx` is the immutable first version imported for
that document, while `current.docx` is the latest document version represented
by the current shadow after completed AI edits or an external refresh.
`candidate.docx` is a verified version waiting for publication, and
`diagnostics.log` records converter warnings and command errors. Older managed
folders containing `base.docx` are migrated automatically; an earlier history
backup is used for `original.docx` when available.

The launcher should run in the host/user execution context when the agent
runtime supports that mode, so persistent files remain removable by the
interactive user. The application never changes Windows ownership or ACLs.

If the source document is open in Word, the CLI verifies and retains a
candidate below `.service/` but does not modify the open document. Live Word
updates, cursor/selection reporting, and undo integration belong to a future
Office add-in. No COM bridge is part of this phase.

## Requirements

The project uses Python 3.10 or newer. Runtime dependencies are listed in
`requirements.txt`; `requirements-dev.txt` adds `Pillow`, `pytest`, and `ruff`
for development and testing. A local `.venv/` is expected and is ignored by
Git.

## Architecture

The forward path tokenizes and parses LaTeX into the shared math AST, then
emits OMML through the document writer. The reverse path loads OMML into the
same AST family and serializes canonical LaTeX. Structural truth lives in
`latexword/math/ast.py`; bidirectional symbol declarations live in
`latexword/symbols/registry.py`.

The AI editing path projects a DOCX into labelled shadow blocks, lets the
agent edit ordinary LaTeX, derives a deterministic block diff, renders only
changed blocks, and assembles a verified DOCX while preserving unchanged XML.
The old model-facing operation protocol and matching fallback are not part of
the active path.

## Repository layout

| Path | Purpose |
| --- | --- |
| `latex2word.py`, `word2latex.py` | Converter CLI shims |
| `latexword/` | Converter, workspace, session, and CLI packages |
| `install.ps1` | One-time runtime and Codex skill installer |
| `requirements*.txt` | Runtime and development dependencies |
| `tests/fixtures/` | Project-authored LaTeX fixtures |
| `tools/` | Focused diagnostics and architecture checks |
| `skills/latexword-word-editing/` | Repository copy of the Codex skill |

Private documents, generated outputs, extracted assets, and managed workspace
folders are Git-ignored and must never be committed.

## Verification

```powershell
.venv\Scripts\python.exe -m pytest tests -q
.venv\Scripts\python.exe tools\architecture_check.py
.venv\Scripts\python.exe -m ruff check . --no-cache
```

The unit suite is a regression net, not proof of corpus fidelity or visual
correctness. Corpus measurements compare output with the original private
documents, and human inspection in Word outranks a green automated report.
