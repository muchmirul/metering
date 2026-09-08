import cytoscape, { type Core, type ElementDefinition } from "cytoscape";
import type { Archive, Candidate, FileChange, FileHistory } from "./types";

const colors = [
  "#61b5ff",
  "#ce99ff",
  "#5bdbb0",
  "#ffc871",
  "#ff8ea5",
  "#8fd5e8",
];
export const branchColor = (index: number): string =>
  colors[index % colors.length];

export function archiveState(
  node: Candidate,
  archive: Archive | undefined,
): string {
  if (!archive) return node.status;
  if (node.registration_sequence > archive.sequence)
    return "not-yet-registered";
  if (archive.members.includes(node.candidate_id)) return "retained";
  if (archive.excluded.some((item) => item.candidate_id === node.candidate_id))
    return "eliminated";
  return "not-yet-archived";
}

export class TraceGraph {
  readonly cy: Core;
  constructor(
    container: HTMLElement,
    onCandidate: (id: string) => void,
    onFile: (key: string) => void,
  ) {
    this.cy = cytoscape({
      container,
      minZoom: 0.05,
      maxZoom: 3,
      wheelSensitivity: 0.25,
      style: [
        {
          selector: "node",
          style: {
            label: "data(label)",
            "text-wrap": "wrap",
            "text-max-width": "180px",
            "font-size": 13,
            color: "#e7edf7",
            "text-valign": "bottom",
            "text-margin-y": 9,
            "background-color": "data(color)",
            width: 24,
            height: 24,
          },
        },
        {
          selector: "node[entity = 'file']",
          style: { shape: "rectangle", width: 16, height: 22 },
        },
        {
          selector: "node[status = 'eliminated']",
          style: {
            "background-opacity": 0.4,
            "border-width": 2,
            "border-color": "data(color)",
          },
        },
        {
          selector: "node[status = 'selected']",
          style: { "border-width": 4, "border-color": "#ffdc7c" },
        },
        {
          selector: "node.focused",
          style: {
            "overlay-color": "#ffffff",
            "overlay-opacity": 0.2,
            "overlay-padding": 10,
          },
        },
        {
          selector: "edge",
          style: {
            "curve-style": "bezier",
            width: 2,
            "line-color": "data(color)",
            "target-arrow-color": "data(color)",
            "target-arrow-shape": "triangle",
          },
        },
        {
          selector: "edge[relation = 'contains']",
          style: {
            "line-style": "dashed",
            "line-color": "#778397",
            "target-arrow-color": "#778397",
          },
        },
      ],
    });
    this.cy.on("tap", "node", (event) => {
      const data = event.target.data();
      if (data.entity === "file") onFile(data.path_id);
      else onCandidate(data.candidate_id);
    });
    new ResizeObserver(() => this.cy.resize()).observe(container);
  }

  draw(
    nodes: Candidate[],
    selected: string | undefined,
    archive: Archive | undefined,
    files: FileChange[] = [],
    history?: FileHistory,
  ): void {
    const elements: ElementDefinition[] = [];
    const ids = new Set(nodes.map((node) => node.candidate_id));
    const rows = new Map(history?.items.map((row) => [row.candidate_id, row]));
    for (const node of nodes) {
      const row = rows.get(node.candidate_id);
      const suffix = history
        ? `\n${row?.file ? `${row.file.blob.slice(0, 10)} · ${row.change}` : "file absent"}`
        : `\n${archiveState(node, archive)}`;
      elements.push({
        data: {
          id: node.candidate_id,
          entity: "candidate",
          candidate_id: node.candidate_id,
          label: node.display_label + suffix,
          color: branchColor(node.branch_index),
          status: archiveState(node, archive),
        },
        position: { x: node.branch_index * 240, y: node.depth * 125 },
        classes: node.candidate_id === selected ? "focused" : "",
      });
      if (node.parent_candidate_id && ids.has(node.parent_candidate_id)) {
        elements.push({
          data: {
            id: `parent:${node.candidate_id}`,
            source: node.parent_candidate_id,
            target: node.candidate_id,
            color: branchColor(node.branch_index),
            relation: history ? "file-history" : "parent",
          },
        });
      }
    }
    if (selected && ids.has(selected) && !history) {
      const right =
        (Math.max(0, ...nodes.map((node) => node.branch_index)) + 1) * 240;
      files
        .filter((file) => file.after !== null)
        .forEach((file, index) => {
          const id = `file:${selected}:${file.path_id}`;
          elements.push({
            data: {
              id,
              entity: "file",
              path_id: file.path_id,
              label: `${file.path.length > 100 ? file.path.slice(0, 99) + "…" : file.path}\n${file.change}`,
              color: "#92a9bf",
              status: "file",
            },
            position: {
              x: right + (index % 2) * 240,
              y: Math.floor(index / 2) * 80,
            },
          });
          elements.push({
            data: {
              id: `contains:${id}`,
              source: selected,
              target: id,
              relation: "contains",
              color: "#778397",
            },
          });
        });
    }
    const oldPan = this.cy.pan(),
      oldZoom = this.cy.zoom();
    const first = this.cy.nodes().length === 0;
    this.cy.elements().remove();
    this.cy.add(elements);
    this.cy.layout({ name: "preset" }).run();
    if (first) this.fit();
    else {
      this.cy.zoom(oldZoom);
      this.cy.pan(oldPan);
    }
  }

  fit(): void {
    this.cy.fit(undefined, 55);
  }
  focus(identity: string): void {
    const node = this.cy.getElementById(identity);
    if (node.empty()) return;
    this.cy.nodes().removeClass("focused");
    node.addClass("focused");
    this.cy.zoom(Math.max(0.65, this.cy.zoom()));
    this.cy.center(node);
  }
}
