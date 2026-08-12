from pathlib import Path

from latexword.document import (
    Attachment,
    Document,
    ExportRequest,
    ImportResult,
    NodeId,
)


def test_adapter_contracts_are_format_neutral_and_immutable():
    document = Document()
    result = ImportResult(document=document)
    request = ExportRequest(document=document, reference_docx=Path("artifact"))
    attachment = Attachment(
        payload_id="payload-a",
        position="inside",
        owner_id=NodeId.allocate(1),
        ordinal=0,
        owner_semantic_hash="hash-a",
    )

    assert result.document is document
    assert request.reference_docx == Path("artifact")
    assert attachment.owner_id == NodeId("n00000001")
