import React from 'react';
import ReactDOM from 'react-dom/client';
import { BrowserRouter } from 'react-router-dom';
import { Toaster } from 'sonner';
import App from './App';
import './styles/globals.css';

async function boot() {
  // Static demo build only (VITE_DEMO=static): answer /api/* in the browser from
  // synthetic data. The condition is a build-time constant, so the default build
  // drops this branch and the demo chunk entirely.
  let Banner: React.ComponentType | null = null;
  if (import.meta.env.VITE_DEMO === 'static') {
    const demo = await import('./demo');
    demo.install();
    Banner = demo.DemoBanner;
  }

  ReactDOM.createRoot(document.getElementById('root')!).render(
    <React.StrictMode>
      <BrowserRouter>
        <App />
        {Banner && <Banner />}
        <Toaster
          position="bottom-right"
          closeButton
          toastOptions={{
            style: {
              background: 'var(--color-bg-secondary)',
              color: 'var(--color-text-primary)',
              border: '1px solid var(--color-border)',
            },
          }}
        />
      </BrowserRouter>
    </React.StrictMode>
  );
}

boot();
