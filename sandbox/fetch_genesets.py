"""Download gene-set libraries at image build time.

The sandbox runs with no network, so anything the agents' code needs from the
internet must be baked into the image. Saved as GMT files in /opt/genesets,
readable with gseapy.read_gmt() or turned into a decoupler net.
"""

import sys
from pathlib import Path

import gseapy

OUT = Path(sys.argv[1] if len(sys.argv) > 1 else "/opt/genesets")
LIBRARIES = [
    "MSigDB_Hallmark_2020",
    "GO_Biological_Process_2023",
    "Reactome_2022",
    "KEGG_2021_Human",
]

OUT.mkdir(parents=True, exist_ok=True)
for name in LIBRARIES:
    sets = gseapy.get_library(name=name, organism="Human")
    with open(OUT / f"{name}.gmt", "w") as f:
        for term, genes in sets.items():
            f.write("\t".join([term, "", *genes]) + "\n")
    print(f"{name}: {len(sets)} gene sets")
