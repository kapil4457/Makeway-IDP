/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** Origin of the Makeway control-plane API. Dev default: the Vite proxy. */
  readonly VITE_API_BASE_URL?: string
}

interface ImportMeta {
  readonly env: ImportMetaEnv
}
