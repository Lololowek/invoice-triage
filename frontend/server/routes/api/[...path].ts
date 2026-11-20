// The browser calls /api/*; this route forwards it to FastAPI. One origin, so no CORS setup,
// and the API address is configured in one place (runtimeConfig.apiUrl / NUXT_API_URL).
export default defineEventHandler((event) => {
  const { apiUrl } = useRuntimeConfig(event)
  const path = event.path.replace(/^\/api/, '')
  return proxyRequest(event, `${apiUrl}${path}`)
})
