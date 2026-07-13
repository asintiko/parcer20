#!/usr/bin/env python3
"""Build a styled, auto-refreshing Чеки.xlsx for the transaction feed.

The workbook embeds a Power Query (DataMashup) that hits the static-key feed
endpoint and refreshes on open, so the customer always sees live data. The
visual styling mirrors the in-app server export (excelExport.ts): grey bold
header, thin slate borders, banded rows, right-aligned thousands-separated
amounts, frozen header, autofilter.

Styling is applied via a custom table style (wholeTable / headerRow /
firstRowStripe dxfs) plus per-column default cell formats, so the look
auto-extends to rows added by a Power Query refresh — not just the rows
pre-baked here.

Usage:
    python3 build_workbook.py                 # fetch live feed, write Чеки.xlsx
    python3 build_workbook.py --offline FILE  # build from a cached feed JSON
    python3 build_workbook.py -o OUT.xlsx     # custom output path
"""
from __future__ import annotations

import argparse
import json
import os
import urllib.request
import zipfile
from pathlib import Path
from typing import Any, Dict, List
from xml.sax.saxutils import escape

HERE = Path(__file__).resolve().parent
TEMPLATE = HERE / "_template"

FEED_URL = (
    "https://64.188.106.221.nip.io/api/feed/transactions"
    "?key=Xh8vMq18Jzk7gekqFr8kMppCfL-1mLLFTo-Q2YhIm7I"
)

# Column id -> (Russian header, alignment, fixed width or None -> dynamic, is_number)
COLUMNS: List[Dict[str, Any]] = [
    {"id": "operation_number",  "h": "№ опер.",           "align": "center", "w": 9,    "num": False},
    {"id": "date_time",         "h": "Дата и Время",      "align": "center", "w": 18,   "num": False},
    {"id": "transaction_date",  "h": "Дата",              "align": "center", "w": 12,   "num": False},
    {"id": "time",              "h": "Время",             "align": "center", "w": 10,   "num": False},
    {"id": "day",               "h": "День",              "align": "center", "w": 6,    "num": False},
    {"id": "operator_raw",      "h": "Оператор/Продавец", "align": "left",   "w": None, "num": False},
    {"id": "application_mapped","h": "Приложение",        "align": "center", "w": None, "num": False},
    {"id": "receiver_name",     "h": "Получатель",        "align": "left",   "w": None, "num": False},
    {"id": "receiver_card",     "h": "Карта получателя",  "align": "center", "w": None, "num": False},
    {"id": "amount",            "h": "Сумма",             "align": "right",  "w": 15,   "num": True},
    {"id": "balance_after",     "h": "Остаток",           "align": "right",  "w": 15,   "num": True},
    {"id": "card_last_4",       "h": "ПК",                "align": "center", "w": 6,    "num": False},
    {"id": "is_p2p",            "h": "П2П",               "align": "center", "w": 6,    "num": False},
    {"id": "transaction_type",  "h": "Тип",               "align": "center", "w": 12,   "num": False},
    {"id": "currency",          "h": "Валюта",            "align": "center", "w": 8,    "num": False},
    {"id": "source_type",       "h": "Источник",          "align": "center", "w": 13,   "num": False},
]
N = len(COLUMNS)  # 16 -> column P

# cellXfs indices (see _styles_xml)
XF_DEFAULT = 0
XF_HEADER = 1
XF_LEFT = 2
XF_CENTER = 3
XF_NUM = 4
ALIGN_XF = {"left": XF_LEFT, "center": XF_CENTER, "right": XF_NUM}


def col_letter(idx: int) -> str:
    s = ""
    idx += 1
    while idx:
        idx, r = divmod(idx - 1, 26)
        s = chr(65 + r) + s
    return s


def fetch_rows(offline: str | None) -> List[Dict[str, Any]]:
    if offline:
        payload = json.loads(Path(offline).read_text(encoding="utf-8"))
    else:
        req = urllib.request.Request(FEED_URL, headers={"Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=60) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    return payload.get("rows", [])


def _styles_xml() -> str:
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        '<numFmts count="1"><numFmt numFmtId="164" formatCode="#,##0.00"/></numFmts>'
        '<fonts count="3">'
        '<font><sz val="11"/><name val="Calibri"/></font>'
        '<font><b/><sz val="10"/><color rgb="FF0F172A"/><name val="Calibri"/></font>'
        '<font><sz val="10"/><name val="Calibri"/></font>'
        '</fonts>'
        '<fills count="4">'
        '<fill><patternFill patternType="none"/></fill>'
        '<fill><patternFill patternType="gray125"/></fill>'
        '<fill><patternFill patternType="solid"><fgColor rgb="FFE5E7EB"/></patternFill></fill>'
        '<fill><patternFill patternType="solid"><fgColor rgb="FFF8FAFC"/></patternFill></fill>'
        '</fills>'
        '<borders count="2">'
        '<border><left/><right/><top/><bottom/><diagonal/></border>'
        '<border>'
        '<left style="thin"><color rgb="FFCBD5E1"/></left>'
        '<right style="thin"><color rgb="FFCBD5E1"/></right>'
        '<top style="thin"><color rgb="FFCBD5E1"/></top>'
        '<bottom style="thin"><color rgb="FFCBD5E1"/></bottom>'
        '<diagonal/></border>'
        '</borders>'
        '<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>'
        '<cellXfs count="5">'
        # 0 default
        '<xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/>'
        # 1 header: bold font, header fill, border, centered
        '<xf numFmtId="0" fontId="1" fillId="2" borderId="1" xfId="0" applyFont="1" applyFill="1" applyBorder="1" applyAlignment="1"><alignment horizontal="center" vertical="center"/></xf>'
        # 2 data left
        '<xf numFmtId="0" fontId="2" fillId="0" borderId="1" xfId="0" applyFont="1" applyBorder="1" applyAlignment="1"><alignment horizontal="left" vertical="center"/></xf>'
        # 3 data center
        '<xf numFmtId="0" fontId="2" fillId="0" borderId="1" xfId="0" applyFont="1" applyBorder="1" applyAlignment="1"><alignment horizontal="center" vertical="center"/></xf>'
        # 4 data number right
        '<xf numFmtId="164" fontId="2" fillId="0" borderId="1" xfId="0" applyNumberFormat="1" applyFont="1" applyBorder="1" applyAlignment="1"><alignment horizontal="right" vertical="center"/></xf>'
        '</cellXfs>'
        '<cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles>'
        '<dxfs count="3">'
        # 0 wholeTable: thin slate borders
        '<dxf><border><left style="thin"><color rgb="FFCBD5E1"/></left><right style="thin"><color rgb="FFCBD5E1"/></right><top style="thin"><color rgb="FFCBD5E1"/></top><bottom style="thin"><color rgb="FFCBD5E1"/></bottom></border></dxf>'
        # 1 headerRow: bold dark font + grey fill
        '<dxf><font><b/><color rgb="FF0F172A"/></font><fill><patternFill patternType="solid"><fgColor rgb="FFE5E7EB"/><bgColor rgb="FFE5E7EB"/></patternFill></fill></dxf>'
        # 2 firstRowStripe: very light slate
        '<dxf><fill><patternFill patternType="solid"><fgColor rgb="FFF8FAFC"/><bgColor rgb="FFF8FAFC"/></patternFill></fill></dxf>'
        '</dxfs>'
        '<tableStyles count="1" defaultTableStyle="TableStyleMedium2" defaultPivotStyle="PivotStyleLight16">'
        '<tableStyle name="ReceiptsStyle" pivot="0" count="3">'
        '<tableStyleElement type="wholeTable" dxfId="0"/>'
        '<tableStyleElement type="headerRow" dxfId="1"/>'
        '<tableStyleElement type="firstRowStripe" dxfId="2"/>'
        '</tableStyle>'
        '</tableStyles>'
        '</styleSheet>'
    )


def _cell(ref: str, xf: int, value: Any, is_num: bool) -> str:
    if is_num and isinstance(value, (int, float)):
        return f'<c r="{ref}" s="{xf}"><v>{value}</v></c>'
    text = "" if value is None else str(value)
    if text == "":
        return f'<c r="{ref}" s="{xf}"/>'
    return f'<c r="{ref}" s="{xf}" t="inlineStr"><is><t xml:space="preserve">{escape(text)}</t></is></c>'


def _sheet_xml(rows: List[Dict[str, Any]], dyn_widths: Dict[str, int]) -> str:
    last_row = len(rows) + 1
    last_col = col_letter(N - 1)

    cols_xml = ['<cols>']
    for i, c in enumerate(COLUMNS, start=1):
        w = c["w"] if c["w"] is not None else dyn_widths[c["id"]]
        style = ALIGN_XF[c["align"]]
        cols_xml.append(
            f'<col min="{i}" max="{i}" width="{w}" style="{style}" customWidth="1"/>'
        )
    cols_xml.append('</cols>')

    parts = [
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>',
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">',
        f'<dimension ref="A1:{last_col}{last_row}"/>',
        '<sheetViews><sheetView tabSelected="1" workbookViewId="0">'
        '<pane ySplit="1" topLeftCell="A2" activePane="bottomLeft" state="frozen"/>'
        '<selection pane="bottomLeft" activeCell="A2" sqref="A2"/>'
        '</sheetView></sheetViews>',
        '<sheetFormatPr defaultRowHeight="15"/>',
        "".join(cols_xml),
        '<sheetData>',
    ]

    # header row
    parts.append('<row r="1" ht="18" customHeight="1">')
    for i, c in enumerate(COLUMNS):
        ref = f"{col_letter(i)}1"
        parts.append(_cell(ref, XF_HEADER, c["h"], False))
    parts.append('</row>')

    # data rows
    for ridx, row in enumerate(rows, start=2):
        parts.append(f'<row r="{ridx}" ht="15" customHeight="1">')
        for i, c in enumerate(COLUMNS):
            ref = f"{col_letter(i)}{ridx}"
            xf = ALIGN_XF[c["align"]]
            parts.append(_cell(ref, xf, row.get(c["id"], ""), c["num"]))
        parts.append('</row>')

    parts.append('</sheetData>')
    parts.append(f'<autoFilter ref="A1:{last_col}{last_row}"/>')
    parts.append('<tableParts count="1"><tablePart r:id="rId1"/></tableParts>')
    parts.append('</worksheet>')
    return "".join(parts)


def _table_xml(n_rows: int) -> str:
    last_row = n_rows + 1
    last_col = col_letter(N - 1)
    cols = "".join(
        f'<tableColumn id="{i}" uniqueName="{i}" name="{escape(c["h"])}" queryTableFieldId="{i}"/>'
        for i, c in enumerate(COLUMNS, start=1)
    )
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<table xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
        f'id="1" name="Receipts" displayName="Receipts" ref="A1:{last_col}{last_row}" '
        'tableType="queryTable" totalsRowShown="0">'
        f'<autoFilter ref="A1:{last_col}{last_row}"/>'
        f'<tableColumns count="{N}">{cols}</tableColumns>'
        '<tableStyleInfo name="ReceiptsStyle" showFirstColumn="0" showLastColumn="0" '
        'showRowStripes="1" showColumnStripes="0"/>'
        '</table>'
    )


def _query_table_xml() -> str:
    fields = "".join(
        f'<queryTableField id="{i}" name="{escape(c["h"])}" tableColumnId="{i}"/>'
        for i, c in enumerate(COLUMNS, start=1)
    )
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<queryTable xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
        'name="Receipts" connectionId="1" autoFormatId="16" applyNumberFormats="0" '
        'applyBorderFormats="0" applyFontFormats="0" applyPatternFormats="0" '
        'applyAlignmentFormats="0" applyWidthHeightFormats="0" preserveFormatting="1">'
        f'<queryTableRefresh nextId="{N + 1}" preserveSortFilterLayout="0">'
        f'<queryTableFields count="{N}">{fields}</queryTableFields>'
        '</queryTableRefresh></queryTable>'
    )


CONNECTIONS_XML = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    '<connections xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
    '<connection id="1" name="Query - Receipts" '
    'description="Подключение к источнику Receipts в книге." type="5" '
    'refreshedVersion="6" minRefreshableVersion="5" refreshOnLoad="1" '
    'background="1" saveData="1">'
    '<dbPr connection="Provider=Microsoft.Mashup.OleDb.1;Data Source=$Workbook$;'
    'Location=Receipts;Extended Properties=&quot;&quot;" command="SELECT * FROM [Receipts]"/>'
    '</connection></connections>'
)

WORKBOOK_XML = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
    'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
    '<sheets><sheet name="Чеки" sheetId="1" r:id="rId1"/></sheets>'
    '</workbook>'
)

WORKBOOK_RELS = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
    '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>'
    '<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>'
    '<Relationship Id="rId3" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/connections" Target="connections.xml"/>'
    '<Relationship Id="rId4" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/customXml" Target="../customXml/item1.xml"/>'
    '</Relationships>'
)

SHEET_RELS = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
    '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/table" Target="../tables/table1.xml"/>'
    '</Relationships>'
)

TABLE_RELS = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
    '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/queryTable" Target="../queryTables/queryTable1.xml"/>'
    '</Relationships>'
)

CUSTOMXML_RELS = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
    '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/customXmlProps" Target="itemProps1.xml"/>'
    '</Relationships>'
)

ROOT_RELS = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
    '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>'
    '<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/package/2006/relationships/metadata/core-properties" Target="docProps/core.xml"/>'
    '<Relationship Id="rId3" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/extended-properties" Target="docProps/app.xml"/>'
    '</Relationships>'
)

CONTENT_TYPES = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
    '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
    '<Default Extension="xml" ContentType="application/xml"/>'
    '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
    '<Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
    '<Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>'
    '<Override PartName="/xl/connections.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.connections+xml"/>'
    '<Override PartName="/xl/tables/table1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.table+xml"/>'
    '<Override PartName="/xl/queryTables/queryTable1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.queryTable+xml"/>'
    '<Override PartName="/customXml/itemProps1.xml" ContentType="application/vnd.openxmlformats-officedocument.customXmlProperties+xml"/>'
    '<Override PartName="/docProps/core.xml" ContentType="application/vnd.openxmlformats-package.core-properties+xml"/>'
    '<Override PartName="/docProps/app.xml" ContentType="application/vnd.openxmlformats-officedocument.extended-properties+xml"/>'
    '</Types>'
)

DOCPROPS_CORE = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    '<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" '
    'xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:dcterms="http://purl.org/dc/terms/" '
    'xmlns:dcmitype="http://purl.org/dc/dcmitype/" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">'
    '<dc:title>Чеки</dc:title><dc:creator>TBSparcer</dc:creator>'
    '</cp:coreProperties>'
)

DOCPROPS_APP = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    '<Properties xmlns="http://schemas.openxmlformats.org/officeDocument/2006/extended-properties">'
    '<Application>Microsoft Excel</Application>'
    '</Properties>'
)


def compute_dynamic_widths(rows: List[Dict[str, Any]]) -> Dict[str, int]:
    widths: Dict[str, int] = {}
    for c in COLUMNS:
        if c["w"] is not None:
            continue
        max_len = len(c["h"])
        for row in rows:
            v = row.get(c["id"], "")
            ln = 0 if v is None else len(str(v))
            if ln > max_len:
                max_len = ln
        widths[c["id"]] = min(max(max_len + 1, 8), 40)
    return widths


def build(rows: List[Dict[str, Any]], out_path: Path) -> None:
    dyn = compute_dynamic_widths(rows)
    datamashup = (TEMPLATE / "datamashup_item1.xml").read_bytes()
    item_props = (TEMPLATE / "itemProps1.xml").read_bytes()

    files = {
        "[Content_Types].xml": CONTENT_TYPES,
        "_rels/.rels": ROOT_RELS,
        "docProps/core.xml": DOCPROPS_CORE,
        "docProps/app.xml": DOCPROPS_APP,
        "xl/workbook.xml": WORKBOOK_XML,
        "xl/_rels/workbook.xml.rels": WORKBOOK_RELS,
        "xl/styles.xml": _styles_xml(),
        "xl/connections.xml": CONNECTIONS_XML,
        "xl/worksheets/sheet1.xml": _sheet_xml(rows, dyn),
        "xl/worksheets/_rels/sheet1.xml.rels": SHEET_RELS,
        "xl/tables/table1.xml": _table_xml(len(rows)),
        "xl/tables/_rels/table1.xml.rels": TABLE_RELS,
        "xl/queryTables/queryTable1.xml": _query_table_xml(),
        "customXml/_rels/item1.xml.rels": CUSTOMXML_RELS,
    }

    out_path.parent.mkdir(parents=True, exist_ok=True)
    if out_path.exists():
        out_path.unlink()
    with zipfile.ZipFile(out_path, "w", zipfile.ZIP_DEFLATED) as z:
        for name, content in files.items():
            z.writestr(name, content)
        z.writestr("customXml/item1.xml", datamashup)
        z.writestr("customXml/itemProps1.xml", item_props)

    print(f"wrote {out_path}  ({out_path.stat().st_size} bytes, {len(rows)} rows)")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--offline", help="path to cached feed JSON instead of live fetch")
    ap.add_argument("-o", "--out", default=str(HERE / "Чеки.xlsx"))
    args = ap.parse_args()

    rows = fetch_rows(args.offline)
    if not rows:
        raise SystemExit("feed returned 0 rows; refusing to build an empty workbook")
    build(rows, Path(args.out))


if __name__ == "__main__":
    main()
