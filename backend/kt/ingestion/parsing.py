"""Format parsers: Confluence storage HTML and Markdown -> structured sections.

Presentation is dropped, structure is kept: headings define the section path,
tables/code/lists become their own typed sections, links are collected.
"""

from __future__ import annotations

import re
from html.parser import HTMLParser

from kt.domain.models import Section

_WS = re.compile(r"[ \t\r\f\v]+")


def _clean(text: str) -> str:
    lines = [_WS.sub(" ", ln).strip() for ln in text.splitlines()]
    out: list[str] = []
    for ln in lines:
        if ln or (out and out[-1]):
            out.append(ln)
    return "\n".join(out).strip()


class _StorageHTMLParser(HTMLParser):
    """Parser for Confluence *storage format* (XHTML + ac:/ri: macros). Also handles plain HTML."""

    HEADINGS = {"h1": 1, "h2": 2, "h3": 3, "h4": 4, "h5": 5, "h6": 6}
    SKIP_MACROS = {"toc", "children", "recently-updated", "pagetree", "excerpt-include", "jira", "status"}

    def __init__(self, title: str):
        super().__init__(convert_charrefs=True)
        self.title = title
        self.sections: list[Section] = []
        self.links: list[str] = []
        self.heading_stack: list[tuple[int, str]] = []
        self.buf: list[str] = []
        self.mode: str = "text"  # text | heading | code | table
        self.heading_level = 0
        self.heading_buf: list[str] = []
        self.code_buf: list[str] = []
        self.table_rows: list[list[str]] = []
        self.cell_buf: list[str] | None = None
        self.list_depth = 0
        self.skip_depth = 0
        self.macro_stack: list[str] = []

    # -- helpers -------------------------------------------------------------
    def _path(self) -> list[str]:
        return [h for _, h in self.heading_stack]

    def _flush_text(self) -> None:
        text = _clean("".join(self.buf))
        self.buf = []
        if text:
            kind = "list" if text.startswith("- ") and text.count("\n- ") >= 1 else "text"
            self.sections.append(Section(heading_path=self._path(), text=text, kind=kind))

    # -- parser callbacks ----------------------------------------------------
    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if self.skip_depth:
            if tag == "ac:structured-macro":
                self.skip_depth += 1
            return
        if tag == "ac:structured-macro":
            name = a.get("ac:name", "")
            if name in self.SKIP_MACROS:
                self.skip_depth = 1
                return
            self.macro_stack.append(name)
            if name in ("code", "noformat"):
                self._flush_text()
                self.mode = "code"
                self.code_buf = []
            return
        if tag in self.HEADINGS:
            self._flush_text()
            self.mode = "heading"
            self.heading_level = self.HEADINGS[tag]
            self.heading_buf = []
        elif tag == "pre" and self.mode != "code":
            self._flush_text()
            self.mode = "code"
            self.code_buf = []
        elif tag == "table":
            self._flush_text()
            self.mode = "table"
            self.table_rows = []
        elif tag == "tr" and self.mode == "table":
            self.table_rows.append([])
        elif tag in ("td", "th") and self.mode == "table":
            self.cell_buf = []
        elif tag in ("ul", "ol"):
            self.list_depth += 1
        elif tag == "li":
            self.buf.append("\n" + "  " * max(self.list_depth - 1, 0) + "- ")
        elif tag in ("p", "div", "br"):
            self._emit("\n")
        elif tag == "a" and a.get("href"):
            self.links.append(a["href"])
        elif tag == "ri:page" and a.get("ri:content-title"):
            self.links.append("title:" + a["ri:content-title"])

    def handle_endtag(self, tag):
        if self.skip_depth:
            if tag == "ac:structured-macro":
                self.skip_depth -= 1
            return
        if tag == "ac:structured-macro":
            name = self.macro_stack.pop() if self.macro_stack else ""
            if name in ("code", "noformat") and self.mode == "code":
                self._finish_code()
            return
        if tag in self.HEADINGS and self.mode == "heading":
            heading = _clean("".join(self.heading_buf))
            while self.heading_stack and self.heading_stack[-1][0] >= self.heading_level:
                self.heading_stack.pop()
            if heading:
                self.heading_stack.append((self.heading_level, heading))
            self.mode = "text"
        elif tag == "pre" and self.mode == "code" and not (self.macro_stack and self.macro_stack[-1] == "code"):
            self._finish_code()
        elif tag in ("td", "th") and self.mode == "table" and self.cell_buf is not None:
            if self.table_rows:
                self.table_rows[-1].append(_clean("".join(self.cell_buf)).replace("\n", " "))
            self.cell_buf = None
        elif tag == "table" and self.mode == "table":
            rows = [" | ".join(r) for r in self.table_rows if any(c for c in r)]
            if rows:
                self.sections.append(Section(heading_path=self._path(), text="\n".join(rows), kind="table"))
            self.mode = "text"
        elif tag in ("ul", "ol"):
            self.list_depth = max(0, self.list_depth - 1)
            if self.list_depth == 0:
                self._emit("\n")
        elif tag in ("p", "div", "li"):
            self._emit("\n")

    def _finish_code(self):
        code = "".join(self.code_buf).strip("\n")
        if code.strip():
            self.sections.append(Section(heading_path=self._path(), text=code, kind="code"))
        self.mode = "text"

    def _emit(self, data: str):
        if self.mode == "heading":
            self.heading_buf.append(data)
        elif self.mode == "code":
            self.code_buf.append(data)
        elif self.mode == "table":
            if self.cell_buf is not None:
                self.cell_buf.append(data)
        else:
            self.buf.append(data)

    def handle_data(self, data):
        if self.skip_depth:
            return
        self._emit(data)

    def close(self):
        super().close()
        if self.mode == "code":
            self._finish_code()
        self._flush_text()


def parse_storage_html(html: str, title: str = "") -> tuple[list[Section], list[str]]:
    # CDATA blocks (code macro bodies) are not delivered as data by HTMLParser — unwrap them.
    html = re.sub(r"<!\[CDATA\[(.*?)\]\]>", lambda m: _escape(m.group(1)), html, flags=re.S)
    parser = _StorageHTMLParser(title)
    parser.feed(html)
    parser.close()
    return parser.sections, parser.links


def _escape(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


_MD_HEADING = re.compile(r"^(#{1,6})\s+(.*?)\s*#*\s*$")
_MD_LINK = re.compile(r"\[[^\]]*\]\(([^)\s]+)[^)]*\)")
_MD_WIKILINK = re.compile(r"\[\[([^\]|]+)(?:\|[^\]]*)?\]\]")


def parse_markdown(text: str) -> tuple[list[Section], list[str]]:
    sections: list[Section] = []
    links = [m.group(1) for m in _MD_LINK.finditer(text)] + [
        "title:" + m.group(1).strip() for m in _MD_WIKILINK.finditer(text)
    ]
    stack: list[tuple[int, str]] = []
    buf: list[str] = []
    table: list[str] = []
    code: list[str] | None = None

    def path():
        return [h for _, h in stack]

    def flush_buf():
        nonlocal buf
        body = _clean("\n".join(buf))
        buf = []
        if body:
            is_list = all(ln.lstrip().startswith(("- ", "* ", "+ ")) or re.match(r"^\s*\d+\.", ln)
                          for ln in body.splitlines() if ln.strip())
            sections.append(Section(heading_path=path(), text=body, kind="list" if is_list else "text"))

    def flush_table():
        nonlocal table
        rows = [r for r in table if not re.fullmatch(r"\|?\s*:?-{2,}.*", r.strip())]
        rows = [" | ".join(c.strip() for c in r.strip().strip("|").split("|")) for r in rows]
        if rows:
            sections.append(Section(heading_path=path(), text="\n".join(rows), kind="table"))
        table = []

    for line in text.splitlines():
        if code is not None:
            if line.strip().startswith("```"):
                body = "\n".join(code)
                if body.strip():
                    sections.append(Section(heading_path=path(), text=body, kind="code"))
                code = None
            else:
                code.append(line)
            continue
        if line.strip().startswith("```"):
            flush_buf()
            flush_table()
            code = []
            continue
        if line.strip().startswith("|"):
            flush_buf()
            table.append(line)
            continue
        if table:
            flush_table()
        m = _MD_HEADING.match(line)
        if m:
            flush_buf()
            level, heading = len(m.group(1)), m.group(2)
            while stack and stack[-1][0] >= level:
                stack.pop()
            stack.append((level, heading))
            continue
        buf.append(_MD_LINK.sub(lambda mm: mm.group(0).split("](")[0].lstrip("["), line))
    if code:
        sections.append(Section(heading_path=path(), text="\n".join(code), kind="code"))
    flush_table()
    flush_buf()
    return sections, links
