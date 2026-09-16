# Reproducing the UFC Gen 1 study

Use the exact nine source files in `SOURCE_MANIFEST.json` from a governed external
directory. Do not place raw data in the repository. Run with Python 3.12.6,
NumPy 1.26.4, pandas 2.2.1, scikit-learn 1.6.1, SciPy 1.17.1 and joblib 1.4.2.
Set `OMP_NUM_THREADS`, `MKL_NUM_THREADS`, `OPENBLAS_NUM_THREADS` and
`LOKY_MAX_CPU_COUNT` to `1`.

```powershell
$source = '<external raw-v87 directory>'
$output = '<new external research output directory>'
$design = 'docs/mma-gen1-research-model-v1/FROZEN_DESIGN.json'
python -B -m server.sports_mma.gen1.cli profile --source-root $source --output-root $output --design $design
python -B -m server.sports_mma.gen1.cli select --source-root $source --output-root $output --design $design
python -B -m server.sports_mma.gen1.cli oot --source-root $source --output-root $output --design $design
python -B -m server.sports_mma.gen1.cli finalize --source-root $source --output-root $output --design $design
python -B -m server.sports_mma.gen1.cli verify --source-root $source --output-root $output --design $design
```

The `oot` command is deliberately one-time and refuses to run when `FINAL_OOT.json`
already exists. Reproduction must use a new output root. The completed study root
must not be rescored or retuned.

Focused tests:

```powershell
$env:MMA_GEN1_SOURCE_ROOT = '<external raw-v87 directory>'
python -B -m unittest server.sports_mma.gen1.test_gen1 -v
```

