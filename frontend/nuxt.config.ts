export default defineNuxtConfig({
  compatibilityDate: '2026-11-01',
  ssr: false, // a single-user tool: no SEO, no server rendering needed
  devtools: { enabled: false },
  telemetry: false,
  css: ['~/assets/main.css'],
  app: {
    head: {
      title: 'Invoice triage',
      htmlAttrs: { lang: 'ru' },
      meta: [{ name: 'viewport', content: 'width=device-width, initial-scale=1' }],
    },
  },
  // Where FastAPI runs (`triage serve`). Overridden at start-up by NUXT_API_URL.
  runtimeConfig: { apiUrl: 'http://127.0.0.1:8000' },
  typescript: { strict: true },
})
