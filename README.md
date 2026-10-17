# single-cell-rna-seq-analysis-pipeline
Single-Cell RNA-seq Analysis Pipeline (SCRAP for short) developed for the NVIDIA x Red Hat Small Models Hack. Leverages small language models, vLLM, and specialized AI agents to automate statistical analysis, literature research, and scientific verification of biological datasets.

## Data sources

- **COVID-19 PBMC atlas.** Wilk, A.J., Rustagi, A., Zhao, N.Q. et al. *A single-cell atlas of the peripheral immune response in patients with severe COVID-19.* Nat Med 26, 1070–1076 (2020). https://doi.org/10.1038/s41591-020-0944-y. Raw data: GEO [GSE150728](https://www.ncbi.nlm.nih.gov/geo/query/acc.cgi?acc=GSE150728). We use the annotated `.h5ad` (44,721 cells) from [CZ CELLxGENE](https://cellxgene.cziscience.com/collections/a72afd53-ab92-4511-88da-252fb0e26b9a).
