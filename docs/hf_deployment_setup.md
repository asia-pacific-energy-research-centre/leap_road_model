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
|------|------|
| `asia-pacific-energy-research-centre/leap_road_model` | Python pipeline — cloned into the container at build time |
| `H3yfinn/road_model_inputs_interface` | Frontend + backend — this IS the HF Space |
| `finbarmaunsell/leap_road_model` (HF) | The live HF Space, synced from road_model_inputs_interface |

## GitHub Actions

### `leap_road_model/.github/workflows/update_interface_sha.yml`
Triggers on push to `main`. Updates `LEAP_ROAD_MODEL_VERSION` in `road_model_inputs_interface/Dockerfile` to the new commit SHA, then commits and pushes to that repo.

**Secret required:** `INTERFACE_REPO_TOKEN` — a GitHub fine-grained PAT with Contents Read & Write on `H3yfinn/road_model_inputs_interface`. Set in `asia-pacific-energy-research-centre/leap_road_model` → Settings → Secrets → Actions.

### `road_model_inputs_interface/.github/workflows/sync_to_hf.yml`
Triggers on push to `main`. Creates an orphan commit (no history) and force-pushes it to the HF Space. Using an orphan avoids HF rejecting pushes that contain large files in old commits.

**Secret required:** `HF_TOKEN` — a Hugging Face token with write access to `finbarmaunsell/leap_road_model`. Set in `H3yfinn/road_model_inputs_interface` → Settings → Secrets → Actions.

## Data files

HF Spaces reject individual files over 10 MB. The two large source files have been replaced:

| Original | Replacement | How |
| --- | --- | --- |
| `00APEC_2024_low_with_subtotals.csv` (34 MB) | Same path, filtered (1.3 MB) | Kept 5 queried flows, years 2000–2022 |
| `transport_leap_export_combined_ALL_ECONS_*.xlsx` (>10 MB) | 21 per-economy files (~0.5 MB each) | Split by Region; app already prefers per-economy files |

To regenerate these when source data changes, run:

```sh
python back-end/scripts/preprocess_large_files.py
```

Then commit the outputs.

## Keys (stored in gitignored `keys.txt`)

- **GitHub PAT** (`INTERFACE_REPO_TOKEN`): fine-grained token, Contents R/W on `road_model_inputs_interface`
- **HF token** (`HF_TOKEN`): huggingface.co token with write access to the Space

To rotate the HF token: huggingface.co/settings/tokens — update the `HF_TOKEN` secret in `road_model_inputs_interface` after rotating.
