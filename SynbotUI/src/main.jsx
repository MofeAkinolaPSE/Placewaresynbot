import React from 'react'
import ReactDOM from 'react-dom/client'
import App from './App'
import './index.css'

function mountApp() {
  const mount = document.getElementById('synbot-admin-root') || document.getElementById('root')
  if (!mount) {
    console.error('Mount element not found: expected #synbot-admin-root or #root')
    return false
  }
  ReactDOM.createRoot(mount).render(
    <React.StrictMode>
      <App />
    </React.StrictMode>
  )
  return true
}

// Try immediate mount, else wait for DOMContentLoaded
if (!mountApp()) {
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', () => mountApp(), { once: true })
  } else {
    // In case scripts loaded before mount div is injected by PHP/template
    setTimeout(() => mountApp(), 0)
  }
}
