import React from 'react'
import ReactDOM from 'react-dom/client'
import './index.css'
import App from './App'
import { installAchievementProbe } from './services/achievementsApi'

installAchievementProbe()

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
)
