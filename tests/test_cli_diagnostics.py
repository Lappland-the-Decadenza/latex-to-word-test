from docx import Document as WordDocument

from latexword.cli.workspace import main
from latexword.cli.progress import Progress, REQUIRED_STAGES
from latexword.workspace.import_docx import classify_warnings


def test_workspace_create_progress_is_stderr_only(tmp_path, capsys):
    source = tmp_path / "source.docx"
    WordDocument().save(source)
    destination = tmp_path / "workspace"

    assert main(["workspace-create", str(source), str(destination)]) == 0
    captured = capsys.readouterr()

    assert str(destination) in captured.out
    assert "stage=package-validate started" in captured.err
    assert "stage=convert started" in captured.err
    assert "stage=provenance started" in captured.err
    assert "anchors" not in captured.err
    assert "elapsed_ms=" in captured.err
    assert "stage=" not in captured.out


def test_expected_failure_has_no_traceback_or_output(tmp_path, capsys):
    destination = tmp_path / "workspace"

    assert main(["workspace-create", str(tmp_path / "missing.docx"), str(destination)]) != 0
    captured = capsys.readouterr()

    assert captured.out == ""
    assert "stage=workspace" in captured.err
    assert "category=workspaceerror" in captured.err
    assert "Traceback" not in captured.err
    assert not destination.exists()


def test_interrupt_is_clean_and_reports_no_publication(tmp_path, monkeypatch, capsys):
    shadow = tmp_path / "shadow.tex"
    shadow.write_text("\\begin{document}\nText\n\\end{document}\n", encoding="utf-8")

    def interrupt(*_args, **_kwargs):
        raise KeyboardInterrupt

    monkeypatch.setattr("latexword.cli.workspace._dispatch", interrupt)
    assert main(["--quiet", "workspace-check", str(shadow)]) == 130
    captured = capsys.readouterr()
    assert "category=interrupted" in captured.err
    assert "no document was published" in captured.err
    assert "Traceback" not in captured.err


def test_quiet_suppresses_progress_but_not_result(tmp_path, capsys):
    source = tmp_path / "source.docx"
    WordDocument().save(source)

    assert main(["--quiet", "workspace-create", str(source), str(tmp_path / "workspace")]) == 0
    captured = capsys.readouterr()

    assert str(tmp_path / "workspace") in captured.out
    assert captured.err == ""


def test_warning_classification_never_defers_dropped_content():
    handled, deferred, unknown = classify_warnings((
        "image metadata at paragraph 2 was not sidecar-preserved: invalid metadata",
        "Word object at paragraph 4 could not be sidecar-preserved: unsafe relationship",
        "non-picture drawing at paragraph 6 was dropped",
    ))

    assert handled == ()
    assert deferred == ("image metadata at paragraph 2 was not sidecar-preserved: invalid metadata",)
    assert unknown == (
        "Word object at paragraph 4 could not be sidecar-preserved: unsafe relationship",
        "non-picture drawing at paragraph 6 was dropped",
    )


def test_every_required_progress_stage_emits_before_work(capsys):
    reporter = Progress()

    for stage in REQUIRED_STAGES:
        with reporter.stage(stage):
            pass

    lines = capsys.readouterr().err.splitlines()
    for stage in REQUIRED_STAGES:
        started = lines.index(f"stage={stage} started")
        completed = next(
            index for index, line in enumerate(lines)
            if line.startswith(f"stage={stage} elapsed_ms=")
        )
        assert started < completed
