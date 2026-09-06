import { existsSync } from "node:fs";
import { mkdir, mkdtemp, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { isAbsolute, join, resolve } from "node:path";
import { setTimeout as delay } from "node:timers/promises";

import { type Message, StringEnum, uuidv7 } from "@earendil-works/pi-ai";
import {
	BorderedLoader,
	type ExtensionAPI,
	type ExtensionContext,
	type SessionEntry,
} from "@earendil-works/pi-coding-agent";
import { Text } from "@earendil-works/pi-tui";
import { Type } from "typebox";

import { showAgentvolveDashboard } from "./agentvolve_dashboard.ts";
import {
	boundedDiagnostic,
	COMMAND_TIMEOUT_MS,
	type CodingAction,
	type CodingKind,
	codingSolutionSummary,
	codingStatus,
	codingWorkflowStatus,
	configuredRuntimeSelection,
	configuredTaskProfile,
	decodeOperatorHistory,
	decodeOperatorProgress,
	decodeOutput,
	type DiscoveredTaskProfile,
	discoverTaskProfiles,
	latestCodingRoot,
	latestRunRoot,
	latestWorkerWorkflowRoot,
	llamaCppModelReady,
	llamaCppService,
	LOCAL_RUNTIME_TIMEOUT_MS,
	type ModeSummary,
	newCodingRunRoot,
	newRunRoot,
	type OperatorHistoryView,
	type OperatorProgressView,
	PROCESS_LABELS,
	processProjection,
	readProcessProjection,
	repositoryRoot,
	runsDirectory,
	runtimeManifest,
	type RuntimeSelection,
	runSummary,
	statusSummary,
	tasksDirectory,
	verificationSummary,
	WORKFLOW_MONITOR_INTERVAL_MS,
} from "./population_evolution_support.ts";

const MODE_NAME = "Agentvolve";
const STATUS_KEY = "population-evolution";
const WIDGET_KEY = "population-evolution";
const ACTIVE_WORKFLOW_STATUSES = new Set(["queued", "running"]);
interface LoaderResult {
	error?: string;
	summary?: ModeSummary;
}

interface CodingInvocation {
	args: string[];
	initialStage: number;
	kind: CodingKind;
	root: string;
}

interface WorkflowConfiguration {
	goal?: string;
	maxRounds?: number;
}

interface WorkerResponse {
	action: string;
	pid: number;
	state: string;
	worker_response_schema: "agentvolve-worker-response-v1";
	workflow_id: string;
	workflow_root: string;
}

class AgentvolveInputRequired extends Error {}

type AgentvolveModelMode = "routed";

type CodingLoaderAction = Exclude<CodingAction, "harness-status" | "solution-status">;

const CODING_LOADER_LABELS: Record<CodingLoaderAction, string> = {
	harness: "[1/6] Validating configuration; then [2/6] evolving the harness…",
	"harness-resume": "[2/6] Resuming committed harness-evolution effects…",
	"harness-retry": "[2/6] Retrying an explicitly approved harness model attempt…",
	solution: "[4/6] Evolving immutable solution commits…",
	"solution-resume": "[4/6] Resuming committed coding evolution effects…",
	"solution-retry": "[4/6] Retrying an explicitly approved model attempt…",
	"solution-verify": "[6/6] Replaying coding evolution evidence…",
};

const POPULATION_TOOL_DESCRIPTION = [
	"Run, inspect, or offline-verify the fixed mutation-only Population experiment.",
	"The run action can take several minutes. It returns only bounded sealed results",
	"and accepts no task, candidate, evaluator, or command input.",
].join(" ");

const POPULATION_TOOL_GUIDELINE = [
	"Use population_evolution only when the user explicitly asks to run, inspect, or verify",
	"Agentvolve's fixed reference Population assay; never emulate its recurrence with bash",
	"or file-editing tools.",
].join(" ");

const CODING_TOOL_DESCRIPTION = [
	"Activate Agentvolve operator mode, start or inspect its detached workflow, prepare a reviewed task from",
	"user-only session context, or use compatibility harness/solution actions. Its action schema accepts no",
	"task text, command, evaluator, candidate, profile path, retry reason, or output path.",
].join(" ");

const CODING_TOOL_GUIDELINE = [
	"Use darwinian_coding workflow_activate when the user asks to activate or enter Agentvolve mode; activation",
	"must not require or start a task. Use workflow_from_session only after the user clearly asks Agentvolve to",
	"solve a coding goal described in their messages; ask a normal follow-up question first when the goal is unclear.",
	"Use workflow_start for an already configured or reviewed task, workflow_status for progress, and",
	"workflow_history for prior runs. Never substitute ordinary in-place edits for Agentvolve's immutable",
	"candidates and independent assays.",
].join(" ");

const SESSION_TASK_SYSTEM_PROMPT = `You create a reviewed Agentvolve task draft from user messages and a Git file list.
Return exactly one JSON object and no markdown. Never include or infer an answer to the task. Do not copy assistant answers because they are not provided. Use the most recent explicit coding goal; treat setup or Agentvolve-interface discussion only as context. Describe only the user's requested outcome and independently checkable acceptance behavior.
The object must have exactly these fields:
- draft_schema: "agentvolve-session-task-draft-v1"
- schema_version: 1
- name: a short lowercase-hyphenated name
- repository_path: the supplied absolute repository path
- goal: a self-contained task description without a solution
- entrypoint: one tracked relative POSIX path that must still exist after mutation
- allowed_paths: sorted unique tracked relative POSIX paths the candidate may change
- development_checks: one or more objects with argv (a shell-free string array using checks already present in the repository), case_id, and timeout_ms
- limits: max_proposal_calls, max_rounds, and max_wall_seconds as finite integers
- stopping: {"minimum_replicates":1,"type":"all-development-cases-pass-v1"}
- final_policy: "replay-development-checks-v1"
Do not invent evaluator files, shell commands, paths absent from the supplied Git file list, hidden criteria, or a solution. If the conversation does not identify enough information for a valid task, use clearly invalid placeholder strings so the operator must correct the draft before registration.`;

function contentText(content: unknown): string[] {
	if (typeof content === "string") return [content];
	if (!Array.isArray(content)) return [];
	return content.flatMap((part) => {
		if (typeof part !== "object" || part === null || Array.isArray(part)) return [];
		const block = part as Record<string, unknown>;
		return block.type === "text" && typeof block.text === "string" ? [block.text] : [];
	});
}

function sessionUserConversation(entries: SessionEntry[]): string {
	const messages: string[] = [];
	for (const entry of entries) {
		if (entry.type !== "message" || entry.message.role !== "user") continue;
		const text = contentText(entry.message.content).join("\n").trim();
		if (text) messages.push(`User: ${text}`);
	}
	return messages.join("\n\n").slice(-32_000);
}

function responseText(response: { content: Array<{ type: string; text?: string }> }): string {
	return response.content
		.filter((part): part is { type: string; text: string } => part.type === "text" && typeof part.text === "string")
		.map((part) => part.text)
		.join("\n")
		.trim();
}

function reviewObject(value: unknown, location: string): Record<string, unknown> {
	if (typeof value !== "object" || value === null || Array.isArray(value)) {
		throw new Error(`${location} must be an object`);
	}
	return value as Record<string, unknown>;
}

function reviewString(value: unknown, location: string): string {
	if (typeof value !== "string" || !value.trim()) throw new Error(`${location} must be a non-empty string`);
	return value;
}

function reviewInteger(value: unknown, location: string): number {
	if (typeof value !== "number" || !Number.isInteger(value)) throw new Error(`${location} must be an integer`);
	return value;
}

function sessionTaskReview(source: string): string {
	const document = reviewObject(JSON.parse(source), "task draft");
	if (document.draft_schema !== "agentvolve-session-task-draft-v1" || document.schema_version !== 1) {
		throw new Error("task draft has an unsupported schema");
	}
	const name = reviewString(document.name, "task name");
	const repository = reviewString(document.repository_path, "repository");
	const goal = reviewString(document.goal, "goal");
	const entrypoint = reviewString(document.entrypoint, "entrypoint");
	if (
		!Array.isArray(document.allowed_paths) ||
		document.allowed_paths.length === 0 ||
		!document.allowed_paths.every((path) => typeof path === "string")
	) {
		throw new Error("allowed paths must be a non-empty string array");
	}
	if (!Array.isArray(document.development_checks) || document.development_checks.length === 0) {
		throw new Error("at least one development check is required");
	}
	const limits = reviewObject(document.limits, "limits");
	const maxRounds = reviewInteger(limits.max_rounds, "generation limit");
	const maxProposalCalls = reviewInteger(limits.max_proposal_calls, "proposal-call limit");
	const maxWallSeconds = reviewInteger(limits.max_wall_seconds, "wall-time limit");
	if (document.final_policy !== "replay-development-checks-v1") {
		throw new Error("task draft has an unsupported final policy");
	}
	const stopping = reviewObject(document.stopping, "stopping policy");
	if (stopping.type !== "all-development-cases-pass-v1") {
		throw new Error("task draft has an unsupported stopping policy");
	}
	const lines = [
		`Task: ${JSON.stringify(name)}`,
		`Repository: ${JSON.stringify(repository)}`,
		`Goal: ${JSON.stringify(goal)}`,
		`Entrypoint: ${JSON.stringify(entrypoint)}`,
		"Writable paths:",
		...document.allowed_paths.map((path) => `  - ${JSON.stringify(path)}`),
		"Development checks:",
	];
	for (const [index, value] of document.development_checks.entries()) {
		const check = reviewObject(value, `development check ${index + 1}`);
		const caseId = reviewString(check.case_id, `development check ${index + 1} case ID`);
		if (!Array.isArray(check.argv) || check.argv.length === 0 || !check.argv.every((item) => typeof item === "string")) {
			throw new Error(`development check ${index + 1} argv must be a non-empty string array`);
		}
		const timeout = reviewInteger(check.timeout_ms, `development check ${index + 1} timeout`);
		lines.push(`  - ${JSON.stringify(caseId)}: ${JSON.stringify(check.argv)} (${timeout} ms)`);
	}
	lines.push(
		`Limits: ${maxRounds} generations, ${maxProposalCalls} proposal calls, ${maxWallSeconds} wall seconds`,
		`Stopping: ${JSON.stringify(stopping)}`,
		`Final policy: ${JSON.stringify(document.final_policy)}`,
		"",
		"The generated protected final repeats these reviewed development checks and adds no hidden coverage.",
	);
	const summary = lines.join("\n");
	if (summary.length > 32_000) throw new Error("task review is too large for the in-session confirmation view");
	return summary;
}

function unquoteArgument(value: string): string {
	const text = value.trim();
	if (
		text.length >= 2 &&
		((text.startsWith('"') && text.endsWith('"')) || (text.startsWith("'") && text.endsWith("'")))
	) {
		return text.slice(1, -1).trim();
	}
	return text;
}

function setModeStatus(
	ctx: ExtensionContext,
	state: "available" | "failed" | "ready" | "running",
	process?: string,
): void {
	const color =
		state === "failed" ? "error" : state === "running" ? "warning" : state === "available" ? "dim" : "accent";
	ctx.ui.setStatus(STATUS_KEY, ctx.ui.theme.fg(color, `agentvolve: ${process ?? state}`));
}

function setModeWidget(
	ctx: ExtensionContext,
	summary?: ModeSummary,
	modelMode?: AgentvolveModelMode,
	modelLabel?: string,
): void {
	if (!summary || !ACTIVE_WORKFLOW_STATUSES.has(summary.status)) {
		ctx.ui.setWidget(WIDGET_KEY, undefined);
		return;
	}
	const lines = [
		ctx.ui.theme.fg("accent", `🧬 ${MODE_NAME}`) + ctx.ui.theme.fg("dim", " · unified workflow"),
		ctx.ui.theme.fg(
			"dim",
			modelMode && modelLabel ? `operator model: ${modelLabel}` : "operator model: mode not active",
		),
	];
	const match = summary?.process?.match(/^\[(\d+)\/6\]/);
	const currentStage = match ? Number.parseInt(match[1], 10) : undefined;
	const failed = ["failed", "inconsistent", "stalled", "stopped", "waiting-retry"].includes(summary?.status ?? "");
	lines.push(ctx.ui.theme.fg("accent", `workflow status: ${summary?.status ?? "not started"}`));
	for (let stage = 1; stage <= 6; stage += 1) {
		const label = PROCESS_LABELS[stage];
		const isCurrent = stage === currentStage;
		const currentComplete = ["completed", "sealed", "verified"].includes(summary?.status ?? "");
		const completed = currentStage !== undefined && (stage < currentStage || (isCurrent && currentComplete));
		const marker = completed ? "✓" : isCurrent && failed ? "!" : isCurrent ? "▶" : "○";
		const color = completed ? "success" : isCurrent && failed ? "error" : isCurrent ? "warning" : "dim";
		lines.push(ctx.ui.theme.fg(color, `${marker} [${stage}/6] ${label}`));
	}
	if (summary) {
		const assay =
			summary.finalPassed === undefined || summary.finalTasks === undefined
				? summary.status
				: `${summary.finalPassed}/${summary.finalTasks} final cases`;
		lines.push(ctx.ui.theme.fg("dim", `${assay} · ${summary.runRoot}`));
	}
	ctx.ui.setWidget(WIDGET_KEY, lines, { placement: "belowEditor" });
}

function humanSummary(summary: ModeSummary): string {
	const fields = [`${MODE_NAME}: ${summary.status}`];
	if (summary.process) fields.push(`process: ${summary.process}`);
	fields.push(`run: ${summary.runRoot}`);
	if (summary.finalPassed !== undefined && summary.finalTasks !== undefined) {
		fields.push(`protected final assay: ${summary.finalPassed}/${summary.finalTasks}`);
	}
	if (summary.candidateId) fields.push(`candidate: ${summary.candidateId}`);
	if (summary.patchPath) fields.push(`selected patch: ${summary.patchPath}`);
	if (summary.runtimeId) fields.push(`runtime: ${summary.runtimeId}`);
	return fields.join("\n");
}

function operatorProgressSummary(progress: OperatorProgressView): string {
	const lines = [
		`${progress.stage_label} · ${progress.state}`,
		progress.activity,
		`workflow: ${progress.workflow_root}`,
	];
	if (progress.task?.goal) lines.push(`goal: ${progress.task.goal.replaceAll(/\s+/g, " ").slice(0, 500)}`);
	if (progress.evolution) {
		lines.push(
			`evolution: ${progress.evolution.completed_rounds}/${progress.evolution.max_rounds ?? "?"} generations · ${progress.evolution.proposal_calls} proposal calls · ${progress.evolution.archive_member_count} archive members`,
		);
	}
	if (progress.result) {
		const selectedCommit = progress.result.selected_commit;
		const selectedCandidate = progress.result.selected_candidate_id;
		const finalPassed = progress.result.final_passed;
		const finalTasks = progress.result.final_tasks;
		const patchPath = progress.result.patch_path;
		if (typeof selectedCommit === "string") lines.push(`selected commit: ${selectedCommit}`);
		if (typeof selectedCandidate === "string") lines.push(`selected candidate: ${selectedCandidate}`);
		if (typeof finalPassed === "number" && typeof finalTasks === "number") {
			lines.push(`protected final assay: ${finalPassed}/${finalTasks}`);
		}
		if (typeof patchPath === "string") lines.push(`selected patch: ${patchPath}`);
	}
	if (progress.error) lines.push(`error: ${progress.error}`);
	if (progress.warnings.length > 0) lines.push(...progress.warnings.map((warning) => `warning: ${warning}`));
	return lines.join("\n");
}

function decodeWorkerResponse(value: Record<string, unknown>): WorkerResponse {
	if (
		value.worker_response_schema !== "agentvolve-worker-response-v1" ||
		typeof value.action !== "string" ||
		typeof value.pid !== "number" ||
		typeof value.state !== "string" ||
		typeof value.workflow_id !== "string" ||
		typeof value.workflow_root !== "string"
	) {
		throw new Error("Agentvolve worker returned an unexpected response");
	}
	return value as unknown as WorkerResponse;
}

function operatorModelLabel(ctx: ExtensionContext): string {
	return ctx.model ? `${ctx.model.provider}/${ctx.model.id} · ${ctx.thinkingLevel}` : "no operator model selected";
}

function summaryLoader(
	ctx: ExtensionContext,
	label: string,
	run: (signal: AbortSignal) => Promise<ModeSummary>,
): Promise<LoaderResult | null> {
	return ctx.ui.custom<LoaderResult | null>((tui, theme, _keybindings, done) => {
		const loader = new BorderedLoader(tui, theme, label);
		loader.onAbort = () => done(null);
		run(loader.signal)
			.then((summary) => done({ summary }))
			.catch((error) => done({ error: String(error) }));
		return loader;
	});
}

export default function populationEvolutionExtension(pi: ExtensionAPI): void {
	let modeActive = false;
	let activeModelMode: AgentvolveModelMode | undefined;
	let activeModelLabel: string | undefined;
	let workflowSummary: ModeSummary | undefined;
	let monitor: ReturnType<typeof setInterval> | undefined;
	let monitorRefreshing = false;
	let monitorFingerprint: string | undefined;
	let monitoredWorkflowRoot: string | undefined;
	let running = false;
	let workflowConfiguration: WorkflowConfiguration = {};
	let configurationWorkflowRoot: string | undefined;
	let reportedStages = new Set<string>();

	function persistWorkflowConfiguration(next: WorkflowConfiguration): void {
		workflowConfiguration = next;
		configurationWorkflowRoot = undefined;
		pi.appendEntry("agentvolve-workflow-configuration", next);
	}

	function consumeWorkflowConfiguration(summary: ModeSummary): void {
		if (summary.kind === "coding-solution" && summary.status === "sealed") {
			persistWorkflowConfiguration({});
		}
	}

	async function ensureLocalRuntime(selection: RuntimeSelection, signal?: AbortSignal): Promise<void> {
		if (selection.provider !== "llamacpp") return;
		if (await llamaCppModelReady(selection, signal)) return;
		const service = llamaCppService();
		const restart = await pi.exec("systemctl", ["--user", "restart", service], {
			signal,
			timeout: 30_000,
		});
		if (restart.killed || restart.code !== 0) {
			throw new Error(boundedDiagnostic(restart.stderr || restart.stdout) || `cannot start ${service}`);
		}
		const deadline = Date.now() + LOCAL_RUNTIME_TIMEOUT_MS;
		while (Date.now() < deadline) {
			signal?.throwIfAborted();
			if (await llamaCppModelReady(selection, signal)) return;
			await delay(1000, undefined, { signal });
		}
		throw new Error(
			`${selection.provider}/${selection.model} did not become ready through ${service}; ` +
				"configure that preset for load-on-startup and inspect the user service",
		);
	}

	function renderModeWidget(ctx: ExtensionContext, summary?: ModeSummary): void {
		if (summary) workflowSummary = summary;
		if (!modeActive) {
			ctx.ui.setWidget(WIDGET_KEY, undefined);
			return;
		}
		setModeWidget(ctx, workflowSummary, activeModelMode, activeModelLabel);
	}

	async function activateAgentvolveMode(
		ctx: ExtensionContext,
		_signal?: AbortSignal,
		_requestedMode: AgentvolveModelMode = "routed",
	): Promise<void> {
		const wasActive = modeActive;
		activeModelMode = "routed";
		activeModelLabel = operatorModelLabel(ctx);
		modeActive = true;
		setModeStatus(ctx, "ready", `operator · ${activeModelLabel}`);
		await startWorkflowMonitor(ctx);
		if (!wasActive) pi.appendEntry("agentvolve-mode", { active: true, modelMode: "routed" });
	}

	async function deactivateAgentvolveMode(ctx: ExtensionContext): Promise<void> {
		modeActive = false;
		activeModelMode = undefined;
		activeModelLabel = undefined;
		stopWorkflowMonitor();
		setModeStatus(ctx, "available");
		ctx.ui.setWidget(WIDGET_KEY, undefined);
		pi.appendEntry("agentvolve-mode", { active: false });
		ctx.ui.notify("Agentvolve mode closed; workflow status monitoring stopped", "info");
	}

	async function executePopulation(
		action: "run" | "status" | "verify",
		ctx: ExtensionContext,
		signal?: AbortSignal,
	): Promise<ModeSummary> {
		if (action === "status") return statusSummary();
		if (running) throw new Error("a Population evolution command is already running in this Pi session");
		if (action === "run") {
			await activateAgentvolveMode(ctx, signal);
			if (activeModelMode === "routed") {
				await ensureLocalRuntime(await configuredRuntimeSelection(), signal);
			}
		}

		const runtime = runtimeManifest();
		if (!existsSync(runtime)) {
			throw new Error(`reviewed runtime manifest is unavailable: ${runtime}`);
		}
		await mkdir(runsDirectory(), { recursive: true });
		const runRoot = action === "run" ? newRunRoot() : await latestRunRoot();
		if (!runRoot) throw new Error(`no Population runs exist under ${runsDirectory()}`);

		running = true;
		setModeStatus(ctx, "running");
		try {
			const args =
				action === "run"
					? ["run", "python", "apps/harness/experiment.py", "pi", runRoot, runtime]
					: ["run", "python", "apps/harness/experiment.py", "verify", runRoot];
			const result = await pi.exec("uv", args, {
				cwd: repositoryRoot(),
				signal,
				timeout: COMMAND_TIMEOUT_MS,
			});
			const report = decodeOutput(result);
			const summary = action === "run" ? runSummary(runRoot, report) : verificationSummary(runRoot, report);
			setModeStatus(ctx, "ready");
			renderModeWidget(ctx, summary);
			return summary;
		} catch (error) {
			setModeStatus(ctx, "failed");
			throw error;
		} finally {
			running = false;
		}
	}

	async function refreshWorkflowMonitor(ctx: ExtensionContext): Promise<void> {
		if (!modeActive || monitorRefreshing || running) return;
		monitorRefreshing = true;
		try {
			const summary = await codingWorkflowStatus();
			const fingerprint = JSON.stringify(summary);
			if (fingerprint === monitorFingerprint) return;
			monitorFingerprint = fingerprint;
			const active = ACTIVE_WORKFLOW_STATUSES.has(summary.status);
			if (active) monitoredWorkflowRoot = summary.runRoot;
			renderModeWidget(ctx, summary);
			setModeStatus(
				ctx,
				active ? "running" : modeActive ? "ready" : "available",
				active ? summary.process : modeActive && activeModelLabel ? `operator · ${activeModelLabel}` : undefined,
			);
			if (!active && monitoredWorkflowRoot !== summary.runRoot) return;
			try {
				const progress = await operatorProgress();
				for (const stage of progress.stages) {
					if (!["complete", "reused"].includes(stage.status)) continue;
					const key = `${progress.workflow_id}:${stage.number}`;
					if (reportedStages.has(key)) continue;
					reportedStages.add(key);
					pi.appendEntry("agentvolve-stage-report", {
						label: stage.label,
						stage: stage.number,
						status: stage.status,
						summary: stage.summary,
						workflowId: progress.workflow_id,
					});
					if (stage.number === 6) ctx.ui.notify(`Agentvolve finished: ${stage.summary}`, "info");
				}
				if (["failed", "inconsistent", "stalled", "stopped", "waiting-retry"].includes(progress.state)) {
					const stateKey = `${progress.workflow_id}:state:${progress.state}`;
					if (!reportedStages.has(stateKey)) {
						reportedStages.add(stateKey);
						ctx.ui.notify(`Agentvolve ${progress.state}: ${progress.activity}`, "warning");
					}
				}
				if (
					(workflowConfiguration.goal !== undefined || workflowConfiguration.maxRounds !== undefined) &&
					configurationWorkflowRoot === progress.workflow_root &&
					["completed", "verified"].includes(progress.state)
				) {
					persistWorkflowConfiguration({});
					configurationWorkflowRoot = undefined;
				}
			} catch {
				// The compact widget still works if the richer read-only projection is temporarily unavailable.
			} finally {
				if (!active) monitoredWorkflowRoot = undefined;
			}
		} finally {
			monitorRefreshing = false;
		}
	}

	async function startWorkflowMonitor(ctx: ExtensionContext): Promise<void> {
		if (monitor) clearInterval(monitor);
		monitorFingerprint = undefined;
		try {
			await refreshWorkflowMonitor(ctx);
		} catch {
			renderModeWidget(ctx);
		}
		monitor = setInterval(() => void refreshWorkflowMonitor(ctx).catch(() => undefined), WORKFLOW_MONITOR_INTERVAL_MS);
	}

	function stopWorkflowMonitor(): void {
		if (monitor) clearInterval(monitor);
		monitor = undefined;
		monitorRefreshing = false;
		monitoredWorkflowRoot = undefined;
	}

	async function requireCodingRoot(kind: CodingKind, completed: boolean, message: string): Promise<string> {
		const root = await latestCodingRoot(kind, completed);
		if (!root) throw new Error(message);
		return root;
	}

	function configuredHarnessDescriptor(): string | undefined {
		const supplied = process.env.METERING_EVOLUTION_HARNESS_DESCRIPTOR?.trim();
		if (!supplied) return undefined;
		if (!isAbsolute(supplied)) throw new Error("configured harness descriptor must be an absolute path");
		if (!existsSync(supplied)) throw new Error(`configured harness descriptor is unavailable: ${supplied}`);
		return supplied;
	}

	async function selectedHarnessDescriptor(): Promise<string | undefined> {
		const configured = configuredHarnessDescriptor();
		if (configured) return configured;
		const root = await latestCodingRoot("harness");
		return root ? join(root, "selected-harness.json") : undefined;
	}

	async function buildCodingInvocation(
		action: CodingLoaderAction,
		argument: string,
		runtime: string,
	): Promise<CodingInvocation> {
		switch (action) {
			case "harness": {
				const root = newCodingRunRoot("harness");
				return {
					args: ["run", "python", "apps/harness/experiment.py", "coding-pi", root, runtime],
					initialStage: 1,
					kind: "harness",
					root,
				};
			}
			case "harness-resume":
			case "harness-retry": {
				const root = await requireCodingRoot("harness", false, "no resumable coding harness run exists");
				const reason = argument.trim();
				if (action === "harness-retry" && !reason) {
					throw new Error("/evolve-harness-retry requires an operator retry reason");
				}
				return {
					args: [
						"run",
						"python",
						"apps/harness/experiment.py",
						action === "harness-retry" ? "retry" : "resume",
						root,
						...(action === "harness-retry" ? [reason] : []),
					],
					initialStage: 2,
					kind: "harness",
					root,
				};
			}
			case "solution": {
				const harness = await selectedHarnessDescriptor();
				if (!harness) throw new Error("run /evolve-harness before evolving a solution");
				const root = newCodingRunRoot("solution");
				return {
					args: [
						"run",
						"python",
						"apps/coding_agent/solution_experiment.py",
						"pi",
						configuredTaskProfile(argument),
						root,
						runtime,
						harness,
					],
					initialStage: 4,
					kind: "solution",
					root,
				};
			}
			case "solution-resume":
			case "solution-retry": {
				const root = await requireCodingRoot("solution", false, "no resumable coding solution run exists");
				const reason = argument.trim();
				if (action === "solution-retry" && !reason) {
					throw new Error("/evolve-code-retry requires an operator retry reason");
				}
				return {
					args: [
						"run",
						"python",
						"apps/coding_agent/solution_experiment.py",
						action === "solution-retry" ? "retry" : "resume",
						root,
						...(action === "solution-retry" ? [reason] : []),
					],
					initialStage: 4,
					kind: "solution",
					root,
				};
			}
			case "solution-verify": {
				const root = await requireCodingRoot("solution", true, "no completed coding solution run exists");
				return {
					args: ["run", "python", "apps/coding_agent/solution_experiment.py", "verify", root],
					initialStage: 6,
					kind: "solution",
					root,
				};
			}
			default:
				throw new Error(`unsupported coding action: ${String(action)}`);
		}
	}

	async function executeCoding(
		action: CodingAction,
		ctx: ExtensionContext,
		profileArgument = "",
		signal?: AbortSignal,
	): Promise<ModeSummary> {
		if (running) throw new Error("an evolution command is already running in this Pi session");
		if (action === "harness-status") return codingStatus("harness");
		if (action === "solution-status") return codingStatus("solution");
		if (action !== "solution-verify") {
			await activateAgentvolveMode(ctx, signal);
			if (activeModelMode === "routed") {
				await ensureLocalRuntime(await configuredRuntimeSelection(), signal);
			}
		}
		const runtime = runtimeManifest();
		if (!existsSync(runtime)) throw new Error(`reviewed runtime manifest is unavailable: ${runtime}`);
		await mkdir(runsDirectory(), { recursive: true });
		const invocation = await buildCodingInvocation(action, profileArgument, runtime);
		const { args, kind: runKind, root } = invocation;
		const initial = processProjection(invocation.initialStage);
		let watching = true;
		let shown = initial.display;
		const refresh = async (): Promise<void> => {
			const process = await readProcessProjection(root, runKind, initial.stage);
			if (!watching || process.display === shown) return;
			shown = process.display;
			setModeStatus(ctx, "running", shown);
			renderModeWidget(ctx, {
				action: "status",
				kind: runKind === "harness" ? "coding-harness" : "coding-solution",
				process: shown,
				runRoot: root,
				status: "in progress",
			});
		};
		running = true;
		setModeStatus(ctx, "running", shown);
		renderModeWidget(ctx, {
			action: "status",
			kind: runKind === "harness" ? "coding-harness" : "coding-solution",
			process: shown,
			runRoot: root,
			status: "in progress",
		});
		const watcher = setInterval(() => void refresh().catch(() => undefined), 1000);
		try {
			const result = await pi.exec("uv", args, {
				cwd: repositoryRoot(),
				signal,
				timeout: COMMAND_TIMEOUT_MS,
			});
			const report = decodeOutput(result);
			const baseSummary = action.startsWith("harness")
				? runSummary(root, report)
				: codingSolutionSummary(root, report, action === "solution-verify" ? "verify" : "run");
			const process = await readProcessProjection(root, runKind, runKind === "harness" ? 3 : 6);
			const summary = { ...baseSummary, process: process.display };
			setModeStatus(ctx, "ready", process.display);
			renderModeWidget(ctx, summary);
			return summary;
		} catch (error) {
			const process = await readProcessProjection(root, runKind, initial.stage).catch(() => initial);
			setModeStatus(ctx, "failed", process.display);
			throw error;
		} finally {
			watching = false;
			clearInterval(watcher);
			running = false;
		}
	}

	async function operatorProgress(selector = ""): Promise<OperatorProgressView> {
		const result = await pi.exec(
			"uv",
			[
				"run",
				"python",
				"-m",
				"apps.coding_agent.operator_view",
				"progress",
				runsDirectory(),
				...(selector.trim() ? [selector.trim()] : []),
			],
			{ cwd: repositoryRoot(), timeout: 15_000 },
		);
		return decodeOperatorProgress(decodeOutput(result));
	}

	async function operatorHistory(): Promise<OperatorHistoryView> {
		const result = await pi.exec(
			"uv",
			["run", "python", "-m", "apps.coding_agent.operator_view", "history", runsDirectory()],
			{ cwd: repositoryRoot(), timeout: 15_000 },
		);
		return decodeOperatorHistory(decodeOutput(result));
	}

	async function launchDetachedWorkflow(
		ctx: ExtensionContext,
		profile: string,
		consumeConfiguration = false,
		signal?: AbortSignal,
	): Promise<boolean> {
		try {
			await activateAgentvolveMode(ctx, signal, "routed");
			const selection = await configuredRuntimeSelection();
			await ensureLocalRuntime(selection, signal);
			const runtime = runtimeManifest();
			const harness = await selectedHarnessDescriptor();
			const result = await pi.exec(
				"uv",
				[
					"run",
					"python",
					"-m",
					"apps.coding_agent.agentvolve_worker",
					"start",
					runsDirectory(),
					configuredTaskProfile(profile),
					runtime,
					...(harness ? [harness] : []),
				],
				{ cwd: repositoryRoot(), signal, timeout: 30_000 },
			);
			const worker = decodeWorkerResponse(decodeOutput(result));
			if (consumeConfiguration) configurationWorkflowRoot = worker.workflow_root;
			pi.appendEntry("agentvolve-worker-launch", { ...worker, consumesConfiguration: consumeConfiguration });
			setModeStatus(ctx, "running", `[1/6] detached worker pid ${worker.pid}`);
			await startWorkflowMonitor(ctx);
			ctx.ui.notify(
				`Agentvolve worker started separately from this Pi session.\nworker pid: ${worker.pid}\nworkflow: ${worker.workflow_root}\nUse /view-progress while you continue using Pi.`,
				"info",
			);
			return true;
		} catch (error) {
			ctx.ui.notify(String(error), "error");
			return false;
		}
	}

	async function launchDetachedAction(
		action: "resume" | "retry" | "stop" | "verify",
		ctx: ExtensionContext,
		reason = "",
		signal?: AbortSignal,
	): Promise<boolean> {
		try {
			await activateAgentvolveMode(ctx, signal, "routed");
			const workflow = await latestWorkerWorkflowRoot();
			if (!workflow) throw new Error("no detached Agentvolve workflow exists");
			if (["resume", "retry"].includes(action)) {
				const selection = await configuredRuntimeSelection();
				await ensureLocalRuntime(selection, signal);
			}
			const result = await pi.exec(
				"uv",
				[
					"run",
					"python",
					"-m",
					"apps.coding_agent.agentvolve_worker",
					action,
					workflow,
					...(action === "retry" ? [reason] : []),
				],
				{ cwd: repositoryRoot(), signal, timeout: 30_000 },
			);
			const worker = decodeWorkerResponse(decodeOutput(result));
			pi.appendEntry("agentvolve-worker-launch", { ...worker, consumesConfiguration: false });
			await startWorkflowMonitor(ctx);
			ctx.ui.notify(
				`Agentvolve worker action accepted: ${action} · ${worker.state}\npid: ${worker.pid}\nworkflow: ${worker.workflow_root}`,
				"info",
			);
			return true;
		} catch (error) {
			ctx.ui.notify(String(error), "error");
			return false;
		}
	}

	async function codingLoader(action: CodingLoaderAction, ctx: ExtensionContext, profileArgument = ""): Promise<void> {
		if (ctx.mode === "rpc") {
			try {
				const summary = await executeCoding(action, ctx, profileArgument);
				pi.appendEntry("darwinian-coding-run", summary);
				if (["solution-resume", "solution-retry"].includes(action)) consumeWorkflowConfiguration(summary);
				ctx.ui.notify(humanSummary(summary), "info");
			} catch (error) {
				ctx.ui.notify(String(error), "error");
			}
			return;
		}
		if (ctx.mode !== "tui") {
			ctx.ui.notify("Agentvolve commands require interactive or RPC Pi", "error");
			return;
		}
		const result = await summaryLoader(ctx, CODING_LOADER_LABELS[action], (signal) =>
			executeCoding(action, ctx, profileArgument, signal),
		);
		if (result === null) {
			ctx.ui.notify("Agentvolve command cancelled", "info");
			return;
		}
		if (result.error) {
			ctx.ui.notify(result.error, "error");
			return;
		}
		if (result.summary) {
			pi.appendEntry("darwinian-coding-run", result.summary);
			if (["solution-resume", "solution-retry"].includes(action)) consumeWorkflowConfiguration(result.summary);
			ctx.ui.notify(humanSummary(result.summary), "info");
		}
	}

	async function commandWithLoader(action: "run" | "verify", ctx: ExtensionContext): Promise<void> {
		if (ctx.mode !== "tui") {
			ctx.ui.notify(`/${action === "run" ? "evolve" : "evolve-verify"} requires interactive Pi`, "error");
			return;
		}
		const label = action === "run" ? "Running isolated Population evolution…" : "Replaying offline verification…";
		const result = await summaryLoader(ctx, label, (signal) => executePopulation(action, ctx, signal));
		if (result === null) {
			ctx.ui.notify("Population evolution cancelled", "info");
			return;
		}
		if (result.error) {
			ctx.ui.notify(result.error, "error");
			return;
		}
		if (result.summary) {
			pi.appendEntry("population-evolution-run", result.summary);
			ctx.ui.notify(humanSummary(result.summary), "info");
		}
	}

	async function showPopulationStatus(ctx: ExtensionContext): Promise<void> {
		try {
			const summary = await executePopulation("status", ctx);
			renderModeWidget(ctx, summary);
			ctx.ui.notify(humanSummary(summary), "info");
		} catch (error) {
			ctx.ui.notify(String(error), "error");
		}
	}

	async function showCodingStatus(kind: CodingKind, ctx: ExtensionContext): Promise<void> {
		try {
			const summary = await executeCoding(kind === "harness" ? "harness-status" : "solution-status", ctx);
			renderModeWidget(ctx, summary);
			ctx.ui.notify(humanSummary(summary), "info");
		} catch (error) {
			ctx.ui.notify(String(error), "error");
		}
	}

	async function showProgress(ctx: ExtensionContext, selector = ""): Promise<void> {
		try {
			const progress = await operatorProgress(selector);
			pi.appendEntry("agentvolve-progress-view", {
				stage: progress.stage,
				state: progress.state,
				workflowId: progress.workflow_id,
				workflowRoot: progress.workflow_root,
			});
			if (ctx.mode !== "tui") {
				ctx.ui.notify(
					`${progress.stage_label} · ${progress.state}\n${progress.activity}\n${progress.workflow_root}`,
					"info",
				);
				return;
			}
			const resumeMonitor = monitor !== undefined;
			if (resumeMonitor) stopWorkflowMonitor();
			try {
				await showAgentvolveDashboard(ctx, operatorModelLabel(ctx), progress, () => operatorProgress(selector));
			} finally {
				if (resumeMonitor && modeActive) await startWorkflowMonitor(ctx);
			}
		} catch (error) {
			ctx.ui.notify(String(error), "error");
		}
	}

	async function showWorkflowHistory(ctx: ExtensionContext): Promise<void> {
		try {
			const history = await operatorHistory();
			if (!history.runs.length) {
				ctx.ui.notify(`No Agentvolve workflow runs exist under ${runsDirectory()}`, "info");
				return;
			}
			if (ctx.mode !== "tui") {
				const lines = history.runs
					.slice(0, 10)
					.map((run) => `${run.name} · ${run.state} · ${run.stage === null ? "?" : `[${run.stage}/6]`}`);
				ctx.ui.notify(lines.join("\n"), "info");
				return;
			}
			const labels = history.runs.map((run) => {
				const goal = run.goal?.replaceAll(/\s+/g, " ").slice(0, 70) ?? "goal unavailable";
				return `${run.stage === null ? "[?/6]" : `[${run.stage}/6]`} ${run.state} · ${run.name} · ${goal}`;
			});
			const selected = await ctx.ui.select("Agentvolve history · choose a run to inspect", labels);
			if (!selected) return;
			const run = history.runs[labels.indexOf(selected)];
			if (!run) return;
			pi.appendEntry("agentvolve-history-view", { name: run.name, state: run.state });
			await showProgress(ctx, run.name);
		} catch (error) {
			ctx.ui.notify(String(error), "error");
		}
	}

	function taskProfileChoice(profile: DiscoveredTaskProfile, cwd: string): string {
		const repository = resolve(profile.repository) === cwd ? "current folder" : profile.repository;
		const goal = profile.goal.replaceAll(/\s+/g, " ").slice(0, 100);
		return `${profile.name} · ${profile.entrypoint} · ${repository} · ${goal}`;
	}

	async function chooseTaskProfile(ctx: ExtensionContext): Promise<string> {
		const configured = process.env.METERING_EVOLUTION_TASK_PROFILE?.trim();
		if (configured) return configuredTaskProfile(configured);
		const discovered = await discoverTaskProfiles();
		const cwd = resolve(ctx.cwd);
		const matching = discovered.filter((profile) => resolve(profile.repository) === cwd);
		if (matching.length === 1) return matching[0]!.path;
		if (ctx.mode === "tui" && discovered.length > 0) {
			const candidates = matching.length > 0 ? matching : discovered;
			const labels = candidates.map((profile) => taskProfileChoice(profile, cwd));
			const title =
				matching.length > 0
					? "Choose the reviewed Agentvolve task for this folder"
					: "No task is bound to this folder; choose a reviewed Agentvolve task";
			const selected = await ctx.ui.select(title, labels);
			if (!selected) throw new AgentvolveInputRequired("Task selection was cancelled; no workflow started.");
			const profile = candidates[labels.indexOf(selected)];
			if (!profile) throw new Error("Agentvolve task selection did not resolve");
			return profile.path;
		}
		if (discovered.length === 0) {
			throw new AgentvolveInputRequired(
				`No reviewed task profiles are registered under ${tasksDirectory()}. Describe the coding goal in this session so Agentvolve can prepare it for direct review.`,
			);
		}
		if (matching.length === 0) {
			throw new AgentvolveInputRequired(
				`No reviewed task profile is bound to the current folder ${cwd}. Describe the coding goal for this repository so Agentvolve can prepare it, or use interactive task selection.`,
			);
		}
		throw new AgentvolveInputRequired(
			`${matching.length} reviewed task profiles match ${cwd}. Choose one in an interactive Pi session before starting.`,
		);
	}

	async function trackedRepositoryFiles(ctx: ExtensionContext): Promise<string[]> {
		const result = await pi.exec("git", ["-C", ctx.cwd, "ls-tree", "-r", "--name-only", "HEAD"], {
			timeout: 10_000,
		});
		if (result.killed || result.code !== 0) {
			throw new Error(boundedDiagnostic(result.stderr || result.stdout) || "current folder is not a Git repository");
		}
		return result.stdout
			.split("\n")
			.map((path) => path.trim())
			.filter(Boolean)
			.slice(0, 2_000);
	}

	async function reviewSessionTaskDraft(ctx: ExtensionContext, generated: string): Promise<string | null> {
		let draft = generated.trim();
		for (;;) {
			let summary: string;
			try {
				summary = sessionTaskReview(draft);
			} catch (error) {
				ctx.ui.notify(`The generated task needs correction: ${String(error)}`, "warning");
				const edited = await ctx.ui.editor("Correct Agentvolve task details (advanced JSON)", draft);
				if (edited === undefined) return null;
				draft = edited.trim();
				continue;
			}
			if (await ctx.ui.confirm("Register and run this reviewed task?", summary)) return draft;
			const action = await ctx.ui.select("Agentvolve task was not approved", [
				"Edit task details (advanced JSON)",
				"Cancel without starting",
			]);
			if (action !== "Edit task details (advanced JSON)") return null;
			const edited = await ctx.ui.editor("Edit Agentvolve task details (advanced JSON)", draft);
			if (edited === undefined) return null;
			draft = edited.trim();
		}
	}

	async function generateSessionTaskDraft(ctx: ExtensionContext, signal?: AbortSignal): Promise<string | null> {
		if (!ctx.model) throw new Error("select a Pi model before generating a session task");
		const model = ctx.model;
		const conversation = sessionUserConversation(ctx.sessionManager.buildContextEntries());
		if (!conversation) throw new Error("the current session has no user task description");
		const files = await trackedRepositoryFiles(ctx);
		if (!files.length) throw new Error("the current Git commit has no tracked files");
		const prompt = [
			`Repository: ${resolve(ctx.cwd)}`,
			"Tracked files:",
			files.join("\n"),
			"",
			"User messages from the active session branch:",
			conversation,
		].join("\n");
		const message: Message = {
			role: "user",
			content: [{ type: "text", text: prompt }],
			timestamp: Date.now(),
		};
		let generated: string;
		if (ctx.mode === "tui") {
			const result = await ctx.ui.custom<{ draft?: string; error?: string } | null>(
				(tui, theme, _keybindings, done) => {
					const loader = new BorderedLoader(tui, theme, "Generating a task draft from user messages only…");
					loader.onAbort = () => done(null);
					ctx.modelRegistry
						.complete(
							model,
							{ systemPrompt: SESSION_TASK_SYSTEM_PROMPT, messages: [message] },
							{ signal: loader.signal, cacheRetention: "none", sessionId: uuidv7() },
						)
						.then((response) => done({ draft: responseText(response) }))
						.catch((error) => done({ error: String(error) }));
					return loader;
				},
			);
			if (result === null) return null;
			if (result.error) throw new Error(result.error);
			generated = result.draft ?? "";
		} else if (ctx.mode === "rpc") {
			const response = await ctx.modelRegistry.complete(
				model,
				{ systemPrompt: SESSION_TASK_SYSTEM_PROMPT, messages: [message] },
				{ signal, cacheRetention: "none", sessionId: uuidv7() },
			);
			generated = responseText(response);
		} else {
			throw new Error("session task preparation requires interactive or RPC Pi");
		}
		const reviewed = await reviewSessionTaskDraft(ctx, generated);
		if (reviewed === null) return null;

		const temporary = await mkdtemp(join(tmpdir(), "agentvolve-session-task-"));
		try {
			const draftPath = join(temporary, "draft.json");
			await writeFile(draftPath, `${reviewed.trimEnd()}\n`, "utf8");
			await mkdir(tasksDirectory(), { recursive: true });
			const command = await pi.exec(
				"uv",
				["run", "python", "-m", "apps.coding_agent.task_profile_tool", "create", draftPath, tasksDirectory()],
				{ cwd: repositoryRoot(), timeout: 30_000 },
			);
			const registration = decodeOutput(command);
			const profile = registration.profile;
			if (registration.registration_schema !== "agentvolve-task-registration-v1" || typeof profile !== "string") {
				throw new Error("task registration returned an unexpected result");
			}
			pi.appendEntry("agentvolve-task-registration", {
				profile,
				sessionId: ctx.sessionManager.getSessionId(),
				taskId: registration.task_id,
			});
			ctx.ui.notify(`Registered Agentvolve task: ${profile}`, "info");
			return profile;
		} finally {
			await rm(temporary, { force: true, recursive: true });
		}
	}

	async function deriveGoalTask(template: string, goal: string, maxRounds: number): Promise<string> {
		const temporary = await mkdtemp(join(tmpdir(), "agentvolve-goal-"));
		try {
			const goalPath = join(temporary, "goal.txt");
			await writeFile(goalPath, `${goal.trim()}\n`, "utf8");
			const output = join(tasksDirectory(), "generated");
			await mkdir(output, { recursive: true });
			const command = await pi.exec(
				"uv",
				[
					"run",
					"python",
					"-m",
					"apps.coding_agent.task_profile_tool",
					"derive",
					template,
					goalPath,
					String(maxRounds),
					output,
				],
				{ cwd: repositoryRoot(), timeout: 30_000 },
			);
			const registration = decodeOutput(command);
			const profile = registration.profile;
			if (registration.registration_schema !== "agentvolve-task-derivation-v1" || typeof profile !== "string") {
				throw new Error("goal task derivation returned an unexpected result");
			}
			pi.appendEntry("agentvolve-task-derivation", {
				maxRounds,
				profile,
				sourceProfile: template,
				taskId: registration.task_id,
			});
			return profile;
		} finally {
			await rm(temporary, { force: true, recursive: true });
		}
	}

	async function runConfiguredGoal(ctx: ExtensionContext): Promise<boolean> {
		const { goal, maxRounds } = workflowConfiguration;
		if (!goal || maxRounds === undefined) return false;
		try {
			if (configurationWorkflowRoot) {
				const associated = await operatorProgress(configurationWorkflowRoot).catch(() => undefined);
				if (associated && ["completed", "verified"].includes(associated.state)) {
					persistWorkflowConfiguration({});
					ctx.ui.notify(
						`The configured Agentvolve workflow already finished at ${associated.workflow_root}. Use /view-progress ${associated.workflow_root.slice(associated.workflow_root.lastIndexOf("/") + 1)} to review it.`,
						"info",
					);
					return true;
				}
			}
			const current = await operatorProgress().catch(() => undefined);
			if (current && !["completed", "verified"].includes(current.state)) {
				const name = current.workflow_root.slice(current.workflow_root.lastIndexOf("/") + 1);
				const recovery = name.startsWith("workflow-")
					? "/agentvolve-resume or /agentvolve-retry REASON"
					: name.startsWith("harness-")
						? "/evolve-harness-resume or /evolve-harness-retry REASON"
						: "/evolve-code-resume or /evolve-code-retry REASON";
				ctx.ui.notify(
					`Existing ${current.state} work requires attention at ${current.workflow_root}; use ${recovery} before starting another task.`,
					"warning",
				);
				return true;
			}
			const template = await chooseTaskProfile(ctx);
			const profile = await deriveGoalTask(template, goal, maxRounds);
			await launchDetachedWorkflow(ctx, profile, true);
		} catch (error) {
			if (error instanceof AgentvolveInputRequired) {
				await activateAgentvolveMode(ctx, undefined, "routed");
				ctx.ui.notify(error.message, "warning");
			} else {
				ctx.ui.notify(String(error), "error");
			}
		}
		return true;
	}

	async function openAgentvolve(ctx: ExtensionContext): Promise<void> {
		if (ctx.mode !== "tui" && ctx.mode !== "rpc") {
			ctx.ui.notify("/agentvolve requires interactive or RPC Pi", "error");
			return;
		}
		if (await runConfiguredGoal(ctx)) return;
		try {
			await activateAgentvolveMode(ctx, undefined, "routed");
			ctx.ui.notify(
				"Agentvolve mode is active. Continue talking to Pi normally: describe a coding goal and ask " +
					"Agentvolve to solve it; Pi can ask clarifying questions and prepare the reviewed task in-session. " +
					"The manifest-pinned model runs in a detached worker while this operator session stays usable. " +
					"You can also use /goal plus /limit, /evolve-start, /view-progress, or /view-history.",
				"info",
			);
		} catch (error) {
			ctx.ui.notify(String(error), "error");
		}
	}

	function registerNoArgumentCommand(
		name: string,
		description: string,
		handler: (ctx: ExtensionContext) => Promise<void>,
	): void {
		pi.registerCommand(name, {
			description,
			handler: async (args, ctx) => {
				if (args.trim()) {
					ctx.ui.notify(`/${name} accepts no arguments`, "error");
					return;
				}
				await handler(ctx);
			},
		});
	}

	pi.registerEntryRenderer<{
		label: string;
		stage: number;
		status: string;
		summary: string;
		workflowId: string;
	}>("agentvolve-stage-report", (entry, _options, theme) => {
		const report = entry.data;
		const marker = report?.status === "reused" ? "↺" : "✓";
		const label = report?.label ?? "Agentvolve stage";
		const stage = report?.stage ?? "?";
		const summary = report?.summary ?? "Stage completed";
		return new Text(
			`${theme.fg("success", `${marker} Agentvolve [${stage}/6] ${label}`)}\n${theme.fg("muted", summary)}`,
			1,
			0,
		);
	});

	pi.registerCommand("goal", {
		description: "Set the natural-language goal for the next Agentvolve workflow",
		handler: async (args, ctx) => {
			const goal = unquoteArgument(args);
			if (!goal) {
				ctx.ui.notify("Usage: /goal describe the independently checked task", "error");
				return;
			}
			if (goal.length > 65_536) {
				ctx.ui.notify("/goal is too long", "error");
				return;
			}
			persistWorkflowConfiguration({ ...workflowConfiguration, goal });
			const suffix = workflowConfiguration.maxRounds === undefined ? "; now set /limit" : "; run /agentvolve";
			ctx.ui.notify(`Agentvolve goal recorded${suffix}`, "info");
		},
	});

	pi.registerCommand("limit", {
		description: "Set the finite generation limit for the next Agentvolve workflow",
		handler: async (args, ctx) => {
			const value = unquoteArgument(args);
			const match = /^(\d+)(?:\s+generations?)?$/i.exec(value);
			const maxRounds = match ? Number.parseInt(match[1]!, 10) : Number.NaN;
			if (!Number.isInteger(maxRounds) || maxRounds < 1 || maxRounds > 256) {
				ctx.ui.notify("Usage: /limit NUMBER [generations], where NUMBER is 1 through 256", "error");
				return;
			}
			persistWorkflowConfiguration({ ...workflowConfiguration, maxRounds });
			const suffix = workflowConfiguration.goal === undefined ? "; now set /goal" : "; run /agentvolve";
			ctx.ui.notify(`Agentvolve limit recorded: ${maxRounds} generations${suffix}`, "info");
		},
	});

	registerNoArgumentCommand(
		"agentvolve",
		"Activate Agentvolve mode or start the configured goal in a detached worker",
		openAgentvolve,
	);
	registerNoArgumentCommand(
		"agentvolve-off",
		"Leave Agentvolve operator mode and stop this session's monitor",
		deactivateAgentvolveMode,
	);
	pi.registerCommand("view-progress", {
		description: "Open the live Agentvolve terminal dashboard; optionally name one run",
		handler: async (args, ctx) => showProgress(ctx, unquoteArgument(args)),
	});
	registerNoArgumentCommand(
		"view-history",
		"Browse Agentvolve workflow history and open a selected dashboard",
		showWorkflowHistory,
	);
	registerNoArgumentCommand("agentvolve-history", "Compatibility alias for /view-history", showWorkflowHistory);
	pi.registerCommand("evolve-start", {
		description: "Start Agentvolve in a detached worker using an optional absolute task profile",
		handler: async (args, ctx) => {
			try {
				const supplied = unquoteArgument(args);
				const profile = supplied ? configuredTaskProfile(supplied) : await chooseTaskProfile(ctx);
				await launchDetachedWorkflow(ctx, profile);
			} catch (error) {
				ctx.ui.notify(String(error), "error");
			}
		},
	});
	registerNoArgumentCommand("evolve-task", "Create a reviewed task from this Pi session and start it", async (ctx) => {
		try {
			const profile = await generateSessionTaskDraft(ctx);
			if (profile) await launchDetachedWorkflow(ctx, profile);
		} catch (error) {
			ctx.ui.notify(String(error), "error");
		}
	});
	registerNoArgumentCommand("agentvolve-resume", "Resume replay-authorized detached workflow effects", (ctx) =>
		launchDetachedAction("resume", ctx).then(() => undefined),
	);
	pi.registerCommand("agentvolve-retry", {
		description: "Authorize one reserved retry in the detached worker",
		handler: async (args, ctx) => {
			const reason = unquoteArgument(args);
			if (!reason) {
				ctx.ui.notify("/agentvolve-retry requires an operator-reviewed reason", "error");
				return;
			}
			await launchDetachedAction("retry", ctx, reason);
		},
	});
	registerNoArgumentCommand("agentvolve-stop", "Interrupt the detached worker; recovery may require retry", (ctx) =>
		launchDetachedAction("stop", ctx).then(() => undefined),
	);
	registerNoArgumentCommand("agentvolve-verify", "Offline-verify the detached workflow result", (ctx) =>
		launchDetachedAction("verify", ctx).then(() => undefined),
	);
	registerNoArgumentCommand("evolve", "Run one sealed two-generation Population experiment", (ctx) =>
		commandWithLoader("run", ctx),
	);
	registerNoArgumentCommand("evolve-status", "Show the latest Population experiment result", showPopulationStatus);
	registerNoArgumentCommand("evolve-verify", "Offline-verify the latest Population experiment", (ctx) =>
		commandWithLoader("verify", ctx),
	);
	registerNoArgumentCommand("evolve-harness", "Evolve and final-seal a Pi harness on coding tasks", (ctx) =>
		codingLoader("harness", ctx),
	);
	registerNoArgumentCommand(
		"evolve-harness-status",
		"Show the latest harness run and its six-stage process position",
		(ctx) => showCodingStatus("harness", ctx),
	);
	registerNoArgumentCommand(
		"evolve-harness-resume",
		"Resume committed effects in the latest coding harness run",
		(ctx) => codingLoader("harness-resume", ctx),
	);

	pi.registerCommand("evolve-harness-retry", {
		description: "Explicitly retry the latest indeterminate harness model attempt",
		handler: async (args, ctx) => {
			if (!args.trim()) {
				ctx.ui.notify("/evolve-harness-retry requires an operator reason", "error");
				return;
			}
			await codingLoader("harness-retry", ctx, args);
		},
	});

	pi.registerCommand("evolve-code", {
		description: "Evolve solution commits for an approved coding task profile",
		handler: async (args, ctx) => {
			await codingLoader("solution", ctx, args);
		},
	});

	registerNoArgumentCommand("evolve-code-resume", "Resume committed effects in the latest coding solution run", (ctx) =>
		codingLoader("solution-resume", ctx),
	);

	pi.registerCommand("evolve-code-retry", {
		description: "Explicitly retry the latest indeterminate coding model attempt",
		handler: async (args, ctx) => {
			if (!args.trim()) {
				ctx.ui.notify("/evolve-code-retry requires an operator reason", "error");
				return;
			}
			await codingLoader("solution-retry", ctx, args);
		},
	});

	registerNoArgumentCommand(
		"evolve-code-status",
		"Show the latest solution run and its six-stage process position",
		(ctx) => showCodingStatus("solution", ctx),
	);
	registerNoArgumentCommand("evolve-code-verify", "Offline-verify the latest Agentvolve solution", (ctx) =>
		codingLoader("solution-verify", ctx),
	);

	pi.registerTool({
		name: "population_evolution",
		label: "Population Evolution",
		description: POPULATION_TOOL_DESCRIPTION,
		promptSnippet: "Run or verify the fixed isolated Population evolutionary harness",
		promptGuidelines: [POPULATION_TOOL_GUIDELINE],
		parameters: Type.Object({
			action: StringEnum(["run", "status", "verify"] as const),
		}),
		async execute(_toolCallId, params, signal, onUpdate, ctx) {
			onUpdate?.({
				content: [
					{
						type: "text",
						text:
							params.action === "run"
								? "Running the fixed isolated experiment; this may take several minutes…"
								: `Population evolution ${params.action}…`,
					},
				],
				details: { action: params.action },
			});
			const summary = await executePopulation(params.action, ctx, signal);
			pi.appendEntry("population-evolution-run", summary);
			return {
				content: [{ type: "text", text: humanSummary(summary) }],
				details: summary,
			};
		},
	});

	pi.registerTool({
		name: "darwinian_coding",
		label: "Agentvolve",
		description: CODING_TOOL_DESCRIPTION,
		promptSnippet: "Activate or operate independently evaluated Agentvolve coding evolution",
		promptGuidelines: [CODING_TOOL_GUIDELINE],
		parameters: Type.Object({
			action: StringEnum([
				"workflow_activate",
				"workflow_from_session",
				"workflow_start",
				"workflow_status",
				"workflow_history",
				"workflow_verify",
				"harness_run",
				"harness_status",
				"solution_run",
				"solution_status",
				"solution_verify",
			] as const),
		}),
		async execute(_toolCallId, params, signal, onUpdate, ctx) {
			onUpdate?.({
				content: [{ type: "text", text: `Agentvolve ${params.action}…` }],
				details: { action: params.action },
			});
			if (params.action === "workflow_activate") {
				await activateAgentvolveMode(ctx, signal, "routed");
				return {
					content: [
						{
							type: "text",
							text: "Agentvolve operator mode is active. Continue in normal conversation: describe a clear coding goal, ask clarifying questions when needed, then prepare or start the reviewed workflow. No task or worker was started by activation.",
						},
					],
					details: { active: true, model: activeModelLabel, status: "operator-mode" },
				};
			}
			if (params.action === "workflow_status") {
				const summary = await codingWorkflowStatus();
				if (!ACTIVE_WORKFLOW_STATUSES.has(summary.status)) {
					return {
						content: [
							{
								type: "text",
								text: "No Agentvolve workflow is currently queued or running. Describe a coding goal or start a reviewed task when ready; use workflow_history for prior runs.",
							},
						],
						details: { active: modeActive, status: "idle" },
					};
				}
				const progress = await operatorProgress();
				return {
					content: [
						{
							type: "text",
							text: operatorProgressSummary(progress),
						},
					],
					details: progress,
				};
			}
			if (params.action === "workflow_history") {
				const history = await operatorHistory();
				const lines = history.runs.slice(0, 20).map((run) => {
					const goal = run.goal?.replaceAll(/\s+/g, " ").slice(0, 160) ?? "goal unavailable";
					return `${run.stage === null ? "[?/6]" : `[${run.stage}/6]`} ${run.state} · ${run.name} · ${goal}`;
				});
				return {
					content: [
						{
							type: "text",
							text: lines.length > 0 ? lines.join("\n") : `No Agentvolve runs exist under ${history.runs_directory}.`,
						},
					],
					details: history,
				};
			}
			if (params.action === "workflow_from_session") {
				await activateAgentvolveMode(ctx, signal, "routed");
				const profile = await generateSessionTaskDraft(ctx, signal);
				if (!profile) {
					return {
						content: [{ type: "text", text: "Agentvolve task preparation was cancelled; no workflow started." }],
						details: { active: true, status: "cancelled" },
					};
				}
				if (!(await launchDetachedWorkflow(ctx, profile, false, signal))) {
					throw new Error("Agentvolve worker did not start");
				}
				const progress = await operatorProgress();
				return {
					content: [
						{
							type: "text",
							text: `The reviewed session task was registered and its detached Agentvolve worker started at ${progress.workflow_root}. Use /view-progress while continuing this Pi session.`,
						},
					],
					details: progress,
				};
			}
			if (params.action === "workflow_start") {
				const { goal, maxRounds } = workflowConfiguration;
				let profile: string;
				try {
					if (goal && maxRounds !== undefined) {
						const template = await chooseTaskProfile(ctx);
						profile = await deriveGoalTask(template, goal, maxRounds);
					} else {
						profile = await chooseTaskProfile(ctx);
					}
				} catch (error) {
					if (!(error instanceof AgentvolveInputRequired)) throw error;
					await activateAgentvolveMode(ctx, signal, "routed");
					return {
						content: [{ type: "text", text: error.message }],
						details: { active: true, status: "needs-task-clarification" },
					};
				}
				if (!(await launchDetachedWorkflow(ctx, profile, goal !== undefined && maxRounds !== undefined, signal))) {
					throw new Error("Agentvolve worker did not start");
				}
				const progress = await operatorProgress();
				return {
					content: [
						{
							type: "text",
							text: `Detached Agentvolve worker started at ${progress.workflow_root}. Use /view-progress while continuing this Pi session.`,
						},
					],
					details: progress,
				};
			}
			if (params.action === "workflow_verify") {
				if (!(await launchDetachedAction("verify", ctx, "", signal)))
					throw new Error("Agentvolve verification did not start");
				const progress = await operatorProgress();
				return {
					content: [{ type: "text", text: `Agentvolve offline verification queued for ${progress.workflow_root}.` }],
					details: progress,
				};
			}
			const action =
				params.action === "harness_run"
					? "harness"
					: params.action === "harness_status"
						? "harness-status"
						: params.action === "solution_run"
							? "solution"
							: params.action === "solution_status"
								? "solution-status"
								: "solution-verify";
			const summary = await executeCoding(action, ctx, "", signal);
			pi.appendEntry("darwinian-coding-run", summary);
			return {
				content: [{ type: "text", text: humanSummary(summary) }],
				details: summary,
			};
		},
	});

	pi.on("session_start", async (_event, ctx) => {
		modeActive = false;
		activeModelMode = undefined;
		activeModelLabel = undefined;
		workflowSummary = undefined;
		workflowConfiguration = {};
		configurationWorkflowRoot = undefined;
		reportedStages = new Set<string>();
		let restoredMode: AgentvolveModelMode | undefined;
		for (const entry of ctx.sessionManager.getBranch()) {
			if (entry.type !== "custom") continue;
			const data = entry.data;
			if (typeof data !== "object" || data === null || Array.isArray(data)) continue;
			const candidate = data as Record<string, unknown>;
			if (entry.customType === "agentvolve-workflow-configuration") {
				workflowConfiguration = {
					...(typeof candidate.goal === "string" ? { goal: candidate.goal } : {}),
					...(Number.isInteger(candidate.maxRounds) ? { maxRounds: candidate.maxRounds as number } : {}),
				};
				configurationWorkflowRoot = undefined;
			} else if (entry.customType === "agentvolve-mode") {
				restoredMode = candidate.active === true ? "routed" : undefined;
			} else if (entry.customType === "agentvolve-worker-launch") {
				if (
					candidate.consumesConfiguration === true &&
					workflowConfiguration.goal !== undefined &&
					workflowConfiguration.maxRounds !== undefined &&
					typeof candidate.workflow_root === "string"
				) {
					configurationWorkflowRoot = candidate.workflow_root;
				}
			} else if (entry.customType === "agentvolve-stage-report") {
				if (typeof candidate.workflowId === "string" && Number.isInteger(candidate.stage)) {
					reportedStages.add(`${candidate.workflowId}:${candidate.stage}`);
				}
			}
		}
		monitorFingerprint = undefined;
		stopWorkflowMonitor();
		if (restoredMode) {
			modeActive = true;
			activeModelMode = restoredMode;
			activeModelLabel = operatorModelLabel(ctx);
			setModeStatus(ctx, "ready", `operator · ${activeModelLabel}`);
			await startWorkflowMonitor(ctx);
		} else {
			setModeStatus(ctx, "available");
			ctx.ui.setWidget(WIDGET_KEY, undefined);
		}
		const configured = workflowConfiguration.goal && workflowConfiguration.maxRounds !== undefined;
		ctx.ui.notify(
			configured
				? `${MODE_NAME} goal and limit restored. Run /agentvolve to start the detached workflow.`
				: restoredMode
					? `${MODE_NAME} operator mode restored. Continue talking to Pi normally or use /view-progress.`
					: `${MODE_NAME} is available. Activate it and describe a coding goal normally, or use /goal and /limit before /agentvolve.`,
			"info",
		);
	});

	pi.on("model_select", async (_event, ctx) => {
		if (!modeActive) return;
		activeModelLabel = operatorModelLabel(ctx);
		renderModeWidget(ctx);
	});

	pi.on("thinking_level_select", async (_event, ctx) => {
		if (!modeActive) return;
		activeModelLabel = operatorModelLabel(ctx);
		renderModeWidget(ctx);
	});

	pi.on("session_shutdown", async () => {
		stopWorkflowMonitor();
	});

	pi.on("before_agent_start", async (event) => {
		if (!modeActive) return;
		const authorityPrompt = [
			`Agentvolve operator mode is active in this Pi session (${activeModelLabel}).`,
			"Continue the interaction as a normal conversation: help the user clarify a coding goal without requiring",
			"JSON or profile paths. Do not start work while the goal is unclear. Once the user explicitly asks Agentvolve",
			"to solve a clear session-described goal, use darwinian_coding workflow_from_session so direct operator review",
			"preserves the canonical task format. For an already configured or reviewed task use workflow_start.",
			"Pi remains the interactive operator. The evolution worker is a separate detached process,",
			"and its provider, model, reasoning level, and budgets stay bound to the canonical runtime manifest.",
			"Use workflow_status for conversational progress; the operator can also use /view-progress and /view-history.",
			"When the user explicitly asks for the reference assay, use population_evolution.",
			"Interactive /goal and /limit state may derive a task only from an already reviewed discovered contract.",
			"Fixed code owns mutation transport, independent evaluation, exact Population recurrence,",
			"protected final assays, Docker isolation, receipts, and sealing. Never replace these",
			"authorities with ordinary in-place edits or describe an unevaluated edit as evolved.",
		].join(" ");
		return {
			systemPrompt: `${event.systemPrompt}\n\n[${MODE_NAME.toUpperCase()}]\n${authorityPrompt}`,
		};
	});
}
