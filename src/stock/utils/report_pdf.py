from __future__ import annotations

import re
from pathlib import Path

from stock.utils.report_html import render_report_html

_WEASYPRINT_ERROR: str | None = None
try:
    from weasyprint import HTML
except Exception as exc:  # 目标机可能缺 weasyprint 或 libpango 等系统库
    HTML = None
    _WEASYPRINT_ERROR = str(exc)


_PRINT_CSS = """
@page { size: A4; margin: 12mm 11mm 14mm 11mm; }
html, body { background:#ffffff !important; padding:0 !important; }
.container { max-width:none !important; margin:0 !important; padding:0 !important;
             box-shadow:none !important; border-radius:0 !important; }
h1, h2 { page-break-after: avoid; }
figure, .figure-row, .split, table, .cards { page-break-inside: avoid; }
.page-break { page-break-before: always; }
"""


def _require_weasyprint() -> None:
    if HTML is None:
        raise RuntimeError(
            "WeasyPrint 不可用（可能缺少 weasyprint 或 libpango 等系统库）: "
            + (_WEASYPRINT_ERROR or "import failed")
        )


def html_to_pdf(html: str, base_url: str | Path = ".") -> bytes:
    _require_weasyprint()
    html = re.sub(
        r'<h1 id="(sec-\d+)">三、详细信息</h1>',
        r'<h1 id="\1" class="page-break">三、详细信息</h1>',
        html,
    )
    html = html.replace("</head>", f"<style>{_PRINT_CSS}</style></head>")
    return HTML(string=html, base_url=str(base_url)).write_pdf()


def render_report_pdf(md_text: str, db_path: Path, code: str) -> bytes:
    html = render_report_html(md_text, db_path, code)
    return html_to_pdf(html)
