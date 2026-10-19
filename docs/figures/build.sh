#!/usr/bin/env bash
# Build SCRAP's figures: each figN_*.tex -> out/figN_*.{pdf,svg,png} (PNG 3840x2160).
# Needs TinyTeX/TeX Live with pgf + standalone + sfmath, and poppler (pdftoppm, pdftocairo).
set -euo pipefail
cd "$(dirname "$0")"
mkdir -p out build
for tex in fig*.tex; do
  name="${tex%.tex}"
  pdflatex -interaction=nonstopmode -halt-on-error -output-directory=build "$tex" >/dev/null \
    || { echo "LaTeX failed for $tex (see build/$name.log)" >&2; exit 1; }
  cp "build/$name.pdf" "out/$name.pdf"
  pdftoppm -png -singlefile -scale-to-x 3840 -scale-to-y 2160 "out/$name.pdf" "out/$name"
  pdftocairo -svg "out/$name.pdf" "out/$name.svg"
  echo "built out/$name.{pdf,svg,png}"
done
