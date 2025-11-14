import pytest
from types import SimpleNamespace

from app.agents import toolkit


@pytest.mark.asyncio
async def test_agent_docs_tool_lists_documents(tmp_path, monkeypatch):
    docs_dir = tmp_path / "docs" / "agent"
    docs_dir.mkdir(parents=True)
    (docs_dir / "b.md").write_text("second", encoding="utf-8")
    (docs_dir / "a.md").write_text("first", encoding="utf-8")
    (docs_dir / "ignore.txt").write_text("skip", encoding="utf-8")
    monkeypatch.setattr(toolkit, "AGENT_DOCS_DIR", docs_dir)

    result = await toolkit.agent_docs_tool(SimpleNamespace(), toolkit.AgentDocsInput())

    assert result.documents == ["a.md", "b.md"]
    assert result.selected_document is None
    assert result.content is None


@pytest.mark.asyncio
async def test_agent_docs_tool_reads_specific_document(tmp_path, monkeypatch):
    docs_dir = tmp_path / "docs" / "agent"
    docs_dir.mkdir(parents=True)
    target_file = docs_dir / "guide.md"
    target_file.write_text("Full content", encoding="utf-8")
    monkeypatch.setattr(toolkit, "AGENT_DOCS_DIR", docs_dir)

    result = await toolkit.agent_docs_tool(
        SimpleNamespace(),
        toolkit.AgentDocsInput(document_name="../guide.md"),
    )

    assert result.documents == ["guide.md"]
    assert result.selected_document == "guide.md"
    assert result.content == "Full content"
