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

HF Spaces enforce three hard limits on git pushes. Each required a code change:

### 1. No files over 10 MB

HF rejects any file in the pushed history that exceeds 10 MB.

**Problem files:**

- `back-end/data/multinodeenergy_backend/00APEC_2024_low_with_subtotals.csv` — 34 MB full APEC energy database
- `back-end/data/road_model/leap_import_workbooks/transport_leap_export_combined_ALL_ECONS_*.xlsx` — combined all-economy LEAP export workbook

**Fix:** Pre-process both files down to what the app actually uses:

| Original | Replacement | How |
| --- | --- | --- |
| `00APEC_2024_low_with_subtotals.csv` (34 MB) | Same path, filtered (1.3 MB) | Kept only the 5 flows the frontend queries, years 2000–2022 |
| `transport_leap_export_combined_ALL_ECONS_*.xlsx` (>10 MB) | 21 per-economy files (~0.5 MB each) | Split by Region column; app already prefers per-economy files over the combined file |

To regenerate when source data changes:

```sh
python back-end/scripts/preprocess_large_files.py
```

Then commit the outputs.

### 2. No large files in git history

Even after fixing the current files, HF rejected the push because old commits in the GitHub history still contained the original large files.

**Fix:** The `sync_to_hf.yml` Action uses `git checkout --orphan` to create a history-free snapshot commit before pushing. This means HF only sees the current state of the repo, not any prior commits.

### 3. No binary files (PNGs etc.)

HF also rejects binary files such as PNGs, asking you to use their Xet storage instead. The `docs/` folder contains PNG diagrams that the HF Space doesn't need.

**Fix:** The Action runs `git rm -rf --cached docs/` on the orphan branch before committing, so the docs folder is never pushed to HF.

## Keys (stored in gitignored `keys.txt`)

- **GitHub PAT** (`INTERFACE_REPO_TOKEN`): fine-grained token, Contents R/W on `road_model_inputs_interface`
- **HF token** (`HF_TOKEN`): huggingface.co token with write access to the Space

To rotate the HF token: huggingface.co/settings/tokens — update the `HF_TOKEN` secret in `road_model_inputs_interface` after rotating.
