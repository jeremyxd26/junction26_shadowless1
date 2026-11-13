/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** `mock` (default) or `live`. */
  readonly VITE_API_MODE?: string
  /** Optional prefix for live API calls; empty means the same origin. */
  readonly VITE_API_BASE?: string
}

interface ImportMeta {
  readonly env: ImportMetaEnv
}
