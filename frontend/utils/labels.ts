import type { Layer, Value } from '~/utils/types'

export const FIELD_LABELS: Record<string, string> = {
  supplier_name: 'Поставщик',
  supplier_tax_id: 'ИНН / БИН / VAT поставщика',
  supplier_account: 'Счёт получателя (IBAN, р/с)',
  supplier_bank_code: 'БИК / BIC',
  buyer_name: 'Покупатель',
  buyer_tax_id: 'ИНН / БИН / VAT покупателя',
  invoice_number: 'Номер счёта',
  contract_number: 'Номер договора',
  issue_date: 'Дата счёта',
  due_date: 'Срок оплаты',
  currency: 'Валюта',
  subtotal: 'Сумма без налога',
  tax_amount: 'Налог',
  total: 'Итого к оплате',
  payment_terms: 'Условия оплаты',
  expense_category: 'Категория расходов',
  is_credit_note: 'Кредит-нота',
  'line_items.description': 'описание',
  'line_items.quantity': 'кол-во',
  'line_items.unit_price': 'цена',
  'line_items.amount': 'сумма',
}

/** "line_items[2].amount" -> "Строка 3 · сумма" */
export function fieldLabel(path: string, spec: string): string {
  const row = /^line_items\[(\d+)\]/.exec(path)
  const label = FIELD_LABELS[spec] ?? spec
  return row ? `Строка ${Number(row[1]) + 1} · ${label}` : label
}

export const LAYER_LABELS: Record<Layer, string> = {
  schema: 'схема',
  grounding: 'источник',
  arithmetic: 'арифметика',
}

export const FLAG_LABELS: Record<string, string> = {
  // grounding
  quote_not_found: 'нет в документе',
  value_mismatch: 'цитата не равна значению',
  unknown_candidate: 'несуществующий кандидат',
  type_mismatch: 'не тот тип значения',
  ambiguous_format: 'неоднозначный формат',
  unparseable: 'не читается',
  no_source: 'без источника',
  missing_required: 'обязательное поле пусто',
  candidate_reused: 'одно значение на два поля',
  duplicate_identifier: 'один номер у двух полей',
  party_mismatch: 'реквизит другой стороны',
  quote_spans_columns: 'захвачена соседняя колонка',
  // schema
  invalid: 'формат или контрольная сумма',
  checksum: 'ключ счёта не сходится',
  unverifiable: 'нельзя проверить',
  due_before_issue: 'срок раньше даты счёта',
  negative_amount: 'отрицательная сумма',
  // arithmetic
  line_mismatch: 'кол-во × цена ≠ сумма',
  sum_mismatch: 'строки не сходятся с итогом',
  total_mismatch: 'подытог + налог ≠ итого',
  // document
  no_line_items: 'строки таблицы не найдены',
}

export const flagLabel = (code: string) => FLAG_LABELS[code] ?? code

export const CATEGORY_LABELS: Record<string, string> = {
  software: 'ПО',
  it_services: 'ИТ-услуги',
  consulting: 'консалтинг',
  logistics: 'логистика',
  office_supplies: 'канцтовары',
  equipment: 'оборудование',
  rent: 'аренда',
  utilities: 'коммунальные',
  marketing: 'маркетинг',
  travel: 'командировки',
  other: 'прочее',
}

/** Value -> text for an input: null is an empty field. */
export function toInput(value: Value): string {
  if (value === null) return ''
  if (typeof value === 'boolean') return value ? 'true' : 'false'
  return value
}

/** Input text -> the value sent to the API; the server normalizes and validates it. */
export function fromInput(text: string, kind: string): Value {
  if (kind === 'derived' && (text === 'true' || text === 'false')) return text === 'true'
  return text.trim() === '' ? null : text
}

export function formatDateTime(iso: string): string {
  return new Date(iso).toLocaleString('ru-RU', { dateStyle: 'short', timeStyle: 'short' })
}

export function percent(rate: number | null): string {
  return rate === null ? '—' : `${(rate * 100).toFixed(1)}%`
}
