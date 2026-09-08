import { API, button, download, element, json } from "./api";
import { archiveState, TraceGraph } from "./graph";
import type {
  Archive,
  Candidate,
  Envelope,
  EventPage,
  FileChange,
  FileHistory,
  FilePage,
  Graph,
  Kind,
  Loop,
  TextPage,
} from "./types";

const get = <T extends HTMLElement>(id: string): T =>
  document.getElementById(id) as T;
const api = new API();
let data: Graph;
let kind: Kind = "solution";
let selected: Candidate | undefined;
let filePage: FilePage | undefined;
let history: FileHistory | undefined;
let fileKey: string | undefined;
let fileReference: Record<string, unknown> | undefined;
let controller = new AbortController();
const graph = new TraceGraph(
  get("graph"),
  (id) =>
    run(async (signal) => {
      const tracedPath = history?.path_id;
      const version = history?.items.find((row) => row.candidate_id === id);
      await selectCandidate(id, signal);
      if (
        tracedPath &&
        version &&
        (version.file || version.change === "deleted")
      )
        await inspectFile(tracedPath, signal);
      else if (tracedPath)
        get("detail").prepend(
          element(
            "p",
            "This exact path is absent in this candidate; no file version is invented.",
            "notice",
          ),
        );
    }),
  (key) => run((signal) => inspectFile(key, signal)),
);

function run(action: (signal: AbortSignal) => Promise<void>): void {
  controller.abort();
  controller = new AbortController();
  const signal = controller.signal;
  get("error").hidden = true;
  get("busy").hidden = false;
  void action(signal)
    .catch((error) => {
      if (!signal.aborted) {
        get("error").textContent = String(error);
        get("error").hidden = false;
      }
    })
    .finally(() => {
      if (!signal.aborted) get("busy").hidden = true;
    });
}

function option(value: string, text: string): HTMLOptionElement {
  const node = element("option", text);
  node.value = value;
  return node;
}
function candidates(): Candidate[] {
  return data?.nodes.filter((node) => node.kind === kind) ?? [];
}
function archive(): Archive | undefined {
  return data.archives.find(
    (item) =>
      item.record_id === get<HTMLSelectElement>("archive").value &&
      item.kind === kind,
  );
}
function base(): string {
  return get<HTMLSelectElement>("base").value;
}
function params(): Record<string, string> {
  if (!selected) throw new Error("Choose a registered candidate first.");
  return { kind, candidate: selected.candidate_id };
}
function recordLink(path?: string): void {
  const hash = new URLSearchParams(location.hash.slice(1));
  hash.set("snapshot", api.snapshot);
  hash.set("kind", kind);
  if (selected) hash.set("candidate", selected.candidate_id);
  if (base()) hash.set("base", base());
  else hash.delete("base");
  if (path) hash.set("path", path);
  else hash.delete("path");
  window.history.replaceState(null, "", `#${hash}`);
}
function draw(): void {
  const at = archive();
  let nodes = candidates().filter(
    (node) =>
      !at ||
      (Number.isInteger(node.registration_sequence) &&
        node.registration_sequence <= at.sequence),
  );
  const query = get<HTMLInputElement>("search").value.trim().toLowerCase();
  if (query) {
    const ids = new Set(
      nodes
        .filter((node) =>
          `${node.display_label} ${node.label} ${node.candidate_id}`
            .toLowerCase()
            .includes(query),
        )
        .map((node) => node.candidate_id),
    );
    const byID = new Map(nodes.map((node) => [node.candidate_id, node]));
    for (const id of Array.from(ids)) {
      let parent = byID.get(id)?.parent_candidate_id;
      while (parent) {
        ids.add(parent);
        parent = byID.get(parent)?.parent_candidate_id;
      }
    }
    nodes = nodes.filter((node) => ids.has(node.candidate_id));
  }
  const files =
    get<HTMLSelectElement>("file-mode").value === "hidden"
      ? []
      : (filePage?.items ?? []);
  graph.draw(nodes, selected?.candidate_id, at, files, history);
  get("graph-title").textContent = history
    ? "Exact-path file history"
    : "Candidate ancestry";
  get("clear-history").hidden = !history;
  get("graph-note").textContent = [
    history?.semantics,
    at
      ? `Archive snapshot ${at.sequence}. Reports retain latest recorded evaluations; they are not rewound.`
      : "Latest archive state. Round number is separate from lineage depth.",
    files.length
      ? "File nodes show this page only. Deleted files remain in the base snapshot."
      : "Expand file nodes using the left-hand control.",
  ]
    .filter(Boolean)
    .join(" ");
}

function configure(): void {
  const source = data.sources.find((source) => source.kind === kind);
  get("source").textContent = source
    ? `${kind}${source.reused ? " · REUSED from original experiment, not new work" : ""} · ${source.run_root}`
    : "Source unavailable";
  const archives = get<HTMLSelectElement>("archive");
  archives.replaceChildren(
    option("", "Latest"),
    ...data.archives
      .filter((item) => item.kind === kind)
      .map((item, index) =>
        option(
          item.record_id,
          `Archive ${index + 1} · sequence ${item.sequence}`,
        ),
      ),
  );
  get<HTMLSelectElement>("candidate").replaceChildren(
    ...candidates().map((node) =>
      option(
        node.candidate_id,
        `${node.display_label} · ${node.status} · legacy ${node.label}`,
      ),
    ),
  );
  get("file-list").replaceChildren();
  get("detail").replaceChildren();
  get("summary").replaceChildren();
  selected = undefined;
  filePage = undefined;
  history = undefined;
  fileKey = undefined;
  fileReference = undefined;
  draw();
  graph.fit();
}

async function loadGraph(signal: AbortSignal, refresh = false): Promise<void> {
  const hash = new URLSearchParams(location.hash.slice(1));
  const old = selected?.candidate_id ?? hash.get("candidate");
  const oldPath = fileKey ?? hash.get("path");
  const oldBase = base() || hash.get("base");
  // An explicit refresh chooses latest evidence. Ordinary reload preserves a pinned link.
  const pinned = hash.get("snapshot");
  const result = await api.get<Graph>(
    "graph",
    refresh ? { refresh: 1 } : pinned ? { snapshot: pinned } : {},
    signal,
  );
  signal.throwIfAborted();
  data = result;
  api.snapshot = result.snapshot_id;
  const proposedKind = refresh ? kind : hash.get("kind");
  kind = data.sources.some((source) => source.kind === proposedKind)
    ? (proposedKind as Kind)
    : data.sources.some((source) => source.kind === "solution")
      ? "solution"
      : "harness";
  get<HTMLSelectElement>("kind").replaceChildren(
    ...data.sources.map((source) =>
      option(source.kind, source.kind === "harness" ? "Harness" : "Solution"),
    ),
  );
  get<HTMLSelectElement>("kind").value = kind;
  get("task").textContent = data.task?.goal ?? data.workflow_root;
  get("snapshot").textContent = `Evidence snapshot: ${data.snapshot_id}`;
  get("verification").textContent = [data.verification, ...data.warnings].join(
    " ",
  );
  configure();
  const node =
    candidates().find((node) => node.candidate_id === old) ?? candidates()[0];
  if (node) {
    await selectCandidate(node.candidate_id, signal);
    if (oldBase && node.candidate_id === old) {
      if (
        !candidates().some(
          (item) =>
            item.candidate_id === oldBase &&
            item.candidate_id !== node.candidate_id,
        )
      )
        throw new Error(
          "Linked comparison base is not in this source snapshot.",
        );
      get<HTMLSelectElement>("base").value = oldBase;
      await loadFiles(0, signal);
      recordLink();
    }
    if (oldPath && node.candidate_id === old)
      await inspectFile(oldPath, signal);
  } else {
    get("inspecting").textContent = "No registered candidates yet";
    recordLink();
  }
}

function renderSummary(node: Candidate): void {
  get("inspecting").textContent = `Inspecting ${node.display_label}`;
  const panel = get("summary");
  panel.replaceChildren();
  const fields = element("dl");
  const evidence = node.evidence;
  const values: Array<[string, string]> = [
    ["Parent", node.parent_display_label ?? "seed"],
    ["Depth / branch", `${node.depth} / ${node.branch}`],
    [
      "Created in round",
      node.birth_round !== null
        ? String(node.birth_round)
        : node.parent_candidate_id
          ? "not recorded in a committed round"
          : "seed",
    ],
    [
      "Latest archive",
      node.archive_status +
        (node.exclusion_reason ? ` · ${node.exclusion_reason}` : ""),
    ],
    ["Graph state", archiveState(node, archive())],
    [
      "Development",
      evidence.development
        ? `${evidence.development.passed_cases}/${evidence.development.total_cases} cumulative cases · ${evidence.development.replicates} replicates`
        : "No recorded development results",
    ],
    [
      "Protected final",
      evidence.final
        ? `${evidence.final.passed_cases}/${evidence.final.total_cases} · safety failures ${evidence.final.safety_failures}`
        : "Not evaluated in recorded evidence",
    ],
  ];
  for (const [name, value] of values)
    fields.append(element("dt", name), element("dd", value));
  panel.append(
    fields,
    button("Copy immutable reference", () =>
      run(async () => {
        await navigator.clipboard.writeText(
          JSON.stringify(
            {
              snapshot_id: api.snapshot,
              source: data.sources.find((source) => source.kind === kind),
              candidate_id: node.candidate_id,
              commit: node.commit,
              git_tree: node.git_tree,
              file_revision: fileReference ?? null,
            },
            null,
            2,
          ),
        );
      }),
    ),
    button("Recorded steps / evidence", () =>
      run((signal) => loadEvents(0, signal)),
    ),
  );
  const detail = element("details");
  detail.append(
    element("summary", "Identities, resources, and experiment bindings"),
    json({
      registration_alias: node.label,
      candidate_id: node.candidate_id,
      commit: node.commit,
      git_tree: node.git_tree,
      resources: evidence,
      experiments: data.experiments,
      source: node.run_root,
      reused: node.reused,
    }),
  );
  panel.append(detail);
}

async function selectCandidate(
  identity: string,
  signal: AbortSignal,
): Promise<void> {
  const node = candidates().find((node) => node.candidate_id === identity);
  if (!node) throw new Error("Candidate is not in this evidence snapshot.");
  selected = node;
  filePage = undefined;
  fileKey = undefined;
  fileReference = undefined;
  get<HTMLSelectElement>("candidate").value = identity;
  get<HTMLSelectElement>("base").replaceChildren(
    option(
      "",
      `Recorded parent${node.parent_display_label ? ` (${node.parent_display_label})` : " (none)"}`,
    ),
    ...candidates()
      .filter((item) => item.candidate_id !== identity)
      .map((item) => option(item.candidate_id, item.display_label)),
  );
  renderSummary(node);
  recordLink();
  draw();
  await Promise.all([loadFiles(0, signal), loadEvents(0, signal)]);
}

function pageControls(
  container: HTMLElement,
  page: {
    offset: number;
    page_size: number;
    next_offset: number | null;
    total_items: number;
  },
  action: (offset: number, signal: AbortSignal) => Promise<void>,
): void {
  container.replaceChildren(
    element(
      "span",
      `${page.total_items ? page.offset + 1 : 0}–${Math.min(page.offset + page.page_size, page.total_items)} / ${page.total_items}`,
    ),
  );
  if (page.offset)
    container.append(
      button("Previous page", () =>
        run((signal) =>
          action(Math.max(0, page.offset - page.page_size), signal),
        ),
      ),
    );
  if (page.next_offset !== null)
    container.append(
      button("Next page", () =>
        run((signal) => action(page.next_offset!, signal)),
      ),
    );
}

async function loadFiles(offset: number, signal: AbortSignal): Promise<void> {
  const page = await api.get<FilePage>(
    "files",
    {
      ...params(),
      base: base(),
      offset,
      changed: get<HTMLSelectElement>("file-mode").value === "changed" ? 1 : 0,
    },
    signal,
  );
  signal.throwIfAborted();
  filePage = page;
  const baseNode = candidates().find(
    (node) => node.candidate_id === page.base_candidate_id,
  );
  get("file-meta").textContent =
    `Exact Git snapshot; compared with ${baseNode?.display_label ?? "empty seed base"}. ${page.total_items} entries in this filter.`;
  const list = get("file-list");
  list.replaceChildren();
  // Native folder disclosure keeps the complete path visible and uses no HTML from files.
  const folders = new Map<string, HTMLElement>([["", list]]);
  for (const file of page.items) {
    const parts = file.path.split("/");
    let key = "",
      parent = list;
    for (const part of parts.slice(0, -1)) {
      key += `${part}/`;
      if (!folders.has(key)) {
        const folder = element("details");
        folder.open = true;
        folder.append(element("summary", part));
        parent.append(folder);
        folders.set(key, folder);
      }
      parent = folders.get(key)!;
    }
    const row = button(
      `${file.change === "unchanged" ? "=" : file.change[0].toUpperCase()} ${parts.at(-1)}`,
      () => run((next) => inspectFile(file.path_id, next)),
    );
    row.className = `file-row ${file.change}`;
    row.title = `${file.path} · ${file.blob} · mode ${file.mode}`;
    row.dataset.pathId = file.path_id;
    parent.append(row);
  }
  pageControls(get("file-pages"), page, loadFiles);
  draw();
}

function renderEvents(
  panel: HTMLElement,
  result: EventPage,
  more: (offset: number, signal: AbortSignal) => Promise<void>,
): void {
  panel.replaceChildren(element("h3", "Recorded steps"));
  for (const event of result.events) {
    const item = element("details");
    item.append(
      element("summary", `${event.step}: ${event.summary}`),
      json(event),
    );
    panel.append(item);
  }
  const pages = element("div", "", "pages");
  pageControls(pages, result, more);
  panel.append(pages);
}
async function loadEvents(offset: number, signal: AbortSignal): Promise<void> {
  const result = await api.get<EventPage>(
    "report",
    { ...params(), offset },
    signal,
  );
  signal.throwIfAborted();
  fileKey = undefined;
  fileReference = undefined;
  recordLink();
  renderEvents(get("detail"), result, loadEvents);
}

async function inspectFile(
  key: string,
  signal: AbortSignal,
  offset = 0,
  diff = false,
): Promise<void> {
  const node = selected;
  if (!node) return;
  const change = await api.get<
    Envelope & { file: FileChange; base_candidate_id: string | null }
  >("file", { ...params(), path: key, base: base() }, signal);
  signal.throwIfAborted();
  const actual =
    change.file.after === null && change.base_candidate_id
      ? change.base_candidate_id
      : node.candidate_id;
  const result = await api.get<TextPage>(
    diff ? "diff" : "content",
    {
      ...params(),
      candidate: diff ? node.candidate_id : actual,
      path: key,
      offset,
      ...(diff ? { base: base() } : {}),
    },
    signal,
  );
  signal.throwIfAborted();
  fileKey = key;
  fileReference = {
    candidate_id: actual,
    commit: candidates().find((item) => item.candidate_id === actual)?.commit,
    path_id: key,
    blob: change.file.blob,
    mode: change.file.mode,
    inspected_in: node.candidate_id,
    comparison_base: change.base_candidate_id,
  };
  recordLink(key);
  const panel = get("detail");
  panel.replaceChildren(element("h3", result.file.path));
  if (actual !== node.candidate_id)
    panel.append(
      element(
        "p",
        `Deleted from ${node.display_label}; source bytes below belong to its comparison base.`,
        "notice",
      ),
    );
  const identity = element("details");
  identity.append(
    element("summary", "File identity / byte metadata"),
    json({
      ...fileReference,
      size: result.file.size,
      sha256: result.sha256,
      crlf_count: result.crlf_count,
      final_newline: result.has_final_newline,
    }),
  );
  panel.append(identity);
  const tools = element("div", "", "pages");
  tools.append(
    button("Source", () => run((next) => inspectFile(key, next))),
    button("Diff", () => run((next) => inspectFile(key, next, 0, true))),
    button("Trace this file", () =>
      run(async (next) => {
        const result = await api.get<FileHistory>(
          "file-history",
          { kind, path: key },
          next,
        );
        next.throwIfAborted();
        history = result;
        draw();
        graph.fit();
      }),
    ),
    button("Download exact bytes", () =>
      run(async (next) => {
        const response = await api.response(
          "blob",
          { ...params(), candidate: actual, path: key },
          next,
        );
        download(
          await response.blob(),
          `candidate-file-${result.file.blob}.bin`,
        );
      }),
    ),
  );
  panel.append(tools);
  if (result.warning) panel.append(element("p", result.warning, "notice"));
  if (result.text !== null) {
    const pre = element("pre", result.text, "source-code");
    pre.dataset.testid = "source-content";
    panel.append(pre);
  }
  if (result.semantics) panel.append(element("p", result.semantics, "muted"));
  const pages = element("div", "", "pages");
  pageControls(pages, result, (page, next) =>
    inspectFile(key, next, page, diff),
  );
  panel.append(pages);
}

async function loadLoop(
  label: string,
  offset: number,
  signal: AbortSignal,
): Promise<void> {
  const result = await api.get<EventPage>(
    "loop",
    { kind, label, offset },
    signal,
  );
  signal.throwIfAborted();
  renderEvents(get("loop-events"), result, (page, next) =>
    loadLoop(label, page, next),
  );
}

get<HTMLSelectElement>("kind").onchange = () =>
  run(async (signal) => {
    if (!data) return;
    kind = get<HTMLSelectElement>("kind").value as Kind;
    configure();
    const node = candidates()[0];
    if (node) await selectCandidate(node.candidate_id, signal);
  });
get<HTMLSelectElement>("candidate").onchange = () =>
  run(async (signal) => {
    const identity = get<HTMLSelectElement>("candidate").value;
    await selectCandidate(identity, signal);
    graph.focus(identity);
  });
get<HTMLSelectElement>("base").onchange = () =>
  run(async (signal) => {
    history = undefined;
    await loadFiles(0, signal);
    await loadEvents(0, signal);
  });
get<HTMLSelectElement>("archive").onchange = () => {
  if (selected) renderSummary(selected);
  draw();
  graph.fit();
};
get<HTMLSelectElement>("file-mode").onchange = () =>
  run((signal) => loadFiles(0, signal));
get<HTMLInputElement>("search").oninput = () => {
  draw();
  graph.fit();
};
get("fit").onclick = () => graph.fit();
get("clear-history").onclick = () => {
  history = undefined;
  draw();
  graph.fit();
};
get("refresh").onclick = () => run((signal) => loadGraph(signal, true));
get("loops").onclick = () =>
  run(async (signal) => {
    const result = await api.get<Envelope & { items: Loop[] }>(
      "loops",
      { kind },
      signal,
    );
    signal.throwIfAborted();
    const select = get<HTMLSelectElement>("loop-select");
    select.replaceChildren(
      ...result.items.map((row) =>
        option(
          row.label,
          `${row.label} · ${row.state} · ${row.attempts} attempts`,
        ),
      ),
    );
    get<HTMLDialogElement>("loop-dialog").showModal();
    get("loop-events").replaceChildren();
    if (result.items[0]) await loadLoop(result.items[0].label, 0, signal);
  });
get<HTMLSelectElement>("loop-select").onchange = () =>
  run((signal) =>
    loadLoop(get<HTMLSelectElement>("loop-select").value, 0, signal),
  );
get("close-dialog").onclick = () =>
  get<HTMLDialogElement>("loop-dialog").close();
get("renames").onclick = () =>
  run(async (signal) => {
    const result = await api.get<Envelope & { items: unknown[] }>(
      "renames",
      { ...params(), base: base() },
      signal,
    );
    signal.throwIfAborted();
    get("detail").replaceChildren(
      element("h3", "Git rename inference — not historical identity"),
      element(
        "p",
        "Exact-path history is unchanged. Similarity detection may not match the author's intent.",
      ),
      json(result),
    );
  });
get<HTMLSelectElement>("export").onchange = () => {
  const select = get<HTMLSelectElement>("export"),
    format = select.value;
  select.value = "";
  run(async (signal) => {
    if (format === "png") {
      const uri = graph.cy.png({
        output: "base64uri",
        full: false,
        bg: "#111a27",
        scale: 2,
      });
      const binary = atob(uri.split(",")[1]);
      download(
        new Blob([Uint8Array.from(binary, (char) => char.charCodeAt(0))], {
          type: "image/png",
        }),
        `agentvolve-graph-${api.snapshot}.png`,
      );
    } else if (format === "trace") {
      if (!history)
        throw new Error("Trace a file first, then export its history.");
      download(
        new Blob(
          [JSON.stringify({ ...history, sources: data.sources }, null, 2)],
          { type: "application/json" },
        ),
        `agentvolve-file-trace-${api.snapshot}.json`,
      );
    } else if (format === "json") {
      const view_context = {
        kind,
        archive_record_id: archive()?.record_id ?? null,
        inspected_candidate_id: selected?.candidate_id ?? null,
        comparison_base: base() || selected?.parent_candidate_id,
        file_revision: fileReference ?? null,
        file_history_path_id: history?.path_id ?? null,
        file_mode: get<HTMLSelectElement>("file-mode").value,
        search: get<HTMLInputElement>("search").value,
        positions: graph.cy
          .nodes()
          .map((node) => ({ id: node.id(), position: node.position() })),
      };
      download(
        new Blob([JSON.stringify({ ...data, view_context }, null, 2)], {
          type: "application/json",
        }),
        `agentvolve-snapshot-${api.snapshot}.json`,
      );
    } else if (format) {
      const response = await api.response("export", { format }, signal);
      download(
        await response.blob(),
        `agentvolve-snapshot-${api.snapshot}.${format}`,
      );
    }
  });
};
run((signal) => loadGraph(signal));
