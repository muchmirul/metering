import { existsSync } from "node:fs";
import { mkdir } from "node:fs/promises";
import { join } from "node:path";
import { setTimeout as delay } from "node:timers/promises";

import { type Api, type Model, StringEnum } from "@earendil-works/pi-ai";
import {
	BorderedLoader,
	DynamicBorder,
	type ExtensionAPI,
	type ExtensionContext,
} from "@earendil-works/pi-coding-agent";
import { Container, type SelectItem, SelectList, Text } from "@earendil-works/pi-tui";
import { Type } from "typebox";

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
	decodeOutput,
	latestCodingRoot,
	latestRunRoot,
	latestUnfinishedCodingRun,
	llamaCppModelReady,
	llamaCppService,
	LOCAL_RUNTIME_TIMEOUT_MS,
	type ModeSummary,
	newCodingRunRoot,
	newRunRoot,
	PROCESS_LABELS,
	processProjection,
	readProcessProjection,
	repositoryRoot,
	runsDirectory,
	runtimeManifest,
	type RuntimeSelection,
	runSummary,
	statusSummary,
	type ThinkingLevel,
	verificationSummary,
	workflowHistory,
	WORKFLOW_MONITOR_INTERVAL_MS,
} from "./population_evolution_support.ts";

const MODE_NAME = "Agentvolve";
const STATUS_KEY = "population-evolution";
const WIDGET_KEY = "population-evolution";
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

interface OriginalModeState {
	model: Model<Api> | undefined;
	thinkingLevel: ThinkingLevel;
}

type AgentvolveModelMode = "local" | "routed";

type AgentvolveMenuAction =
	| "close"
	| "deactivate"
	| "workflow"
	| "workflow-history"
	| "workflow-resume"
	| "workflow-retry"
	| "workflow-status"
	| "workflow-verify";

type WorkflowAction = "run" | "resume" | "retry" | "status" | "verify";
type WorkflowEffectAction = Exclude<WorkflowAction, "status">;
type CodingLoaderAction = Exclude<CodingAction, "harness-status" | "solution-status">;

const WORKFLOW_LOADER_LABELS: Record<WorkflowEffectAction, string> = {
	run: "Running the unified Agentvolve workflow [1/6] → [6/6]…",
	resume: "Resuming the current Agentvolve workflow stage…",
	retry: "Retrying the explicitly approved pending workflow attempt…",
	verify: "Verifying the completed Agentvolve workflow offline…",
};

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
	"Run or inspect Agentvolve's fixed Pi coding-harness and solution evolution using only",
	"the operator-approved METERING_EVOLUTION_TASK_PROFILE. It accepts no task text, command,",
	"evaluator, candidate, or output path.",
].join(" ");

const CODING_TOOL_GUIDELINE = [
	"Use darwinian_coding only after the user explicitly requests harness or solution evolution.",
	"Never substitute ordinary in-place edits for its immutable candidates and independent assays.",
].join(" ");

function setModeStatus(
	ctx: ExtensionContext,
	state: "available" | "failed" | "ready" | "running",
	process?: string,
): void {
	const color = state === "failed" ? "error" : state === "running" ? "warning" : state === "available" ? "dim" : "accent";
	ctx.ui.setStatus(STATUS_KEY, ctx.ui.theme.fg(color, `agentvolve: ${process ?? state}`));
}

function setModeWidget(
	ctx: ExtensionContext,
	summary?: ModeSummary,
	modelMode?: AgentvolveModelMode,
	modelLabel?: string,
): void {
	const lines = [
		ctx.ui.theme.fg("accent", `🧬 ${MODE_NAME}`) + ctx.ui.theme.fg("dim", " · unified workflow"),
		ctx.ui.theme.fg(
			"dim",
			modelMode && modelLabel ? `model mode: ${modelMode} · ${modelLabel}` : "model mode: not active",
		),
	];
	const match = summary?.process?.match(/^\[(\d+)\/6\]/);
	const currentStage = match ? Number.parseInt(match[1], 10) : undefined;
	const inProgress = summary?.status === "in progress";
	const failed = summary?.status === "failed";
	lines.push(ctx.ui.theme.fg("accent", `workflow status: ${summary?.status ?? "not started"}`));
	for (let stage = 1; stage <= 6; stage += 1) {
		const label = PROCESS_LABELS[stage];
		const isCurrent = stage === currentStage;
		const completed = currentStage !== undefined && (stage < currentStage || (isCurrent && !inProgress && !failed));
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

function selectMenu<Value extends string>(
	ctx: ExtensionContext,
	title: string,
	items: SelectItem[],
	cancelLabel: string,
): Promise<Value | null> {
	return ctx.ui.custom<Value | null>((tui, theme, _keybindings, done) => {
		const container = new Container();
		container.addChild(new DynamicBorder((text: string) => theme.fg("accent", text)));
		container.addChild(new Text(theme.fg("accent", theme.bold(title)), 1, 0));
		const list = new SelectList(items, Math.min(items.length, 12), {
			selectedPrefix: (text) => theme.fg("accent", text),
			selectedText: (text) => theme.fg("accent", text),
			description: (text) => theme.fg("muted", text),
			scrollInfo: (text) => theme.fg("dim", text),
			noMatch: (text) => theme.fg("warning", text),
		});
		list.onSelect = (item) => done(item.value as Value);
		list.onCancel = () => done(null);
		container.addChild(list);
		container.addChild(new Text(theme.fg("dim", `↑↓ navigate • enter select • esc ${cancelLabel}`), 1, 0));
		container.addChild(new DynamicBorder((text: string) => theme.fg("accent", text)));
		return {
			render: (width: number) => container.render(width),
			invalidate: () => container.invalidate(),
			handleInput: (data: string) => {
				list.handleInput(data);
				tui.requestRender();
			},
		};
	});
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
	let originalModeState: OriginalModeState | undefined;
	let workflowSummary: ModeSummary | undefined;
	let monitor: ReturnType<typeof setInterval> | undefined;
	let monitorRefreshing = false;
	let monitorFingerprint: string | undefined;
	let running = false;

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
		signal?: AbortSignal,
		requestedMode: AgentvolveModelMode = activeModelMode ?? "local",
	): Promise<void> {
		const wasActive = modeActive;
		const previousMode = activeModelMode;
		const previousLabel = activeModelLabel;
		if (!originalModeState) {
			originalModeState = {
				model: ctx.model,
				thinkingLevel: pi.getThinkingLevel(),
			};
		}
		if (requestedMode === "routed") {
			setModeStatus(ctx, "running", "selecting routed Pi model");
			try {
				if (originalModeState.model && !(await pi.setModel(originalModeState.model))) {
					throw new Error("Pi could not restore the routed model that preceded Agentvolve");
				}
				pi.setThinkingLevel(originalModeState.thinkingLevel);
				const model = originalModeState.model ?? ctx.model;
				activeModelMode = "routed";
				activeModelLabel = model ? `${model.provider}/${model.id}` : "current Pi route";
				modeActive = true;
				setModeStatus(ctx, "ready", `routed · ${activeModelLabel}`);
				await startWorkflowMonitor(ctx);
				return;
			} catch (error) {
				modeActive = wasActive;
				activeModelMode = previousMode;
				activeModelLabel = previousLabel;
				if (!wasActive) originalModeState = undefined;
				setModeStatus(ctx, "failed", "routed Pi model");
				throw error;
			}
		}

		const selection = await configuredRuntimeSelection();
		setModeStatus(ctx, "running", `activating ${selection.provider}/${selection.model}`);
		try {
			await ensureLocalRuntime(selection, signal);
			const model = ctx.modelRegistry.find(selection.provider, selection.model);
			if (!model) throw new Error(`Pi model is unavailable: ${selection.provider}/${selection.model}`);
			if (!(await pi.setModel(model))) {
				throw new Error(`Pi has no usable authentication for ${selection.provider}/${selection.model}`);
			}
			pi.setThinkingLevel(selection.reasoning);
			activeModelMode = "local";
			activeModelLabel = `${selection.provider}/${selection.model}`;
			modeActive = true;
			setModeStatus(ctx, "ready", `local · ${activeModelLabel}`);
			await startWorkflowMonitor(ctx);
		} catch (error) {
			modeActive = wasActive;
			activeModelMode = previousMode;
			activeModelLabel = previousLabel;
			if (!wasActive) originalModeState = undefined;
			setModeStatus(ctx, "failed", `${selection.provider}/${selection.model}`);
			throw error;
		}
	}

	async function activateAgentvolveWithLoader(
		ctx: ExtensionContext,
		requestedMode: AgentvolveModelMode,
	): Promise<boolean> {
		const result = await ctx.ui.custom<{ error?: string } | null>((tui, theme, _keybindings, done) => {
			const label =
				requestedMode === "local"
					? "Activating Qwen through llama.cpp…"
					: "Entering Agentvolve with the routed Pi model…";
			const loader = new BorderedLoader(tui, theme, label);
			loader.onAbort = () => done(null);
			activateAgentvolveMode(ctx, loader.signal, requestedMode)
				.then(() => done({}))
				.catch((error) => done({ error: String(error) }));
			return loader;
		});
		if (result === null) {
			ctx.ui.notify("Agentvolve activation cancelled", "info");
			return false;
		}
		if (result.error) {
			ctx.ui.notify(result.error, "error");
			return false;
		}
		return true;
	}

	async function deactivateAgentvolveMode(ctx: ExtensionContext): Promise<void> {
		if (originalModeState?.model && !(await pi.setModel(originalModeState.model))) {
			ctx.ui.notify("Could not restore the model that preceded Agentvolve", "warning");
		}
		if (originalModeState) pi.setThinkingLevel(originalModeState.thinkingLevel);
		modeActive = false;
		activeModelMode = undefined;
		activeModelLabel = undefined;
		originalModeState = undefined;
		stopWorkflowMonitor();
		setModeStatus(ctx, "available");
		ctx.ui.setWidget(WIDGET_KEY, undefined);
		ctx.ui.notify("Agentvolve mode closed; workflow status monitoring stopped", "info");
	}

	async function selectAgentvolveModelMode(ctx: ExtensionContext): Promise<AgentvolveModelMode | null> {
		const routedModel = modeActive && originalModeState?.model ? originalModeState.model : ctx.model;
		const routedLabel = routedModel ? `${routedModel.provider}/${routedModel.id}` : "the current Pi model";
		const items: SelectItem[] = [
			{
				value: "local",
				label: activeModelMode === "local" ? "Local model ✓" : "Local model",
				description: "Use the canonical Qwen model through llama.cpp",
			},
			{
				value: "routed",
				label: activeModelMode === "routed" ? "Routed Pi model ✓" : "Routed Pi model",
				description: `Use ${routedLabel} for the outer Pi session; experiments stay runtime-pinned`,
			},
		];
		return selectMenu<AgentvolveModelMode>(ctx, "Agentvolve · choose model mode", items, "cancel");
	}

	async function selectAgentvolveAction(ctx: ExtensionContext): Promise<AgentvolveMenuAction | null> {
		const items: SelectItem[] = [
			{
				value: "workflow",
				label: "Start Agentvolve workflow",
				description: "Run the complete [1/6] through [6/6] pipeline",
			},
			{
				value: "workflow-status",
				label: "Refresh workflow status",
				description: "Refresh the always-visible six-stage tracker",
			},
			{
				value: "workflow-history",
				label: "Browse workflow history",
				description: "Inspect shared runs from this or any other Pi session",
			},
			{
				value: "workflow-resume",
				label: "Resume workflow",
				description: "Continue the latest replay-authorized workflow effect",
			},
			{
				value: "workflow-retry",
				label: "Retry pending attempt",
				description: "Explicitly authorize the workflow's pending model attempt",
			},
			{
				value: "workflow-verify",
				label: "Verify completed workflow",
				description: "Replay the latest sealed workflow result offline",
			},
			{ value: "close", label: "Close menu", description: "Keep Agentvolve mode and its status tracker active" },
			{ value: "deactivate", label: "Exit Agentvolve mode", description: "Restore the preceding Pi model" },
		];
		const title = `Agentvolve workflow [1/6] → [6/6] · ${activeModelMode} · ${activeModelLabel}`;
		return selectMenu<AgentvolveMenuAction>(ctx, title, items, "close");
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
			renderModeWidget(ctx, summary);
			const state = summary.status === "in progress" ? "running" : modeActive ? "ready" : "available";
			setModeStatus(ctx, state, summary.process ?? (modeActive ? activeModelLabel : undefined));
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
	}

	async function requireCodingRoot(kind: CodingKind, completed: boolean, message: string): Promise<string> {
		const root = await latestCodingRoot(kind, completed);
		if (!root) throw new Error(message);
		return root;
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
				const harnessRoot = await requireCodingRoot(
					"harness",
					true,
					"run /evolve-harness before evolving a solution",
				);
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
						join(harnessRoot, "selected-harness.json"),
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

	async function executeWorkflow(
		action: WorkflowAction,
		ctx: ExtensionContext,
		argument = "",
		signal?: AbortSignal,
	): Promise<ModeSummary> {
		if (action === "status") return codingWorkflowStatus();
		if (action === "run") {
			const unfinished = await latestUnfinishedCodingRun();
			if (unfinished) {
				throw new Error(
					`an unfinished workflow is already at ${unfinished.root}; choose Resume workflow or Retry pending attempt`,
				);
			}
			const profile = configuredTaskProfile(argument);
			if (!(await latestCodingRoot("harness"))) await executeCoding("harness", ctx, "", signal);
			return executeCoding("solution", ctx, profile, signal);
		}
		if (action === "verify") return executeCoding("solution-verify", ctx, "", signal);
		const unfinished = await latestUnfinishedCodingRun();
		if (!unfinished) throw new Error(`no unfinished Agentvolve workflow exists to ${action}`);
		if (action === "retry" && !argument.trim()) {
			throw new Error("Retry pending attempt requires an operator-approved reason");
		}
		const codingAction =
			unfinished.kind === "harness"
				? action === "retry"
					? "harness-retry"
					: "harness-resume"
				: action === "retry"
					? "solution-retry"
					: "solution-resume";
		return executeCoding(codingAction, ctx, argument, signal);
	}

	async function workflowLoader(
		action: WorkflowEffectAction,
		ctx: ExtensionContext,
		argument = "",
	): Promise<void> {
		if (ctx.mode !== "tui") {
			ctx.ui.notify("Agentvolve workflow commands require interactive Pi", "error");
			return;
		}
		const result = await summaryLoader(ctx, WORKFLOW_LOADER_LABELS[action], (signal) =>
			executeWorkflow(action, ctx, argument, signal),
		);
		if (result === null) {
			ctx.ui.notify("Agentvolve workflow command cancelled", "info");
			return;
		}
		if (result.error) {
			try {
				renderModeWidget(ctx, await codingWorkflowStatus());
			} catch {
				renderModeWidget(ctx);
			}
			ctx.ui.notify(result.error, "error");
			return;
		}
		if (result.summary) {
			renderModeWidget(ctx, result.summary);
			pi.appendEntry("darwinian-coding-run", result.summary);
			ctx.ui.notify(humanSummary(result.summary), "info");
		}
	}

	async function codingLoader(
		action: CodingLoaderAction,
		ctx: ExtensionContext,
		profileArgument = "",
	): Promise<void> {
		if (ctx.mode !== "tui") {
			ctx.ui.notify("Agentvolve commands require interactive Pi", "error");
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

	async function showWorkflowStatus(ctx: ExtensionContext): Promise<void> {
		try {
			const summary = await codingWorkflowStatus();
			renderModeWidget(ctx, summary);
			setModeStatus(ctx, modeActive ? "ready" : "available", modeActive ? summary.process : undefined);
			ctx.ui.notify(humanSummary(summary), "info");
		} catch (error) {
			ctx.ui.notify(String(error), "error");
		}
	}

	async function showWorkflowHistory(ctx: ExtensionContext): Promise<void> {
		if (ctx.mode !== "tui") {
			ctx.ui.notify("Workflow history requires interactive Pi", "error");
			return;
		}
		const summaries = await workflowHistory();
		if (!summaries.length) {
			ctx.ui.notify(`No Agentvolve workflow runs exist under ${runsDirectory()}`, "info");
			return;
		}
		const labels = summaries.map((summary) => {
			const name = summary.runRoot.slice(summary.runRoot.lastIndexOf("/") + 1);
			return `${summary.process ?? "[?/6] Unknown stage"} · ${summary.status} · ${name}`;
		});
		const selected = await ctx.ui.select("Agentvolve workflow history", labels);
		if (!selected) return;
		const summary = summaries[labels.indexOf(selected)];
		if (!summary) return;
		pi.appendEntry("agentvolve-history-view", summary);
		ctx.ui.notify(humanSummary(summary), "info");
	}

	async function openAgentvolve(ctx: ExtensionContext): Promise<void> {
		if (ctx.mode !== "tui") {
			ctx.ui.notify("/agentvolve requires interactive Pi", "error");
			return;
		}
		const modelMode = await selectAgentvolveModelMode(ctx);
		if (modelMode === null || !(await activateAgentvolveWithLoader(ctx, modelMode))) return;
		const action = await selectAgentvolveAction(ctx);
		if (action === null || action === "close") return;
		if (action === "deactivate") {
			await deactivateAgentvolveMode(ctx);
			return;
		}
		if (action === "workflow-status") {
			await showWorkflowStatus(ctx);
			return;
		}
		if (action === "workflow-history") {
			await showWorkflowHistory(ctx);
			return;
		}
		if (action === "workflow") {
			const profile = await ctx.ui.input(
				"Agentvolve workflow task profile",
				process.env.METERING_EVOLUTION_TASK_PROFILE ?? "/absolute/path/to/task.json",
			);
			if (!profile) {
				ctx.ui.notify("Agentvolve workflow cancelled", "info");
				return;
			}
			await workflowLoader("run", ctx, profile);
			return;
		}
		if (action === "workflow-retry") {
			const reason = await ctx.ui.input("Operator-approved retry reason", "reviewed reason");
			if (!reason) {
				ctx.ui.notify("Agentvolve retry cancelled", "info");
				return;
			}
			await workflowLoader("retry", ctx, reason);
			return;
		}
		await workflowLoader(action === "workflow-resume" ? "resume" : "verify", ctx);
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

	registerNoArgumentCommand("agentvolve", "Open Agentvolve in local Qwen or routed Pi model mode", openAgentvolve);
	registerNoArgumentCommand(
		"agentvolve-history",
		"Browse shared Agentvolve workflow history from any Pi session",
		showWorkflowHistory,
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

	registerNoArgumentCommand(
		"evolve-code-resume",
		"Resume committed effects in the latest coding solution run",
		(ctx) => codingLoader("solution-resume", ctx),
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
		promptSnippet: "Run independently evaluated Agentvolve coding evolution",
		promptGuidelines: [CODING_TOOL_GUIDELINE],
		parameters: Type.Object({
			action: StringEnum([
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
		originalModeState = undefined;
		workflowSummary = undefined;
		monitorFingerprint = undefined;
		stopWorkflowMonitor();
		setModeStatus(ctx, "available");
		ctx.ui.setWidget(WIDGET_KEY, undefined);
		ctx.ui.notify(`${MODE_NAME} is available. Run /agentvolve to activate workflow status monitoring.`, "info");
	});

	pi.on("session_shutdown", async () => {
		stopWorkflowMonitor();
	});

	pi.on("before_agent_start", async (event) => {
		if (!modeActive) return;
		const authorityPrompt = [
			`Agentvolve mode is active in ${activeModelMode} outer-session model mode (${activeModelLabel}).`,
			"When the user explicitly asks for the reference assay, use population_evolution.",
			"For coding-harness or immutable solution evolution, use darwinian_coding; solution_run",
			"is valid only with an operator-approved METERING_EVOLUTION_TASK_PROFILE.",
			"Nested evolution calls remain bound to the provider, model, reasoning level, and budgets",
			"in the canonical runtime manifest; routed outer-session mode does not rewrite that evidence identity.",
			"Fixed code owns mutation transport, independent evaluation, exact Population recurrence,",
			"protected final assays, Docker isolation, receipts, and sealing. Never replace these",
			"authorities with ordinary in-place edits or describe an unevaluated edit as evolved.",
		].join(" ");
		return {
			systemPrompt: `${event.systemPrompt}\n\n[${MODE_NAME.toUpperCase()}]\n${authorityPrompt}`,
		};
	});
}
