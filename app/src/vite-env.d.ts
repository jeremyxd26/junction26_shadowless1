/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** `mock` (default) or `live`. */
  readonly VITE_API_MODE?: string
  /** Optional prefix for live API calls; empty means the same origin. */
  readonly VITE_API_BASE?: string
  /** `true` sends the bill flow's calls to the core (only with VITE_API_MODE=live); else the mock. */
  readonly VITE_BILL_LIVE?: string
}

interface ImportMeta {
  readonly env: ImportMetaEnv
}
