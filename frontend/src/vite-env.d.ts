/// <reference types="vite/client" />

/** The version this site was built from (backend __version__), baked in by vite.config. */
declare const __APP_VERSION__: string;

/** Per-build id (git short SHA, else build date), baked in by vite.config — see changelog (#16). */
declare const __BUILD_ID__: string;

interface ImportMetaEnv {
  /** "1" when the build is the GitHub Pages site that talks to a local operator (spec §6.3). */
  readonly VITE_SITE_MODE?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
