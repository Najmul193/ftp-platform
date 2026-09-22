/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** Absolute API base, e.g. `https://ftp-api.example.com/api/v1`.
   *
   *  Left unset the client calls `/api/v1` on its own origin, which is how it
   *  runs in development (Vite proxies it) and behind any same-origin reverse
   *  proxy. Set it when the API is on a different host, which also requires
   *  that host to allow this origin via CORS_ORIGINS. */
  readonly VITE_API_BASE?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
