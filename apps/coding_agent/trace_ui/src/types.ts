export type Kind = "harness" | "solution";
export interface Envelope {
  view_schema: "agentvolve-trace-graph-v1";
  authority: "projection-only";
  snapshot_id: string;
}
export interface Evaluation {
  replicates: number;
  passed_cases: number;
  total_cases: number;
  safety_failures: number;
  cost: Record<string, number>;
}
export interface Candidate {
  candidate_id: string;
  parent_candidate_id: string | null;
  kind: Kind;
  run_root: string;
  reused: boolean;
  label: string;
  display_label: string;
  parent_display_label: string | null;
  depth: number;
  branch: string;
  branch_index: number;
  commit: string;
  git_tree: string;
  birth_round: number | null;
  registration_sequence: number;
  status: string;
  archive_status: string;
  exclusion_reason: string | null;
  evidence: {
    development: Evaluation | null;
    final: Evaluation | null;
    final_status: string;
    semantics: string;
  };
}
export interface Source {
  kind: Kind;
  run_root: string;
  reused: boolean;
  population_id: string | null;
  population_head: string | null;
  driver_head: string | null;
  pending_id: string | null;
}
export interface Archive {
  kind: Kind;
  record_id: string;
  sequence: number;
  members: string[];
  excluded: Array<{ candidate_id: string; reason: string }>;
}
export interface Graph extends Envelope {
  workflow_root: string;
  task: { goal?: string } | null;
  nodes: Candidate[];
  archives: Archive[];
  sources: Source[];
  experiments: unknown[];
  verification: string;
  semantics: string;
  warnings: string[];
}
export interface FileEntry {
  path_id: string;
  path: string;
  blob: string;
  mode: string;
  object_type: string;
  size: number | null;
}
export interface FileChange extends FileEntry {
  change: "added" | "deleted" | "modified" | "unchanged";
  before: FileEntry | null;
  after: FileEntry | null;
}
export interface Page extends Envelope {
  offset: number;
  page_size: number;
  next_offset: number | null;
  total_items: number;
}
export interface FilePage extends Page {
  candidate_id: string;
  commit: string;
  base_candidate_id: string | null;
  items: FileChange[];
  semantics: string;
}
export interface TextPage extends Page {
  candidate_id: string;
  text: string | null;
  warning?: string | null;
  semantics?: string;
  file: FileEntry | FileChange;
  sha256?: string;
  has_final_newline?: boolean;
  crlf_count?: number;
}
export interface EventPage extends Page {
  events: Array<Record<string, unknown> & { step: string; summary: string }>;
  node?: Candidate;
  label?: string;
}
export interface Loop {
  label: string;
  parent_label: string;
  child_label: string | null;
  state: string;
  attempts: number;
  round: number;
}
export interface HistoryItem {
  candidate_id: string;
  parent_candidate_id: string | null;
  display_label: string;
  depth: number;
  branch_index: number;
  file: FileEntry | null;
  change: string;
}
export interface FileHistory extends Envelope {
  kind: Kind;
  path_id: string;
  items: HistoryItem[];
  semantics: string;
}
