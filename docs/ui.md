# Shared browser UI

The browser terminal and proxy management page come from the sibling `external-sandbox-ui` repository. This server commits a complete, pinned copy in `src/external_sandbox_container/ui/`, so cloning, installing, and running the server does not require that sibling checkout, Git submodules, npm, or network access to fetch UI assets. Node.js is required only to run the shared JavaScript tests during development.

The shared source owns the HTML, CSS, JavaScript, and frontend interaction tests. Python's `terminal.py` and `proxy_management.py` remain small HTTP adapters that serve package resources, substitute template values, and enforce the existing Host, Origin, token, and CSP rules. Terminal branding stays `External sandbox terminal` and `External sandbox container`. Template substitution is one pass, so marker-like text in a working directory remains literal after HTML escaping.

## Change and update the UI

Edit and test the UI in `../external-sandbox-ui`, then commit it and choose a release tag or full commit. Do not edit the copies under `src/external_sandbox_container/ui/`. From this server's repository root, import a release:

```sh
uv run python ../external-sandbox-ui/scripts/sync.py --ref v0.3.0 --dest src/external_sandbox_container/ui
```

Replace `v0.2.0` with the release or commit to adopt. The command copies the shared assets and tests and records the package version, source commit, file inventory, and SHA-256 hashes in `manifest.json`. Review and commit the resulting bundle changes alongside any necessary Python adapter changes. Both server implementations can adopt the same release independently.

Check that the copy still matches its recorded source commit:

```sh
uv run python ../external-sandbox-ui/scripts/sync.py --check --dest src/external_sandbox_container/ui
```

The shared checkout is needed for updating and for that source comparison. The ordinary Python test suite also checks the local bundle's inventory and hashes against its manifest, without needing the shared checkout. This catches missing, stale, or edited files; source comparison additionally checks those bytes against the recorded Git commit.

## Verify and package

```sh
uv run pytest -m 'not integration'
node --test tests/test_terminal_js.mjs
uv run ruff check .
uv build
```

`tests/test_terminal_js.mjs` imports the bundled terminal, proxy, and template tests, so each server runs the same frontend checks against the assets it ships. Python tests cover the HTTP adapters, including browser access checks, CSP, branding, and safe template substitution.

To run those frontend checks using assets fetched from a running proxy-enabled server, set `EXTERNAL_SANDBOX_UI_URL`:

```sh
EXTERNAL_SANDBOX_UI_URL=http://127.0.0.1:8687 node --test tests/test_terminal_js.mjs
```

This mode fetches only the two HTML pages and terminal JavaScript with GET requests; frontend interactions then use the same simulated DOM, WebSocket, and proxy API fixtures as the local asset tests. It does not execute commands or change the running server's policy.

The wheel includes `ui/assets/`, `ui/package.json`, and `ui/manifest.json`. It omits the shared JavaScript tests, while the source distribution retains them along with the local test wrapper. Assets are read through `importlib.resources`, so the installed wheel serves the same files without depending on a source checkout. The manifest describes the complete source bundle, including its tests, even though the wheel includes only its runtime subset.

## Verification — 9 October 2026

The initial `exec-server-ui` 0.1.0 integration (before the shared UI package was renamed) passed 244 Python tests with 22 integration tests deselected, plus 26 shared JavaScript tests with one mode-specific test skipped. Ruff, whitespace checks, and comparison with the recorded shared Git commit passed. `uv build` produced a source distribution and built the wheel from it; archive inspection checked every bundled hash, confirmed that the source distribution retains the tests, and confirmed that the wheel excludes them.

The built wheel was installed in an isolated uv environment and imported from `site-packages`. A temporary aiohttp fixture served both pages and the JavaScript using the installed package resources, preserving Python branding and escaped marker-like directory names. The shared suite also passed against those HTTP-served assets: 26 tests passed, with the raw-template-only test skipped. This verification used a fake execution backend and proxy; it did not restart the demo server or repeat Apple Container integration tests.

The subsequent server rename adopted the shared UI bundle 0.2.0 and passed 255 Python unit/protocol tests, 16 real Apple Container/client/proxy integration tests, and 51 Pi extension tests. Four optional tool-image integration checks were skipped. The shared JavaScript suite again passed 26 tests in both bundled-asset and installed-wheel HTTP modes, with one mode-specific skip per run. The renamed wheel's CLI help, setup export, package imports, asset hashes, and frontend routes were verified in an isolated environment; source distribution contents, Ruff, and the pinned-source check also passed. The separately configured Codex CLI tests were not repeated.
