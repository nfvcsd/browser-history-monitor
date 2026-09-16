import { FormEvent, ReactNode, useEffect, useRef, useState } from "react";
import { api } from "./api";

export interface AdminIdentity {
  mode: "development" | "google";
  sub: string;
  email: string | null;
  name: string;
  expires_at: number | null;
}
export interface AuthConfig {
  mode: "development" | "google";
  google_client_id: string | null;
  configured: boolean;
}
interface GoogleIdentity {
  initialize(options: {
    client_id: string;
    callback: (response: { credential: string }) => void;
    auto_select: boolean;
    ux_mode: string;
  }): void;
  renderButton(
    element: HTMLElement,
    options: { theme: string; size: string; text: string },
  ): void;
  disableAutoSelect(): void;
}
declare global {
  interface Window {
    google?: { accounts: { id: GoogleIdentity } };
  }
}
const STORAGE_KEY = "browserHistoryAdminSession";
let googleScript: Promise<void> | undefined;
function loadGoogle() {
  if (window.google?.accounts.id) return Promise.resolve();
  if (!googleScript) {
    googleScript = new Promise<void>((resolve, reject) => {
      const script = document.createElement("script");
      script.src = "https://accounts.google.com/gsi/client";
      script.async = true;
      script.onload = () => resolve();
      script.onerror = () => {
        script.remove();
        googleScript = undefined;
        reject(
          new Error(
            "Google sign-in could not load. Check your connection and refresh.",
          ),
        );
      };
      document.head.appendChild(script);
    });
  }
  return googleScript;
}
function GoogleButton({
  clientId,
  onCredential,
  onError,
}: {
  clientId: string;
  onCredential: (token: string) => void;
  onError: (message: string) => void;
}) {
  const element = useRef<HTMLDivElement>(null);
  const callback = useRef(onCredential);
  callback.current = onCredential;
  const errorCallback = useRef(onError);
  errorCallback.current = onError;
  useEffect(() => {
    let active = true;
    loadGoogle()
      .then(() => {
        if (!active || !element.current) return;
        const id = window.google?.accounts.id;
        if (!id)
          throw new Error("Google sign-in is unavailable. Please refresh.");
        id.initialize({
          client_id: clientId,
          auto_select: false,
          ux_mode: "popup",
          callback: (response) => {
            if (active) callback.current(response.credential);
          },
        });
        id.renderButton(element.current, {
          theme: "outline",
          size: "large",
          text: "signin_with",
        });
      })
      .catch((error) => {
        if (active) errorCallback.current(error.message);
      });
    return () => {
      active = false;
    };
  }, [clientId]);
  return <div ref={element} className="google-signin" />;
}

export default function AuthGate({
  children,
}: {
  children: (props: {
    token: string;
    identity: AdminIdentity;
    logout: () => void;
  }) => ReactNode;
}) {
  const [config, setConfig] = useState<AuthConfig | null>(null);
  const [session, setSession] = useState<{
    token: string;
    identity: AdminIdentity;
  } | null>(null);
  const [busy, setBusy] = useState(true);
  const [error, setError] = useState("");
  const [retry, setRetry] = useState(0);
  const currentToken = useRef<string | null>(null);
  const attempt = useRef(0);
  function clear(message = "") {
    attempt.current += 1;
    currentToken.current = null;
    sessionStorage.removeItem(STORAGE_KEY);
    localStorage.removeItem("adminToken");
    setSession(null);
    setBusy(false);
    setError(message);
    window.google?.accounts.id.disableAutoSelect();
  }
  async function login(token: string) {
    const generation = ++attempt.current;
    setBusy(true);
    setError("");
    try {
      const identity = await api.me(token);
      if (generation !== attempt.current) return;
      currentToken.current = token;
      sessionStorage.setItem(STORAGE_KEY, token);
      setSession({ token, identity });
    } catch (e) {
      if (generation === attempt.current) {
        sessionStorage.removeItem(STORAGE_KEY);
        setError(e instanceof Error ? e.message : "Sign-in failed");
      }
    } finally {
      if (generation === attempt.current) setBusy(false);
    }
  }
  useEffect(() => {
    let active = true;
    setBusy(true);
    setError("");
    api
      .authConfig()
      .then(async (settings) => {
        if (!active) return;
        setConfig(settings);
        const legacy = localStorage.getItem("adminToken");
        localStorage.removeItem("adminToken");
        const saved =
          sessionStorage.getItem(STORAGE_KEY) ||
          (settings.mode === "development" && legacy ? `dev:${legacy}` : null);
        const prefix = settings.mode === "google" ? "google:" : "dev:";
        if (settings.configured && saved?.startsWith(prefix))
          await login(saved);
        else {
          sessionStorage.removeItem(STORAGE_KEY);
          setBusy(false);
        }
      })
      .catch((e) => {
        if (active) {
          setError(e.message);
          setBusy(false);
        }
      });
    return () => {
      active = false;
      attempt.current += 1;
    };
  }, [retry]);

  useEffect(() => {
    const expired = (event: Event) => {
      const detail = (event as CustomEvent<{ token: string; message: string }>)
        .detail;
      if (detail.token === currentToken.current) clear(detail.message);
    };
    window.addEventListener("admin-auth-required", expired);
    return () => window.removeEventListener("admin-auth-required", expired);
  }, []);
  useEffect(() => {
    if (!session || session.identity.expires_at === null) return;
    const remaining = session.identity.expires_at * 1000 - Date.now();
    const timer = setTimeout(
      () => clear("Your Google sign-in expired. Please sign in again."),
      Math.max(0, remaining),
    );
    const verify = () => {
      void api.me(session.token).catch(() => {
        /* 401/403 handled globally; transient errors allow retry. */
      });
    };
    const interval = setInterval(verify, 5 * 60 * 1000);
    window.addEventListener("focus", verify);
    return () => {
      clearTimeout(timer);
      clearInterval(interval);
      window.removeEventListener("focus", verify);
    };
  }, [session]);

  function developmentLogin(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const token = String(
      new FormData(event.currentTarget).get("token") || "",
    ).trim();
    if (token) void login(`dev:${token}`);
  }
  if (session) return <>{children({ ...session, logout: () => clear() })}</>;
  return (
    <main className="login-shell">
      <section className="login-card">
        <span className="eyebrow">Administrator sign-in</span>
        <h1>Browser History Monitor</h1>
        {error && (
          <p role="alert" className="error">
            {error}
          </p>
        )}
        {busy && <p role="status">Checking sign-in…</p>}
        {config && !config.configured && (
          <p role="alert">
            Sign-in is not configured. Contact your administrator.
          </p>
        )}
        {config?.configured && config.mode === "google" && (
          <>
            <p>
              Sign in with your authorized Google Workspace administrator
              account.
            </p>
            <div aria-busy={busy}>
              <GoogleButton
                key={retry}
                clientId={config.google_client_id!}
                onCredential={(credential) => {
                  void login(`google:${credential}`);
                }}
                onError={setError}
              />
            </div>
          </>
        )}
        {config?.configured && config.mode === "development" && (
          <form onSubmit={developmentLogin}>
            <p>Development mode: enter the administrator token.</p>
            <input
              name="token"
              type="password"
              aria-label="Administrator token"
              autoComplete="off"
              required
            />
            <button disabled={busy}>Open dashboard</button>
          </form>
        )}
        {!busy && (!config || !config.configured || error) && (
          <button
            className="secondary auth-retry"
            onClick={() => setRetry((v) => v + 1)}
          >
            Retry sign-in setup
          </button>
        )}
      </section>
    </main>
  );
}
