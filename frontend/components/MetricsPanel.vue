<script setup lang="ts">
import { computed } from 'vue'
import type { Metrics } from '~/utils/types'

const props = defineProps<{ metrics: Metrics }>()

const checks = computed(() =>
  Object.entries(props.metrics.by_check)
    .map(([key, s]) => {
      const [layer, code] = key.split(':') as [keyof typeof LAYER_LABELS, string]
      return { key, layer: LAYER_LABELS[layer] ?? layer, code: flagLabel(code), ...s }
    })
    .sort((a, b) => b.fired - a.fired),
)
</script>

<template>
  <section class="card">
    <h2>Качество по правкам людей</h2>
    <p class="muted">
      Проверено документов: {{ metrics.documents }}, полей: {{ metrics.fields }}.
      Считается по последней проверке каждого документа.
    </p>
    <div class="stats">
      <div class="stat"><b>{{ percent(metrics.review_load) }}</b><span>полей показано человеку</span></div>
      <div class="stat"><b>{{ metrics.caught_by_checks }}</b><span>ошибок поймали проверки</span></div>
      <div class="stat"><b>{{ metrics.false_alarms }}</b><span>ложных тревог</span></div>
      <div class="stat"><b>{{ percent(metrics.flag_precision) }}</b><span>точность флагов</span></div>
      <div class="stat"><b>{{ metrics.caught_by_policy }}</b><span>поймала только политика риска</span></div>
      <div class="stat"><b>{{ metrics.corrected_outside_queue }}</b><span>исправлено вне очереди</span></div>
    </div>
    <p class="muted small">
      «Исправлено вне очереди» — нижняя оценка тихих ошибок: принятые поля человек не проверяет.
      Точное число даёт замер по разметке (<code>triage eval</code>).
    </p>
    <table v-if="checks.length" class="plain">
      <thead>
        <tr><th>Проверка</th><th>сработала</th><th>показана</th><th>человек исправил</th></tr>
      </thead>
      <tbody>
        <tr v-for="c in checks" :key="c.key">
          <td>{{ c.layer }}: {{ c.code }}</td>
          <td>{{ c.fired }}</td>
          <td>{{ c.shown }}</td>
          <td>{{ c.corrected }}</td>
        </tr>
      </tbody>
    </table>
  </section>
</template>
