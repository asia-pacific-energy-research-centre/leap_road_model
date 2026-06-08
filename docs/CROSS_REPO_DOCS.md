# Cross-repository docs references

This repository is designed to be worked on alongside `../road_model_inputs_interface`.

## Contents

1. [Key docs in `road_model_inputs_interface`](#key-docs-in-road_model_inputs_interface)
2. [Working convention](#working-convention)

## Key docs in `road_model_inputs_interface`

- `..\..\road_model_inputs_interface\docs\new model\multinode_road_module1_repo_guide.md`
- `..\..\road_model_inputs_interface\front-end\road-module1-static\README.md`
- `..\..\road_model_inputs_interface\docs\CROSS_REPO_DOCS.md`

## Working convention

- Keep both repos open in one multi-root VS Code workspace.
- Treat docs in both repos as one shared design corpus.
- Prefer source-data contracts in `road_model_inputs_interface/back-end/data/road_model` and avoid manual assumptions files.
