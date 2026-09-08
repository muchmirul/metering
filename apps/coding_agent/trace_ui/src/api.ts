import type { Envelope } from "./types";

export class API {
  readonly token =
    new URLSearchParams(location.hash.slice(1)).get("token") ?? "";
  snapshot = "";

  async response(
    action: string,
    values: Record<string, string | number> = {},
    signal?: AbortSignal,
  ): Promise<Response> {
    if (!this.token)
      throw new Error(
        "Missing viewer capability. Open a new trace viewer from Pi.",
      );
    const params = new URLSearchParams();
    if (this.snapshot && String(values.refresh) !== "1")
      params.set("snapshot", this.snapshot);
    for (const [key, value] of Object.entries(values))
      params.set(key, String(value));
    const response = await fetch(`/api/${action}?${params}`, {
      headers: { Authorization: `Bearer ${this.token}` },
      signal,
      cache: "no-store",
    });
    if (!response.ok) {
      const error = await response
        .json()
        .catch(() => ({ error: `HTTP ${response.status}` }));
      throw new Error(String(error.error ?? "Viewer request failed"));
    }
    return response;
  }

  async get<T extends Envelope>(
    action: string,
    values: Record<string, string | number> = {},
    signal?: AbortSignal,
  ): Promise<T> {
    const result = await (await this.response(action, values, signal)).json();
    if (
      result?.view_schema !== "agentvolve-trace-graph-v1" ||
      result.authority !== "projection-only" ||
      typeof result.snapshot_id !== "string"
    ) {
      throw new Error("Unsupported trace projection schema");
    }
    if (action !== "graph" && result.snapshot_id !== this.snapshot)
      throw new Error("Evidence snapshot changed; refresh the graph.");
    return result as T;
  }
}

export function download(blob: Blob, name: string): void {
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = name;
  anchor.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

export function element<K extends keyof HTMLElementTagNameMap>(
  tag: K,
  text = "",
  className = "",
): HTMLElementTagNameMap[K] {
  const node = document.createElement(tag);
  node.textContent = text;
  node.className = className;
  return node;
}

export function button(label: string, action: () => void): HTMLButtonElement {
  const node = element("button", label);
  node.type = "button";
  node.onclick = action;
  return node;
}

export function json(value: unknown): HTMLPreElement {
  return element("pre", JSON.stringify(value, null, 2), "evidence-json");
}
