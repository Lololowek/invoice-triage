<script setup lang="ts">
import { onMounted, ref } from 'vue'
import type { DocumentSummary, Metrics } from '~/utils/types'

const { listDocuments, metrics: loadMetrics } = useApi()
const documents = ref<DocumentSummary[]>([])
const metrics = ref<Metrics | null>(null)
const error = ref('')

async function refresh() {
  try {
    ;[documents.value, metrics.value] = await Promise.all([listDocuments(), loadMetrics()])
    error.value = ''
  } catch (e) {
    error.value = errorDetail(e).message
  }
}
onMounted(refresh)

const open = (id: string) => navigateTo(`/documents/${id}`)
</script>

<template>
  <div class="page">
    <UploadBox @uploaded="open" />
    <p v-if="error" class="error-text">{{ error }}</p>

    <section class="card">
      <h2>Документы</h2>
      <p v-if="!documents.length" class="muted">Пока ничего не загружено.</p>
      <table v-else class="plain clickable">
        <thead>
          <tr>
            <th>Файл</th><th>Загружен</th><th>На проверку</th><th>С флагами</th><th>Проверен</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="d in documents" :key="d.id" @click="open(d.id)">
            <td><NuxtLink :to="`/documents/${d.id}`">{{ d.filename }}</NuxtLink></td>
            <td>{{ formatDateTime(d.uploaded_at) }}</td>
            <td>{{ d.to_review }} из {{ d.fields }}</td>
            <td :class="{ warn: d.flagged > 0 }">{{ d.flagged }}</td>
            <td>{{ d.reviewed_at ? formatDateTime(d.reviewed_at) : '—' }}</td>
          </tr>
        </tbody>
      </table>
    </section>

    <MetricsPanel v-if="metrics && metrics.fields > 0" :metrics="metrics" />
  </div>
</template>
