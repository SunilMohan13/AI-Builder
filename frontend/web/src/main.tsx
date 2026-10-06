import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './maplibreWorker'
import './styles/index.css'
import { AppRouter } from './app/router'

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <AppRouter />
  </StrictMode>,
)
