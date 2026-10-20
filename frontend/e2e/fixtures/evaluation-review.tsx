// Development-only fixture: the browser test supplies authorized API responses.
import React from 'react'
import { createRoot } from 'react-dom/client'
import { MemoryRouter } from 'react-router-dom'
import JurySession from '../../src/components/evaluation/JurySession'
import '../../src/i18n'
import '../../src/index.css'
import '../../src/components/evaluation/evaluations.css'
import '../../src/components/evaluation/evaluationA.css'
import '../../src/components/evaluation/evaluationHub.css'
if (!import.meta.env.DEV) throw new Error('Review fixture is development-only')
createRoot(document.getElementById('root')!).render(<React.StrictMode><MemoryRouter><JurySession automatic autoStart /></MemoryRouter></React.StrictMode>)
