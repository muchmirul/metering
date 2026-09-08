import { existsSync } from "node:fs";
import { mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import { homedir, tmpdir } from "node:os";
import { basename, isAbsolute, join, resolve } from "node:path";
import { setTimeout as delay } from "node:timers/promises";

import { type Message, StringEnum, uuidv7 } from "@earendil-works/pi-ai";
import { BorderedLoader, type ExtensionAPI, type ExtensionContext, type SessionEntry } from "@earendil-works/pi-coding-agent";
import { Text } from "@earendil-works/pi-tui";
import { Type } from "typebox";

import { manageWorkflow, registryStatus } from "./agentvolve_recovery.ts";
import { openTraceViewer } from "./agentvolve_trace_viewer.ts";
import { showCandidateBrowser } from "./agentvolve_candidate_browser.ts";
import { showAgentvolveDashboard } from "./agentvolve_dashboard.ts";
import {
	boundedDiagnostic,
	codingWorkflowStatus,
	configuredRuntimeSelection,
	configuredTaskProfile,
	decodeCandidateReport,
	decodeOperatorTree,
	decodeOperatorHistory,
	decodeOperatorProgress,
	decodeOperatorTrace,
	decodeOutput,
	discoverTaskProfiles,
	latestSealedHarnessRoot,
	latestWorkerWorkflowRoot,
	llamaCppModelReady,
	llamaCppService,
	LOCAL_RUNTIME_TIMEOUT_MS,
	type ModeSummary,
	type OperatorHistoryView,
	type OperatorProgressView,
	type OperatorTraceView,
	PROCESS_LABELS,
	repositoryRoot,
	runsDirectory,
	runtimeManifest,
	type RuntimeSelection,
	tasksDirectory,
	WORKFLOW_MONITOR_INTERVAL_MS,
} from "./population_evolution_support.ts";

const STATUS_KEY = "population-evolution";
const WIDGET_KEY = "population-evolution";
const ACTIVE_WORKFLOW_STATUSES = new Set(["queued", "running"]);

interface WorkflowConfiguration {
	goal?: string;
	maxRounds?: number;
	repository?: string;
	managedWorkspace?: boolean;
	freshWorkspace?: boolean;
}

interface WorkerResponse {
	action: string;
	pid: number;
	state: string;
	worker_response_schema: "agentvolve-worker-response-v1";
	workflow_id: string;
	workflow_root: string;
}

interface DevelopmentReservation {
	max_wall_seconds: number;
	max_rounds: number;
	round_reservation_seconds: number;
	requested_rounds_seconds: number;
	funded_rounds_without_retries: number;
}

class AgentvolveInputRequired extends Error {}

const CODING_TOOL_DESCRIPTION = [
	"Activate Agentvolve, prepare an operator-reviewed coding goal, start its detached workflow, or inspect history,",
	"progress, and offline verification. Manage interrupted workflows through an operator-approved session dialog.",
	"Its action schema accepts no task text, command, evaluator, candidate, profile path, retry reason, or output path.",
	"A start requires a user-set generation limit and direct approval.",
].join(" ");
const CODING_TOOL_GUIDELINE = [
	"Use darwinian_coding workflow_activate for conversational activation; it starts no task.",
	"Use workflow_from_session only after the user explicitly asks Agentvolve to solve a clear coding goal in their",
	"messages; ask normal clarifying questions when needed. Use workflow_start for an already configured goal or",
	"reviewed task. Both work in casual Pi sessions without a repository path prompt: task review selects the",
	"current/remembered project or an automatically prepared private workspace. Organize messy user requests,",
	"state inferred assumptions, and ask only essential clarifications. Never invent user facts or solve by",
	"ordinary edits instead of Agentvolve. Pi's cwd is unchanged; shell cd does not change the session.",
	"Both require a user-set limit and direct task approval. Use workflow_status for the most recent run and",
	"workflow_history for prior runs. Use workflow_manage when the user asks to resume, retry, stop, or close an",
	"unfinished workflow; fixed dialogs select the run and collect direct approval and any operator reason.",
	"Never auto-retry, delete evidence, or switch run directories to bypass interrupted work.",
	"The only Agentvolve slash commands are /goal, /limit, /history, and /progress.",
	"Never replace Agentvolve's immutable candidates and independent assays with ordinary in-place edits.",
].join(" ");

const SESSION_TASK_SYSTEM_PROMPT = `You create an Agentvolve task draft from user messages and a Git file list.
Return exactly one JSON object and no markdown. Never include or infer a solution. Use the current explicit goal, or the most recent clear coding goal in the supplied user messages. Setup and Agentvolve-interface discussion are context, not a task.
Accept casual, messy, misspelled requests. Organize them into concise requirements, preserve the user's intent, and fill routine implementation defaults as explicit assumptions. Never fabricate user facts, supplied data, credentials, or permissions. Ask a concise question only if essential task meaning, input data, or independently checkable success criteria are missing; do not ask for a repository path or require formal task wording.
The object must have exactly these fields:
- draft_schema: "agentvolve-session-task-draft-v1"
- schema_version: 1
- name: a short lowercase-hyphenated name
- repository_path: the supplied absolute repository path
- goal: a self-contained task description without a solution
- requirements: an array of concise requirement statements (at most 32, 1000 characters each)
- assumptions: an array of explicit inferred defaults (same bounds; empty if none)
- entrypoint: one relative POSIX file path that must still exist after mutation
- allowed_paths: sorted unique relative POSIX paths the candidate may change
- development_checks: one or more objects with argv (a shell-free string array), case_id, and timeout_ms; prefer check_schema: "stdout-json-v1" with expected_stdout when actual answer values can be checked externally
- limits: max_proposal_calls and max_rounds equal to the supplied generation limit; max_wall_seconds a finite positive integer for direct operator review
- stopping: {"minimum_replicates":1,"type":"all-development-cases-pass-v1"}
- final_policy: "replay-development-checks-v1"
For an existing repository, entrypoint and allowed_paths must come from the supplied Git list and checks must already exist; never invent files or claim repository-wide tests cover a new goal without evidence.
For a NEW managed workspace, no project setup is required from the user. Choose at most 64 safe output FILE paths (not directory prefixes), include entrypoint in allowed_paths, and never use TASK.md or its descendants. Fixed code will create only empty starter files plus TASK.md containing this reviewed request, requirements, and assumptions. Define goal-specific, self-contained check argv for operator review (for example python -c importing the future solution). Do not refer to nonexistent test files, install dependencies, embed a solution, or use unconditional success / existence-only checks as a substitute for requested behavior. Prefer Python standard library or self-contained text/HTML when the request leaves technology open. Checks execute only in the reviewed sandbox after approval, never on the host. The proposed checks are not proof of completion or hidden coverage.
If essential information is insufficient, return {"clarification":"one concise question for the user"} instead of a task draft. Fixed code will calculate the timeout reservation and ask the operator to correct an insufficient wall budget before registration.`;

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
	return entries.flatMap((entry) => {
		if (entry.type !== "message" || entry.message.role !== "user") return [];
		const text = contentText(entry.message.content).join("\n").trim();
		return text ? [`User: ${text}`] : [];
	}).join("\n\n").slice(-32_000);
}

function responseText(response: { content: Array<{ type: string; text?: string }> }): string {
	return response.content.flatMap((part) => part.type === "text" && typeof part.text === "string" ? [part.text] : []).join("\n").trim();
}

function reviewObject(value: unknown, location: string): Record<string, unknown> {
	if (typeof value !== "object" || value === null || Array.isArray(value)) throw new Error(`${location} must be an object`);
	return value as Record<string, unknown>;
}

function unquoteArgument(value: string): string {
	const text = value.trim();
	if (text.length >= 2 && ((text.startsWith('"') && text.endsWith('"')) || (text.startsWith("'") && text.endsWith("'")))) {
		return text.slice(1, -1).trim();
	}
	return text;
}

function generationLimit(value: string): number {
	const match = /^(\d+)(?:\s+generations?)?$/i.exec(unquoteArgument(value));
	const limit = match ? Number(match[1]) : Number.NaN;
	if (!Number.isInteger(limit) || limit < 1 || limit > 256) {
		throw new AgentvolveInputRequired("Use a generation limit from 1 through 256, for example /limit 10.");
	}
	return limit;
}

function taskBrief(document: Record<string, unknown>): string[] {
	return ["requirements", "assumptions"].flatMap((key) => {
		const items = document[key] ?? [];
		if (!Array.isArray(items) || items.length > 32 || items.some((item) => typeof item !== "string" || !item.trim() || item.length > 1000 || item.includes("\0"))) throw new Error(`Task ${key} must contain at most 32 bounded, non-empty statements.`);
		return items.length ? [`\n${key === "requirements" ? "Requirements" : "Inferred assumptions (review these)"}:`, ...items.map((item) => `  - ${item}`)] : [];
	});
}

function taskReview(document: Record<string, unknown>, draft: boolean, budget: DevelopmentReservation, baseCommit?: string): string {
	const repository = draft ? {
		path: document.repository_path,
		entrypoint: document.entrypoint,
		base_commit: baseCommit,
	} : reviewObject(document.repository, "repository");
	const checks = document.development_checks;
	if (!Array.isArray(checks) || !checks.length) throw new Error("At least one development check is required.");
	const limits = reviewObject(document.limits, "limits");
	const paths = document.allowed_paths;
	if (!Array.isArray(paths) || !paths.length) throw new Error("At least one writable path is required.");
	const lines = [
		`Goal: ${JSON.stringify(document.goal)}`,
		...taskBrief(document),
		`\nRepository: ${JSON.stringify(repository.path)}`,
		`Base commit: ${repository.base_commit === undefined ? "new empty seed, created only after approval" : JSON.stringify(repository.base_commit)}`,
		...(repository.base_commit === undefined ? ["A private Git workspace will be prepared automatically. TASK.md will preserve the reviewed request and brief; output files start empty. Nothing is implemented during setup."] : []),
		`Entrypoint: ${JSON.stringify(repository.entrypoint)}`,
		"Writable paths:",
		...paths.map((path) => `  - ${JSON.stringify(path)}`),
		"Development checks (the operator must confirm these actually test the goal):",
		...checks.map((value) => {
			const check = reviewObject(value, "development check");
			return `  - ${JSON.stringify(check.case_id)}: ${JSON.stringify(check.argv)} (${JSON.stringify(check.timeout_ms)} ms)` +
				`\n    Output contract: ${JSON.stringify(check.check_schema ?? "exit-status-only")}` +
				(check.expected_stdout === undefined ? "" : `\n    Expected stdout: ${JSON.stringify(check.expected_stdout)}`);
		}),
		`Limits: ${limits.max_rounds} generations, ${limits.max_proposal_calls} proposal calls, ${limits.max_wall_seconds} development timeout-reservation seconds`,
		`Reservation: ${budget.round_reservation_seconds} seconds per generation; ${budget.requested_rounds_seconds} for the generation cap without retries.`,
		`This budget can fund at most ${budget.funded_rounds_without_retries} of ${budget.max_rounds} generations without retries. The cap is not a promise to execute every generation.`,
		"Reservations are not elapsed runtime or a total-workflow deadline; harness work, protected-final work and retry needs are not covered by this per-generation estimate.",
		`Stopping: ${JSON.stringify(document.stopping ?? "numeric-limit-only")}`,
		draft
			? "Final policy: replay-development-checks-v1. The protected final repeats these checks and adds no hidden coverage."
			: `Protected final binding (contents not disclosed): ${JSON.stringify(document.final_assay)}`,
		...(draft ? [] : [
			`Allocation draws: ${JSON.stringify(document.allocation_draws)}`,
			`Final draw: ${JSON.stringify(document.final_draw)}`,
		]),
		"The detached worker uses the reviewed runtime manifest. No selected patch is applied automatically.",
	];
	const summary = lines.join("\n");
	if (summary.length > 32_000) throw new Error("Task review exceeds the in-session display bound; narrow the task.");
	return summary;
}

function operatorModelLabel(ctx: ExtensionContext): string {
	return ctx.model ? `${ctx.model.provider}/${ctx.model.id} · ${ctx.thinkingLevel}` : "no operator model selected";
}

function operatorProgressSummary(progress: OperatorProgressView): string {
	const lines = [`${progress.stage_label} · ${progress.state}`, progress.activity, `workflow: ${progress.workflow_root}`];
	if (progress.task) lines.push(`goal: ${progress.task.goal}`);
	for (const stage of progress.stages) lines.push(`[${stage.number}/6] ${stage.status}: ${stage.summary}`);
	if (progress.evolution) {
		lines.push(`evolution: ${progress.evolution.completed_rounds}/${progress.evolution.max_rounds ?? "?"} generations · ${progress.evolution.proposal_calls} proposal calls`);
	}
	if (progress.result) {
		lines.push(`selected commit: ${progress.result.selected_commit ?? "unavailable"}`);
		lines.push(`protected final: ${progress.result.final_passed ?? "?"}/${progress.result.final_tasks ?? "?"}`);
		lines.push(`patch: ${progress.result.patch_path ?? "unavailable"}`);
	}
	if (progress.error) lines.push(`error: ${progress.error}`);
	lines.push(...progress.warnings.map((warning) => `warning: ${warning}`));
	return lines.join("\n");
}

function decodeWorkerResponse(value: Record<string, unknown>): WorkerResponse {
	if (value.worker_response_schema !== "agentvolve-worker-response-v1" ||
		typeof value.action !== "string" || typeof value.pid !== "number" || typeof value.state !== "string" ||
		typeof value.workflow_id !== "string" || typeof value.workflow_root !== "string") {
		throw new Error("Agentvolve worker returned an unexpected response");
	}
	return value as unknown as WorkerResponse;
}

export default function populationEvolutionExtension(pi: ExtensionAPI): void {
	let modeActive = false;
	let activeModelLabel: string | undefined;
	let workflowConfiguration: WorkflowConfiguration = {};
	let preparing = false;
	let operationController: AbortController | undefined;
	let monitor: ReturnType<typeof setInterval> | undefined;
	let monitorRefreshing = false;
	let monitorEpoch = 0;
	let monitoredWorkflowRoot: string | undefined;
	let reportedStages = new Set<string>();

	function persistWorkflowConfiguration(next: WorkflowConfiguration): void {
		workflowConfiguration = next;
		pi.appendEntry("agentvolve-workflow-configuration", next);
	}

	function renderModeWidget(ctx: ExtensionContext, summary?: ModeSummary): void {
		const active = modeActive && summary && ACTIVE_WORKFLOW_STATUSES.has(summary.status);
		ctx.ui.setStatus(STATUS_KEY, ctx.ui.theme.fg(active ? "warning" : "accent",
			`agentvolve: ${active ? summary.process : modeActive ? `operator · ${activeModelLabel}` : "available"}`));
		if (!active) {
			ctx.ui.setWidget(WIDGET_KEY, undefined);
			return;
		}
		const current = Number(summary.process?.match(/^\[(\d+)\/6\]/)?.[1]);
		const lines = [ctx.ui.theme.fg("accent", "🧬 Agentvolve"), `operator: ${activeModelLabel}`];
		for (let stage = 1; stage <= 6; stage += 1) {
			const marker = stage < current ? "✓" : stage === current ? "▶" : "○";
			lines.push(ctx.ui.theme.fg(stage === current ? "warning" : "dim", `${marker} [${stage}/6] ${PROCESS_LABELS[stage]}`));
		}
		lines.push(`${summary.status} · ${summary.runRoot}`);
		ctx.ui.setWidget(WIDGET_KEY, lines, { placement: "belowEditor" });
	}

	async function operatorProgress(selector = ""): Promise<OperatorProgressView> {
		const result = await pi.exec("uv", ["run", "python", "-m", "apps.coding_agent.operator_view", "progress", runsDirectory(),
			...(selector ? [selector] : [])], { cwd: repositoryRoot(), timeout: 15_000 });
		return decodeOperatorProgress(decodeOutput(result));
	}

	async function operatorHistory(offset = 0): Promise<OperatorHistoryView> {
		const result = await pi.exec("uv", ["run", "python", "-m", "apps.coding_agent.operator_view", "history", runsDirectory(), String(offset)],
			{ cwd: repositoryRoot(), timeout: 15_000 });
		return decodeOperatorHistory(decodeOutput(result));
	}

	async function operatorTrace(selector: string, offset = 0): Promise<OperatorTraceView> {
		const result = await pi.exec("uv", ["run", "python", "-m", "apps.coding_agent.operator_view", "trace", runsDirectory(), selector, String(offset)],
			{ cwd: repositoryRoot(), timeout: 15_000 });
		return decodeOperatorTrace(decodeOutput(result));
	}

	async function refreshWorkflowMonitor(ctx: ExtensionContext): Promise<void> {
		if (!modeActive || monitorRefreshing) return;
		const epoch = monitorEpoch;
		monitorRefreshing = true;
		try {
			const summary = await codingWorkflowStatus();
			if (!modeActive || epoch !== monitorEpoch) return;
			renderModeWidget(ctx, summary);
			const active = ACTIVE_WORKFLOW_STATUSES.has(summary.status);
			if (active) monitoredWorkflowRoot = summary.runRoot;
			if (monitoredWorkflowRoot !== summary.runRoot) return;
			const progress = await operatorProgress(summary.runRoot);
			if (!modeActive || epoch !== monitorEpoch) return;
			for (const stage of progress.stages) {
				if (!["complete", "reused"].includes(stage.status)) continue;
				const key = `${progress.workflow_id}:${stage.number}`;
				if (reportedStages.has(key)) continue;
				reportedStages.add(key);
				pi.appendEntry("agentvolve-stage-report", { ...stage, workflowId: progress.workflow_id, stage: stage.number });
				if (stage.number === 6) ctx.ui.notify(`Agentvolve finished: ${stage.summary}`, "info");
			}
			if (!active) monitoredWorkflowRoot = undefined;
		} catch {
			if (epoch === monitorEpoch) renderModeWidget(ctx);
		} finally {
			if (epoch === monitorEpoch) monitorRefreshing = false;
		}
	}

	function stopWorkflowMonitor(): void {
		if (monitor) clearInterval(monitor);
		monitor = undefined;
		monitorEpoch += 1;
		monitorRefreshing = false;
		monitoredWorkflowRoot = undefined;
	}

	async function startWorkflowMonitor(ctx: ExtensionContext): Promise<void> {
		stopWorkflowMonitor();
		const epoch = monitorEpoch;
		await refreshWorkflowMonitor(ctx);
		if (epoch !== monitorEpoch) return;
		monitor = setInterval(() => void refreshWorkflowMonitor(ctx), WORKFLOW_MONITOR_INTERVAL_MS);
	}

	async function activateAgentvolveMode(ctx: ExtensionContext): Promise<void> {
		const wasActive = modeActive;
		modeActive = true;
		activeModelLabel = operatorModelLabel(ctx);
		if (!wasActive) pi.appendEntry("agentvolve-mode", { active: true, modelMode: "routed" });
		await startWorkflowMonitor(ctx);
	}

	async function ensureLocalRuntime(selection: RuntimeSelection, signal?: AbortSignal): Promise<void> {
		if (selection.provider !== "llamacpp" || await llamaCppModelReady(selection, signal)) return;
		const service = llamaCppService();
		const restart = await pi.exec("systemctl", ["--user", "restart", service], { signal, timeout: 30_000 });
		if (restart.killed || restart.code !== 0) throw new Error(boundedDiagnostic(restart.stderr || restart.stdout) || `cannot start ${service}`);
		const deadline = Date.now() + LOCAL_RUNTIME_TIMEOUT_MS;
		while (Date.now() < deadline) {
			signal?.throwIfAborted();
			if (await llamaCppModelReady(selection, signal)) return;
			await delay(1000, undefined, { signal });
		}
		throw new Error(`${selection.provider}/${selection.model} did not become ready through ${service}`);
	}

	async function selectedHarnessDescriptor(): Promise<string | undefined> {
		const supplied = process.env.METERING_EVOLUTION_HARNESS_DESCRIPTOR?.trim();
		if (supplied) {
			if (!isAbsolute(supplied) || !existsSync(supplied)) throw new Error("configured harness descriptor must be an existing absolute path");
			return supplied;
		}
		const root = await latestSealedHarnessRoot();
		return root ? join(root, "selected-harness.json") : undefined;
	}

	async function prepareRuntime(manifest: string, signal?: AbortSignal): Promise<void> {
		signal?.throwIfAborted();
		const preflight = await pi.exec("uv", ["run", "python", "-m", "connectors.fixed.pi.runtime", "check", manifest],
			{ cwd: repositoryRoot(), signal, timeout: 30_000 });
		decodeOutput(preflight);
		await ensureLocalRuntime(await configuredRuntimeSelection(manifest), signal);
	}

	async function launchDetachedWorkflow(ctx: ExtensionContext, profile: string, signal: AbortSignal): Promise<WorkerResponse> {
		await prepareRuntime(runtimeManifest(), signal);
		const harness = await selectedHarnessDescriptor();
		const result = await pi.exec("uv", ["run", "python", "-m", "connectors.fixed.pi.runtime", "start", runsDirectory(),
			configuredTaskProfile(profile), runtimeManifest(), ...(harness ? [harness] : [])],
			{ cwd: repositoryRoot(), signal, timeout: 30_000 });
		const worker = decodeWorkerResponse(decodeOutput(result));
		pi.appendEntry("agentvolve-worker-launch", worker);
		persistWorkflowConfiguration({ maxRounds: workflowConfiguration.maxRounds,
			...(!workflowConfiguration.managedWorkspace && workflowConfiguration.repository ? { repository: workflowConfiguration.repository } : {}) });
		await startWorkflowMonitor(ctx);
		ctx.ui.notify(`Agentvolve worker started separately.\nworkflow: ${worker.workflow_root}\nUse /progress or /history while continuing this Pi session.`, "info");
		return worker;
	}

	async function requireLimit(ctx: ExtensionContext, signal: AbortSignal): Promise<number> {
		if (workflowConfiguration.maxRounds !== undefined) return workflowConfiguration.maxRounds;
		const value = await ctx.ui.input("Agentvolve needs a generation limit before preparing this task", "1–256 generations", { signal });
		if (value === undefined) throw new AgentvolveInputRequired("No limit was set; nothing started. Set /limit and submit /goal again.");
		const maxRounds = generationLimit(value);
		persistWorkflowConfiguration({ ...workflowConfiguration, maxRounds });
		return maxRounds;
	}

	async function chooseRepository(ctx: ExtensionContext, signal: AbortSignal, manual = false): Promise<string | undefined> {
		if (workflowConfiguration.freshWorkspace && !manual) return undefined;
		const current = await pi.exec("git", ["-C", ctx.cwd, "rev-parse", "--show-toplevel"], { signal, timeout: 10_000 });
		signal.throwIfAborted();
		if (current.killed) throw new AgentvolveInputRequired(`Git discovery timed out in ${JSON.stringify(ctx.cwd)}; no workflow started.`);
		let configuredRepository: string | undefined;
		const configured = process.env.METERING_EVOLUTION_TASK_PROFILE?.trim();
		if (configured) {
			const document = reviewObject(JSON.parse(await readFile(configuredTaskProfile(configured), "utf8")), "configured task");
			const target = reviewObject(document.repository, "configured repository");
			if (typeof target.path !== "string" || !isAbsolute(target.path)) throw new AgentvolveInputRequired("The configured task needs an absolute repository path.");
			configuredRepository = target.path;
		}
		const repositories = [...new Set([
			...(workflowConfiguration.repository ? [workflowConfiguration.repository] : []),
			...(configuredRepository ? [configuredRepository] : []),
			...(current.code === 0 ? [resolve(current.stdout.trim())] : []),
		])];
		// The normal flow has no setup dialog: the full task review approves this target.
		let directory = repositories[0];
		if (manual) {
			const labels = repositories.map((path) => `Use ${JSON.stringify(path)}`);
			const selected = await ctx.ui.select("Change task destination (optional)",
				[...labels, "Create a private workspace", "Enter another repository path"], { signal });
			if (!selected) throw new AgentvolveInputRequired("Destination unchanged; no workflow started.");
			if (selected === "Create a private workspace") {
				persistWorkflowConfiguration({ goal: workflowConfiguration.goal, maxRounds: workflowConfiguration.maxRounds, freshWorkspace: true });
				return undefined;
			}
			directory = repositories[labels.indexOf(selected)];
			if (!directory) {
				const value = await ctx.ui.input("Optional existing repository path", `Absolute, ~/path, or relative to ${ctx.cwd}`, { signal });
				if (value === undefined) throw new AgentvolveInputRequired("Destination unchanged; no workflow started.");
				const path = unquoteArgument(value);
				if (!path || path.includes("\0")) throw new AgentvolveInputRequired("Enter a non-empty repository path; no workflow started.");
				directory = path === "~" ? homedir() : path.startsWith("~/") ? resolve(homedir(), path.slice(2)) : resolve(ctx.cwd, path);
			}
		}
		if (!directory) return undefined;
		const result = await pi.exec("git", ["-C", directory, "rev-parse", "--show-toplevel"], { signal, timeout: 10_000 });
		signal.throwIfAborted();
		if (result.killed || result.code !== 0) {
			throw new AgentvolveInputRequired(`Cannot open Git repository at ${JSON.stringify(directory)}: ${result.killed ? "Git timed out" : boundedDiagnostic(result.stderr || result.stdout)}. Submit /goal again to choose a repository.`);
		}
		const repository = resolve(result.stdout.trim());
		const status = await pi.exec("git", ["-C", repository, "status", "--porcelain"], { signal, timeout: 10_000 });
		signal.throwIfAborted();
		if (status.killed || status.code !== 0) throw new AgentvolveInputRequired(`Cannot check Git status in ${JSON.stringify(repository)}: ${status.killed ? "Git timed out" : boundedDiagnostic(status.stderr || status.stdout)}`);
		if (status.stdout.trim()) throw new AgentvolveInputRequired(`Repository ${JSON.stringify(repository)} has uncommitted changes (including untracked files). Commit or stash them yourself, or choose another repository with /goal. Nothing was changed or started.`);
		const head = await pi.exec("git", ["-C", repository, "rev-parse", "HEAD^{commit}"], { signal, timeout: 10_000 });
		signal.throwIfAborted();
		if (head.killed || head.code !== 0 || !/^[0-9a-f]{40}$/.test(head.stdout.trim())) throw new AgentvolveInputRequired(`Repository ${JSON.stringify(repository)} needs a readable committed HEAD before Agentvolve can bind a task. No workflow started.`);
		if (manual) persistWorkflowConfiguration({ goal: workflowConfiguration.goal, maxRounds: workflowConfiguration.maxRounds, repository });
		return repository;
	}

	async function chooseTaskProfile(ctx: ExtensionContext, repository: string, signal: AbortSignal): Promise<string | undefined> {
		const configured = process.env.METERING_EVOLUTION_TASK_PROFILE?.trim();
		if (configured) {
			const path = configuredTaskProfile(configured);
			const document = reviewObject(JSON.parse(await readFile(path, "utf8")), "configured task");
			const target = reviewObject(document.repository, "configured repository");
			if (typeof target.path !== "string" || resolve(target.path) !== repository) {
				throw new AgentvolveInputRequired("The configured task belongs to another repository; select its target repository with /goal or correct METERING_EVOLUTION_TASK_PROFILE first.");
			}
			return path;
		}
		const matching = (await discoverTaskProfiles()).filter((profile) => resolve(profile.repository) === repository);
		if (!matching.length) return undefined;
		const draftLabel = "Prepare a new task from this goal";
		const labels = matching.map((profile, index) => `${index + 1}. ${profile.name} · ${profile.goal.replaceAll(/\s+/g, " ").slice(0, 160)}`);
		// Selection is explicit: even a single unrelated registered contract must not silently define this goal's checks.
		const selected = await ctx.ui.select("Use a reviewed task contract or prepare a new one", [...labels, draftLabel], { signal });
		if (!selected) throw new AgentvolveInputRequired("Task selection cancelled; no workflow started.");
		if (selected === draftLabel) return undefined;
		const profile = matching[labels.indexOf(selected)];
		if (!profile) throw new Error("Task selection did not resolve");
		return profile.path;
	}

	async function reviewDevelopmentBudget(ctx: ExtensionContext, document: Record<string, unknown>, maxRounds: number, signal: AbortSignal): Promise<DevelopmentReservation> {
		if (!Array.isArray(document.development_checks)) throw new Error("Development checks must be an array.");
		const timeouts = document.development_checks.map((check) => reviewObject(check, "development check").timeout_ms);
		let maxWallSeconds = reviewObject(document.limits, "limits").max_wall_seconds;
		const temporary = await mkdtemp(join(tmpdir(), "agentvolve-budget-"));
		try {
			const path = join(temporary, "budget.json");
			for (;;) {
				signal.throwIfAborted();
				await writeFile(path, JSON.stringify({ check_timeouts_ms: timeouts, max_rounds: maxRounds, max_wall_seconds: maxWallSeconds }) + "\n", "utf8");
				const result = decodeOutput(await pi.exec("uv", ["run", "python", "-m", "apps.coding_agent.task_profile_tool", "budget", path],
					{ cwd: repositoryRoot(), signal, timeout: 30_000 }));
				if (result.reservation_schema !== "agentvolve-development-reservation-v1" || result.authority !== "diagnostic-only" ||
					result.max_rounds !== maxRounds || result.max_wall_seconds !== maxWallSeconds ||
					!["controller_timeout_seconds", "evidence_timeout_seconds", "round_reservation_seconds", "requested_rounds_seconds", "funded_rounds_without_retries"].every((key) => Number.isSafeInteger(result[key]) && (result[key] as number) >= 0)) throw new Error("Unexpected development reservation response.");
				const budget = result as unknown as DevelopmentReservation;
				if (budget.round_reservation_seconds <= 0 || budget.requested_rounds_seconds !== budget.round_reservation_seconds * maxRounds ||
					budget.funded_rounds_without_retries !== Math.min(maxRounds, Math.floor(budget.max_wall_seconds / budget.round_reservation_seconds))) throw new Error("Inconsistent development reservation response.");
				if (budget.funded_rounds_without_retries > 0) return budget;
				const value = await ctx.ui.input(
					`Agentvolve budget cannot fund one generation: ${maxWallSeconds} seconds configured; at least ${budget.round_reservation_seconds} required (${budget.requested_rounds_seconds} for ${maxRounds} generations without retries).`,
					"Enter an approved development reservation budget in seconds, or cancel", { signal });
				if (value === undefined) throw new AgentvolveInputRequired("Budget review cancelled; no task registered or worker started. Existing profiles and run limits are unchanged.");
				const chosen = /^\d+$/.test(value.trim()) ? Number(value.trim()) : Number.NaN;
				if (!Number.isSafeInteger(chosen) || chosen < budget.round_reservation_seconds || chosen > 1_000_000_000) {
					ctx.ui.notify(`Enter integer seconds from ${budget.round_reservation_seconds} through 1000000000, or cancel. No budget was changed.`, "warning");
					continue;
				}
				maxWallSeconds = chosen;
			}
		} finally {
			await rm(temporary, { recursive: true, force: true });
		}
	}

	async function deriveGoalTask(template: string, goal: string, maxRounds: number, maxWallSeconds: number, signal: AbortSignal): Promise<string> {
		const temporary = await mkdtemp(join(tmpdir(), "agentvolve-goal-"));
		try {
			const goalPath = join(temporary, "goal.txt");
			await writeFile(goalPath, goal, "utf8");
			const output = join(tasksDirectory(), "generated");
			const command = await pi.exec("uv", ["run", "python", "-m", "apps.coding_agent.task_profile_tool", "derive", template, goalPath, String(maxRounds), output, String(maxWallSeconds)],
				{ cwd: repositoryRoot(), signal, timeout: 30_000 });
			const registration = decodeOutput(command);
			if (registration.registration_schema !== "agentvolve-task-derivation-v1" || typeof registration.profile !== "string") throw new Error("Task derivation returned an unexpected result");
			return registration.profile;
		} finally {
			await rm(temporary, { recursive: true, force: true });
		}
	}

	async function generateSessionTaskDraft(ctx: ExtensionContext, repository: string, goal: string | undefined, maxRounds: number, signal: AbortSignal, newWorkspace = false): Promise<string | null> {
		if (!ctx.model) throw new AgentvolveInputRequired("Select a Pi model before preparing a new task.");
		const conversation = sessionUserConversation(ctx.sessionManager.getBranch());
		if (!goal && !conversation) throw new AgentvolveInputRequired("Describe a coding problem with /goal first.");
		let baseCommit: string | undefined;
		let files: string[] = [];
		if (!newWorkspace) {
			const head = await pi.exec("git", ["-C", repository, "rev-parse", "HEAD^{commit}"], { signal, timeout: 10_000 });
			if (head.killed || head.code !== 0 || !/^[0-9a-f]{40}$/.test(head.stdout.trim())) throw new Error("Cannot bind the reviewed Git commit.");
			baseCommit = head.stdout.trim();
			const result = await pi.exec("git", ["-C", repository, "ls-tree", "-rz", "--name-only", baseCommit], { signal, timeout: 10_000 });
			if (result.killed || result.code !== 0) throw new Error(boundedDiagnostic(result.stderr || result.stdout));
			files = result.stdout.split("\0").filter(Boolean).slice(0, 2_000);
			if (!files.length) throw new AgentvolveInputRequired("The current Git commit has no tracked files.");
		}
		const prompt = [
			`Repository: ${repository}`, `Workspace mode: ${newWorkspace ? "NEW managed workspace; created only after approval" : "existing repository"}`,
			`Generation limit: ${maxRounds}`, "Tracked files:", JSON.stringify(files),
			"User messages from the active branch (assistant and tool output excluded):", conversation,
			...(goal ? ["Current /goal, supplied directly by the user:", goal] : []),
		].join("\n");
		const message: Message = { role: "user", content: [{ type: "text", text: prompt }], timestamp: Date.now() };
		const model = ctx.model;
		const complete = async (completionSignal: AbortSignal): Promise<string> => {
			const response = await ctx.modelRegistry.complete(model, { systemPrompt: SESSION_TASK_SYSTEM_PROMPT, messages: [message] },
				{ signal: completionSignal, cacheRetention: "none", sessionId: uuidv7() });
			completionSignal.throwIfAborted();
			if (["aborted", "error", "length"].includes(response.stopReason)) throw new Error(`Task drafting did not finish: ${response.stopReason}`);
			return responseText(response);
		};
		let generated: string;
		if (ctx.mode === "tui") {
			const output = await ctx.ui.custom<{ text?: string; error?: string } | null>((tui, theme, _keys, done) => {
				const loader = new BorderedLoader(tui, theme, "Preparing the Agentvolve task for your review…");
				loader.onAbort = () => done(null);
				complete(AbortSignal.any([signal, loader.signal])).then((text) => done({ text })).catch((error) => done({ error: String(error) }));
				return loader;
			});
			if (!output) return null;
			if (output.error) throw new Error(output.error);
			generated = output.text ?? "";
		} else generated = await complete(signal);

		let reviewed: string;
		for (;;) {
			signal.throwIfAborted();
			const document = reviewObject(JSON.parse(generated), "task draft");
			if (typeof document.clarification === "string") throw new AgentvolveInputRequired(document.clarification);
			if (document.draft_schema !== "agentvolve-session-task-draft-v1" || document.schema_version !== 1 || document.final_policy !== "replay-development-checks-v1") throw new Error("Task draft has an unsupported schema or final policy.");
			// These values belong to the user, not the drafting model or advanced editor.
			document.repository_path = repository;
			if (goal) document.goal = goal;
			document.requirements ??= [document.goal];
			document.assumptions ??= [];
			taskBrief(document);
			const limits = reviewObject(document.limits, "limits");
			limits.max_rounds = maxRounds;
			limits.max_proposal_calls = maxRounds;
			const budget = await reviewDevelopmentBudget(ctx, document, maxRounds, signal);
			limits.max_wall_seconds = budget.max_wall_seconds;
			reviewed = JSON.stringify(document, null, 2);
			if (await ctx.ui.confirm("Register and run this reviewed task?", taskReview(document, true, budget, baseCommit), { signal })) break;
			const action = await ctx.ui.select("Task not approved", ["Change destination (optional)", "Edit task details (advanced JSON)", "Cancel without starting"], { signal });
			if (action === "Change destination (optional)") {
				await chooseRepository(ctx, signal, true);
				throw new AgentvolveInputRequired("Destination updated. Submit /goal or ask Agentvolve again to prepare the task; no workflow started.");
			}
			if (action !== "Edit task details (advanced JSON)") return null;
			const edited = await ctx.ui.editor("Edit Agentvolve task details (goal and generation limit stay user-bound)", reviewed);
			if (edited === undefined) return null;
			generated = edited;
		}
		signal.throwIfAborted();
		const temporary = await mkdtemp(join(tmpdir(), "agentvolve-session-task-"));
		try {
			const draftPath = join(temporary, "draft.json");
			const document = JSON.parse(reviewed);
			pi.appendEntry("agentvolve-task-brief", { goal: document.goal, repository, requirements: document.requirements, assumptions: document.assumptions });
			if (!newWorkspace) { delete document.requirements; delete document.assumptions; }
			await writeFile(draftPath, `${JSON.stringify(document)}\n`, "utf8");
			persistWorkflowConfiguration({ ...workflowConfiguration, repository, managedWorkspace: newWorkspace || workflowConfiguration.managedWorkspace, freshWorkspace: false });
			const command = await pi.exec("uv", ["run", "python", "-m", "apps.coding_agent.task_profile_tool", newWorkspace ? "workspace" : "create", draftPath, tasksDirectory()],
				{ cwd: repositoryRoot(), signal, timeout: 30_000 });
			const registration = decodeOutput(command);
			if (registration.registration_schema !== "agentvolve-task-registration-v1" || typeof registration.profile !== "string") throw new Error("Task registration returned an unexpected result");
			if (!newWorkspace && registration.base_commit !== baseCommit) throw new AgentvolveInputRequired("Repository HEAD changed during task review; no worker started. Submit /goal again.");
			pi.appendEntry("agentvolve-task-registration", { ...registration, sessionId: ctx.sessionManager.getSessionId() });
			return registration.profile;
		} finally {
			await rm(temporary, { recursive: true, force: true });
		}
	}

	async function solveGoal(ctx: ExtensionContext, goal: string | undefined, fromSession: boolean, signal?: AbortSignal): Promise<WorkerResponse | null> {
		if (!ctx.hasUI) throw new AgentvolveInputRequired("Task approval requires interactive or RPC Pi.");
		if (preparing) throw new AgentvolveInputRequired("Another task is being prepared; finish or cancel its review first.");
		preparing = true;
		operationController = new AbortController();
		const operationSignal = signal ? AbortSignal.any([signal, operationController.signal]) : operationController.signal;
		try {
			await activateAgentvolveMode(ctx);
			if (goal) persistWorkflowConfiguration({ ...workflowConfiguration, goal });
			const maxRounds = await requireLimit(ctx, operationSignal);
			let registry = await registryStatus(pi, operationSignal);
			while (registry.blocker) {
				const outcome = await manageWorkflow(pi, ctx, prepareRuntime, registry.blocker.workflow_root, operationSignal);
				ctx.ui.notify(outcome.message, "info");
				await refreshWorkflowMonitor(ctx);
				if (outcome.status !== "closed-incomplete") throw new AgentvolveInputRequired("No new task started. Your goal remains pending while the existing workflow is managed; ask again when ready.");
				registry = await registryStatus(pi, operationSignal);
			}
			if (registry.legacy_unfinished_count) ctx.ui.notify(`${registry.legacy_unfinished_count} unfinished legacy runs remain unchanged in /history. They do not block this separately reviewed task and will not be resumed automatically.`, "info");
			let selectedRepository: string | undefined;
			try { selectedRepository = await chooseRepository(ctx, operationSignal); }
			catch (error) {
				if (!(error instanceof AgentvolveInputRequired)) throw error;
				if (!(await ctx.ui.confirm("Use a new private workspace instead?",
					`${error.message}\n\nThe existing project will remain unchanged and will NOT be copied. A fresh task still needs review and approval.`, { signal: operationSignal }))) throw error;
				persistWorkflowConfiguration({ goal: workflowConfiguration.goal, maxRounds: workflowConfiguration.maxRounds, freshWorkspace: true });
			}
			const newWorkspace = selectedRepository === undefined;
			const repository = selectedRepository ?? join(tasksDirectory(), "workspaces", `task-${uuidv7()}`);
			const template = fromSession || newWorkspace ? undefined : await chooseTaskProfile(ctx, repository, operationSignal);
			let profile: string | null;
			if (template) {
				const source = reviewObject(JSON.parse(await readFile(template, "utf8")), "task profile");
				const taskGoal = goal ?? source.goal;
				if (typeof taskGoal !== "string" || !taskGoal.trim()) throw new AgentvolveInputRequired("Describe the problem with /goal.");
				const budget = await reviewDevelopmentBudget(ctx, source, maxRounds, operationSignal);
				profile = await deriveGoalTask(template, taskGoal, maxRounds, budget.max_wall_seconds, operationSignal);
				const derived = reviewObject(JSON.parse(await readFile(profile, "utf8")), "derived task");
				if (!(await ctx.ui.confirm("Run this reviewed Agentvolve task?", taskReview(derived, false, budget), { signal: operationSignal }))) return null;
				persistWorkflowConfiguration({ ...workflowConfiguration, repository });
			} else profile = await generateSessionTaskDraft(ctx, repository, goal, maxRounds, operationSignal, newWorkspace);
			if (!profile) return null;
			operationSignal.throwIfAborted();
			return await launchDetachedWorkflow(ctx, profile, operationSignal);
		} finally {
			preparing = false;
			operationController = undefined;
		}
	}

	async function showCandidateTrees(ctx: ExtensionContext, selector: string): Promise<void> {
		const inspect = async (action: string, arguments_: string[]) => {
			const result = await pi.exec("uv", ["run", "python", "-m", "apps.coding_agent.operator_view", action, runsDirectory(), selector, ...arguments_],
				{ cwd: repositoryRoot(), timeout: 30_000 });
			return decodeOutput(result);
		};
		await showCandidateBrowser(ctx, {
			tree: async (offset, loops) => decodeOperatorTree(await inspect(loops ? "loops" : "tree", [String(offset)])),
			report: async (label, eventOffset, diffOffset, loop) => decodeCandidateReport(await inspect(loop ? "loop" : "candidate",
				[label, String(eventOffset), ...(loop ? [] : [String(diffOffset)])])),
			record: (view) => pi.appendEntry("agentvolve-candidate-inspection", view),
			openGraph: () => openTraceViewer(pi, ctx, selector),
		});
	}

	async function showProgress(ctx: ExtensionContext, selector = ""): Promise<void> {
		const history = await operatorHistory();
		if (!selector && !history.runs.length) {
			ctx.ui.notify("No Agentvolve runs yet. Set /limit, then use /goal to solve a problem.", "info");
			return;
		}
		const progress = await operatorProgress(selector);
		const selected = basename(progress.workflow_root);
		const trace = await operatorTrace(selected);
		pi.appendEntry("agentvolve-progress-view", { progress, trace });
		if (ctx.mode !== "tui") {
			ctx.ui.notify(operatorProgressSummary(progress), "info");
			let page = trace;
			for (;;) {
				pi.appendEntry("agentvolve-trace-view", page);
				ctx.ui.notify(JSON.stringify(page), "info");
				const options = [
					...(page.offset > 0 ? ["Previous generations"] : []),
					...(page.next_offset !== null ? ["Next generations"] : []), "Candidate trees / child reports", "Open Trace Viewer", "Return",
				];
				const choice = await ctx.ui.select("Evolution trace", options);
				if (choice === "Candidate trees / child reports") await showCandidateTrees(ctx, selected);
				else if (choice === "Open Trace Viewer") await openTraceViewer(pi, ctx, selected);
				else if (choice === "Previous generations") page = await operatorTrace(selected, Math.max(0, page.offset - page.page_size));
				else if (choice === "Next generations" && page.next_offset !== null) page = await operatorTrace(selected, page.next_offset);
				else return;
			}
		}
		let current = progress;
		let currentTrace = trace;
		for (;;) {
			const action = await showAgentvolveDashboard(ctx, operatorModelLabel(ctx), current, () => operatorProgress(selected), currentTrace, (offset) => operatorTrace(selected, offset));
			if (action === "graph") await openTraceViewer(pi, ctx, selected);
			else if (action === "tree") await showCandidateTrees(ctx, selected);
			else return;
			current = await operatorProgress(selected);
			currentTrace = await operatorTrace(selected);
		}
	}

	async function showHistory(ctx: ExtensionContext, selector = ""): Promise<void> {
		if (selector) return showProgress(ctx, selector);
		let offset = 0;
		for (;;) {
			const history = await operatorHistory(offset);
			pi.appendEntry("agentvolve-history-view", history);
			if (!history.runs.length) {
				ctx.ui.notify("No Agentvolve runs on this history page.", "info");
				return;
			}
			const labels = history.runs.map((run) => `${run.name} · ${run.state} · ${run.goal?.replaceAll(/\s+/g, " ").slice(0, 100) ?? "goal unavailable"}`);
			const selected = await ctx.ui.select(`Agentvolve history · ${offset + 1}–${offset + history.runs.length} of ${history.total_runs}`, [
				...labels, ...(offset > 0 ? ["Newer runs"] : []), ...(history.next_offset !== null ? ["Older runs"] : []),
			]);
			if (!selected) return;
			if (selected === "Newer runs") offset = Math.max(0, offset - history.page_size);
			else if (selected === "Older runs" && history.next_offset !== null) offset = history.next_offset;
			else {
				const run = history.runs[labels.indexOf(selected)];
				if (!run) throw new Error("History selection did not resolve");
				await showProgress(ctx, run.name);
			}
		}
	}

	function command(name: string, description: string, handler: (args: string, ctx: ExtensionContext) => Promise<void>): void {
		pi.registerCommand(name, { description, handler: async (args, ctx) => {
			try { await handler(unquoteArgument(args), ctx); }
			catch (error) { ctx.ui.notify(error instanceof Error ? error.message : String(error), error instanceof AgentvolveInputRequired ? "warning" : "error"); }
		} });
	}

	command("goal", "Review and solve a coding problem with Agentvolve", async (args, ctx) => {
		const goal = args || workflowConfiguration.goal;
		if (!goal) throw new AgentvolveInputRequired("Usage: /goal describe the independently checked problem");
		if (goal.length > 65_536) throw new AgentvolveInputRequired("/goal is too long");
		const worker = await solveGoal(ctx, goal, false, ctx.signal);
		if (!worker) ctx.ui.notify("Task not approved; no workflow started.", "info");
	});
	command("limit", "Set the generation limit for future Agentvolve tasks", async (args, ctx) => {
		if (preparing) throw new AgentvolveInputRequired("Finish or cancel the current task review before changing /limit.");
		const maxRounds = generationLimit(args);
		persistWorkflowConfiguration({ ...workflowConfiguration, maxRounds });
		ctx.ui.notify(`Agentvolve limit: ${maxRounds} generations for future tasks. Submit /goal to review and start; a running task is unchanged.`, "info");
	});
	command("history", "Browse every run's evolution trace and stage reports; optionally name a run", async (args, ctx) => { await showHistory(ctx, args); });
	command("progress", "Inspect the most recent Agentvolve run", async (args, ctx) => {
		if (args) throw new AgentvolveInputRequired("/progress accepts no arguments; use /history RUN_NAME for a past run.");
		await showProgress(ctx);
	});

	pi.registerEntryRenderer<{ label: string; stage: number; status: string; summary: string }>("agentvolve-stage-report", (entry, _options, theme) => {
		const report = entry.data;
		return new Text(`${theme.fg("success", `${report?.status === "reused" ? "↺" : "✓"} Agentvolve [${report?.stage ?? "?"}/6] ${report?.label ?? "Stage"}`)}\n${report?.summary ?? ""}`, 1, 0);
	});

	pi.registerTool({
		name: "darwinian_coding", label: "Agentvolve", description: CODING_TOOL_DESCRIPTION,
		promptSnippet: "Operate Agentvolve's reviewed detached coding workflow",
		promptGuidelines: [CODING_TOOL_GUIDELINE],
		parameters: Type.Object({ action: StringEnum([
			"workflow_activate", "workflow_from_session", "workflow_start", "workflow_status", "workflow_history", "workflow_verify",
			"workflow_manage",
		] as const) }, { additionalProperties: false }),
		async execute(_toolCallId, params, signal, onUpdate, ctx) {
			onUpdate?.({ content: [{ type: "text", text: `Agentvolve ${params.action}…` }], details: { action: params.action } });
			if (params.action === "workflow_activate") {
				await activateAgentvolveMode(ctx);
				return { content: [{ type: "text", text: "Agentvolve is active. No task or worker was started by activation. Use /goal, /limit, /history, and /progress." }], details: { active: true, status: "operator-mode" } };
			}
			if (params.action === "workflow_history") {
				const history = await operatorHistory();
				return { content: [{ type: "text", text: history.runs.map((run) => `${run.name} · ${run.state} · ${run.goal ?? ""}`).join("\n") || "No Agentvolve runs yet." }], details: history };
			}
			if (params.action === "workflow_status") {
				const history = await operatorHistory();
				if (!history.runs.length) return { content: [{ type: "text", text: "No Agentvolve runs yet." }], details: { active: modeActive, status: "idle" } };
				const progress = await operatorProgress();
				return { content: [{ type: "text", text: operatorProgressSummary(progress) }], details: progress };
			}
			if (params.action === "workflow_manage") {
				if (preparing) return { content: [{ type: "text", text: "Finish or cancel the current task/workflow review first." }], details: { status: "review-in-progress" } };
				preparing = true;
				operationController = new AbortController();
				const operationSignal = signal ? AbortSignal.any([signal, operationController.signal]) : operationController.signal;
				try {
					const result = await manageWorkflow(pi, ctx, prepareRuntime, undefined, operationSignal);
					await refreshWorkflowMonitor(ctx);
					return { content: [{ type: "text", text: result.message }], details: result };
				} finally {
					preparing = false;
					operationController = undefined;
				}
			}
			if (params.action === "workflow_verify") {
				const root = await latestWorkerWorkflowRoot();
				if (!root) throw new Error("No detached Agentvolve workflow exists");
				const result = await pi.exec("uv", ["run", "python", "-m", "apps.coding_agent.agentvolve_worker", "verify", root], { cwd: repositoryRoot(), signal, timeout: 30_000 });
				const worker = decodeWorkerResponse(decodeOutput(result));
				pi.appendEntry("agentvolve-worker-launch", worker);
				return { content: [{ type: "text", text: `Offline verification queued for ${root}.` }], details: worker };
			}
			try {
				const fromSession = params.action === "workflow_from_session";
				const worker = await solveGoal(ctx, fromSession ? undefined : workflowConfiguration.goal, fromSession, signal);
				return { content: [{ type: "text", text: worker ? `Detached Agentvolve workflow started at ${worker.workflow_root}. Use /progress.` : "Task preparation cancelled; no workflow started." }], details: worker ?? { status: "cancelled" } };
			} catch (error) {
				if (!(error instanceof AgentvolveInputRequired)) throw error;
				return { content: [{ type: "text", text: error.message }], details: { status: "needs-task-clarification" } };
			}
		},
	});

	pi.on("session_start", async (_event, ctx) => {
		stopWorkflowMonitor();
		modeActive = false;
		workflowConfiguration = {};
		reportedStages = new Set<string>();
		for (const entry of ctx.sessionManager.getBranch()) {
			if (entry.type !== "custom" || typeof entry.data !== "object" || entry.data === null || Array.isArray(entry.data)) continue;
			const data = entry.data as Record<string, unknown>;
			if (entry.customType === "agentvolve-workflow-configuration") {
				workflowConfiguration = {
					...(typeof data.goal === "string" ? { goal: data.goal } : {}),
					...(typeof data.maxRounds === "number" && Number.isInteger(data.maxRounds) && data.maxRounds >= 1 && data.maxRounds <= 256 ? { maxRounds: data.maxRounds } : {}),
					...(typeof data.repository === "string" && isAbsolute(data.repository) ? { repository: data.repository } : {}),
					...(data.managedWorkspace === true ? { managedWorkspace: true } : {}),
					...(data.freshWorkspace === true ? { freshWorkspace: true } : {}),
				};
			} else if (entry.customType === "agentvolve-mode") modeActive = data.active === true;
			else if (entry.customType === "agentvolve-stage-report" && typeof data.workflowId === "string" && Number.isInteger(data.stage)) reportedStages.add(`${data.workflowId}:${data.stage}`);
		}
		activeModelLabel = operatorModelLabel(ctx);
		renderModeWidget(ctx);
		if (modeActive) await startWorkflowMonitor(ctx);
		ctx.ui.notify("Agentvolve: /goal solves a reviewed problem, /limit sets generations, /history browses traces, /progress inspects the latest run. Restoring a session starts no task.", "info");
	});
	pi.on("model_select", async (_event, ctx) => { activeModelLabel = operatorModelLabel(ctx); if (modeActive) await refreshWorkflowMonitor(ctx); });
	pi.on("thinking_level_select", async (_event, ctx) => { activeModelLabel = operatorModelLabel(ctx); if (modeActive) await refreshWorkflowMonitor(ctx); });
	pi.on("session_shutdown", async () => { operationController?.abort(); stopWorkflowMonitor(); });
	pi.on("before_agent_start", async (event) => {
		if (!modeActive) return;
		return { systemPrompt: `${event.systemPrompt}\n\n[AGENTVOLVE]\nAgentvolve operator mode is active. ${CODING_TOOL_GUIDELINE} Pi remains the interactive operator; the detached worker's provider/model/reasoning and budgets stay manifest-bound. Fixed code owns mutation transport, independent evaluation, exact Population recurrence, protected final assays, Docker isolation, receipts, and sealing. Use workflow_manage for directly approved in-session recovery or closing an inactive workflow as incomplete; the worker CLI retains the same recovery and verification authority. Removed slash commands are not available.` };
	});
}
