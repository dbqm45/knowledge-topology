from kt.domain.models import NormalizedDocument
from kt.ingestion.parsing import parse_markdown, parse_storage_html
from kt.semantic.chunking import chunk_document

STORAGE = """
<h1>Payment Service</h1><p>Intro text about payments.</p>
<ac:structured-macro ac:name="toc"><ac:parameter ac:name="x">y</ac:parameter></ac:structured-macro>
<h2>Retries</h2><p>Failed payments are retried <strong>3 times</strong>.</p>
<ul><li>first</li><li>second</li></ul>
<ac:structured-macro ac:name="code"><ac:plain-text-body><![CDATA[retry: 3
if a < b: pass]]></ac:plain-text-body></ac:structured-macro>
<table><tr><th>Code</th><th>Meaning</th></tr><tr><td>PAY-1</td><td>declined</td></tr></table>
<p>See <ac:link><ri:page ri:content-title="Refunds"/></ac:link> and <a href="https://x.example/doc">docs</a>.</p>
"""


def test_storage_format_structure():
    sections, links = parse_storage_html(STORAGE, "Payment Service")
    kinds = [(s.kind, s.heading_path) for s in sections]
    assert ("code", ["Payment Service", "Retries"]) in kinds
    assert ("table", ["Payment Service", "Retries"]) in kinds
    code = next(s for s in sections if s.kind == "code")
    assert "if a < b" in code.text  # CDATA preserved, not treated as markup
    table = next(s for s in sections if s.kind == "table")
    assert "PAY-1 | declined" in table.text
    assert "title:Refunds" in links and "https://x.example/doc" in links
    assert not any("y" == s.text for s in sections)  # toc macro skipped


def test_markdown_structure_and_links():
    md = "# A\ntext [x](other.md)\n## B\n| h1 | h2 |\n|---|---|\n| v1 | v2 |\n```\ncode()\n```\nsee [[Some Page]]\n"
    sections, links = parse_markdown(md)
    assert [s.kind for s in sections] == ["text", "table", "code", "text"]
    assert sections[1].text == "h1 | h2\nv1 | v2"
    assert sections[1].heading_path == ["A", "B"]
    assert "other.md" in links and "title:Some Page" in links


def test_chunking_respects_sections_and_budget():
    from kt.domain.models import Section

    long = "\n\n".join(f"Paragraph {i} " + "word " * 120 for i in range(8))
    doc = NormalizedDocument(external_id="x", title="T", sections=[
        Section(heading_path=["T", "One"], text=long), Section(heading_path=["T", "Two"], text="short", kind="text"),
        Section(heading_path=["T", "Two"], text="print()", kind="code")])
    chunks = chunk_document(doc, target_tokens=300, max_tokens=500)
    assert all(c.token_count <= 520 for c in chunks)
    assert {tuple(c.heading_path) for c in chunks} == {("T", "One"), ("T", "Two")}
    assert any(c.kind == "code" for c in chunks)
    assert chunks[0].embedding_text("T").startswith("T > T > One")


def test_content_hash_ignores_acl():
    a = NormalizedDocument(external_id="x", title="T", principals=["*"])
    b = NormalizedDocument(external_id="x", title="T", principals=["group:hr"])
    assert a.content_hash() == b.content_hash()
