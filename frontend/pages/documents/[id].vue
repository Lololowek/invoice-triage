<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import type { Action, DocumentOut, FieldResult, FieldSpec, ReviewOut } from '~/utils/types'

const route = useRoute()
const id = route.params.id as string
const api = useApi()

const doc = ref<DocumentOut | null>(null)
const specs = ref<Record<string, FieldSpec>>({})
const categories = ref<string[]>([])
const actions = ref<Record<string, Action>>({})
const drafts = ref<Record<string, string>>({})
const errors = ref<Record<string, string>>({})
const loadError = ref('')
const saveError = ref('')
const saved = ref<ReviewOut | null>(null)
const saving = ref(false)
const selected = ref<string | null>(null)

/** The value a field has now: from the last saved review, else as extracted. */
function current(f: FieldResult): string {
  const finals = doc.value?.final_values
  return toInput(finals && f.path in finals ? finals[f.path]! : f.value)
}

async function load() {
  try {
    const [d, schema] = await Promise.all([api.getDocument(id), api.schema()])
    specs.value = Object.fromEntries(schema.fields.map((s) => [s.name, s]))
    categories.value = schema.expense_categories
    actions.value = d.reviewed_at
      ? Object.fromEntries((await api.edits(id)).map((e) => [e.path, e.action]))
      : {}
    doc.value = d
    drafts.value = Object.fromEntries(d.fields.map((f) => [f.path, current(f)]))
    selected.value ??= queue.value[0]?.path ?? null
  } catch (e) {
    loadError.value = errorDetail(e).message
  }
}
onMounted(load)

// Review queue first, flagged before merely high-risk; the rest in schema order.
const queue = computed(() =>
  (doc.value?.fields ?? [])
    .filter((f) => f.needs_review)
    .sort((a, b) => Number(b.flags.length > 0) - Number(a.flags.length > 0)),
)
const accepted = computed(() => (doc.value?.fields ?? []).filter((f) => !f.needs_review))

const changedPaths = computed(() =>
  (doc.value?.fields ?? [])
    .filter((f) => (drafts.value[f.path] ?? '').trim() !== current(f).trim())
    .map((f) => f.path),
)

const selectedField = computed(() => doc.value?.fields.find((f) => f.path === selected.value) ?? null)
const span = computed(() => {
  const s = selectedField.value?.source
  return s ? { start: s.start, end: s.end } : null
})
const missing = computed(() => {
  const f = selectedField.value
  if (!f || f.source) return null
  if (f.kind === 'derived') return 'вывод модели, в тексте не ищется'
  return f.value === null ? 'значения нет' : 'этого значения в тексте нет'
})

async function save() {
  if (!doc.value) return
  saving.value = true
  saveError.value = ''
  errors.value = {}
  const byPath = Object.fromEntries(doc.value.fields.map((f) => [f.path, f]))
  const values = Object.fromEntries(
    changedPaths.value.map((p) => [p, fromInput(drafts.value[p] ?? '', byPath[p]!.kind)]),
  )
  try {
    saved.value = await api.review(id, values)
    await load()
  } catch (e) {
    const detail = errorDetail(e)
    saveError.value = detail.message
    errors.value = detail.fields
  } finally {
    saving.value = false
  }
}
</script>

<template>
  <div class="page">
    <p v-if="loadError" class="error-text">{{ loadError }}</p>
    <template v-if="doc">
      <div class="doc-head">
        <div>
          <NuxtLink to="/" class="muted">← все документы</NuxtLink>
          <h1>{{ doc.filename }}</h1>
          <p class="muted small">
            сопоставление: {{ doc.mapper }} · строки таблицы нашёл {{ doc.line_items_source === 'code' ? 'код' : 'модель' }}
            · загружен {{ formatDateTime(doc.uploaded_at) }}
            <template v-if="doc.reviewed_at"> · проверен {{ formatDateTime(doc.reviewed_at) }}</template>
          </p>
        </div>
        <div class="save-box">
          <button type="button" class="primary" :disabled="saving" @click="save">
            {{ saving ? 'Сохраняю…' : changedPaths.length ? `Сохранить проверку (${changedPaths.length} изм.)` : 'Подтвердить проверку' }}
          </button>
          <p v-if="saved && !saveError" class="ok small">
            Сохранено: исправлено {{ saved.corrected.length }}, подтверждено {{ saved.confirmed }}
          </p>
          <p v-if="saveError" class="error-text small">{{ saveError }}</p>
        </div>
      </div>

      <div v-for="flag in doc.document_flags" :key="flag.code" class="banner">
        {{ flagLabel(flag.code) }} — {{ flag.message }}
      </div>

      <div class="review-layout">
        <div class="fields">
          <table class="fields-table">
            <thead>
              <tr><th>Поле</th><th>Значение</th><th>Источник</th><th>Проверки</th></tr>
            </thead>
            <tbody>
              <tr class="group"><td colspan="4">Нужна проверка человеком — {{ queue.length }}</td></tr>
              <FieldRow
                v-for="f in queue"
                :key="f.path"
                v-model="drafts[f.path]!"
                :field="f"
                :spec="specs[f.spec]"
                :current="current(f)"
                :extracted="toInput(f.value)"
                :action="actions[f.path]"
                :error="errors[f.path]"
                :selected="selected === f.path"
                :categories="categories"
                @select="selected = f.path"
              />
              <tr class="group"><td colspan="4">Принято автоматически — {{ accepted.length }}</td></tr>
              <FieldRow
                v-for="f in accepted"
                :key="f.path"
                v-model="drafts[f.path]!"
                :field="f"
                :spec="specs[f.spec]"
                :current="current(f)"
                :extracted="toInput(f.value)"
                :action="actions[f.path]"
                :error="errors[f.path]"
                :selected="selected === f.path"
                :categories="categories"
                @select="selected = f.path"
              />
            </tbody>
          </table>
          <p class="muted small">
            Пустое значение очищает поле. Даты и суммы можно писать как в документе
            («15.01.2026», «1 250 000,00») — сервер проверит их теми же правилами, что и ответ модели.
          </p>
        </div>
        <SourceText class="source-sticky" :text="doc.text" :span="span" :missing="missing" />
      </div>
    </template>
  </div>
</template>
