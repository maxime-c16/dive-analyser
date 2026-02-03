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

// Add request interceptor for error handling
api.interceptors.response.use(
  (response) => response,
  (error) => {
    console.error('API Error:', error.response?.status, error.response?.data)
    return Promise.reject(error)
  }
)

export { api }
export default api
