// Sample chats per project for mock mode; replaced by backend data later.
import type { Chat, FindingCard, ProjectFile, ProjectOverview } from "../types/ui";
import type { ChatMessage } from "../types/schemas";

const HOUR = 3_600_000;
const ago = (ms: number) => new Date(Date.now() - ms).toISOString();

const SEED: Record<string, [string, string][]> = {
  p1: [
    ["Which cell types change most between COVID and healthy donors?", "Classical monocytes and plasmablasts show the largest shifts in abundance."],
    ["Is the interferon signature driven by one donor?", "No: the ISG score is elevated in 6 of 7 patients after pseudobulking by donor."],
    ["Check HLA class II expression in monocytes.", "HLA-DR genes are down in CD14 monocytes (log2FC −1.1, p_adj 3e−6)."],
    ["Summarize the developing neutrophil population.", "A small cluster expresses immature neutrophil markers (ELANE, MPO) mainly in ventilated patients."],
  ],
};
const DEFAULT_SEED: [string, string][] = [["What does this dataset contain?", "Single-cell RNA-seq counts with donor, condition and cell-type annotations."]];

/** Chat ids are stable ("<project>-chat-<n>") so tests and screenshots are predictable. */
export function mockChatsFor(projectId: string): { chats: Chat[]; messages: Record<string, ChatMessage[]> } {
  const seed = SEED[projectId] ?? (projectId.startsWith("p") ? DEFAULT_SEED : []);
  const chats: Chat[] = [];
  const messages: Record<string, ChatMessage[]> = {};
  seed.forEach(([question, answer], i) => {
    const id = `${projectId}-chat-${i + 1}`;
    const created = ago((seed.length - i) * 3 * HOUR);
    chats.push({ id, project_id: projectId, title: `Chat ${i + 1}`, created_at: created });
    messages[id] = [
      { id: `${id}-q`, project_id: projectId, role: "user", content: question, created_at: created },
      { id: `${id}-a`, project_id: projectId, role: "assistant", content: answer, created_at: created },
    ];
  });
  return { chats, messages };
}

// ---------------------------------------------------------------------------
// Files and findings (sample data until the backend provides them)

const KB = 1024;
const MB = 1024 * KB;

/** Sample files; the previewable ones are real files under public/mock-files/. */
export function mockFilesFor(projectId: string): ProjectFile[] {
  if (!projectId.startsWith("p")) return [];
  const file = (name: string, kind: ProjectFile["kind"], size: number, hoursAgo: number, url: string | null, summary?: string): ProjectFile => ({
    id: `${projectId}-${name}`,
    project_id: projectId,
    name,
    kind,
    size_bytes: size,
    url,
    added_at: ago(hoursAgo * HOUR),
    summary,
  });
  const files = [
    file("processed.h5ad", "h5ad", 1.8 * 1024 * MB, 30, null, "44,649 cells · 13 donors · 7 COVID-19 / 6 healthy"),
    file("wilk_2020_covid_pbmc.pdf", "pdf", 1095, 26, "/mock-files/wilk_2020_covid_pbmc.pdf", "Wilk et al. 2020, Nature Medicine"),
    file("de_results.csv", "csv", 1017, 5, "/mock-files/de_results.csv", "Pseudobulk DE, CD14 monocytes"),
    file("umap_clusters.svg", "image", 46_907, 4, "/mock-files/umap_clusters.svg", "UMAP coloured by cell type"),
    file("analysis_notes.txt", "text", 671, 1, "/mock-files/analysis_notes.txt"),
    // Real outputs from a SCRAP run on the Wilk et al. COVID data:
    file("report.md", "text", 1547, 0.5, "/mock-files/report.md", "Final report"),
    file("ifn_alpha_cd14_monocytes.ipynb", "notebook", 78_759, 0.6, "/mock-files/ifn_alpha_cd14_monocytes.ipynb", "Notebook: IFN-α response in CD14 monocytes"),
    file("ifn_alpha_donor_scores.png", "image", 32_596, 0.6, "/mock-files/ifn_alpha_donor_scores.png", "Figure: IFN-α score per donor"),
  ];
  return projectId === "p1" ? files : files.slice(2);
}

/** Small deterministic PRNG so the sample scatter looks the same on every load. */
function seeded(seed: number) {
  return () => {
    seed = (seed + 0x6d2b79f5) | 0;
    let t = Math.imul(seed ^ (seed >>> 15), 1 | seed);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

function cluster(rand: () => number, cx: number, cy: number, spread: number, n: number): [number, number][] {
  return Array.from({ length: n }, () => {
    // Sum of uniforms ≈ normal; keeps the blob soft-edged.
    const dx = (rand() + rand() + rand() - 1.5) * spread;
    const dy = (rand() + rand() + rand() - 1.5) * spread;
    return [cx + dx, cy + dy];
  });
}

export function mockFindingsFor(projectId: string): FindingCard[] {
  if (!projectId.startsWith("p")) return [];
  const rand = seeded(7);
  const base = { critic_notes: "", citations: [], sources_searched: [], notebook_path: null, figure_path: null };
  return [
    {
      mock: true,
      finding: {
        ...base,
        id: `${projectId}-f1`,
        hypothesis_id: `${projectId}-h1`,
        claim: "Interferon-stimulated genes are up in COVID-19 monocytes",
        test: "Pseudobulk DESeq2 (donor)",
        statistic: 6.2,
        p_adj: 2.1e-8,
        effect_size: 2.4,
        critic_verdict: "approve",
        novelty: "known",
      },
      chart: {
        type: "volcano",
        labels: [
          { x: 214, y: 34, text: "IFI27" },
          { x: 188, y: 62, text: "ISG15" },
          { x: 58, y: 70, text: "HLA-DRA" },
        ],
      },
    },
    {
      mock: true,
      finding: {
        ...base,
        id: `${projectId}-f2`,
        hypothesis_id: `${projectId}-h2`,
        claim: "Type I interferon pathways are the most enriched in patients",
        test: "GSEA (Hallmark)",
        statistic: 2.9,
        p_adj: 4.0e-6,
        effect_size: 1.9,
        critic_verdict: "approve",
        novelty: "partly_known",
      },
      chart: {
        type: "bar",
        xLabel: "−log₁₀ p_adj",
        bars: [
          { label: "IFN-α response", value: 7.4 },
          { label: "IFN-γ response", value: 5.6 },
          { label: "Inflammatory", value: 3.9 },
          { label: "TNF-α / NF-κB", value: 2.8 },
          { label: "Oxidative phos.", value: 1.6 },
        ],
      },
    },
    {
      mock: true,
      finding: {
        ...base,
        id: `${projectId}-f3`,
        hypothesis_id: `${projectId}-h3`,
        claim: "A developing-neutrophil cluster appears mainly in ventilated patients",
        test: "Cluster abundance, Wilcoxon (donor)",
        statistic: 3.1,
        p_adj: 1.2e-3,
        effect_size: 1.3,
        critic_verdict: "revise",
        novelty: "not_found_in_sources",
      },
      chart: {
        type: "umap",
        clusters: [
          { label: "Monocytes", color: "#a4c7ed", points: cluster(rand, 70, 70, 34, 70) },
          { label: "T cells", color: "#9ca9b9", points: cluster(rand, 170, 60, 38, 80) },
          { label: "B cells", color: "#c7d9a8", points: cluster(rand, 190, 140, 24, 40) },
          { label: "Dev. neutrophils", color: "#e8adb1", points: cluster(rand, 85, 150, 20, 35) },
        ],
      },
    },
  ];
}

/** Sample overview for the first sample project. */
export function mockOverviewFor(projectId: string): ProjectOverview | null {
  if (projectId !== "p1") return null;
  return {
    goal: "Understand how innate immune cells, especially monocytes, respond differently in hospitalized COVID-19 patients versus healthy donors.",
    organism: "human",
    n_cells: 44649,
    n_donors: 13,
    conditions: { "COVID-19": 28023, normal: 16626 },
    summary:
      "CD14 monocytes from COVID-19 patients show a stronger interferon-alpha response and lower HLA class II expression than healthy donors; both reproduce Wilk et al. 2020.",
  };
}
