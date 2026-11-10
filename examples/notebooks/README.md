# Upstream mock notebooks

> These notebooks demonstrate the reused library with mocks. They do not make live ClaimDocs extraction calls or measure its accuracy. Use the [application README](../../README.md) for the billing demo.

# py-idp example notebooks

Three Jupyter notebooks that walk through py-idp from "freshly installed"
to "running a real batch with checkpoint resume." All three use the
in-tree `MockBackend`, so **no API key is required** to run them.

| notebook | story | time |
|---|---|---|
| [01_pipeline_minimal.ipynb](01_pipeline_minimal.ipynb) | one document through all six stages | 5 min |
| [02_hitl_loop.ipynb](02_hitl_loop.ipynb) | low-confidence → human review → policy override → second run | 10 min |
| [03_batch.ipynb](03_batch.ipynb) | 30 docs through `process_batch()`, DataFrame view, checkpoint resume | 15 min |

## Run them

```bash
# from the repo root
pip install py-idp jupyter nbformat nbconvert ipykernel pandas  # pandas only for notebook 03

# Launch jupyter
jupyter lab examples/notebooks/
```

## Environment

The notebooks resolve sample documents relative to the repo root. They
look for the env var `IDP_REPO_ROOT` first, then fall back to `Path.cwd()`.
Set it once in your shell so all notebooks find their samples:

```bash
export IDP_REPO_ROOT=/path/to/py-idp
```

If you launch Jupyter from the repo root, no env var is needed.

## Outputs

Each notebook is **executed-and-saved with output cells** so the rendered
view on GitHub shows real numbers, not blank code blocks. To re-execute
a notebook after editing, run:

```bash
jupyter nbconvert --to notebook --execute --inplace examples/notebooks/01_pipeline_minimal.ipynb
```

## What this collection covers (and doesn't)

| in scope | out of scope |
|---|---|
| the happy path | real backend API calls (use examples/02_anthropic.py etc. for that) |
| end-to-end execution | schema discovery (covered by `idp discover-schema` CLI) |
| the six pipeline stages | template discovery (covered by `idp discover-template` CLI) |
| HITL feedback loop | HITL Streamlit UI (covered by `hitl/app.py`) |

For the broader examples catalog, see [`../`](../).