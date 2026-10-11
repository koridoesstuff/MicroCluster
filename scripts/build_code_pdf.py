"""Builds docs/code.pdf: every hand-written source file in this repo, as
one PDF, for a judge to read without cloning. Same approach as the
one-pager (docs/one_pager.html -> docs/one_pager.pdf): generate HTML, print
it with headless Chrome. No PDF-generation library is a runtime dependency
of the project; it is only used here, as a build-time helper, to look up
which page each file actually landed on for the table of contents.

The file list comes from `git ls-files`, restricted to the directories and
names the submission calls for -- so anything .gitignore already excludes
(__pycache__, .venv, .git, .env) or that was never committed is excluded
automatically, and results/*.json, images and the PDFs themselves are
excluded because their directories/names are simply not in the list below.

Regenerate: python -m scripts.build_code_pdf
Needs a Chromium browser on PATH or at the hardcoded Windows path below,
and pypdf (`pip install pypdf`) -- a build-time-only tool dependency, not
added to requirements.txt, used solely to find each file's starting page
across the two rendering passes this needs (TOC page numbers depend on
where Chrome actually breaks pages, which depends on the TOC's own length
-- so pass 1 renders with placeholder numbers to discover real ones, pass
2 bakes them in, and a 3rd pass runs only if that insertion shifted
anything).
"""

from __future__ import annotations

import datetime
import html
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REPO_URL = "https://github.com/koridoesstuff/MicroCluster"
PROJECT = "MicroCluster"

# order matches the submission's own grouping, not strict alphabetical
GROUP_DIRS = ["microcluster", "simulation", "api", "adversarial", "web", "tests", "scripts"]
EXTRA_FILES = [
    "render.yaml", "requirements.txt", "requirements-runtime.txt",
    "Procfile", "conftest.py", "CLAUDE.md",
]

CHROME_CANDIDATES = [
    "chrome", "google-chrome", "chromium",
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
]


def find_chrome() -> str:
    for c in CHROME_CANDIDATES:
        if shutil.which(c) or Path(c).is_file():
            return c
    raise SystemExit("no Chromium found on PATH or at the usual Windows install locations")


def tracked_files() -> set[str]:
    out = subprocess.run(["git", "ls-files"], cwd=ROOT, capture_output=True, text=True, check=True)
    return set(out.stdout.splitlines())


def collect_files() -> list[tuple[str, list[str]]]:
    """[(group label, [repo-relative paths, sorted]), ...], last group is "other"."""
    tracked = tracked_files()
    groups: list[tuple[str, list[str]]] = []
    for name in GROUP_DIRS:
        folder = ROOT / name
        if not folder.is_dir():
            continue
        files = sorted(
            p.relative_to(ROOT).as_posix()
            for p in folder.rglob("*")
            if p.is_file() and p.relative_to(ROOT).as_posix() in tracked
        )
        if files:
            groups.append((name + "/", files))
    extras = [f for f in EXTRA_FILES if f in tracked and (ROOT / f).is_file()]
    if extras:
        groups.append(("other", extras))
    return groups


def render_file_section(relpath: str, anchor_id: str) -> tuple[str, int]:
    text = (ROOT / relpath).read_text(encoding="utf-8")
    lines = text.splitlines()
    width = max(len(str(len(lines))), 2)
    body = "\n".join(f"{i:>{width}} | {html.escape(line)}" for i, line in enumerate(lines, start=1))
    if not body:
        body = "(empty file)"
    section = (
        f'<section class="file" id="{anchor_id}">\n'
        f'  <h2>{html.escape(relpath)}</h2>\n'
        f'  <pre>{body}</pre>\n'
        f'</section>\n'
    )
    return section, len(lines)


def build_html(groups: list[tuple[str, list[str]]], toc_pages: dict[str, int] | None) -> tuple[str, list[str], int]:
    sections: list[str] = []
    ordered_files: list[str] = []
    total_lines = 0
    toc_rows: list[str] = []

    file_num = 0
    for label, files in groups:
        toc_rows.append(f'<tr class="toc-group"><td colspan="2">{html.escape(label)}</td></tr>')
        for relpath in files:
            file_num += 1
            anchor_id = f"file-{file_num}"
            # a plain same-document "#fragment" href -- verified this prints
            # as an internal PDF GoTo destination (/Dest), never a file://
            # URI, which is the bug this anchor scheme exists to avoid
            section, n = render_file_section(relpath, anchor_id)
            sections.append(section)
            ordered_files.append(relpath)
            total_lines += n
            page = toc_pages.get(relpath, "\u2013") if toc_pages else "\u2013"
            toc_rows.append(
                f'<tr><td class="toc-path"><a href="#{anchor_id}">{html.escape(relpath)}</a></td>'
                f'<td class="toc-page">{page}</td></tr>'
            )

    today = datetime.date.today().isoformat()
    doc = f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>{PROJECT} -- source code</title>
<style>
  @page {{
    size: Letter; margin: 16mm 14mm 20mm 14mm;
    @bottom-center {{
      content: counter(page);
      font-family: "IBM Plex Sans", sans-serif; font-size: 9pt; color: #5c574e;
    }}
  }}
  * {{ box-sizing: border-box; }}
  html, body {{
    margin: 0; background: #ffffff; color: #161616;
    font-family: "IBM Plex Sans", "Source Sans Pro", ui-sans-serif, system-ui,
      -apple-system, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
  }}
  .title-page {{
    height: 225mm; display: flex; flex-direction: column; justify-content: center;
  }}
  .title-page h1 {{ font-size: 28pt; margin: 0 0 8pt; }}
  .title-page p {{ font-size: 12pt; margin: 3pt 0; color: #444; }}
  .toc {{ page-break-before: always; break-before: page; }}
  .toc h1 {{ font-size: 16pt; margin: 0 0 10pt; }}
  table.toc-table {{ width: 100%; border-collapse: collapse; font-size: 9.5pt; }}
  table.toc-table td {{ padding: 2pt 4pt; border-bottom: 1px dotted #bbb; }}
  tr.toc-group td {{
    font-weight: 700; border-bottom: 1px solid #161616; padding-top: 9pt;
    font-family: "IBM Plex Mono", Consolas, "Courier New", monospace;
  }}
  .toc-path {{ font-family: "IBM Plex Mono", Consolas, "Courier New", monospace; }}
  .toc-path a {{ color: #161616; text-decoration: none; }}
  .toc-page {{ text-align: right; width: 34pt; font-variant-numeric: tabular-nums; }}
  section.file {{ page-break-before: always; break-before: page; }}
  section.file h2 {{
    font-family: "IBM Plex Mono", Consolas, "Courier New", monospace;
    font-size: 11pt; font-weight: 700; margin: 0 0 7pt; padding-bottom: 4pt;
    border-bottom: 1px solid #161616;
  }}
  pre {{
    font-family: "IBM Plex Mono", Consolas, "Courier New", monospace;
    font-size: 9.5pt; line-height: 1.32; margin: 0;
    white-space: pre-wrap; word-break: break-all; overflow-wrap: anywhere;
  }}
</style>
</head>
<body>

<div class="title-page">
  <h1>{PROJECT}</h1>
  <p>Source code, submitted for review.</p>
  <p>{REPO_URL}</p>
  <p>{today}</p>
  <p>{total_lines:,} lines across {len(ordered_files)} files.</p>
</div>

<div class="toc">
  <h1>Contents</h1>
  <table class="toc-table">
{"".join(toc_rows)}
  </table>
</div>

{"".join(sections)}
</body>
</html>
"""
    return doc, ordered_files, total_lines


def print_pdf(chrome: str, html_path: Path, pdf_path: Path) -> None:
    subprocess.run(
        [chrome, "--headless", "--disable-gpu", "--no-pdf-header-footer",
         f"--print-to-pdf={pdf_path}", html_path.resolve().as_uri()],
        check=True, capture_output=True,
    )


def discover_pages(pdf_path: Path, files: list[str]) -> dict[str, int]:
    import pypdf

    reader = pypdf.PdfReader(str(pdf_path))
    found: dict[str, int] = {}
    remaining = set(files)
    for i, page in enumerate(reader.pages, start=1):
        text = page.extract_text() or ""
        # the CSS page-counter footer can extract before the body text, so
        # a file's header may not be the first line -- check the first few
        # non-blank lines rather than requiring an exact prefix match
        lead = [ln.strip() for ln in text.splitlines() if ln.strip()][:3]
        for f in list(remaining):
            if f in lead:
                found[f] = i
                remaining.discard(f)
                break
    return found


def main() -> None:
    chrome = find_chrome()
    groups = collect_files()
    html_path = ROOT / "docs" / "code.html"
    pdf_path = ROOT / "docs" / "code.pdf"

    doc, files, total_lines = build_html(groups, None)
    html_path.write_text(doc, encoding="utf-8")
    print_pdf(chrome, html_path, pdf_path)
    pages = discover_pages(pdf_path, files)

    for attempt in range(2):
        doc, files, total_lines = build_html(groups, pages)
        html_path.write_text(doc, encoding="utf-8")
        print_pdf(chrome, html_path, pdf_path)
        new_pages = discover_pages(pdf_path, files)
        if new_pages == pages:
            break
        pages = new_pages
    else:
        print("warning: TOC page numbers had not fully stabilised after 3 passes", file=sys.stderr)

    missing = [f for f in files if f not in pages]
    if missing:
        print("warning: could not locate a page for:", missing, file=sys.stderr)

    import pypdf
    page_count = len(pypdf.PdfReader(str(pdf_path)).pages)
    print(f"built {pdf_path}: {page_count} pages, {total_lines:,} lines across {len(files)} files")


if __name__ == "__main__":
    main()
