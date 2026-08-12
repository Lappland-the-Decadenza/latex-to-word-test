"""Open DOCX samples safely in desktop Word and optionally export PDFs."""

from __future__ import annotations

import argparse
import json
import subprocess
import tempfile
from pathlib import Path


def inspect_with_word(paths, *, render_dir=None, timeout=60):
    documents = [str(Path(path).resolve()) for path in paths]
    exports = []
    if render_dir is not None:
        target = Path(render_dir).resolve()
        target.mkdir(parents=True, exist_ok=True)
        exports = [str(target / f"sample-{index:02d}.pdf") for index in range(len(documents))]
    payload = json.dumps({"documents": documents, "exports": exports})
    script = r'''
$ErrorActionPreference = "Stop"
$request = Get-Content -LiteralPath $args[0] -Raw | ConvertFrom-Json
$word = $null
try {
    $word = New-Object -ComObject Word.Application
    $word.Visible = $false
    $word.DisplayAlerts = 0
    $word.AutomationSecurity = 3
    $word.Options.UpdateLinksAtOpen = $false
    for ($index = 0; $index -lt $request.documents.Count; $index++) {
        $document = $null
        try {
            $document = $word.Documents.Open($request.documents[$index], $false, $true, $false)
            if ($request.exports.Count -gt $index) {
                $document.ExportAsFixedFormat($request.exports[$index], 17, $false, 0, 0)
            }
        } finally {
            if ($null -ne $document) { $document.Close(0) }
        }
    }
} finally {
    if ($null -ne $word) { $word.Quit() }
}
'''
    try:
        with tempfile.TemporaryDirectory(prefix="latexword-word-") as directory:
            root = Path(directory)
            request = root / "request.json"
            command = root / "open.ps1"
            request.write_text(payload, encoding="utf-8")
            command.write_text(script, encoding="utf-8")
            result = subprocess.run(
                ["powershell", "-NoProfile", "-STA", "-ExecutionPolicy", "Bypass", "-File", str(command), str(request)],
                capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout,
            )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"status": "blocked", "reason": str(exc), "exports": []}
    if result.returncode:
        reason = (result.stderr or result.stdout).strip().splitlines()
        return {"status": "blocked", "reason": reason[0] if reason else "Word automation failed", "exports": []}
    missing = [path for path in exports if not Path(path).is_file()]
    if missing:
        return {"status": "blocked", "reason": "Word did not produce every requested rendering", "exports": []}
    return {"status": "pass", "opened": len(documents), "exports": exports}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("documents", nargs="+")
    parser.add_argument("--render-dir")
    parser.add_argument("--timeout", type=float, default=60)
    args = parser.parse_args(argv)
    result = inspect_with_word(args.documents, render_dir=args.render_dir, timeout=args.timeout)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0 if result["status"] == "pass" else 3


if __name__ == "__main__":
    raise SystemExit(main())
