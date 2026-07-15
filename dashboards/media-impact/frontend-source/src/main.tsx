// frontend/src/main.tsx - LLYC Intelligence Dashboard React Frontend
import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { ErrorBoundary } from 'react-error-boundary'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import './index.css'
import App from './App.tsx'

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      refetchOnWindowFocus: false, // Prevents excessive refetches on tab focus
      retry: 1, // Retry once on network failures
    },
  },
});

function ErrorFallback({error}: {error: any}) {
  return (
    <div role="alert" style={{padding: '40px', color: '#F54963', background: '#F0F2F4', minHeight: '100vh', fontFamily: 'sans-serif'}}>
      <h2 style={{fontWeight: '900'}}>Algo ha salido mal:</h2>
      <pre style={{fontSize: '12px', background: '#fff', padding: '20px', borderRadius: '8px', border: '1px solid rgba(10,38,59,.1)'}}>
        {error.message || JSON.stringify(error)}
      </pre>
      <button 
        onClick={() => window.location.href = '/'}
        style={{marginTop: '20px', padding: '10px 20px', background: '#0A263B', color: '#fff', border: 'none', borderRadius: '5px', fontWeight: 'bold', cursor: 'pointer'}}
      >
        Volver al inicio
      </button>
    </div>
  )
}

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <ErrorBoundary FallbackComponent={ErrorFallback}>
      <QueryClientProvider client={queryClient}>
        <App />
      </QueryClientProvider>
    </ErrorBoundary>
  </StrictMode>,
)

