import { useEffect, useState } from 'react';

import { AccountPage } from './AccountPage';
import { AdvisorPage } from './AdvisorPage';
import { ApplicationPage } from './ApplicationPage';
import { clearSession, readSession, saveSession } from './auth';
import { HomePage } from './HomePage';
import { PolicyCenterPage } from './PolicyCenterPage';
import { ServicePage } from './ServicePage';
import type { AuthSession } from './types';

function navigate(path: string) {
  window.history.pushState({}, '', path);
  window.dispatchEvent(new PopStateEvent('popstate'));
}

function applyPath(target: { productId: string; planId: string; itemId: string }) {
  const params = new URLSearchParams({
    product_id: target.productId,
    plan_id: target.planId,
    item_id: target.itemId,
  });
  return `/apply?${params.toString()}`;
}

export default function App() {
  const [path, setPath] = useState(window.location.pathname);
  const [session, setSession] = useState<AuthSession | null>(() => readSession());

  useEffect(() => {
    const updatePath = () => setPath(window.location.pathname);
    window.addEventListener('popstate', updatePath);
    return () => window.removeEventListener('popstate', updatePath);
  }, []);

  function authenticated(nextSession: AuthSession) {
    saveSession(nextSession);
    setSession(nextSession);
  }

  function logout() {
    clearSession();
    setSession(null);
    if (path !== '/' && path !== '/service') navigate('/');
  }

  function sessionExpired() {
    clearSession();
    setSession(null);
    navigate('/');
  }

  if (path === '/service') {
    return <ServicePage onBack={() => navigate('/')} onProducts={() => navigate('/#products')} />;
  }

  if (path === '/policies' && session) {
    return (
      <PolicyCenterPage
        session={session}
        onBack={() => navigate('/')}
        onLogout={logout}
        onAccount={() => navigate('/account')}
      />
    );
  }

  if (path === '/account' && session) {
    return <AccountPage session={session} onBack={() => navigate('/')} />;
  }

  if (path === '/advisor' && session) {
    return (
      <AdvisorPage
        session={session}
        onBack={() => navigate('/')}
        onSessionExpired={sessionExpired}
        onApplyProduct={(target) => navigate(applyPath(target))}
      />
    );
  }

  if (path === '/apply' && session) {
    return (
      <ApplicationPage
        session={session}
        onBack={() => navigate('/advisor')}
        onSessionExpired={sessionExpired}
      />
    );
  }

  return (
    <HomePage
      session={session}
      initialAuthOpen={path === '/advisor' || path === '/apply' || path === '/policies'}
      initialAuthTarget={path === '/policies' ? 'policies' : 'advisor'}
      onAuthenticated={authenticated}
      onLogout={logout}
      onHome={() => navigate('/')}
      onConsult={() => navigate('/advisor')}
      onService={() => navigate('/service')}
      onPolicies={() => navigate('/policies')}
      onAccount={() => navigate('/account')}
    />
  );
}
