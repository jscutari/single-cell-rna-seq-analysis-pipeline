/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** "false" talks to the FastAPI backend; anything else uses mock data. */
  readonly VITE_USE_MOCK?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
