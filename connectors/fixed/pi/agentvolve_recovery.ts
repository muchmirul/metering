import { basename, dirname, isAbsolute, join, resolve } from "node:path";
import type { ExtensionAPI, ExtensionContext } from "@earendil-works/pi-coding-agent";
import { decodeOperatorHistory, decodeOutput, repositoryRoot, runsDirectory } from "./population_evolution_support.ts";

interface ControlState {
	workflow_root: string;
	workflow_id: string;
	runtime_manifest: string;
	active: boolean;
	complete: boolean;
	closed: boolean;
	retry_required: boolean;
}

export interface RegistryStatus {
	blocker: ControlState | null;
	legacy_unfinished_count: number;
}

export interface ManagementResult {
	status: string;
	message: string;
}

type PrepareRuntime = (manifest: string, signal?: AbortSignal) => Promise<void>;

async function workerCommand(pi: ExtensionAPI, args: string[], signal?: AbortSignal): Promise<Record<string, unknown>> {
	return decodeOutput(await pi.exec("uv", ["run", "python", "-m", "apps.coding_agent.agentvolve_worker", ...args],
		{ cwd: repositoryRoot(), signal, timeout: 30_000 }));
}

function controlState(value: unknown): ControlState {
	if (typeof value !== "object" || value === null || Array.isArray(value)) throw new Error("Agentvolve control state must be an object");
	const control = value as Record<string, unknown>;
	if (control.control_schema !== "agentvolve-workflow-control-v1" || control.authority !== "projection-only" ||
		typeof control.workflow_root !== "string" || !isAbsolute(control.workflow_root) || resolve(dirname(control.workflow_root)) !== resolve(runsDirectory()) ||
		!/^workflow-pi-\d{8}T\d{9}Z(?:-\d+)?$/.test(basename(control.workflow_root)) ||
		typeof control.workflow_id !== "string" || typeof control.runtime_manifest !== "string" || !isAbsolute(control.runtime_manifest) ||
		["active", "complete", "closed", "retry_required"].some((key) => typeof control[key] !== "boolean")) {
		throw new Error("Agentvolve control state has an unexpected identity");
	}
	return control as unknown as ControlState;
}

export async function registryStatus(pi: ExtensionAPI, signal?: AbortSignal): Promise<RegistryStatus> {
	const result = await workerCommand(pi, ["registry", runsDirectory()], signal);
	if (result.registry_schema !== "agentvolve-registry-status-v1" || result.authority !== "projection-only" ||
		!Number.isSafeInteger(result.legacy_unfinished_count) || (result.legacy_unfinished_count as number) < 0) {
		throw new Error("Agentvolve registry returned an unexpected response");
	}
	return { blocker: result.blocker === null ? null : controlState(result.blocker), legacy_unfinished_count: result.legacy_unfinished_count as number };
}

async function chooseWorkflow(pi: ExtensionAPI, ctx: ExtensionContext, signal?: AbortSignal): Promise<string | undefined> {
	let offset = 0;
	for (;;) {
		const history = decodeOperatorHistory(decodeOutput(await pi.exec("uv", ["run", "python", "-m", "apps.coding_agent.operator_view",
			"history", runsDirectory(), String(offset)], { cwd: repositoryRoot(), signal, timeout: 15_000 })));
		const workflows = history.runs.filter((run) => run.name.startsWith("workflow-pi-"));
		const labels = workflows.map((run) => `${run.name} · ${run.state} · ${run.goal?.replaceAll(/\s+/g, " ").slice(0, 100) ?? "goal unavailable"}`);
		if (!history.total_runs) return undefined;
		const chosen = await ctx.ui.select("Manage an Agentvolve workflow (legacy evidence stays in /history)", [
			...labels, ...(offset > 0 ? ["Newer runs"] : []), ...(history.next_offset !== null ? ["Older runs"] : []), "Cancel",
		], { signal });
		if (chosen === "Newer runs") offset = Math.max(0, offset - history.page_size);
		else if (chosen === "Older runs" && history.next_offset !== null) offset = history.next_offset;
		else return chosen && labels.includes(chosen) ? join(runsDirectory(), workflows[labels.indexOf(chosen)]!.name) : undefined;
	}
}

export async function manageWorkflow(
	pi: ExtensionAPI, ctx: ExtensionContext, prepareRuntime: PrepareRuntime, root?: string, signal?: AbortSignal,
): Promise<ManagementResult> {
	const cancelled = { status: "cancelled", message: "No workflow operation was approved; existing work and evidence are unchanged." };
	if (!ctx.hasUI) return { status: "needs-operator-approval", message: "Workflow management requires direct approval in interactive or RPC Pi." };
	signal?.throwIfAborted();
	root ??= await chooseWorkflow(pi, ctx, signal);
	if (!root) return cancelled;
	const control = controlState(await workerCommand(pi, ["control", root], signal));
	if (control.workflow_root !== root) throw new Error("Agentvolve control state targets another workflow");
	if (control.closed) return { status: "closed-incomplete", message: "This workflow was closed as incomplete. Its evidence is preserved; submit a new reviewed goal rather than reopening it." };
	const actions = control.active ? { "Stop worker": "stop" }
		: control.complete ? { "Verify offline": "verify" }
		: { [control.retry_required ? "Retry one reserved attempt" : "Resume workflow"]: control.retry_required ? "retry" : "resume",
			"Close as incomplete (keep evidence)": "close" };
	const choice = await ctx.ui.select(`Agentvolve workflow: ${basename(root)}`, [...Object.keys(actions), "Cancel"], { signal });
	const action = choice ? (actions as Record<string, string>)[choice] : undefined;
	if (!action) return cancelled;
	let reason: string | undefined;
	if (action === "retry" || action === "close") {
		reason = await ctx.ui.input(`Operator reason to ${action} this workflow`, "Explain the decision (required, at most 2000 characters)", { signal });
		if (reason === undefined) return cancelled;
		if (!reason.trim() || reason.includes("\0") || reason.length > 2000) throw new Error("An operator-authored reason of 1–2000 characters without NUL is required; nothing changed.");
	}
	const explanation = action === "close"
		? "Permanently close this inactive workflow as INCOMPLETE, not successful. Keep all candidates, receipts, pending attempts and history at their original paths. No retry, final assay or patch application occurs. It cannot resume; a new goal needs its own review and budget."
		: action === "retry" ? "Request one explicit retry under the original pending intent and remaining reserved call/time budget. This may spend model time; it cannot extend limits or replace an indeterminate protected assay."
		: action === "resume" ? "Resume the original reviewed workflow under its original runtime and budgets. Replay-authorized work may continue; an unreceipted model call is never implicitly repeated."
		: action === "stop" ? "Signal only the identified live worker. This does not create a clean checkpoint or declare success; later recovery may require explicit retry."
		: "Replay the completed evidence offline. No model calls or patch application.";
	if (!(await ctx.ui.confirm("Approve Agentvolve workflow operation?", `${choice}\nWorkflow: ${root}\nRuntime: ${control.runtime_manifest}\n${explanation}` +
		(reason === undefined ? "" : `\nOperator reason: ${JSON.stringify(reason)}`), { signal }))) return cancelled;
	signal?.throwIfAborted();
	// Recheck after the human review. Projections never authorize effects by themselves.
	const current = controlState(await workerCommand(pi, ["control", root], signal));
	if (JSON.stringify(current) !== JSON.stringify(control)) throw new Error("Workflow state changed during review; inspect it again. No operation started.");
	const args = [action, root, ...(reason === undefined ? [] : [reason])];
	let result: Record<string, unknown>;
	if (action === "resume" || action === "retry") {
		await prepareRuntime(control.runtime_manifest, signal);
		result = decodeOutput(await pi.exec("uv", ["run", "python", "-m", "connectors.fixed.pi.runtime", ...args],
			{ cwd: repositoryRoot(), signal, timeout: 30_000 }));
	} else result = await workerCommand(pi, args, signal);
	if (result.worker_response_schema !== "agentvolve-worker-response-v1" || result.workflow_id !== control.workflow_id ||
		result.workflow_root !== root || result.action !== action || typeof result.state !== "string") throw new Error("Agentvolve returned an unexpected operation response; inspect progress before retrying.");
	pi.appendEntry("agentvolve-workflow-operation", result);
	return { status: result.state, message: action === "close" ? "Workflow closed as incomplete. Evidence is preserved and new goals are unblocked."
		: `Agentvolve ${action} requested for ${root}. Use /progress; completion is not yet established.` };
}
