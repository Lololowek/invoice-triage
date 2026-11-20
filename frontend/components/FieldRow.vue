<script setup lang="ts">
import { computed } from 'vue'
import type { Action, FieldResult, FieldSpec } from '~/utils/types'

const props = defineProps<{
  field: FieldResult
  spec?: FieldSpec
  current: string // value before this edit: extracted, or from the last saved review
  extracted: string
  action?: Action // from the edit log of the last saved review
  error?: string
  selected: boolean
  categories: string[]
}>()
const draft = defineModel<string>({ required: true })
defineEmits<{ select: [] }>()

const changed = computed(() => draft.value.trim() !== props.current.trim())
const label = computed(() => fieldLabel(props.field.path, props.field.spec))
const hiddenFlags = computed(() => !props.field.needs_review && props.field.flags.length > 0)

const source = computed(() => {
  const s = props.field.source
  if (props.field.kind === 'derived') return { head: 'вывод модели', text: '' }
  if (!s) return props.field.value === null ? { head: '—', text: '' } : { head: 'нет источника', text: '' }
  if (s.via === 'candidate') return { head: s.candidate_id ?? '', text: s.text }
  return { head: s.match === 'fuzzy' ? `цитата ≈${Math.round(s.score ?? 0)}%` : 'цитата', text: s.text }
})
</script>

<template>
  <tr
    class="field-row"
    :class="{ selected, flagged: field.flags.length > 0, changed, invalid: error }"
    @click="$emit('select')"
  >
    <td class="col-name">
      <div class="name" :title="spec?.description">
        {{ label }}<span v-if="spec?.required" class="required" title="обязательное поле">*</span>
      </div>
      <div class="path">{{ field.path }}</div>
      <span v-if="field.risk === 'high'" class="badge badge-high">высокий риск</span>
      <span v-else-if="field.risk === 'low'" class="badge badge-low">низкий риск</span>
    </td>

    <td class="col-value" @click.stop="$emit('select')">
      <select v-if="field.spec === 'is_credit_note'" v-model="draft">
        <option value="">—</option>
        <option value="true">да</option>
        <option value="false">нет</option>
      </select>
      <select v-else-if="field.spec === 'expense_category'" v-model="draft">
        <option value="">—</option>
        <option v-for="c in categories" :key="c" :value="c">{{ CATEGORY_LABELS[c] ?? c }}</option>
      </select>
      <input v-else v-model="draft" type="text" placeholder="пусто" spellcheck="false" />

      <div v-if="changed" class="hint">
        было: <code>{{ current || 'пусто' }}</code>
        <button type="button" class="link" @click.stop="draft = current">вернуть</button>
      </div>
      <div v-else-if="action === 'corrected'" class="hint hint-corrected">
        исправлено человеком; модель: <code>{{ extracted || 'пусто' }}</code>
      </div>
      <div v-else-if="action === 'confirmed'" class="hint">подтверждено человеком</div>
      <div v-if="error" class="error-text">{{ error }}</div>
    </td>

    <td class="col-source">
      <span class="source-head-chip">{{ source.head }}</span>
      <code v-if="source.text" class="source-quote">{{ source.text }}</code>
    </td>

    <td class="col-checks">
      <div v-for="flag in field.flags" :key="flag.layer + flag.code" class="flag" :class="hiddenFlags && 'flag-hidden'">
        <span class="chip" :class="`chip-${flag.layer}`">{{ LAYER_LABELS[flag.layer] }}: {{ flagLabel(flag.code) }}</span>
        <div class="flag-message">{{ flag.message }}</div>
      </div>
      <div v-if="hiddenFlags" class="hint">не показывается: низкий риск, флаг только в журнале</div>
      <div v-else-if="field.needs_review && !field.flags.length" class="hint">проверок не провалило, но поле высокого риска — смотрит человек</div>
      <div v-else-if="field.kind === 'derived'" class="hint">не сверяется с документом: это суждение модели</div>
      <span v-else-if="!field.flags.length" class="ok" title="все проверки пройдены">✓</span>
    </td>
  </tr>
</template>
