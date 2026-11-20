<script setup lang="ts">
import { computed, nextTick, ref, watch } from 'vue'
// The extracted document text with the selected field's source span marked. This is the
// grounding layer made visible: a value either points at a place in the document, or it has
// nowhere to point (a hallucinated contract number).
const props = defineProps<{
  text: string
  span: { start: number; end: number } | null
  missing?: string | null // shown instead of a mark when the selected value has no source
}>()

const parts = computed(() => {
  const s = props.span
  if (!s || s.end <= s.start) return null
  return {
    before: props.text.slice(0, s.start),
    mark: props.text.slice(s.start, s.end),
    after: props.text.slice(s.end),
  }
})

const textEl = ref<HTMLElement | null>(null)
const markEl = ref<HTMLElement | null>(null)
// Scroll the text panel only: scrollIntoView would also move the page under the reviewer's cursor.
watch(
  () => props.span,
  async () => {
    await nextTick()
    const box = textEl.value
    const mark = markEl.value
    if (box && mark) {
      box.scrollTo({ top: mark.offsetTop - box.clientHeight / 2, behavior: 'smooth' })
    }
  },
)
</script>

<template>
  <div class="source-panel">
    <div class="source-head">
      <span>Текст документа</span>
      <span v-if="missing" class="source-missing">{{ missing }}</span>
    </div>
    <pre v-if="parts" ref="textEl" class="source-text">{{ parts.before }}<mark ref="markEl">{{ parts.mark }}</mark>{{ parts.after }}</pre>
    <pre v-else class="source-text">{{ text }}</pre>
  </div>
</template>
