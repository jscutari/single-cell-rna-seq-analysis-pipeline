# Figures

Paper-style diagrams for the demo video, drawn with TikZ (16:9, white background).

| Figure | Shows | Files |
| --- | --- | --- |
| 1 | The multi-agent pipeline: eight agent roles over six stages, three parallel hypothesis lanes with sandboxes, and the critic's review loops | `out/fig1_pipeline.{png,pdf,svg}` |
| 2 | How the agents use NVIDIA Nemotron Lightning through Red Hat vLLM on an NVIDIA Brev H100 | `out/fig2_nvidia.{png,pdf,svg}` |

PNGs are 3840×2160 for video; the PDF and SVG copies are vectors.

**Rebuild:** `bash docs/figures/build.sh`. Needs TinyTeX/TeX Live with `pgf`, `standalone` and `sfmath` (`tlmgr install pgf standalone sfmath`) and poppler (`pdftoppm`, `pdftocairo`). Shared colours, fonts and node styles are in `style.tex`.
