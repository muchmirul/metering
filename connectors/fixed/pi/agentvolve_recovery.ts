import { basename, dirname, isAbsolute, resolve } from "node:path";
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { decodeOutput, repositoryRoot, runsDirectory } from "./population_evolution_support.ts";

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

export type ManagementAction = "resume" | "retry" | "stop" | "verify" | "close";

export interface ManagementRequest {
	workflow?: string;
	action?: ManagementAction;
	reason?: string;
}

export interface ManagementResult {
	status: string;
	message: string;
	workflow?: string;
	actions?: ManagementAction[];
}

type PrepareRuntime = (manifest: string, signal?: AbortSignal, boundExecution?: boolean) => Promise<void>;

async function workerCommand(pi: ExtensionAPI, args: string[], signal?: AbortSignal): Promise<Record<string, unknown>> {
	return decodeOutput(await pi.exec("uv", ["run", "python", "-m", "apps.coding_agent.agentvolve_worker", ...args],
		{ cwd: repositoryRoot(), signal, timeout: 30_000 }));
}

function controlState(value: unknown, registry: string): ControlState {
	if (typeof value !== "object" || value === null || Array.isArray(value)) throw new Error("Agentvolve control state must be an object");
	const control = value as Record<string, unknown>;
	if (control.control_schema !== "agentvolve-workflow-control-v1" || control.authority !== "projection-only" ||
		typeof control.workflow_root !== "string" || !isAbsolute(control.workflow_root) || resolve(dirname(control.workflow_root)) !== resolve(registry) ||
		!/^workflow-pi-\d{8}T\d{9}Z(?:-\d+)?$/.test(basename(control.workflow_root)) ||
		typeof control.workflow_id !== "string" || typeof control.runtime_manifest !== "string" || !isAbsolute(control.runtime_manifest) ||
		["active", "complete", "closed", "retry_required"].some((key) => typeof control[key] !== "boolean")) {
		throw new Error("Agentvolve control state has an unexpected identity");
	}
	return control as unknown as ControlState;
}

export async function registryStatus(pi: ExtensionAPI, signal?: AbortSignal, registry = runsDirectory()): Promise<RegistryStatus> {
	const result = await workerCommand(pi, ["registry", registry], signal);
	if (result.registry_schema !== "agentvolve-registry-status-v1" || result.authority !== "projection-only" ||
		!Number.isSafeInteger(result.legacy_unfinished_count) || (result.legacy_unfinished_count as number) < 0) {
		throw new Error("Agentvolve registry returned an unexpected response");
	}
	return { blocker: result.blocker === null ? null : controlState(result.blocker, registry), legacy_unfinished_count: result.legacy_unfinished_count as number };
}

function availableActions(control: ControlState): ManagementAction[] {
	if (control.closed) return [];
	if (control.active) return ["stop"];
	if (control.complete) return ["verify"];
	return [control.retry_required ? "retry" : "resume", "close"];
}

function workflowPath(value: string, registry: string): string {
	const root = resolve(value);
	if (!isAbsolute(value) || resolve(dirname(root)) !== resolve(registry) || !/^workflow-pi-\d{8}T\d{9}Z(?:-\d+)?$/.test(basename(root))) {
		throw new Error(`Workflow must be an absolute workflow-pi-* path directly under ${registry}.`);
	}
	return root;
}

export async function manageWorkflow(
	pi: ExtensionAPI, prepareRuntime: PrepareRuntime, request: ManagementRequest = {}, signal?: AbortSignal,
	registry = runsDirectory(),
): Promise<ManagementResult> {
	signal?.throwIfAborted();
	let root = request.workflow;
	if (!root) {
		const status = await registryStatus(pi, signal, registry);
		root = status.blocker?.workflow_root;
		if (!root) return { status: "needs-workflow", message: "Name the exact workflow from workflow_history, then call workflow_manage again.", actions: [] };
	}
	root = workflowPath(root, registry);
	const control = controlState(await workerCommand(pi, ["control", root], signal), registry);
	if (control.workflow_root !== root) throw new Error("Agentvolve control state targets another workflow");
	if (control.closed) return { status: "closed-incomplete", workflow: root, message: "This workflow was closed as incomplete. Its evidence is preserved; submit a new goal rather than reopening it.", actions: [] };
	const actions = availableActions(control);
	const action = request.action;
	if (!action || !actions.includes(action)) return {
		status: "needs-action", workflow: root, actions,
		message: `Workflow ${basename(root)} accepts: ${actions.join(", ")}. Ask the user what to do, then call workflow_manage with action and workflow.`,
	};
	let reason = request.reason;
	if (action === "retry" || action === "close") {
		if (reason === undefined) return { status: "needs-reason", workflow: root, actions,
			message: `Ask the user for a reason to ${action} this workflow, then call workflow_manage again.` };
		if (!reason.trim() || reason.includes("\0") || reason.length > 2000) throw new Error("A reason of 1–2000 characters without NUL is required; nothing changed.");
	} else if (reason !== undefined) throw new Error(`A reason is accepted only for retry or close, not ${action}.`);
	signal?.throwIfAborted();
	// Recheck immediately before the requested effect. Projection data alone never
	// authorizes recurrence, and immutable runtime/budget rules still apply.
	const current = controlState(await workerCommand(pi, ["control", root], signal), registry);
	if (JSON.stringify(current) !== JSON.stringify(control)) throw new Error("Workflow state changed; inspect it again. No operation started.");
	const args = [action, root, ...(reason === undefined ? [] : [reason])];
	let result: Record<string, unknown>;
	if (action === "resume" || action === "retry") {
		await prepareRuntime(control.runtime_manifest, signal, true);
		result = decodeOutput(await pi.exec("uv", ["run", "python", "-m", "connectors.fixed.pi.runtime", ...args],
			{ cwd: repositoryRoot(), signal, timeout: 30_000 }));
	} else result = await workerCommand(pi, args, signal);
	if (result.worker_response_schema !== "agentvolve-worker-response-v1" || result.workflow_id !== control.workflow_id ||
		result.workflow_root !== root || result.action !== action || typeof result.state !== "string") throw new Error("Agentvolve returned an unexpected operation response; inspect progress before retrying.");
	pi.appendEntry("agentvolve-workflow-operation", result);
	return { status: result.state as string, workflow: root, actions: [], message: action === "close" ? "Workflow closed as incomplete. Evidence is preserved and new goals are unblocked."
		: action === "stop" && result.state === "stopped" ? `Agentvolve process tree stopped for ${root}. Evidence is preserved; this does not declare success.`
		: action === "stop" ? `Workflow ${basename(root)} reached ${String(result.state)} before stop finalized. Evidence is preserved.`
		: `Agentvolve ${action} requested for ${root}. Inspect /history ${basename(root)}; completion is not yet established.` };
}
