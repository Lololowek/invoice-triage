"""Five invoice layouts drawn with reportlab platypus.

kz_classic     Kazakh 1C-style "Счет на оплату": bank box on top, supplier/buyer lines, items grid
ru_requisites  Russian: requisites as a two-column key/value table, ИНН/КПП, р/с and к/с
en_modern      English: title + two-column header (seller | invoice meta), bill-to, totals box
en_compact     English: plain "Label: value" lines, no boxes
en_eu          English in a German letter layout: sender line, recipient | meta, footer bank line
"""

from __future__ import annotations

import os
from collections.abc import Callable
from datetime import date
from decimal import Decimal
from pathlib import Path
from xml.sax.saxutils import escape

from reportlab import rl_config
from reportlab.lib import colors
from reportlab.lib.enums import TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import Flowable, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from synth.specs import InvoiceDoc

FONT, BOLD = "DejaVuSans", "DejaVuSans-Bold"
_FONT_DIRS = [
    os.environ.get("SYNTH_FONT_DIR", ""),
    "/usr/share/fonts/truetype/dejavu",
    "/usr/share/fonts/dejavu",
    "/Library/Fonts",
    str(Path.home() / "Library/Fonts"),
    "C:/Windows/Fonts",
]


def register_fonts() -> None:
    rl_config.invariant = 1  # no timestamps or random ids: same input, same bytes
    for directory in filter(None, _FONT_DIRS):
        regular, bold = Path(directory, "DejaVuSans.ttf"), Path(directory, "DejaVuSans-Bold.ttf")
        if regular.exists() and bold.exists():
            pdfmetrics.registerFont(TTFont(FONT, str(regular)))
            pdfmetrics.registerFont(TTFont(BOLD, str(bold)))
            return
    raise SystemExit(
        "DejaVuSans.ttf / DejaVuSans-Bold.ttf not found (needed for Cyrillic). "
        "Install fonts-dejavu or set SYNTH_FONT_DIR. The committed PDFs work without this."
    )


P = ParagraphStyle("p", fontName=FONT, fontSize=9, leading=12)
PB = ParagraphStyle("pb", parent=P, fontName=BOLD)
PR = ParagraphStyle("pr", parent=P, alignment=TA_RIGHT)
PBR = ParagraphStyle("pbr", parent=PB, alignment=TA_RIGHT)
H = ParagraphStyle("h", fontName=BOLD, fontSize=14, leading=18, spaceAfter=6)
SMALL = ParagraphStyle("s", parent=P, fontSize=7.5, leading=10)

NBSP = "\u00a0"
RU_MONTHS = ["января", "февраля", "марта", "апреля", "мая", "июня", "июля", "августа",
             "сентября", "октября", "ноября", "декабря"]  # fmt: skip
EN_MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August",
             "September", "October", "November", "December"]  # fmt: skip


def para(text: str, style: ParagraphStyle = P) -> Paragraph:
    return Paragraph(escape(text).replace("\n", "<br/>"), style)


# --- formatting ---


class Fmt:
    def __init__(self, doc: InvoiceDoc) -> None:
        self.doc = doc

    def number(self, value: Decimal, decimals: int = 2) -> str:
        sign = "-" if value < 0 else ""
        text = f"{abs(value):.{decimals}f}" if decimals else format(abs(value).normalize(), "f")
        int_part, _, frac = text.partition(".")
        groups = []
        while len(int_part) > 3:
            groups.insert(0, int_part[-3:])
            int_part = int_part[:-3]
        groups.insert(0, int_part)
        thousands, decimal_sep = {"ru": (NBSP, ","), "en": (",", "."), "de": (".", ",")}[
            self.doc.num_locale
        ]
        result = thousands.join(groups) + (decimal_sep + frac if frac else "")
        return sign + result

    def money(self, value: Decimal) -> str:
        return self.number(value)

    def money_cur(self, value: Decimal) -> str:
        amount = self.money(value)
        match self.doc.currency_style:
            case "prefix":
                return f"{self.doc.currency_label}{amount}"
            case "suffix":
                return f"{amount} {self.doc.currency_label}"
        return amount

    def qty(self, value: Decimal) -> str:
        if value == value.to_integral_value():
            return str(int(value))
        return self.number(value, decimals=0)

    def date(self, value: date) -> str:
        match self.doc.date_style:
            case "dmy":
                return value.strftime("%d.%m.%Y")
            case "ru_text":
                return f"{value.day} {RU_MONTHS[value.month - 1]} {value.year} г."
            case "ru_text_q":
                return f"«{value.day:02d}» {RU_MONTHS[value.month - 1]} {value.year} г."
            case "en_text":
                return f"{value.day:02d} {EN_MONTHS[value.month - 1][:3]} {value.year}"
            case "en_long":
                return f"{EN_MONTHS[value.month - 1]} {value.day}, {value.year}"
        return value.isoformat()

    def extra(self, template: str, dates: tuple[date, ...]) -> str:
        return template.format(*(self.date(x) for x in dates))


def label(doc: InvoiceDoc, key: str, default: str) -> str:
    return doc.labels.get(key, default)


def grouped_iban(value: str) -> str:
    return " ".join(value[i : i + 4] for i in range(0, len(value), 4))


# --- shared blocks ---

GRID = [
    ("FONTNAME", (0, 0), (-1, -1), FONT),
    ("FONTSIZE", (0, 0), (-1, -1), 9),
    ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
    ("VALIGN", (0, 0), (-1, -1), "TOP"),
]
PLAIN = [("FONTNAME", (0, 0), (-1, -1), FONT), ("FONTSIZE", (0, 0), (-1, -1), 9),
         ("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 0)]  # fmt: skip


def items_table(doc: InvoiceDoc, headers: list[str], with_unit: bool, numbered: bool) -> Table:
    f = Fmt(doc)
    rows: list[list[object]] = [[para(h, PB) for h in headers]]
    for n, item in enumerate(doc.items, 1):
        row: list[object] = [str(n)] if numbered else []
        row += [para(item.description), f.qty(item.quantity)]
        if with_unit:
            row.append(item.unit)
        row += [f.money(item.unit_price), f.money(item.amount)]
        rows.append(row)
    widths = ([22] if numbered else []) + [230 if with_unit else 260, 50]
    widths += [45] if with_unit else []
    widths += [85, 90]
    table = Table(rows, colWidths=widths, repeatRows=1)
    numeric_from = len(widths) - 2
    table.setStyle(TableStyle([*GRID, ("ALIGN", (numeric_from, 1), (-1, -1), "RIGHT")]))
    return table


def totals_table(rows: list[tuple[str, str]], bold_last: bool = True) -> Table:
    data = []
    for i, (name, value) in enumerate(rows):
        style = PBR if bold_last and i == len(rows) - 1 else PR
        data.append([para(name, style), para(value, style)])
    table = Table(data, colWidths=[330, 150], hAlign="RIGHT")
    table.setStyle(TableStyle(PLAIN))
    return table


def standard_totals(doc: InvoiceDoc, names: dict[str, str]) -> list[tuple[str, str]]:
    f = Fmt(doc)
    subtotal, tax, total = doc.totals()
    rows: list[tuple[str, str]] = []
    if subtotal is not None:
        rows.append((names["subtotal"], f.money_cur(subtotal)))
    if tax is not None:
        rows.append((names["tax"], f.money_cur(tax)))
    rows.append((names["total"], f.money_cur(total)))
    return rows


def kv_table(
    rows: list[tuple[str, str]], widths: tuple[int, int] = (150, 380), grid: bool = False
) -> Table:
    table = Table([[para(k, PB), para(v)] for k, v in rows], colWidths=list(widths))
    table.setStyle(TableStyle(GRID if grid else PLAIN))
    return table


def rate_text(doc: InvoiceDoc) -> str:
    return f"{doc.vat_rate.normalize():f}" if doc.vat_rate is not None else ""


# --- layouts ---


def kz_classic(doc: InvoiceDoc) -> list[Flowable]:
    f, s, b = Fmt(doc), doc.supplier, doc.buyer
    bank = Table(
        [
            [para("Бенефициар:", PB), para("ИИК", PB), para("Кбе", PB)],
            [para(s.name), para(s.account or ""), para("17")],
            [para(f"БИН: {s.tax_id}"), "", ""],
            [para("Банк бенефициара:", PB), para("БИК", PB), para("Код назначения платежа", PB)],
            [para(s.bank_name or ""), para(s.bank_code or ""), para("859")],
        ],
        colWidths=[230, 170, 130],
    )
    bank.setStyle(TableStyle(GRID))
    title = f"{label(doc, 'title', 'Счет на оплату')} № {doc.invoice_number} от {f.date(doc.issue_date)}"
    rows = [
        ("Поставщик:", f"БИН / ИИН {s.tax_id}, {s.name}, {s.address}"),
        ("Покупатель:", f"БИН / ИИН {b.tax_id}, {b.name}, {b.address}"),
    ]
    if doc.contract_number and doc.contract_date:
        contract = label(doc, "contract", "Договор")
        rows.append(
            ("Договор:", f"{contract} № {doc.contract_number} от {f.date(doc.contract_date)}")
        )
    rows += [(e.label + ":", f.extra(e.template, e.dates)) for e in doc.extras]
    if doc.due_date:
        rows.append((label(doc, "due_date", "Оплатить до") + ":", f.date(doc.due_date)))
    _, tax, total = doc.totals()
    totals = [("Итого:", f.money(total))]
    if tax is not None:
        totals.append((f"В том числе НДС {rate_text(doc)}%:", f.money(tax)))
    story: list[Flowable] = [
        bank, Spacer(1, 14), para(title, H), kv_table(rows, (100, 430)), Spacer(1, 10),
        items_table(doc, ["№", "Наименование", "Кол-во", "Ед.", "Цена", "Сумма"], True, True),
        Spacer(1, 6), totals_table(totals, bold_last=False), Spacer(1, 8),
        para(f"Всего наименований {len(doc.items)}, на сумму {f.money(total)} {doc.currency_label}"),
        para(f"Всего к оплате: {f.money_cur(total)}", PB),
    ]  # fmt: skip
    if doc.payment_terms:
        story.append(para(f"Условия оплаты: {doc.payment_terms}"))
    story += [Spacer(1, 24), para("Исполнитель ____________________ /Директор/")]
    return story


def ru_requisites(doc: InvoiceDoc) -> list[Flowable]:
    f, s, b = Fmt(doc), doc.supplier, doc.buyer
    rows = [(label(doc, "issue_date", "Дата счёта"), f.date(doc.issue_date))]
    if doc.due_date:
        rows.append((label(doc, "due_date", "Срок оплаты"), f.date(doc.due_date)))
    if doc.contract_number and doc.contract_date:
        contract = label(doc, "contract", "Договор")
        rows.append(
            ("Основание", f"{contract} № {doc.contract_number} от {f.date(doc.contract_date)}")
        )
    rows += [(e.label, f.extra(e.template, e.dates)) for e in doc.extras]
    rows += [
        (label(doc, "supplier", "Поставщик"), s.name),
        ("ИНН / КПП", f"{s.tax_id} / {s.kpp}"),
        ("Банк", s.bank_name or ""),
        ("БИК", s.bank_code or ""),
        ("Р/с", s.account or ""),
        ("К/с", s.corr_account or ""),
        ("Адрес", s.address),
        (label(doc, "buyer", "Покупатель"), b.name),
        ("ИНН / КПП", f"{b.tax_id} / {b.kpp}"),
        ("Адрес", b.address),
    ]
    cur = doc.currency_label
    if doc.vat_mode == "none":
        _, _, total = doc.totals()
        totals = [
            ("Итого:", f.money(total)),
            ("НДС:", "Без НДС"),
            ("Всего к оплате:", f.money(total)),
        ]
    else:
        totals = standard_totals(
            doc,
            {
                "subtotal": "Сумма без НДС:",
                "tax": f"НДС {rate_text(doc)}%:",
                "total": "Итого к оплате:",
            },
        )
    story: list[Flowable] = [
        para(f"{label(doc, 'title', 'Счёт')} № {doc.invoice_number}", H),
        kv_table(rows, (150, 380), grid=True), Spacer(1, 12),
        items_table(doc, ["№", "Наименование работ, услуг", "Кол-во", "Ед.", f"Цена, {cur}",
                          f"Сумма, {cur}"], True, True),
        Spacer(1, 6), totals_table(totals),
    ]  # fmt: skip
    if doc.payment_terms:
        story += [Spacer(1, 8), para(f"Условия оплаты: {doc.payment_terms}")]
    story += [Spacer(1, 24), para("Генеральный директор ____________________")]
    return story


def en_modern(doc: InvoiceDoc) -> list[Flowable]:
    f, s, b = Fmt(doc), doc.supplier, doc.buyer
    head = Table(
        [[para(label(doc, "title", "INVOICE"), H), para(s.name, PBR)]], colWidths=[265, 265]
    )
    head.setStyle(TableStyle(PLAIN))
    meta = [(label(doc, "number", "Invoice no."), doc.invoice_number),
            (label(doc, "issue_date", "Invoice date"), f.date(doc.issue_date))]  # fmt: skip
    if doc.due_date:
        meta.append((label(doc, "due_date", "Due date"), f.date(doc.due_date)))
    meta += [(e.label, f.extra(e.template, e.dates)) for e in doc.extras]
    if doc.contract_number:
        meta.append((label(doc, "contract", "Agreement ref"), doc.contract_number))
    left = f"From\n{s.name}\n{s.address}\n{label(doc, 'vat', 'VAT reg. no.')}: {s.tax_id}"
    right = "\n".join(f"{k}: {v}" for k, v in meta)
    top = Table([[para(left), para(right)]], colWidths=[265, 265])
    top.setStyle(TableStyle(PLAIN))
    bill_to = f"{label(doc, 'buyer', 'Bill to')}\n{b.name}\n{b.address}\nVAT: {b.tax_id}"
    cur = doc.currency
    rate = rate_text(doc)
    totals = standard_totals(
        doc,
        {
            "subtotal": label(doc, "subtotal", "Subtotal"),
            "tax": label(doc, "tax", f"VAT ({rate}%)"),
            "total": f"{label(doc, 'total', 'Total due')} ({cur})",
        },
    )
    story: list[Flowable] = [
        head, Spacer(1, 8), top, Spacer(1, 10), para(bill_to), Spacer(1, 12),
        items_table(doc, ["Description", "Qty", f"Unit price ({cur})", f"Amount ({cur})"], False, False),
        Spacer(1, 6), totals_table(totals), Spacer(1, 14),
        para("Payment details", PB),
        para(f"Bank: {s.bank_name}\nIBAN: {grouped_iban(s.account or '')}\nBIC: {s.bank_code}"),
    ]  # fmt: skip
    if doc.payment_terms:
        story += [Spacer(1, 6), para(f"Terms: {doc.payment_terms}")]
    return story


def en_compact(doc: InvoiceDoc) -> list[Flowable]:
    f, s, b = Fmt(doc), doc.supplier, doc.buyer
    lines = [f"{label(doc, 'issue_date', 'Date')}: {f.date(doc.issue_date)}"]
    if doc.due_date:
        lines.append(f"{label(doc, 'due_date', 'Due date')}: {f.date(doc.due_date)}")
    lines += [f"{e.label}: {f.extra(e.template, e.dates)}" for e in doc.extras]
    if doc.contract_number:
        lines.append(f"{label(doc, 'contract', 'Contract')} {doc.contract_number}")
    lines += [
        "",
        f"Seller: {s.name}, {s.address}, VAT {s.tax_id}",
        f"Buyer: {b.name}, {b.address}, {'BIN' if b.tax_id.isdigit() else 'VAT'} {b.tax_id}",
    ]
    cur = doc.currency
    if doc.vat_mode == "none":
        total = doc.totals()[2]
        totals = [("VAT: not applicable, export of services", ""),
                  (label(doc, "total", "Total"), f.money_cur(total))]  # fmt: skip
    else:
        totals = standard_totals(
            doc,
            {
                "subtotal": label(doc, "subtotal", "Subtotal"),
                "tax": label(doc, "tax", f"VAT {rate_text(doc)}%"),
                "total": label(doc, "total", "Total"),
            },
        )
    story: list[Flowable] = [
        para(s.name, PB),
        para(f"{label(doc, 'title', 'Invoice')} {doc.invoice_number}", H),
        para("\n".join(lines)), Spacer(1, 12),
        items_table(doc, ["Description", "Qty", "Unit", f"Price, {cur}", f"Amount, {cur}"], True, False),
        Spacer(1, 6), totals_table(totals), Spacer(1, 12),
        para(f"Bank: {s.bank_name}, IBAN {s.account}, SWIFT {s.bank_code}"),
    ]  # fmt: skip
    if doc.payment_terms:
        story.append(para(f"Terms: {doc.payment_terms}"))
    return story


def en_eu(doc: InvoiceDoc) -> list[Flowable]:
    f, s, b = Fmt(doc), doc.supplier, doc.buyer
    meta = [("Invoice no.", doc.invoice_number), ("Invoice date", f.date(doc.issue_date))]
    meta += [(e.label, f.extra(e.template, e.dates)) for e in doc.extras]
    contract_in_meta = "contract" in doc.labels
    if doc.contract_number and contract_in_meta:
        meta.append((doc.labels["contract"], doc.contract_number))
    recipient = f"{b.name}\n{b.address}\nVAT ID {b.tax_id}"
    top = Table(
        [[para(recipient), para("\n".join(f"{k}: {v}" for k, v in meta))]], colWidths=[265, 265]
    )
    top.setStyle(TableStyle(PLAIN))
    if doc.contract_number and not contract_in_meta:
        intro = f"Our services according to framework agreement no. {doc.contract_number}:"
    else:
        intro = "We hereby invoice the following:"
    totals = standard_totals(
        doc, {"subtotal": "Net amount", "tax": f"VAT {rate_text(doc)}%", "total": "Amount due"}
    )
    story: list[Flowable] = [
        para(f"{s.name} · {s.address}", SMALL), Spacer(1, 10), top, Spacer(1, 14),
        para(f"Invoice {doc.invoice_number}", H), para(intro), Spacer(1, 8),
        items_table(doc, ["Pos.", "Description", "Quantity", "Unit price", "Total"], False, True),
        Spacer(1, 6), totals_table(totals), Spacer(1, 12),
    ]  # fmt: skip
    if doc.due_date:
        story.append(
            para(f"Please transfer the amount by {f.date(doc.due_date)} to the account below.")
        )
    if doc.payment_terms:
        story.append(para(f"Terms of payment: {doc.payment_terms}"))
    vat_label = label(doc, "vat", "VAT ID")
    story += [
        Spacer(1, 30),
        para(f"{s.name} · {vat_label} {s.tax_id}", SMALL),
        para(f"{s.bank_name} · IBAN {grouped_iban(s.account or '')} · BIC {s.bank_code}", SMALL),
    ]
    return story


LAYOUTS: dict[str, Callable[[InvoiceDoc], list[Flowable]]] = {
    "kz_classic": kz_classic,
    "ru_requisites": ru_requisites,
    "en_modern": en_modern,
    "en_compact": en_compact,
    "en_eu": en_eu,
}


def render(doc: InvoiceDoc, path: Path) -> None:
    template = SimpleDocTemplate(
        str(path), pagesize=A4, leftMargin=32, rightMargin=32, topMargin=36, bottomMargin=36,
        title=f"{doc.supplier.name} {doc.invoice_number}", author="synthetic", creator="invoice-triage",
    )  # fmt: skip
    template.build(LAYOUTS[doc.layout](doc))
