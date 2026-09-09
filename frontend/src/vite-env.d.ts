/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** "1" when the build is the GitHub Pages site that talks to a local operator (spec §6.3). */
  readonly VITE_SITE_MODE?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
