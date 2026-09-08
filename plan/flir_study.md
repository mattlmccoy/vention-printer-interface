# FLIR Research Interface — family architecture (condensed from study, 2026-09-08)

Repo: /Users/mattmccoy/GaTech Dropbox/Matthew McCoy/FLIR. Layout: backend/ frontend/ docs/ plan/ scripts/ .github/ .claude/launch.json install.sh install.ps1 README LICENSE(MIT).

## Backend (uv, hatchling, py>=3.10,<3.13)
- deps: numpy psutil fastapi uvicorn[standard] websockets zarr<3 numcodecs pillow h5py; dev: pytest ruff mypy httpx.
- ruff line-length 100, select E F I B UP N W; mypy strict py3.12; pytest testpaths=tests, marker `hardware` (skipped unless `--hardware`, via conftest.py pytest_addoption).
- CLIs `fri-*` = `module:main`, every `main(argv=None) -> int`, argparse, `--host 127.0.0.1 --port 8000 --backend {simulated,spinnaker} --site-origin https://mattlmccoy.github.io -v`.
- Package subpackages: camera/ (ABC base.py + simulated.py + spinnaker.py + controls.py + __init__ registry `register_backend(name)` / `create_backend(name, **kw)` / `CAMERA_BACKENDS`), radiometry/ (pure), acquisition/service.py (thread, state enum DISCONNECTED/CONNECTED/ACQUIRING/ERROR, listeners, newest-wins slot, `wait_for_frame(after_id, timeout_s)`, `stats()`), recording/recorder.py (bounded queue -> writer thread -> Zarr; metadata.json at start; manifest.json ONLY on clean stop; `complete` = no error & no drops & written==received; dir `<YYYYMMDD_HHMMSS>_<slug>`), playback/, analysis/, api/ (app.py `create_app(*, default_backend, ..., site_origin)` all routes closures, state on app.state via lifespan, blocking via run_in_threadpool, background jobs `{state,step,done,total,error}` + `.../status` GET; frames.py wire format; server.py CLI; mounts frontend/dist at "/").
- Only camera/ may import the vendor SDK (PySpin). Everything else sees the ABC.
- Cross-origin: `install_cross_origin_policy(app, site_origin)`: middleware rejects cross-origin non-GET /api/ without `X-FRI-Client: 1` (403); CORSMiddleware allow_origins=[site_origin] + localhost regex. `API_VERSION="1.0"` handshake.
- WS `/ws/frames`: binary `[u32 BE header len][JSON header][payload]`; text JSON `{"type":"status",...}` when idle. Server never sends rendered pixels; client derives.
- Tests: flat backend/tests/test_<module>.py, plain functions, TestClient with injected fakes.

## Frontend (Vite 5 + React 18 + TS 5, NO other runtime deps)
- scripts: dev / build (`tsc --noEmit && vite build`) / test (`node --experimental-strip-types --test 'src/**/*.test.ts'`). No jest/vitest/jsdom; only pure src/lib/*.ts is tested; tests colocated.
- tsconfig: verbatimModuleSyntax + allowImportingTsExtensions -> imports carry `.ts/.tsx`.
- vite.config: base=VITE_BASE, port 5173, proxy /api->127.0.0.1:8000, /ws (ws:true). Site mode = `VITE_SITE_MODE=1` (talks to http://localhost:8000, OperatorGate, sw.js). Pages base `/flir-research-interface/`.
- src/: main.tsx, App.tsx (page state, reducers, WS effect, StudioFrame per page), theme.css (ONLY place colours defined), styles.css (no :root, no colour literals - enforced by lib/theme.test.ts), components/ flat, components/studio/ (StudioFrame, ToolStrip, StripActions, StripIcons, Rail, RailSection, PlotDock, StatusBar, FloatContext, FloatingPanel), lib/ pure logic (layout.ts reducer + loadLayout/saveLayout `fri.layout.v1` validated on load; api.ts `req()` adds X-FRI-Client; operator.ts base URL `fri.operator.v1`; protocol.ts decode).
- Studio grid: rows `--topbar-h 40px | 1fr | --statusbar-h 28px`; cols `--strip-w 40px | 1fr | --rail-w 400px`; areas top/strip-center-rail/status; center = image + `--dock-h 260px` dock; `.studio.page` = no strip/dock. Resizers absolutely positioned. Slot contract: strip/rail/statusbar slots render exactly one element with class strip/rail/statusbar. RAIL_W {280..760 def 400 snap 24}, DOCK_H {140..620 def 260}.
- StatusBar rule: never shows green; drops red, gaps amber; thresholds come from backend, never invented.
- ToolStrip: disabled tools stay visible (aria-disabled), CSS tooltips via data-tip.

## theme.css tokens (verbatim values)
color-scheme dark; --bg #101418; --bg-deep #0b0e12; --panel #141920; --line #232a33; --line-strong #2f3843; --line-control #4a5561; --fg #d7dde5; --fg-strong #f5f7fa; --muted #8b97a5; --accent #ffb454; --accent-ink var(--bg); --focus var(--accent); --live #5cff8a; --live-glow 0 0 8px rgba(92,255,138,.7); --live-glow-dim 0 0 3px rgba(92,255,138,.4); --live-bg rgba(92,255,138,.12); --warn var(--accent); --warn-bg rgba(255,180,84,.10); --err #ff5f56; --err-bg rgba(255,95,86,.12); --rec var(--err); --trace-3 #6ec3ff; --trace-4 #ff8ad8; --trace-5 #c9d64f; --trace-6 #b48cff; --image-bg #000; --scrim rgba(11,14,18,.85); --danger-ink #fff; --font-ui "IBM Plex Sans"...; --font-mono "Space Mono","IBM Plex Mono"...; --font-read "Helvetica Neue"...; --fs 13px; --space 4px; --radius 3px; --strip-w 40px; --rail-w 400px; --shadow 0 12px 40px rgba(0,0,0,.55); --dock-h 260px; --topbar-h 40px; --statusbar-h 28px. Keyframes fri-glow, fri-blink. Fonts self-hosted woff2 in public/fonts (test checks wOF2 magic; no Google Fonts).

## Docs
architecture.md (3 data classes never overwrite each other; backend ABC is the only interface; camera thread never blocks on consumer; recorder in service process; reading never writes), radiometry.md (every claim cited or marked UNKNOWN), data_format.md, installation.md, camera_setup.md, validation.md, visible_camera.md, development.md (TDD; `uv run pytest`; ruff+mypy strict; SDK import boundary; Conventional Commits; milestone gates table).

## Deploy / CI
ci.yml: backend job (setup-uv, py3.12, uv sync --extra dev, ruff, mypy, pytest) + frontend job (node 23, npm ci, npm test, tsc, build). pages.yml: on push main paths frontend/**, VITE_SITE_MODE=1 VITE_BASE=/repo/, upload-pages-artifact + deploy-pages. install.sh/ps1 one-command operator install + background service. .claude/launch.json: backend 8000, frontend-dev 5173, site 5174, staged 5175.

## Conventions
package flir_research_interface / dist flir-research-interface / CLIs fri-* / header X-FRI-Client / localStorage fri.*.v1 / experiment dir `<ts>_<slug>` / every module docstring names purpose + spec section / `# noqa: BLE001 - reason`. README has status table with per-row State (tested / verified in browser / hardware tests pass / unverified). plan/task_plan.md uses [x] [~] [ ], "Blocked on the user", "Open technical unknowns". plan/notes.md = dated evidence log with UNKNOWN/DISCREPANCY rows. .gitignore: vendor SDKs, experiment data, probe outputs, .env, .claude/logs.
