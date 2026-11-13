import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import '@fontsource/figtree/400.css'
import '@fontsource/figtree/500.css'
import '@fontsource/figtree/600.css'
import '@fontsource/figtree/700.css'
import './index.css'
import App from './App.tsx'
import { ErrorBoundary } from './components/ErrorBoundary.tsx'

const root = document.getElementById('root')
if (!root) throw new Error('Missing #root element')

// Keep the browser bar colour equal to the page token, so a token change needs no HTML edit.
const pageColour = getComputedStyle(document.documentElement).getPropertyValue('--color-page').trim()
if (pageColour) document.querySelector('meta[name="theme-color"]')?.setAttribute('content', pageColour)

createRoot(root).render(
  <StrictMode>
    <ErrorBoundary>
      <App />
    </ErrorBoundary>
  </StrictMode>,
)
