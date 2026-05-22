#!/usr/bin/env python3
"""
Gera PDF com fluxogramas a partir de docs/FLUXOS_DENIALFLOW_EVA.md.

Requisitos: Node.js (npx), markdown, playwright (+ chromium).
Uso: python scripts/generate_fluxos_pdf.py
Saída: docs/FLUXOS_DENIALFLOW_EVA.pdf
"""
from __future__ import annotations

import base64
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MD_PATH = ROOT / "docs" / "FLUXOS_DENIALFLOW_EVA.md"
OUT_PDF = ROOT / "docs" / "FLUXOS_DENIALFLOW_EVA.pdf"
MERMAID_CLI = "@mermaid-js/mermaid-cli@11.4.0"


def _require_import(name: str, pip_name: str) -> None:
    try:
        __import__(name)
    except ImportError as exc:
        raise SystemExit(f"Instale: pip install {pip_name}") from exc


def _extract_mermaid_blocks(md: str) -> list[str]:
    return re.findall(r"```mermaid\s*\n([\s\S]*?)```", md)


def _render_mermaid_pngs(blocks: list[str], work: Path) -> list[Path]:
    if not shutil.which("npx"):
        raise SystemExit("Node.js/npx nao encontrado. Instale Node para renderizar fluxogramas.")

    paths: list[Path] = []
    for i, src in enumerate(blocks):
        mmd = work / f"diagram_{i:02d}.mmd"
        png = work / f"diagram_{i:02d}.png"
        mmd.write_text(src.strip() + "\n", encoding="utf-8")
        cmd = [
            "npx",
            "-y",
            MERMAID_CLI,
            "-i",
            str(mmd),
            "-o",
            str(png),
            "-b",
            "white",
            "-w",
            "1200",
        ]
        print(f"  Renderizando diagrama {i + 1}/{len(blocks)}...")
        subprocess.run(cmd, cwd=ROOT, check=True, shell=(sys.platform == "win32"))
        if not png.exists():
            raise RuntimeError(f"Falha ao gerar {png}")
        paths.append(png)
    return paths


def _png_data_uri(path: Path) -> str:
    b64 = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:image/png;base64,{b64}"


def _md_to_html_with_images(md: str, pngs: list[Path]) -> str:
    import markdown

    idx = 0

    def replacer(_match: re.Match[str]) -> str:
        nonlocal idx
        if idx >= len(pngs):
            return "<p><em>[diagrama nao renderizado]</em></p>"
        src = _png_data_uri(pngs[idx])
        n = idx + 1
        idx += 1
        return (
            f'<figure class="diagram"><img src="{src}" alt="Fluxograma {n}" '
            'style="max-width:100%;height:auto;"/></figure>'
        )

    md_no_mermaid = re.sub(r"```mermaid\s*\n[\s\S]*?```", replacer, md)
    body = markdown.markdown(
        md_no_mermaid,
        extensions=["tables", "fenced_code", "toc"],
        extension_configs={"toc": {"permalink": False}},
    )
    return f"""<!DOCTYPE html>
<html lang="pt-BR">
<head>
  <meta charset="utf-8"/>
  <title>DenialFlow AI — Fluxos EVA</title>
  <style>
    @page {{
      size: A4;
      margin: 2cm 1.8cm;
    }}
    body {{
      font-family: "Segoe UI", Helvetica, Arial, sans-serif;
      font-size: 10.5pt;
      line-height: 1.45;
      color: #1a1a1a;
    }}
    h1 {{
      font-size: 20pt;
      color: #0d47a1;
      border-bottom: 2px solid #0d47a1;
      padding-bottom: 0.3em;
      page-break-after: avoid;
    }}
    h2 {{
      font-size: 14pt;
      color: #1565c0;
      margin-top: 1.4em;
      page-break-after: avoid;
    }}
    h3 {{
      font-size: 11.5pt;
      color: #1976d2;
      page-break-after: avoid;
    }}
    table {{
      border-collapse: collapse;
      width: 100%;
      font-size: 9pt;
      margin: 0.8em 0;
    }}
    th, td {{
      border: 1px solid #ccc;
      padding: 6px 8px;
      text-align: left;
    }}
    th {{
      background: #e3f2fd;
    }}
    figure.diagram {{
      text-align: center;
      margin: 1em 0;
      page-break-inside: avoid;
    }}
    figure.diagram img {{
      max-width: 100%;
    }}
    code {{
      background: #f5f5f5;
      padding: 1px 4px;
      font-size: 9pt;
    }}
    pre {{
      background: #f5f5f5;
      padding: 8px;
      font-size: 8.5pt;
      overflow-wrap: break-word;
      white-space: pre-wrap;
    }}
    hr {{
      border: none;
      border-top: 1px solid #ddd;
      margin: 1.5em 0;
    }}
    blockquote {{
      border-left: 4px solid #ff9800;
      margin: 1em 0;
      padding: 0.2em 1em;
      background: #fff8e1;
      font-size: 9.5pt;
    }}
  </style>
</head>
<body>
{body}
</body>
</html>"""


def _html_to_pdf_playwright(html_path: Path, pdf_path: Path) -> None:
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        page.goto(html_path.as_uri(), wait_until="networkidle")
        page.pdf(
            path=str(pdf_path),
            format="A4",
            margin={"top": "20mm", "bottom": "20mm", "left": "18mm", "right": "18mm"},
            print_background=True,
        )
        browser.close()


def main() -> None:
    _require_import("markdown", "markdown")
    _require_import("playwright", "playwright")

    if not MD_PATH.exists():
        raise SystemExit(f"Arquivo nao encontrado: {MD_PATH}")

    md = MD_PATH.read_text(encoding="utf-8")
    blocks = _extract_mermaid_blocks(md)
    print(f"Encontrados {len(blocks)} diagramas Mermaid em {MD_PATH.name}")

    with tempfile.TemporaryDirectory(prefix="denialflow_pdf_") as tmp:
        work = Path(tmp)
        pngs = _render_mermaid_pngs(blocks, work) if blocks else []
        html = _md_to_html_with_images(md, pngs)
        html_path = work / "fluxos.html"
        html_path.write_text(html, encoding="utf-8")

        OUT_PDF.parent.mkdir(parents=True, exist_ok=True)
        print(f"Gerando PDF: {OUT_PDF}")
        _html_to_pdf_playwright(html_path, OUT_PDF)

    print(f"OK — PDF salvo em: {OUT_PDF}")


if __name__ == "__main__":
    main()
