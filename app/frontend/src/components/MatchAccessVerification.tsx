import { useEffect, useRef, useState, useSyncExternalStore } from 'react';
import {
  cancelMatchAccess, getMatchAccessRequest, submitMatchAccessToken, subscribeMatchAccess,
} from '../matchAccess';
import { t } from '../translate';
import './MatchAccessVerification.css';

interface Turnstile {
  render(container: HTMLElement, options: {
    sitekey: string;
    action: string;
    appearance: 'interaction-only';
    retry: 'never';
    callback: (token: string) => void;
    'before-interactive-callback': () => void;
    'error-callback': () => void;
    'expired-callback': () => void;
    'timeout-callback': () => void;
    'unsupported-callback': () => void;
  }): string;
  remove(id: string): void;
}

declare global {
  interface Window { turnstile?: Turnstile }
}

let scriptPromise: Promise<Turnstile> | null = null;
function loadTurnstile(): Promise<Turnstile> {
  if (window.turnstile) return Promise.resolve(window.turnstile);
  if (scriptPromise) return scriptPromise;
  scriptPromise = new Promise<Turnstile>((resolve, reject) => {
    const script = document.createElement('script');
    script.src = 'https://challenges.cloudflare.com/turnstile/v0/api.js?render=explicit';
    script.async = true;
    const timeout = window.setTimeout(() => fail(), 15000);
    const fail = () => {
      window.clearTimeout(timeout);
      script.onload = null;
      script.onerror = null;
      script.remove();
      scriptPromise = null;
      reject(new Error('Unable to load verification.'));
    };
    script.onerror = fail;
    script.onload = () => {
      window.clearTimeout(timeout);
      if (window.turnstile) resolve(window.turnstile);
      else fail();
    };
    document.head.appendChild(script);
  });
  return scriptPromise;
}

function Challenge({ siteKey }: { siteKey: string }) {
  const container = useRef<HTMLDivElement>(null);
  const [interactive, setInteractive] = useState(false);
  const [failed, setFailed] = useState(false);
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    let active = true;
    let widgetId: string | undefined;
    let turnstile: Turnstile | undefined;
    const fail = () => { if (active) setFailed(true); };
    setFailed(false);
    setInteractive(false);
    const timeout = window.setTimeout(fail, 90000);
    loadTurnstile().then(api => {
      if (!active || !container.current) return;
      turnstile = api;
      widgetId = api.render(container.current, {
        sitekey: siteKey,
        action: 'match_access',
        appearance: 'interaction-only',
        retry: 'never',
        callback: token => {
          if (!active) return;
          submitMatchAccessToken(token).catch(fail);
        },
        'before-interactive-callback': () => { if (active) setInteractive(true); },
        'error-callback': fail,
        'expired-callback': fail,
        'timeout-callback': fail,
        'unsupported-callback': fail,
      });
    }).catch(fail);
    return () => {
      active = false;
      window.clearTimeout(timeout);
      if (widgetId !== undefined) turnstile?.remove(widgetId);
    };
  }, [siteKey, attempt]);

  return (
    <div className={`match-access-verification${interactive || failed ? ' is-visible' : ''}`}>
      {interactive && !failed && <p role="status">{t('Please verify to view matches.')}</p>}
      <div ref={container} />
      {failed && (
        <div role="alert">
          <p>{t('Verification could not finish. Please allow the verification script and try again.')}</p>
          <button className="button is-small is-link" onClick={() => setAttempt(value => value + 1)}>
            {t('Try again')}
          </button>
        </div>
      )}
      {(interactive || failed) && (
        <button className="button is-small" onClick={cancelMatchAccess}>{t('Cancel')}</button>
      )}
    </div>
  );
}

export default function MatchAccessVerification() {
  const request = useSyncExternalStore(subscribeMatchAccess, getMatchAccessRequest, () => null);
  return request ? <Challenge siteKey={request.siteKey} /> : null;
}
