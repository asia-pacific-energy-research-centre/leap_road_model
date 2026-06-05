# HF Space Deployment Setup

## How it works

Two GitHub repos feed one Hugging Face Space (`finbarmaunsell/leap_road_model`):

```
push to leap_road_model (GitHub)
    → Action updates LEAP_ROAD_MODEL_VERSION SHA in road_model_inputs_interface Dockerfile
        → Action pushes road_model_inputs_interface to HF Space
            → HF rebuilds the container with the new leap_road_model code
```

## Repo roles

| Repo | Role |
| --- | --- |
| `asia-pacific-energy-research-centre/leap_road_model` | Python pipeline — cloned into the container at build time |
| `H3yfinn/road_model_inputs_interface` | Frontend + backend — this IS the HF Space |
| `finbarmaunsell/leap_road_model` (HF) | The live HF Space, synced from road_model_inputs_interface |

## GitHub Actions

### `leap_road_model/.github/workflows/update_interface_sha.yml`

Triggers on push to `main`. Updates `LEAP_ROAD_MODEL_VERSION` in `road_model_inputs_interface/Dockerfile` to the new commit SHA, then commits and pushes to that repo.

**Secret required:** `INTERFACE_REPO_TOKEN` — a GitHub fine-grained PAT with Contents Read & Write on `H3yfinn/road_model_inputs_interface`. Set in `asia-pacific-energy-research-centre/leap_road_model` → Settings → Secrets → Actions.

### `road_model_inputs_interface/.github/workflows/sync_to_hf.yml`

Triggers on push to `main`. Creates an orphan commit (no history) and force-pushes it to the HF Space.

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

## ⚠️ After every deployment: hard-refresh your browser

After a new deployment, your browser will likely still be running the **old cached `app.js`**. This causes subtle failures — e.g. requesting `.json` files when the new code expects `.csv` — that look like server errors but are actually stale client code.

**Always hard-refresh after a deploy:**

- Windows/Linux: `Ctrl + Shift + R`
- Mac: `Cmd + Shift + R`

If the error persists after a hard refresh, then it is a real server-side issue.

## Keys (stored in gitignored `keys.txt`)

- **GitHub PAT** (`INTERFACE_REPO_TOKEN`): fine-grained token, Contents R/W on `road_model_inputs_interface`
- **HF token** (`HF_TOKEN`): huggingface.co token with write access to the Space

To rotate the HF token: huggingface.co/settings/tokens — update the `HF_TOKEN` secret in `road_model_inputs_interface` after rotating.
