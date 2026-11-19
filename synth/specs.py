"""The 15 synthetic invoices. Single source of truth for both the PDFs and gold.json.

All companies, people, banks and identifiers are fictional; identifiers are generated with valid
checksums (synth/ids.py). Each document carries the traps the pipeline must survive: several dates,
several numbers, tax "в том числе", order / customer / delivery-note numbers next to (or instead of)
a contract number.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Literal

from synth import ids

D = Decimal
CENT = D("0.01")


def money(value: Decimal) -> Decimal:
    return value.quantize(CENT, rounding=ROUND_HALF_UP)


@dataclass(frozen=True)
class Party:
    name: str
    tax_id: str
    address: str
    kpp: str | None = None
    bank_name: str | None = None
    account: str | None = None  # IBAN / ИИК or Russian р/с
    bank_code: str | None = None  # BIC or БИК
    corr_account: str | None = None  # Russian к/с


@dataclass(frozen=True)
class Item:
    description: str
    quantity: Decimal
    unit_price: Decimal
    unit: str = ""

    @property
    def amount(self) -> Decimal:
        return money(self.quantity * self.unit_price)


@dataclass(frozen=True)
class Extra:
    """A labelled line that is NOT a schema field (order no., delivery date...) - a trap."""

    label: str
    template: str
    dates: tuple[date, ...] = ()


VatMode = Literal["excluded", "included", "none", "zero"]


@dataclass
class InvoiceDoc:
    file: str
    layout: str
    num_locale: Literal["ru", "en", "de"]
    date_style: Literal["dmy", "ru_text", "ru_text_q", "en_text", "en_long", "iso"]
    supplier: Party
    buyer: Party
    invoice_number: str
    issue_date: date
    currency: str
    currency_label: str
    currency_style: Literal["suffix", "prefix", "header"]
    items: list[Item]
    vat_mode: VatMode
    vat_rate: Decimal | None = None
    due_date: date | None = None
    contract_number: str | None = None
    contract_date: date | None = None
    payment_terms: str | None = None
    expense_category: str = "other"
    is_credit_note: bool = False
    extras: list[Extra] = field(default_factory=list)
    labels: dict[str, str] = field(default_factory=dict)
    notes: str = ""

    def totals(self) -> tuple[Decimal | None, Decimal | None, Decimal]:
        """(printed subtotal or None, tax or None, total)."""
        lines = sum((i.amount for i in self.items), D(0))
        rate = self.vat_rate or D(0)
        if self.vat_mode == "excluded":
            tax = money(lines * rate / 100)
            return lines, tax, lines + tax
        if self.vat_mode == "included":
            return None, money(lines * rate / (100 + rate)), lines
        if self.vat_mode == "zero":
            return lines, D("0.00"), lines
        return None, None, lines

    def gold(self) -> dict[str, Any]:
        subtotal, tax, total = self.totals()

        def amount(v: Decimal | None) -> str | None:
            return None if v is None else f"{v:.2f}"

        return {
            "fields": {
                "supplier_name": self.supplier.name,
                "supplier_tax_id": self.supplier.tax_id,
                "supplier_account": self.supplier.account,
                "supplier_bank_code": self.supplier.bank_code,
                "buyer_name": self.buyer.name,
                "buyer_tax_id": self.buyer.tax_id,
                "invoice_number": self.invoice_number.upper(),
                "contract_number": self.contract_number.upper() if self.contract_number else None,
                "issue_date": self.issue_date.isoformat(),
                "due_date": self.due_date.isoformat() if self.due_date else None,
                "currency": self.currency,
                "subtotal": amount(subtotal),
                "tax_amount": amount(tax),
                "total": amount(total),
                "payment_terms": self.payment_terms,
            },
            "line_items": [
                {
                    "description": i.description,
                    "quantity": format(i.quantity.normalize(), "f"),
                    "unit_price": f"{i.unit_price:.2f}",
                    "amount": f"{i.amount:.2f}",
                }
                for i in self.items
            ],
            "derived": {
                "expense_category": self.expense_category,
                "is_credit_note": self.is_credit_note,
            },
            "notes": self.notes,
        }


# --- parties ---

KESTREL_BIN = ids.kz_bin("kestrel", "1805")
KESTREL_KZ = Party("ТОО «Кестрел Дата»", KESTREL_BIN, "г. Астана, ул. Сыганак, 10")
KESTREL_KZ_EN = Party("Kestrel Data LLP", KESTREL_BIN, "10 Syganak St, Astana, Kazakhstan")
_kestrel_ru_inn = ids.ru_inn10("kestrel-ru", "77")
KESTREL_RU = Party(
    "ООО «Кестрел Дата Рус»",
    _kestrel_ru_inn,
    "г. Москва, ул. Лесная, 7",
    kpp=ids.ru_kpp(_kestrel_ru_inn),
)
KESTREL_UK = Party(
    "Kestrel Data UK Ltd", ids.vat("kestrel-uk", "GB"), "20 Wharf Road, London N1 7GR"
)
KESTREL_DE = Party("Kestrel Data GmbH", ids.vat("kestrel-de", "DE"), "Lindenstraße 8, 10969 Berlin")
KESTREL_NL = Party(
    "Kestrel Data B.V.", ids.vat("kestrel-nl", "NL"), "Keizersgracht 210, 1016 DZ Amsterdam"
)


def kz_supplier(
    key: str, name: str, address: str, registered: str, bank: str, bank_code: str
) -> Party:
    return Party(
        name, ids.kz_bin(key, registered), address,
        bank_name=bank, account=ids.kz_iban(key, bank_code), bank_code=ids.bic(key, "KZ"),
    )  # fmt: skip


def ru_supplier(key: str, name: str, address: str, region: str, bank: str) -> Party:
    inn = ids.ru_inn10(key, region)
    bik, account, corr = ids.ru_bank(key)
    return Party(
        name, inn, address, kpp=ids.ru_kpp(inn),
        bank_name=bank, account=account, bank_code=bik, corr_account=corr,
    )  # fmt: skip


def eu_supplier(key: str, name: str, address: str, country: str, bank: str) -> Party:
    return Party(
        name, ids.vat(key, country), address,
        bank_name=bank, account=ids.eu_iban(key, country), bank_code=ids.bic(key, country),
    )  # fmt: skip


ARNA = kz_supplier("arna", "ТОО «Арна Логистик»", "г. Алматы, ул. Желтоксан, 115", "1502",
                   "АО «Банк Жетысу Капитал»", "722")  # fmt: skip
TENGRI = kz_supplier("tengri", "ТОО «Тенгри Софт»", "г. Алматы, пр. Абая, 52", "1709",
                     "АО «Нурлы Банк»", "914")  # fmt: skip
KANZLER = kz_supplier("kanzler", "ТОО «Канцлер Плюс»", "г. Астана, ул. Кенесары, 40", "1311",
                      "АО «Банк Жетысу Капитал»", "722")  # fmt: skip
VETER = ru_supplier("veter", "ООО «Северный Ветер Консалтинг»", "г. Санкт-Петербург, наб. реки Мойки, 58",
                    "78", "ПАО «Балтийский Расчётный Банк»")  # fmt: skip
GRANAT = ru_supplier("granat", "ООО «Бизнес-центр Гранат»", "г. Москва, ул. Лесная, 7, стр. 2",
                     "77", "АО «Банк Сокольники»")  # fmt: skip
MEDIAKIT = ru_supplier("mediakit", "ООО «Медиа Кит»", "г. Москва, ул. Правды, 24", "77",
                       "АО «Банк Сокольники»")  # fmt: skip
BRIGHTLINE = eu_supplier("brightline", "Brightline Analytics Ltd", "4 Canal Street, Manchester M1 3HE",
                         "GB", "Northgate Bank plc")  # fmt: skip
VOSSBERG = eu_supplier("vossberg", "Vossberg Consulting B.V.", "Herengracht 182, 1016 BR Amsterdam",
                       "NL", "Polder Handelsbank N.V.")  # fmt: skip
LUMENTA = eu_supplier("lumenta", "Lumenta OÜ", "Narva mnt 7, 10117 Tallinn, Estonia", "EE",
                      "Harju Pank AS")  # fmt: skip
BALTIC = eu_supplier("baltic", "Baltic Rack Systems UAB", "Savanorių pr. 178, LT-03154 Vilnius",
                     "LT", "Nemunas Bankas AB")  # fmt: skip
CLIFFSIDE = eu_supplier("cliffside", "Cliffside Events Ltd", "12 Harbour Road, Howth, Dublin D13",
                        "IE", "Liffey Commercial Bank")  # fmt: skip
NORDWERK = eu_supplier("nordwerk", "Nordwerk Systems GmbH", "Hafenstraße 12, 20457 Hamburg", "DE",
                       "Elbe Handelsbank AG")  # fmt: skip
HALLMANN = eu_supplier("hallmann", "Hallmann Bürotechnik GmbH", "Gutenbergstraße 3, 70176 Stuttgart",
                       "DE", "Neckar Volksbank eG")  # fmt: skip
ALPENWOLKE = eu_supplier("alpenwolke", "Alpenwolke Hosting GmbH", "Mariahilfer Straße 45, 1060 Wien",
                         "AT", "Donau Privatbank AG")  # fmt: skip


def d(y: int, m: int, day: int) -> date:
    return date(y, m, day)


def I(desc: str, qty: str, price: str, unit: str = "") -> Item:  # noqa: E743
    return Item(desc, D(qty), D(price), unit)


DOCS: list[InvoiceDoc] = [
    # --- Kazakhstan, 1C-style "Счет на оплату" ----------------------------------------------
    InvoiceDoc(
        file="inv_01_kz_logistics.pdf", layout="kz_classic", num_locale="ru", date_style="dmy",
        supplier=ARNA, buyer=KESTREL_KZ, invoice_number="45", issue_date=d(2026, 1, 15),
        due_date=d(2026, 1, 30), contract_number="12/2025-ТЭ", contract_date=d(2025, 12, 1),
        currency="KZT", currency_label="тенге", currency_style="suffix",
        items=[
            I("Экспедирование груза Алматы — Астана", "2", "150000.00", "рейс"),
            I("Погрузочно-разгрузочные работы", "4", "12500.00", "час"),
            I("Хранение груза на складе", "10", "1200.00", "сут."),
        ],
        vat_mode="included", vat_rate=D(16),
        payment_terms="Оплата в течение 10 банковских дней",
        expense_category="logistics",
        notes="VAT included ('в том числе'), no printed subtotal; contract date next to contract "
              "number; total printed twice; Кбе/КНП codes as noise numbers",
    ),
    InvoiceDoc(
        file="inv_02_kz_it.pdf", layout="kz_classic", num_locale="ru", date_style="ru_text_q",
        supplier=TENGRI, buyer=KESTREL_KZ, invoice_number="0012", issue_date=d(2026, 1, 20),
        due_date=d(2026, 2, 4),
        currency="KZT", currency_label="₸", currency_style="suffix",
        items=[
            I("Сопровождение 1С: Бухгалтерия, январь", "1", "280000.00", "мес."),
            I("Доработка отчётных форм", "12", "18500.00", "час"),
        ],
        vat_mode="included", vat_rate=D(16),
        expense_category="it_services",
        labels={"title": "Счёт на оплату", "due_date": "Срок оплаты"},
        notes="NO contract number; dates as «20» января 2026 г.",
    ),
    InvoiceDoc(
        file="inv_03_kz_office.pdf", layout="kz_classic", num_locale="ru", date_style="dmy",
        supplier=KANZLER, buyer=KESTREL_KZ, invoice_number="318", issue_date=d(2026, 1, 22),
        contract_number="ДП-0457", contract_date=d(2025, 11, 10),
        currency="KZT", currency_label="тенге", currency_style="suffix",
        items=[
            I("Бумага офисная А4, 500 л.", "20", "2350.00", "пач."),
            I("Картридж лазерный универсальный", "3", "18900.00", "шт."),
            I("Папка-регистратор 75 мм", "15", "990.00", "шт."),
            I("Ручка шариковая синяя", "50", "120.00", "шт."),
            I("Стикеры 76×76 мм", "10", "450.00", "уп."),
        ],
        vat_mode="included", vat_rate=D(16),
        payment_terms="100% предоплата",
        expense_category="office_supplies",
        extras=[Extra("Доверенность", "№ 17 от {0}", (d(2026, 1, 12),))],
        labels={"contract": "Договор поставки"},
        notes="no due date; power of attorney '№ 17 от 12.01.2026' is a second numbered document; "
              "numbers inside descriptions (500 л., 75 мм)",
    ),
    # --- Russia, requisites table ----------------------------------------------------------
    InvoiceDoc(
        file="inv_04_ru_consulting.pdf", layout="ru_requisites", num_locale="ru", date_style="dmy",
        supplier=VETER, buyer=KESTREL_RU, invoice_number="СЧ-00045", issue_date=d(2026, 1, 15),
        due_date=d(2026, 1, 26), contract_number="77/К-2025", contract_date=d(2025, 11, 3),
        currency="RUB", currency_label="руб.", currency_style="header",
        items=[
            I("Консультации по налоговому планированию", "16", "9500.00", "час"),
            I("Подготовка аналитической записки", "1", "65000.00", "шт."),
        ],
        vat_mode="excluded", vat_rate=D(22),
        payment_terms="Оплата в течение 5 рабочих дней",
        expense_category="consulting",
        labels={"title": "СЧЁТ"},
        notes="р/с and к/с both printed (20 digits each); two ИНН/КПП pairs",
    ),
    InvoiceDoc(
        file="inv_05_ru_rent.pdf", layout="ru_requisites", num_locale="ru", date_style="ru_text",
        supplier=GRANAT, buyer=KESTREL_RU, invoice_number="117", issue_date=d(2026, 2, 5),
        due_date=d(2026, 2, 10), contract_number="А-14/2024", contract_date=d(2024, 3, 1),
        currency="RUB", currency_label="RUB", currency_style="header",
        items=[
            I("Аренда офиса 214, февраль", "1", "185000.00", "мес."),
            I("Парковочное место", "2", "7500.00", "мес."),
        ],
        vat_mode="none",
        expense_category="rent",
        labels={"title": "Счёт на оплату", "supplier": "Арендодатель", "buyer": "Арендатор",
                "issue_date": "Дата выставления", "due_date": "Оплатить до",
                "contract": "Договор аренды"},
        notes="'Без НДС' (no tax); landlord/tenant labels instead of supplier/buyer; "
              "contract dated 2024",
    ),
    InvoiceDoc(
        file="inv_06_ru_marketing.pdf", layout="ru_requisites", num_locale="ru", date_style="dmy",
        supplier=MEDIAKIT, buyer=KESTREL_RU, invoice_number="2026/031", issue_date=d(2026, 1, 28),
        due_date=d(2026, 2, 6),
        currency="RUB", currency_label="руб.", currency_style="header",
        items=[
            I("Таргетированная реклама, январь", "1", "120000.00", "усл."),
            I("Дизайн рекламных баннеров", "6", "4500.00", "шт."),
            I("Отчёт по эффективности кампании", "1", "15000.00", "шт."),
        ],
        vat_mode="excluded", vat_rate=D(22),
        payment_terms="Предоплата 100%",
        expense_category="marketing",
        extras=[Extra("Заказ", "№ 3318 от {0}", (d(2026, 1, 12),))],
        labels={"title": "Счёт", "supplier": "Исполнитель", "buyer": "Заказчик",
                "issue_date": "Дата", "due_date": "Срок оплаты"},
        notes="NO contract number, but an order number '№ 3318' that a naive model files as one",
    ),
    # --- English, modern two-column --------------------------------------------------------
    InvoiceDoc(
        file="inv_07_uk_software.pdf", layout="en_modern", num_locale="en", date_style="en_text",
        supplier=BRIGHTLINE, buyer=KESTREL_UK, invoice_number="INV-2026-0042",
        issue_date=d(2026, 1, 15), due_date=d(2026, 2, 14), contract_number="MSA-2025-031",
        currency="GBP", currency_label="£", currency_style="prefix",
        items=[
            I("Analytics Platform licence, Jan", "25", "48.00", "seat"),
            I("Premium support, Jan", "1", "350.00"),
            I("Onboarding workshop (remote)", "1.5", "600.00", "day"),
        ],
        vat_mode="excluded", vat_rate=D(20),
        payment_terms="Net 30",
        expense_category="software",
        extras=[Extra("PO number", "PO-7731")],
        notes="PO number next to the agreement reference; fractional quantity",
    ),
    InvoiceDoc(
        file="inv_08_nl_consulting.pdf", layout="en_modern", num_locale="de", date_style="iso",
        supplier=VOSSBERG, buyer=KESTREL_NL, invoice_number="2026-0007",
        issue_date=d(2026, 1, 15), due_date=d(2026, 1, 29),
        currency="EUR", currency_label="€", currency_style="prefix",
        items=[
            I("Data governance assessment", "6", "1450.00", "day"),
            I("Workshop facilitation", "2", "1450.00", "day"),
            I("Travel expenses (flat rate)", "1", "380.00"),
        ],
        vat_mode="excluded", vat_rate=D(21),
        payment_terms="Payment within 14 days",
        expense_category="consulting",
        extras=[Extra("Customer ID", "C-20419")],
        labels={"number": "Invoice number", "issue_date": "Date of issue",
                "due_date": "Payment due", "buyer": "Client"},
        notes="NO contract number; ISO dates; 1.234,56 number format in an English document",
    ),
    InvoiceDoc(
        file="inv_09_uk_credit_note.pdf", layout="en_modern", num_locale="en", date_style="en_text",
        supplier=BRIGHTLINE, buyer=KESTREL_UK, invoice_number="CN-2026-007",
        issue_date=d(2026, 1, 20), contract_number="MSA-2025-031",
        currency="GBP", currency_label="GBP", currency_style="header",
        items=[
            I("Credit: unused seats, Dec", "5", "-48.00", "seat"),
            I("Credit: support SLA breach", "1", "-150.00"),
        ],
        vat_mode="excluded", vat_rate=D(20),
        expense_category="software", is_credit_note=True,
        extras=[Extra("Original invoice", "INV-2025-1184 of {0}", (d(2025, 12, 12),))],
        labels={"title": "CREDIT NOTE", "number": "Credit note no.", "issue_date": "Date",
                "total": "Total credit"},
        notes="credit note with negative amounts; references the original invoice number and date",
    ),
    # --- English, compact label: value -----------------------------------------------------
    InvoiceDoc(
        file="inv_10_ee_it.pdf", layout="en_compact", num_locale="en", date_style="en_long",
        supplier=LUMENTA, buyer=KESTREL_KZ_EN, invoice_number="2026-117",
        issue_date=d(2026, 1, 15), due_date=d(2026, 2, 14), contract_number="SA-2025/88",
        currency="USD", currency_label="USD", currency_style="suffix",
        items=[
            I("Backend development", "120", "85.00", "h"),
            I("Code review and QA", "24", "70.00", "h"),
        ],
        vat_mode="none",
        payment_terms="Net 30 days",
        expense_category="it_services",
        extras=[Extra("Service period", "{0} – {1}", (d(2026, 1, 1), d(2026, 1, 31)))],
        labels={"title": "Invoice", "issue_date": "Date of issue", "due_date": "Payment due",
                "contract": "Contract No.", "total": "Total due"},
        notes="no VAT (export of services); four dates; US-style 'January 15, 2026'",
    ),
    InvoiceDoc(
        file="inv_11_lt_equipment.pdf", layout="en_compact", num_locale="en", date_style="en_text",
        supplier=BALTIC, buyer=KESTREL_DE, invoice_number="BRS-26-0019",
        issue_date=d(2026, 1, 15),
        currency="EUR", currency_label="EUR", currency_style="suffix",
        items=[
            I("Server rack 42U, 800x1000", "2", "1240.00", "pcs"),
            I("PDU 16A, 24 outlets", "4", "189.50", "pcs"),
            I("Cable management kit", "6", "35.90", "pcs"),
        ],
        vat_mode="zero", vat_rate=D(0),
        payment_terms="Prepayment",
        expense_category="equipment",
        extras=[Extra("Order date", "{0}", (d(2026, 1, 5),)),
                Extra("Delivery date", "{0}", (d(2026, 1, 12),))],
        labels={"title": "Invoice No.", "issue_date": "Invoice date", "subtotal": "Net amount",
                "tax": "VAT 0% (reverse charge)", "total": "Amount payable"},
        notes="NO contract and NO due date; order and delivery dates; VAT printed as 0.00",
    ),
    InvoiceDoc(
        file="inv_12_ie_travel.pdf", layout="en_compact", num_locale="en", date_style="iso",
        supplier=CLIFFSIDE, buyer=KESTREL_UK, invoice_number="CE-4471",
        issue_date=d(2026, 1, 15), due_date=d(2026, 2, 14), contract_number="EV-2026/004",
        currency="EUR", currency_label="€", currency_style="prefix",
        items=[
            I("Conference package, per delegate", "2", "690.00"),
            I("Hotel, single room", "6", "145.00", "night"),
            I("Airport transfers", "4", "35.00"),
        ],
        vat_mode="excluded", vat_rate=D(23),
        expense_category="travel",
        extras=[Extra("Booking reference", "BK-88213")],
        labels={"title": "Invoice #", "issue_date": "Issued", "due_date": "Due",
                "contract": "Agreement No.", "total": "Balance due"},
        notes="booking reference next to agreement number; ISO dates; no payment terms",
    ),
    # --- English, German-style letter --------------------------------------------------------
    InvoiceDoc(
        file="inv_13_de_software.pdf", layout="en_eu", num_locale="de", date_style="dmy",
        supplier=NORDWERK, buyer=KESTREL_DE, invoice_number="RE-2026-0113",
        issue_date=d(2026, 1, 15), due_date=d(2026, 1, 29), contract_number="RV-2024-17",
        currency="EUR", currency_label="EUR", currency_style="suffix",
        items=[
            I("Backend development, sprints 23–24", "84", "105.00", "h"),
            I("Project management", "16", "95.00", "h"),
            I("Cloud infrastructure setup", "1", "4200.00", "flat"),
        ],
        vat_mode="excluded", vat_rate=D(19),
        payment_terms="14 days net",
        expense_category="it_services",
        extras=[Extra("Customer no.", "10442"),
                Extra("Service period", "{0} – {1}", (d(2025, 12, 1), d(2025, 12, 31)))],
        notes="due date only inside a sentence ('transfer the amount by ...'); service period "
              "dates; contract named in the intro sentence",
    ),
    InvoiceDoc(
        file="inv_14_de_equipment.pdf", layout="en_eu", num_locale="de", date_style="dmy",
        supplier=HALLMANN, buyer=KESTREL_DE, invoice_number="2026-00381",
        issue_date=d(2026, 1, 20), due_date=d(2026, 1, 30),
        currency="EUR", currency_label="€", currency_style="suffix",
        items=[
            I("Monitor 27 inch, 4K", "6", "389.00", "pcs"),
            I("Docking station USB-C", "6", "149.90", "pcs"),
            I("Ergonomic office chair", "3", "429.00", "pcs"),
        ],
        vat_mode="excluded", vat_rate=D(19),
        payment_terms="Payable within 10 days without deduction",
        expense_category="equipment",
        extras=[Extra("Delivery date", "{0}", (d(2026, 1, 16),)),
                Extra("Delivery note no.", "LS-55190")],
        notes="NO contract number, but a delivery note number; delivery date",
    ),
    InvoiceDoc(
        file="inv_15_at_hosting.pdf", layout="en_eu", num_locale="de", date_style="iso",
        supplier=ALPENWOLKE, buyer=KESTREL_DE, invoice_number="AW-26-00094",
        issue_date=d(2026, 1, 31), contract_number="AW-2023-0912",
        currency="EUR", currency_label="EUR", currency_style="suffix",
        items=[
            I("Managed Kubernetes cluster, 3 nodes", "1", "1350.00", "month"),
            I("Object storage", "2.4", "22.50", "TB"),
            I("Backup service", "1", "180.00", "month"),
        ],
        vat_mode="excluded", vat_rate=D(20),
        payment_terms="Payable within 30 days without deduction",
        expense_category="it_services",
        extras=[Extra("Billing period", "{0} – {1}", (d(2026, 1, 1), d(2026, 1, 31)))],
        labels={"vat": "VAT reg. no. (UID)", "contract": "Contract no."},
        notes="NO due date; invoice and contract numbers share a prefix (AW-...); issue date "
              "equals the billing period end",
    ),
]  # fmt: skip
