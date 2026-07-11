from __future__ import annotations

import html
import json
from typing import Any, Dict, List


def cell_source_lines(source: str) -> List[str]:
    text = source or ""
    if not text:
        return []
    return [line + "\n" for line in text.splitlines()]


def code_source_for_cell(cell: Dict[str, Any]) -> str:
    source = str(cell.get("source") or "")
    cell_type = str(cell.get("cellType") or "python")
    if cell_type == "sql":
        return f"# ATLAS cell type: SQL\n# Execute through ATLAS SQL Data Studio preview engine.\n{source}"
    if cell_type == "r":
        return f"# ATLAS cell type: R\n# Execute through ATLAS R local runtime when available.\n{source}"
    if cell_type == "sas_compatible":
        return f"# ATLAS cell type: SAS-compatible\n# No SAS license required for ATLAS SAS-compatible mode.\n{source}"
    return source


def output_to_nb(cell: Dict[str, Any]) -> List[Dict[str, Any]]:
    output = cell.get("output") or {}
    streams: List[Dict[str, Any]] = []
    stdout = str(output.get("stdout") or output.get("listing") or "")
    stderr = str(output.get("stderr") or output.get("error") or output.get("log") or "")
    if stdout:
        streams.append({"name": "stdout", "output_type": "stream", "text": cell_source_lines(stdout)})
    if stderr:
        streams.append({"name": "stderr", "output_type": "stream", "text": cell_source_lines(stderr)})
    rows = output.get("rows")
    if isinstance(rows, list) and rows:
        streams.append(
            {
                "output_type": "execute_result",
                "execution_count": None,
                "metadata": {},
                "data": {"text/plain": json.dumps(rows[:20], indent=2).splitlines(True)},
            }
        )
    for image in (output.get("images") or [])[:5]:
        if isinstance(image, dict) and image.get("data"):
            streams.append(
                {
                    "output_type": "display_data",
                    "metadata": {},
                    "data": {
                        str(image.get("mimeType") or "image/png"): str(image.get("data") or ""),
                        "text/plain": str(image.get("alt") or "ATLAS notebook image"),
                    },
                }
            )
    return streams


def build_ipynb(notebook: Dict[str, Any]) -> Dict[str, Any]:
    cells = [
        {
            "cell_type": "markdown",
            "metadata": {},
            "source": cell_source_lines(
                f"# {notebook.get('name') or 'ATLAS Notebook'}\n\n"
                "Generated from ATLAS Notebook Studio. Review dataset lineage, execution context, and governance warnings before relying on outputs."
            ),
        }
    ]
    for cell in notebook.get("cells") or []:
        cell_type = str(cell.get("cellType") or "markdown")
        if cell_type == "markdown":
            cells.append({"cell_type": "markdown", "metadata": {}, "source": cell_source_lines(str(cell.get("source") or ""))})
        else:
            cells.append(
                {
                    "cell_type": "code",
                    "execution_count": None,
                    "metadata": {"atlas_cell_type": cell_type},
                    "outputs": output_to_nb(cell),
                    "source": cell_source_lines(code_source_for_cell(cell)),
                }
            )
    return {
        "cells": cells,
        "metadata": {
            "kernelspec": {"display_name": "ATLAS", "language": "python", "name": "atlas"},
            "language_info": {"name": "python"},
            "atlas": {
                "notebookId": notebook.get("notebookId"),
                "projectId": notebook.get("projectId"),
                "primaryDatasetId": notebook.get("primaryDatasetId"),
                "previewRowsOnly": True,
            },
        },
        "nbformat": 4,
        "nbformat_minor": 5,
    }


def render_table(rows: Any) -> str:
    if not isinstance(rows, list) or not rows:
        return ""
    columns = list({key for row in rows[:25] if isinstance(row, dict) for key in row.keys()})[:12]
    if not columns:
        return ""
    body = []
    for row in rows[:50]:
        if isinstance(row, dict):
            body.append("<tr>" + "".join(f"<td>{html.escape(str(row.get(column, '')))}</td>" for column in columns) + "</tr>")
    return (
        "<div class='table-wrap'><table><thead><tr>"
        + "".join(f"<th>{html.escape(str(column))}</th>" for column in columns)
        + "</tr></thead><tbody>"
        + "".join(body)
        + "</tbody></table></div>"
    )


def render_images(images: Any) -> str:
    if not isinstance(images, list) or not images:
        return ""
    rendered = []
    for image in images[:5]:
        if not isinstance(image, dict) or not image.get("data"):
            continue
        mime_type = html.escape(str(image.get("mimeType") or "image/png"))
        data = html.escape(str(image.get("data") or ""))
        alt = html.escape(str(image.get("alt") or "ATLAS notebook chart"))
        rendered.append(f"<figure><img src='data:{mime_type};base64,{data}' alt='{alt}' /><figcaption>{alt}</figcaption></figure>")
    return "<div class='image-grid'>" + "".join(rendered) + "</div>" if rendered else ""


def render_markdown(source: str) -> str:
    pieces = []
    for line in (source or "").splitlines():
        escaped = html.escape(line)
        if line.startswith("# "):
            pieces.append(f"<h2>{html.escape(line[2:])}</h2>")
        elif line.startswith("## "):
            pieces.append(f"<h3>{html.escape(line[3:])}</h3>")
        elif line.startswith("### "):
            pieces.append(f"<h4>{html.escape(line[4:])}</h4>")
        elif line.startswith("- "):
            pieces.append(f"<li>{html.escape(line[2:])}</li>")
        elif not line.strip():
            pieces.append("<br />")
        else:
            pieces.append(f"<p>{escaped}</p>")
    return "<div class='markdown'>" + "".join(pieces) + "</div>"


def build_html(notebook: Dict[str, Any]) -> str:
    cells_html = []
    for index, cell in enumerate(notebook.get("cells") or [], start=1):
        output = cell.get("output") or {}
        rows = output.get("rows") or []
        tables = output.get("tables") or []
        table_html = render_table(rows)
        if not table_html and isinstance(tables, list) and tables:
            table_html = render_table((tables[0] or {}).get("rows"))
        image_html = render_images(output.get("images"))
        source_html = render_markdown(str(cell.get("source") or "")) if str(cell.get("cellType") or "") == "markdown" else f"<pre class='source'>{html.escape(str(cell.get('source') or ''))}</pre>"
        cells_html.append(
            f"""
            <section class="cell">
              <div class="cell-meta">Cell {index} - {html.escape(str(cell.get('cellType') or 'markdown'))} - {html.escape(str(output.get('status') or 'idle'))}</div>
              {source_html}
              {f"<pre class='stdout'>{html.escape(str(output.get('stdout') or output.get('listing') or ''))}</pre>" if output.get('stdout') or output.get('listing') else ""}
              {f"<pre class='stderr'>{html.escape(str(output.get('stderr') or output.get('error') or output.get('log') or ''))}</pre>" if output.get('stderr') or output.get('error') or output.get('log') else ""}
              {table_html}
              {image_html}
            </section>
            """
        )
    warnings = notebook.get("governance", {}).get("warnings", [])
    warning_html = "".join(f"<li>{html.escape(str(warning))}</li>" for warning in warnings)
    return f"""<!doctype html>
<html>
<head>
  <meta charset="utf-8" />
  <title>{html.escape(str(notebook.get('name') or 'ATLAS Notebook'))}</title>
  <style>
    body {{ margin: 0; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; color: #0f172a; background: #f8fafc; }}
    main {{ max-width: 1120px; margin: 0 auto; padding: 32px; }}
    header, .cell {{ background: white; border: 1px solid #e2e8f0; border-radius: 14px; padding: 20px; margin-bottom: 16px; box-shadow: 0 1px 2px rgba(15,23,42,0.05); }}
    h1 {{ margin: 0; font-size: 28px; }}
    .meta, .cell-meta {{ color: #64748b; font-size: 13px; font-weight: 600; margin-top: 8px; }}
    pre {{ white-space: pre-wrap; word-break: break-word; border-radius: 10px; padding: 12px; overflow: auto; }}
    .source {{ background: #f1f5f9; }}
    .stdout {{ background: #ecfdf5; border: 1px solid #bbf7d0; }}
    .stderr {{ background: #fff1f2; border: 1px solid #fecdd3; }}
    .table-wrap {{ overflow-x: auto; border: 1px solid #e2e8f0; border-radius: 10px; }}
    table {{ border-collapse: collapse; width: 100%; font-size: 13px; }}
    th {{ background: #f8fafc; color: #334155; text-align: left; position: sticky; top: 0; }}
    th, td {{ border-bottom: 1px solid #e2e8f0; padding: 8px 10px; vertical-align: top; }}
    tr:nth-child(even) td {{ background: #f8fafc; }}
    .image-grid {{ display: grid; gap: 14px; margin-top: 14px; }}
    figure {{ margin: 0; border: 1px solid #e2e8f0; border-radius: 12px; padding: 12px; background: #fff; }}
    img {{ max-width: 100%; height: auto; display: block; }}
    figcaption {{ color: #64748b; font-size: 12px; margin-top: 8px; }}
    .markdown p {{ line-height: 1.6; }}
  </style>
</head>
<body>
<main>
  <header>
    <h1>ATLAS Notebook Studio</h1>
    <div class="meta">{html.escape(str(notebook.get('name') or 'Untitled Notebook'))} - Project: {html.escape(str(notebook.get('projectName') or notebook.get('projectId') or 'Not linked'))}</div>
    <p>Governed notebook artifact generated by ATLAS. Outputs are compacted for review and documentation.</p>
    <ul>{warning_html}</ul>
  </header>
  {''.join(cells_html)}
</main>
</body>
</html>"""
