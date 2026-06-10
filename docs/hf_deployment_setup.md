# HF Space Deployment Setup

## Contents

1. [How it works](#how-it-works)
2. [Repo roles](#repo-roles)
3. [GitHub Actions](#github-actions)
4. [HF push constraints and how we handle them](#hf-push-constraints-and-how-we-handle-them)
5. [After every deployment: hard-refresh your browser](#after-every-deployment-hard-refresh-your-browser)
6. [Keys](#keys-stored-in-gitignored-keystxt)

## How it works

Two GitHub repos feed one Hugging Face Space (`finbarmaunsell/leap_road_model`):

```
push to leap_road_model (GitHub)
    → update_interface_sha.yml dispatches sync_to_hf.yml in road_model_inputs_interface
        → sync_to_hf.yml pushes road_model_inputs_interface to HF Space
            → HF rebuilds the container, cloning leap_road_model at latest main
```

The Dockerfile uses `LEAP_ROAD_MODEL_REF=main` — no SHA pinning. Every rebuild always picks up the latest `leap_road_model` main.

**Important:** Docker caches build layers. The `git clone leap_road_model` step is only re-run when something before it in the Dockerfile changes. Without a cache-bust mechanism, HF would keep serving the old clone even after `leap_road_model` is updated. To prevent this, `sync_to_hf.yml` writes the current `leap_road_model` HEAD SHA into `leap_road_model_sha.txt` before each push. The Dockerfile COPYs that file immediately before the `git clone` step — when the SHA changes, Docker invalidates the clone layer and re-clones.

## Repo roles

| Repo | Role |
| --- | --- |
| `asia-pacific-energy-research-centre/leap_road_model` | Python pipeline — cloned into the container at build time |
| `H3yfinn/road_model_inputs_interface` | Frontend + backend — this IS the HF Space |
| `finbarmaunsell/leap_road_model` (HF) | The live HF Space, synced from road_model_inputs_interface |

## GitHub Actions

### `leap_road_model/.github/workflows/update_interface_sha.yml`

Triggers on push to `main`. Calls the GitHub API to dispatch `sync_to_hf.yml` in the interface repo, which triggers an HF Space rebuild.

**Secret required:** `INTERFACE_REPO_TOKEN` — a GitHub fine-grained PAT with Contents Read & Write on `H3yfinn/road_model_inputs_interface`. Set in `asia-pacific-energy-research-centre/leap_road_model` → Settings → Secrets → Actions.

### `road_model_inputs_interface/.github/workflows/sync_to_hf.yml`

Triggers on push to `main` or `workflow_dispatch`. Creates an orphan commit (no history) and force-pushes it to the HF Space. HF detects the new commit and rebuilds, cloning `leap_road_model` at `main`.

**Secret required:** `HF_TOKEN` — a Hugging Face token with write access to `finbarmaunsell/leap_road_model`. Set in `H3yfinn/road_model_inputs_interface` → Settings → Secrets → Actions.

## HF push constraints and how we handle them

HF Spaces enforce hard limits on git pushes. Each required a change:

### 1. No files over 10 MB / no binary files (PNGs etc.)

The repo had large source data files and PNG diagrams in `docs/` that HF rejects.

**Fix:** These files are simply not pushed to HF:

- The APEC energy database CSV and LEAP export xlsx files are gitignored — the app's `processed_source/` per-economy CSVs (already committed) are what HF uses at runtime. The energy model tab (residential/industry sector view) is not needed on HF so the APEC CSV is excluded entirely.
- `docs/` is stripped from the orphan commit before pushing via `git rm -rf --cached docs/`

### 2. No large files in git history

Even with large files absent from the current commit, HF rejected pushes because old commits in the GitHub history still contained them.

**Fix:** The `sync_to_hf.yml` Action uses `git checkout --orphan` to create a history-free snapshot commit before pushing. HF only ever sees the current state of the repo, not any prior commits.

## After every deployment: hard-refresh your browser

After a new deployment, your browser will likely still be running the **old cached `app.js`**. This causes subtle failures — e.g. requesting `.json` files when the new code expects `.csv` — that look like server errors but are actually stale client code.

**Always hard-refresh after a deploy:**

- Windows/Linux: `Ctrl + Shift + R`
- Mac: `Cmd + Shift + R`

If the error persists after a hard refresh, then it is a real server-side issue.

## Manual rebuild

To trigger a rebuild without pushing new code, run `sync_to_hf.yml` manually from the GitHub Actions UI in the interface repo: Actions → Sync to Hugging Face Space → Run workflow.

## Verifying a deployment

After a rebuild and model run, use the diagnostic endpoint to confirm the container has fresh results:

```text
https://finbarmaunsell-leap-road-model.hf.space/api/v1/road-results-info/{economy}
```

Returns file existence and last-modified timestamps for the three key output files (`module6.html`, `T8_fuel_allocation.csv`, `T11_leap_ready.csv`). If `module6.html` shows `exists: false`, the model has not been run yet on this container. A recent timestamp confirms the run completed with the new code.

## Keys (stored in gitignored `keys.txt`)

- **GitHub PAT** (`INTERFACE_REPO_TOKEN`): fine-grained token, Contents R/W on `road_model_inputs_interface`
- **HF token** (`HF_TOKEN`): huggingface.co token with write access to the Space

To rotate the HF token: huggingface.co/settings/tokens — update the `HF_TOKEN` secret in `road_model_inputs_interface` after rotating.
