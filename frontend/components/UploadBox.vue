<script setup lang="ts">
import { ref } from 'vue'
const emit = defineEmits<{ uploaded: [id: string] }>()
const { upload } = useApi()

const busy = ref(false)
const error = ref('')
const seconds = ref(0)
const dragging = ref(false)
let timer: ReturnType<typeof setInterval> | undefined

async function send(file: File | undefined) {
  if (!file || busy.value) return
  error.value = ''
  busy.value = true
  seconds.value = 0
  timer = setInterval(() => seconds.value++, 1000)
  try {
    const doc = await upload(file)
    emit('uploaded', doc.id)
  } catch (e) {
    error.value = errorDetail(e).message
  } finally {
    clearInterval(timer)
    busy.value = false
  }
}

function onDrop(event: DragEvent) {
  dragging.value = false
  send(event.dataTransfer?.files[0])
}
</script>

<template>
  <label
    class="upload"
    :class="{ dragging, busy }"
    @dragover.prevent="dragging = true"
    @dragleave="dragging = false"
    @drop.prevent="onDrop"
  >
    <input
      type="file"
      accept="application/pdf,.pdf"
      :disabled="busy"
      @change="send(($event.target as HTMLInputElement).files?.[0])"
    />
    <template v-if="busy">
      <strong>Модель читает счёт… {{ seconds }} с</strong>
      <span>на видеокарте — секунды, на CPU — до минуты</span>
    </template>
    <template v-else>
      <strong>Загрузить счёт (PDF)</strong>
      <span>перетащите файл сюда или нажмите; нужен PDF с текстовым слоем</span>
    </template>
  </label>
  <p v-if="error" class="error-text">{{ error }}</p>
</template>
