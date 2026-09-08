import type { ExtensionAPI, ExtensionContext } from "@earendil-works/pi-coding-agent";
import { decodeOutput, repositoryRoot, runsDirectory } from "./population_evolution_support.ts";

/** Explicit operator action only: never called by activation, monitoring, or model tools. */
export async function openTraceViewer(pi: ExtensionAPI, ctx: ExtensionContext, selector: string): Promise<void> {
  const result = await pi.exec("uv", ["run", "python", "-m", "apps.coding_agent.trace_server", "launch", runsDirectory(), selector,
    ...(ctx.mode === "tui" ? ["--open"] : [])], {cwd: repositoryRoot(), timeout: 45_000});
  const view = decodeOutput(result);
  if (view.view_schema !== "agentvolve-trace-launch-v1" || view.authority !== "projection-only" ||
      !Number.isSafeInteger(view.pid) || Number(view.pid) < 1 ||
      typeof view.url !== "string" || !/^http:\/\/127\.0\.0\.1:[1-9][0-9]{0,4}\/#token=[A-Za-z0-9_-]{43}$/.test(view.url)) {
    throw new Error("Trace Viewer returned an invalid loopback capability URL");
  }
  // Do not persist the temporary capability in projection entries or worker records.
  ctx.ui.notify(`Trace Viewer ready (read-only). Open this local link:\n${view.url}\nViewer PID: ${view.pid} (not the evolution worker). Expires after 15 minutes idle or 4 hours. Closing it never stops Agentvolve.`, "info");
}
