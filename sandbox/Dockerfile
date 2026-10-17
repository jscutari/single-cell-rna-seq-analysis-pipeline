# scverse analysis image. One container per hypothesis runs a Jupyter kernel
# with no network; the agents send it code cells (see kernel_manager.py).
#
#   docker build -t scrap-sandbox sandbox/
FROM python:3.12-slim

COPY --from=ghcr.io/astral-sh/uv:0.13.1 /uv /usr/local/bin/uv

# Hackathon rule: libraries must be at least 2 weeks old.
ENV UV_EXCLUDE_NEWER=2026-10-03T00:00:00Z

RUN uv pip install --system --no-cache \
      scanpy anndata scikit-misc igraph leidenalg \
      decoupler pydeseq2 statsmodels scipy pandas gseapy \
      matplotlib seaborn \
      ipykernel

# Gene sets baked in at build time, since the kernel has no network.
COPY fetch_genesets.py /tmp/
RUN python /tmp/fetch_genesets.py /opt/genesets && rm /tmp/fetch_genesets.py

# Run as an unprivileged user; plots render to files, never a display.
RUN useradd --create-home --uid 1000 analyst
USER analyst
WORKDIR /work
ENV MPLBACKEND=Agg \
    GENESETS_DIR=/opt/genesets \
    PYTHONUNBUFFERED=1
