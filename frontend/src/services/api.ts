import { clearLibraryCache } from './libraryCache'
import { clearIntentData } from './intentCache'
import { clearCodeSummaryCache } from './codeSummariesApi'
import axios, { AxiosInstance } from 'axios'

// Default to a relative API path so the browser uses the dev server proxy.
// If VITE_API_URL is set to '/api' (dev proxy), use empty baseURL so
// axios requests like '/api/v1/...' are sent as-is and handled by the proxy.
const rawApiUrl = import.meta.env.VITE_API_URL
const API_URL = rawApiUrl === '/api' ? '' : rawApiUrl || ''

const api: AxiosInstance = axios.create({
  baseURL: API_URL,
  headers: {
    'Content-Type': 'application/json',
  },
})

function invalidateReads() {
  clearIntentData()
  clearLibraryCache()
  clearCodeSummaryCache()
}

// Invalidate before writes and after success: concurrent reads cannot refill
// the cache with data fetched while a mutation was still in progress.
api.interceptors.request.use((config) => {
  if (config.method && !['get', 'head', 'options'].includes(config.method.toLowerCase())) invalidateReads()
  return config
})

// Add request interceptor for error handling
api.interceptors.response.use(
  (response) => {
    if (response.config.method && !['get', 'head', 'options'].includes(response.config.method.toLowerCase())) invalidateReads()
    return response
  },
  (error) => {
    if ([401, 403].includes(error.response?.status)) invalidateReads()
    console.error('API Error:', error.response?.status, error.response?.data)
    return Promise.reject(error)
  }
)

export { api }
export default api
