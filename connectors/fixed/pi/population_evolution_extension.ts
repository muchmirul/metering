import { existsSync } from "node:fs";
import { mkdir, readdir, readFile } from "node:fs/promises";
import { homedir } from "node:os";
import { dirname, isAbsolute, join, resolve } from "node:path";
import { setTimeout as delay } from "node:timers/promises";
import { fileURLToPath } from "node:url";

import { type Api, type Model, StringEnum } from "@earendil-works/pi-ai";
import {
	BorderedLoader,
	DynamicBorder,
	type ExecResult,
	type ExtensionAPI,
	type ExtensionContext,
} from "@earendil-works/pi-coding-agent";
import { Container, type SelectItem, SelectList, Text } from "@earendil-works/pi-tui";
import { Type } from "typebox";

const MODE_NAME = "Agentvolve";
const STATUS_KEY = "population-evolution";
const WIDGET_KEY = "population-evolution";
const RUN_NAME = /^pi-\d{8}T\d{6}(?:\d{3})?Z$/;
const COMMAND_TIMEOUT_MS = 2 * 60 * 60 * 1000;
const LOCAL_RUNTIME_TIMEOUT_MS = 3 * 60 * 1000;
const WORKFLOW_MONITOR_INTERVAL_MS = 2000;
const MAX_DIAGNOSTIC_CHARS = 4000;
const DEFAULT_LLAMACPP_SERVICE = "llama-qwen38.service";
const DEFAULT_LLAMACPP_HEALTH_URL = "http://127.0.0.1:8080/v1/models";
const PROCESS_LABELS: Record<number, string> = {
	1: "Task and runtime configured",
	2: "Evolving harness",
	3: "Harness sealed",
	4: "Evolving solution",
	5: "Protected final assay",
	6: "Result ready for review",
};

interface ProcessProjection {
	display: string;
	stage: number;
}

interface ModeSummary {
	action: "run" | "status" | "verify";
	candidateId?: string;
	finalPassed?: number;
	finalTasks?: number;
	kind?: "arithmetic" | "coding-harness" | "coding-solution";
	patchPath?: string;
	process?: string;
	runRoot: string;
	runtimeId?: string;
	status: string;
}

interface LoaderResult {
	error?: string;
	summary?: ModeSummary;
}

type ThinkingLevel = "off" | "minimal" | "low" | "medium" | "high" | "xhigh" | "max";

interface RuntimeSelection {
	model: string;
	provider: string;
	reasoning: ThinkingLevel;
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

function repositoryRoot(): string {
	return resolve(dirname(fileURLToPath(import.meta.url)), "../../..");
}

function configuredAbsolutePath(name: string, fallback: string): string {
	const value = process.env[name];
	if (value !== undefined && !isAbsolute(value)) {
		throw new Error(`${name} must be an absolute path`);
	}
	return value ?? fallback;
}

function runtimeManifest(): string {
	return configuredAbsolutePath(
		"METERING_EVOLUTION_RUNTIME_MANIFEST",
		join(homedir(), ".config", "metering", "harness", "runtime.pi.local.json"),
	);
}

async function configuredRuntimeSelection(): Promise<RuntimeSelection> {
	const path = runtimeManifest();
	if (!existsSync(path)) throw new Error(`reviewed runtime manifest is unavailable: ${path}`);
	const value: unknown = JSON.parse(await readFile(path, "utf8"));
	if (typeof value !== "object" || value === null || Array.isArray(value)) {
		throw new Error("reviewed runtime manifest is malformed");
	}
	const model = (value as Record<string, unknown>).model;
	if (typeof model !== "object" || model === null || Array.isArray(model)) {
		throw new Error("reviewed runtime manifest has no model selection");
	}
	const selection = model as Record<string, unknown>;
	const levels = new Set<ThinkingLevel>(["off", "minimal", "low", "medium", "high", "xhigh", "max"]);
	if (
		typeof selection.provider !== "string" ||
		typeof selection.model !== "string" ||
		typeof selection.reasoning !== "string" ||
		!levels.has(selection.reasoning as ThinkingLevel)
	) {
		throw new Error("reviewed runtime manifest has an invalid model selection");
	}
	return {
		model: selection.model,
		provider: selection.provider,
		reasoning: selection.reasoning as ThinkingLevel,
	};
}

function llamaCppService(): string {
	return process.env.METERING_EVOLUTION_LLAMACPP_SERVICE?.trim() || DEFAULT_LLAMACPP_SERVICE;
}

function llamaCppHealthUrl(): string {
	return process.env.METERING_EVOLUTION_LLAMACPP_HEALTH_URL?.trim() || DEFAULT_LLAMACPP_HEALTH_URL;
}

async function llamaCppModelReady(selection: RuntimeSelection, signal?: AbortSignal): Promise<boolean> {
	try {
		const response = await fetch(llamaCppHealthUrl(), {
			headers: {
				Authorization: `Bearer ${process.env.METERING_EVOLUTION_LLAMACPP_API_KEY ?? "llamacpp"}`,
			},
			signal,
		});
		if (!response.ok) return false;
		const value: unknown = await response.json();
		if (typeof value !== "object" || value === null || Array.isArray(value)) return false;
		const data = (value as Record<string, unknown>).data;
		if (!Array.isArray(data)) return false;
		return data.some((item) => {
			if (typeof item !== "object" || item === null || Array.isArray(item)) return false;
			const model = item as Record<string, unknown>;
			const status = model.status;
			return (
				model.id === selection.model &&
				typeof status === "object" &&
				status !== null &&
				!Array.isArray(status) &&
				["loaded", "ready"].includes(String((status as Record<string, unknown>).value))
			);
		});
	} catch (error) {
		if (signal?.aborted) throw error;
		return false;
	}
}

function runsDirectory(): string {
	return configuredAbsolutePath("METERING_EVOLUTION_RUNS_DIR", resolve(repositoryRoot(), "..", "metering-live-runs"));
}

function timestamp(): string {
	return new Date().toISOString().replaceAll(/[-:.]/g, "");
}

function newRunRoot(): string {
	return join(runsDirectory(), `pi-${timestamp()}`);
}

function newCodingRunRoot(kind: "harness" | "solution"): string {
	return join(runsDirectory(), `${kind}-pi-${timestamp()}`);
}

async function latestRunRoot(): Promise<string | undefined> {
	try {
		const entries = await readdir(runsDirectory(), { withFileTypes: true });
		return entries
			.filter((entry) => entry.isDirectory() && RUN_NAME.test(entry.name))
			.map((entry) => join(runsDirectory(), entry.name))
			.filter((root) => existsSync(join(root, "experiment-report.json")))
			.sort()
			.reverse()[0];
	} catch {
		return undefined;
	}
}

async function latestCodingRoot(kind: "harness" | "solution", requireCompleted = true): Promise<string | undefined> {
	const pattern = new RegExp(`^${kind}-pi-\\d{8}T\\d{6}(?:\\d{3})?Z$`);
	try {
		const entries = await readdir(runsDirectory(), { withFileTypes: true });
		const marker = kind === "harness" ? "selected-harness.json" : "selected-solution.json";
		return entries
			.filter((entry) => entry.isDirectory() && pattern.test(entry.name))
			.map((entry) => join(runsDirectory(), entry.name))
			.filter((root) =>
				requireCompleted
					? existsSync(join(root, marker))
					: existsSync(join(root, "process-status.json")) || existsSync(join(root, "state", "driver.jsonl")),
			)
			.sort()
			.reverse()[0];
	} catch {
		return undefined;
	}
}

function configuredTaskProfile(argument: string): string {
	const supplied = argument.trim() || process.env.METERING_EVOLUTION_TASK_PROFILE;
	if (!supplied) {
		throw new Error("provide an absolute darwinian-coding-task-v1 path or set METERING_EVOLUTION_TASK_PROFILE");
	}
	if (!isAbsolute(supplied)) throw new Error("coding task profile must be an absolute path");
	if (!existsSync(supplied)) throw new Error(`coding task profile is unavailable: ${supplied}`);
	return supplied;
}

function processProjection(stage: number): ProcessProjection {
	const label = PROCESS_LABELS[stage];
	if (!label) throw new Error(`unsupported Darwinian coding process stage: ${stage}`);
	return { display: `[${stage}/6] ${label}`, stage };
}

async function readProcessProjection(
	runRoot: string,
	runKind: "harness" | "solution",
	fallbackStage: number,
): Promise<ProcessProjection> {
	const path = join(runRoot, "process-status.json");
	if (!existsSync(path)) return processProjection(fallbackStage);
	const value: unknown = JSON.parse(await readFile(path, "utf8"));
	if (typeof value !== "object" || value === null || Array.isArray(value)) {
		throw new Error("coding process status is malformed");
	}
	const document = value as Record<string, unknown>;
	const stage = integer(document.stage);
	if (
		document.authority !== "projection-only" ||
		document.process_schema !== "darwinian-coding-process-v1" ||
		document.run_kind !== runKind ||
		document.total_stages !== 6 ||
		stage === undefined
	) {
		throw new Error("coding process status has an unexpected identity");
	}
	const expected = processProjection(stage);
	if (document.display !== expected.display || document.stage_label !== PROCESS_LABELS[stage]) {
		throw new Error("coding process status does not replay");
	}
	return expected;
}

function boundedDiagnostic(value: string): string {
	const text = value.trim();
	return text.length <= MAX_DIAGNOSTIC_CHARS ? text : `…${text.slice(-MAX_DIAGNOSTIC_CHARS)}`;
}

function decodeOutput(result: ExecResult): Record<string, unknown> {
	if (result.killed || result.code !== 0) {
		const detail = boundedDiagnostic(result.stderr || result.stdout);
		throw new Error(detail || `evolution command exited with code ${result.code}`);
	}
	if (result.stderr.trim()) {
		throw new Error(`evolution command wrote standard error: ${boundedDiagnostic(result.stderr)}`);
	}
	const lines = result.stdout
		.split("\n")
		.map((line) => line.trim())
		.filter(Boolean);
	if (lines.length !== 1) {
		throw new Error("evolution command did not return exactly one JSON document");
	}
	let value: unknown;
	try {
		value = JSON.parse(lines[0]!);
	} catch (error) {
		throw new Error(`evolution command returned invalid JSON: ${String(error)}`);
	}
	if (typeof value !== "object" || value === null || Array.isArray(value)) {
		throw new Error("evolution command response must be a JSON object");
	}
	return value as Record<string, unknown>;
}

function text(value: unknown): string | undefined {
	return typeof value === "string" ? value : undefined;
}

function integer(value: unknown): number | undefined {
	return Number.isInteger(value) ? (value as number) : undefined;
}

function runSummary(runRoot: string, report: Record<string, unknown>): ModeSummary {
	if (report.schema !== "evolutionary-harness-experiment-v1") {
		throw new Error("live experiment returned an unexpected schema");
	}
	const final = report.final;
	if (typeof final !== "object" || final === null || Array.isArray(final)) {
		throw new Error("live experiment omitted its final result");
	}
	const finalResult = final as Record<string, unknown>;
	return {
		action: "run",
		candidateId: text(finalResult.candidate_id),
		finalPassed: integer(finalResult.passed_count),
		finalTasks: integer(finalResult.task_count),
		kind: report.assay === "coding-agent-v1" ? "coding-harness" : "arithmetic",
		runRoot,
		runtimeId: text(report.runtime_id),
		status: "sealed",
	};
}

function verificationSummary(runRoot: string, report: Record<string, unknown>): ModeSummary {
	if (report.schema !== "evolutionary-harness-verification-v1") {
		throw new Error("offline verifier returned an unexpected schema");
	}
	return {
		action: "verify",
		kind: report.assay === "coding-agent-v1" ? "coding-harness" : "arithmetic",
		runRoot,
		runtimeId: text(report.runtime_id),
		status: text(report.status) ?? "unknown",
	};
}

function codingSolutionSummary(
	runRoot: string,
	report: Record<string, unknown>,
	action: "run" | "status" | "verify",
): ModeSummary {
	const expected = action === "verify" ? "darwinian-coding-verification-v1" : "darwinian-coding-experiment-v1";
	if (report.schema !== expected) throw new Error("coding evolution returned an unexpected schema");
	const final = report.final;
	const selected = report.selected_solution;
	const finalResult =
		typeof final === "object" && final !== null && !Array.isArray(final)
			? (final as Record<string, unknown>)
			: undefined;
	const selectedResult =
		typeof selected === "object" && selected !== null && !Array.isArray(selected)
			? (selected as Record<string, unknown>)
			: undefined;
	return {
		action,
		candidateId: text(selectedResult?.candidate_id) ?? text(report.selected_candidate_id),
		finalPassed: integer(finalResult?.passed_count),
		finalTasks: integer(finalResult?.task_count),
		kind: "coding-solution",
		patchPath: action === "verify" ? undefined : join(runRoot, "selected.patch"),
		runRoot,
		runtimeId: text(report.runtime_id) ?? text(report.coding_runtime_id),
		status: action === "verify" ? (text(report.status) ?? "unknown") : "sealed",
	};
}

async function statusSummary(): Promise<ModeSummary> {
	const runRoot = await latestRunRoot();
	if (!runRoot) {
		throw new Error(`no Population runs exist under ${runsDirectory()}`);
	}
	const reportPath = join(runRoot, "experiment-report.json");
	let report: Record<string, unknown>;
	try {
		const value: unknown = JSON.parse(await readFile(reportPath, "utf8"));
		if (typeof value !== "object" || value === null || Array.isArray(value)) {
			throw new Error("report is not an object");
		}
		report = value as Record<string, unknown>;
	} catch (error) {
		throw new Error(`latest run has no valid experiment report: ${String(error)}`);
	}
	const summary = runSummary(runRoot, report);
	return { ...summary, action: "status" };
}

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
		return ctx.ui.custom<AgentvolveModelMode | null>((tui, theme, _keybindings, done) => {
			const container = new Container();
			container.addChild(new DynamicBorder((text: string) => theme.fg("accent", text)));
			container.addChild(new Text(theme.fg("accent", theme.bold("Agentvolve · choose model mode")), 1, 0));
			const list = new SelectList(items, items.length, {
				selectedPrefix: (text) => theme.fg("accent", text),
				selectedText: (text) => theme.fg("accent", text),
				description: (text) => theme.fg("muted", text),
				scrollInfo: (text) => theme.fg("dim", text),
				noMatch: (text) => theme.fg("warning", text),
			});
			list.onSelect = (item) => done(item.value as AgentvolveModelMode);
			list.onCancel = () => done(null);
			container.addChild(list);
			container.addChild(new Text(theme.fg("dim", "↑↓ navigate • enter select • esc cancel"), 1, 0));
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
		return ctx.ui.custom<AgentvolveMenuAction | null>((tui, theme, _keybindings, done) => {
			const container = new Container();
			container.addChild(new DynamicBorder((text: string) => theme.fg("accent", text)));
			container.addChild(
				new Text(
					theme.fg(
						"accent",
						theme.bold(`Agentvolve workflow [1/6] → [6/6] · ${activeModelMode} · ${activeModelLabel}`),
					),
					1,
					0,
				),
			);
			const list = new SelectList(items, Math.min(items.length, 12), {
				selectedPrefix: (text) => theme.fg("accent", text),
				selectedText: (text) => theme.fg("accent", text),
				description: (text) => theme.fg("muted", text),
				scrollInfo: (text) => theme.fg("dim", text),
				noMatch: (text) => theme.fg("warning", text),
			});
			list.onSelect = (item) => done(item.value as AgentvolveMenuAction);
			list.onCancel = () => done(null);
			container.addChild(list);
			container.addChild(new Text(theme.fg("dim", "↑↓ navigate • enter select • esc close"), 1, 0));
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

	async function execute(
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

	async function codingStatusAtRoot(kind: "harness" | "solution", root: string): Promise<ModeSummary> {
		const completed = existsSync(join(root, "experiment-report.json"));
		const fallbackStage = kind === "harness" ? (completed ? 3 : 2) : completed ? 6 : 4;
		const process = await readProcessProjection(root, kind, fallbackStage);
		if (!completed) {
			return {
				action: "status",
				kind: kind === "harness" ? "coding-harness" : "coding-solution",
				process: process.display,
				runRoot: root,
				status: "in progress",
			};
		}
		const value: unknown = JSON.parse(await readFile(join(root, "experiment-report.json"), "utf8"));
		if (typeof value !== "object" || value === null || Array.isArray(value)) {
			throw new Error(`coding ${kind} report is malformed: ${root}`);
		}
		const summary =
			kind === "harness"
				? { ...runSummary(root, value as Record<string, unknown>), action: "status" as const }
				: codingSolutionSummary(root, value as Record<string, unknown>, "status");
		return { ...summary, process: process.display };
	}

	async function codingStatus(kind: "harness" | "solution"): Promise<ModeSummary> {
		const root = await latestCodingRoot(kind, false);
		if (!root) throw new Error(`no coding ${kind} runs exist under ${runsDirectory()}`);
		return codingStatusAtRoot(kind, root);
	}

	async function latestUnfinishedCodingRun(): Promise<{ kind: "harness" | "solution"; root: string } | null> {
		const runs: Array<{ kind: "harness" | "solution"; root: string }> = [];
		for (const kind of ["harness", "solution"] as const) {
			const root = await latestCodingRoot(kind, false);
			if (root && !existsSync(join(root, "experiment-report.json"))) runs.push({ kind, root });
		}
		runs.sort((left, right) => {
			const leftStamp = left.root.slice(left.root.lastIndexOf("-pi-") + 4);
			const rightStamp = right.root.slice(right.root.lastIndexOf("-pi-") + 4);
			return rightStamp.localeCompare(leftStamp);
		});
		return runs[0] ?? null;
	}

	async function codingWorkflowStatus(): Promise<ModeSummary> {
		const unfinished = await latestUnfinishedCodingRun();
		if (unfinished) return codingStatus(unfinished.kind);
		if (await latestCodingRoot("solution")) return codingStatus("solution");
		if (await latestCodingRoot("harness")) return codingStatus("harness");
		return {
			action: "status",
			kind: "coding-solution",
			runRoot: runsDirectory(),
			status: "not started",
		};
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

	async function workflowHistory(limit = 50): Promise<ModeSummary[]> {
		let entries: Array<{ isDirectory(): boolean; name: string }>;
		try {
			entries = await readdir(runsDirectory(), { withFileTypes: true });
		} catch {
			return [];
		}
		const names = entries
			.filter(
				(entry) =>
					entry.isDirectory() &&
					/^(?:harness|solution)-pi-\d{8}T\d{6}(?:\d{3})?Z$/.test(entry.name),
			)
			.map((entry) => entry.name)
			.sort((left, right) => {
				const leftStamp = left.slice(left.lastIndexOf("-pi-") + 4);
				const rightStamp = right.slice(right.lastIndexOf("-pi-") + 4);
				return rightStamp.localeCompare(leftStamp);
			})
			.slice(0, limit);
		const summaries: ModeSummary[] = [];
		for (const name of names) {
			const kind = name.startsWith("harness-") ? "harness" : "solution";
			const root = join(runsDirectory(), name);
			try {
				summaries.push(await codingStatusAtRoot(kind, root));
			} catch {
				const fallback = kind === "harness" ? 2 : 4;
				summaries.push({
					action: "status",
					kind: kind === "harness" ? "coding-harness" : "coding-solution",
					process: processProjection(fallback).display,
					runRoot: root,
					status: "unreadable",
				});
			}
		}
		return summaries;
	}

	async function executeCoding(
		action:
			| "harness"
			| "harness-resume"
			| "harness-retry"
			| "harness-status"
			| "solution"
			| "solution-resume"
			| "solution-retry"
			| "solution-status"
			| "solution-verify",
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
		let root: string;
		let args: string[];
		if (action === "harness") {
			root = newCodingRunRoot("harness");
			args = ["run", "python", "apps/harness/experiment.py", "coding-pi", root, runtime];
		} else if (action === "harness-resume" || action === "harness-retry") {
			const latest = await latestCodingRoot("harness", false);
			if (!latest) throw new Error("no resumable coding harness run exists");
			root = latest;
			if (action === "harness-retry") {
				const reason = profileArgument.trim();
				if (!reason) throw new Error("/evolve-harness-retry requires an operator retry reason");
				args = ["run", "python", "apps/harness/experiment.py", "retry", root, reason];
			} else {
				args = ["run", "python", "apps/harness/experiment.py", "resume", root];
			}
		} else if (action === "solution") {
			const harnessRoot = await latestCodingRoot("harness");
			if (!harnessRoot) throw new Error("run /evolve-harness before evolving a solution");
			root = newCodingRunRoot("solution");
			args = [
				"run",
				"python",
				"apps/coding_agent/solution_experiment.py",
				"pi",
				configuredTaskProfile(profileArgument),
				root,
				runtime,
				join(harnessRoot, "selected-harness.json"),
			];
		} else if (action === "solution-resume" || action === "solution-retry") {
			const latest = await latestCodingRoot("solution", false);
			if (!latest) throw new Error("no resumable coding solution run exists");
			root = latest;
			if (action === "solution-retry") {
				const reason = profileArgument.trim();
				if (!reason) throw new Error("/evolve-code-retry requires an operator retry reason");
				args = ["run", "python", "apps/coding_agent/solution_experiment.py", "retry", root, reason];
			} else {
				args = ["run", "python", "apps/coding_agent/solution_experiment.py", "resume", root];
			}
		} else {
			const latest = await latestCodingRoot("solution");
			if (!latest) throw new Error("no completed coding solution run exists");
			root = latest;
			args = ["run", "python", "apps/coding_agent/solution_experiment.py", "verify", root];
		}
		const runKind = action.startsWith("harness") ? "harness" : "solution";
		const initial = processProjection(
			runKind === "harness" && action === "harness"
				? 1
				: runKind === "harness"
					? 2
					: action === "solution-verify"
						? 6
						: 4,
		);
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
		action: Exclude<WorkflowAction, "status">,
		ctx: ExtensionContext,
		argument = "",
	): Promise<void> {
		if (ctx.mode !== "tui") {
			ctx.ui.notify("Agentvolve workflow commands require interactive Pi", "error");
			return;
		}
		const result = await ctx.ui.custom<LoaderResult | null>((tui, theme, _keybindings, done) => {
			const label =
				action === "run"
					? "Running the unified Agentvolve workflow [1/6] → [6/6]…"
					: action === "resume"
						? "Resuming the current Agentvolve workflow stage…"
						: action === "retry"
							? "Retrying the explicitly approved pending workflow attempt…"
							: "Verifying the completed Agentvolve workflow offline…";
			const loader = new BorderedLoader(tui, theme, label);
			loader.onAbort = () => done(null);
			executeWorkflow(action, ctx, argument, loader.signal)
				.then((summary) => done({ summary }))
				.catch((error) => done({ error: String(error) }));
			return loader;
		});
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
		action:
			| "harness"
			| "harness-resume"
			| "harness-retry"
			| "solution"
			| "solution-resume"
			| "solution-retry"
			| "solution-verify",
		ctx: ExtensionContext,
		profileArgument = "",
	): Promise<void> {
		if (ctx.mode !== "tui") {
			ctx.ui.notify("Agentvolve commands require interactive Pi", "error");
			return;
		}
		const result = await ctx.ui.custom<LoaderResult | null>((tui, theme, _keybindings, done) => {
			const label =
				action === "harness"
					? "[1/6] Validating configuration; then [2/6] evolving the harness…"
					: action === "harness-resume"
						? "[2/6] Resuming committed harness-evolution effects…"
						: action === "harness-retry"
							? "[2/6] Retrying an explicitly approved harness model attempt…"
							: action === "solution"
								? "[4/6] Evolving immutable solution commits…"
								: action === "solution-resume"
									? "[4/6] Resuming committed coding evolution effects…"
									: action === "solution-retry"
										? "[4/6] Retrying an explicitly approved model attempt…"
										: "[6/6] Replaying coding evolution evidence…";
			const loader = new BorderedLoader(tui, theme, label);
			loader.onAbort = () => done(null);
			executeCoding(action, ctx, profileArgument, loader.signal)
				.then((summary) => done({ summary }))
				.catch((error) => done({ error: String(error) }));
			return loader;
		});
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
		const result = await ctx.ui.custom<LoaderResult | null>((tui, theme, _keybindings, done) => {
			const label = action === "run" ? "Running isolated Population evolution…" : "Replaying offline verification…";
			const loader = new BorderedLoader(tui, theme, label);
			loader.onAbort = () => done(null);
			execute(action, ctx, loader.signal)
				.then((summary) => done({ summary }))
				.catch((error) => done({ error: String(error) }));
			return loader;
		});
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

	async function showCodingStatus(kind: "harness" | "solution", ctx: ExtensionContext): Promise<void> {
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

	pi.registerCommand("agentvolve", {
		description: "Open Agentvolve in local Qwen or routed Pi model mode",
		handler: async (args, ctx) => {
			if (args.trim()) {
				ctx.ui.notify("/agentvolve accepts no arguments; choose an action in the UI", "error");
				return;
			}
			await openAgentvolve(ctx);
		},
	});

	pi.registerCommand("agentvolve-history", {
		description: "Browse shared Agentvolve workflow history from any Pi session",
		handler: async (args, ctx) => {
			if (args.trim()) {
				ctx.ui.notify("/agentvolve-history accepts no arguments", "error");
				return;
			}
			await showWorkflowHistory(ctx);
		},
	});

	pi.registerCommand("evolve", {
		description: "Run one sealed two-generation Population experiment",
		handler: async (args, ctx) => {
			if (args.trim()) {
				ctx.ui.notify("/evolve accepts no arguments; fixed policy chooses the run identity", "error");
				return;
			}
			await commandWithLoader("run", ctx);
		},
	});

	pi.registerCommand("evolve-status", {
		description: "Show the latest Population experiment result",
		handler: async (_args, ctx) => {
			try {
				const summary = await execute("status", ctx);
				renderModeWidget(ctx, summary);
				ctx.ui.notify(humanSummary(summary), "info");
			} catch (error) {
				ctx.ui.notify(String(error), "error");
			}
		},
	});

	pi.registerCommand("evolve-verify", {
		description: "Offline-verify the latest Population experiment",
		handler: async (args, ctx) => {
			if (args.trim()) {
				ctx.ui.notify("/evolve-verify accepts no arguments and verifies the latest fixed run", "error");
				return;
			}
			await commandWithLoader("verify", ctx);
		},
	});

	pi.registerCommand("evolve-harness", {
		description: "Evolve and final-seal a Pi harness on coding tasks",
		handler: async (args, ctx) => {
			if (args.trim()) {
				ctx.ui.notify("/evolve-harness accepts no arguments", "error");
				return;
			}
			await codingLoader("harness", ctx);
		},
	});

	pi.registerCommand("evolve-harness-status", {
		description: "Show the latest harness run and its six-stage process position",
		handler: async (args, ctx) => {
			if (args.trim()) {
				ctx.ui.notify("/evolve-harness-status accepts no arguments", "error");
				return;
			}
			await showCodingStatus("harness", ctx);
		},
	});

	pi.registerCommand("evolve-harness-resume", {
		description: "Resume committed effects in the latest coding harness run",
		handler: async (args, ctx) => {
			if (args.trim()) {
				ctx.ui.notify("/evolve-harness-resume accepts no arguments", "error");
				return;
			}
			await codingLoader("harness-resume", ctx);
		},
	});

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

	pi.registerCommand("evolve-code-resume", {
		description: "Resume committed effects in the latest coding solution run",
		handler: async (args, ctx) => {
			if (args.trim()) {
				ctx.ui.notify("/evolve-code-resume accepts no arguments", "error");
				return;
			}
			await codingLoader("solution-resume", ctx);
		},
	});

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

	pi.registerCommand("evolve-code-status", {
		description: "Show the latest solution run and its six-stage process position",
		handler: async (args, ctx) => {
			if (args.trim()) {
				ctx.ui.notify("/evolve-code-status accepts no arguments", "error");
				return;
			}
			await showCodingStatus("solution", ctx);
		},
	});

	pi.registerCommand("evolve-code-verify", {
		description: "Offline-verify the latest Agentvolve solution",
		handler: async (args, ctx) => {
			if (args.trim()) {
				ctx.ui.notify("/evolve-code-verify accepts no arguments", "error");
				return;
			}
			await codingLoader("solution-verify", ctx);
		},
	});

	pi.registerTool({
		name: "population_evolution",
		label: "Population Evolution",
		description:
			"Run, inspect, or offline-verify the fixed mutation-only Population experiment. The run action can take several minutes. It returns only bounded sealed results and accepts no task, candidate, evaluator, or command input.",
		promptSnippet: "Run or verify the fixed isolated Population evolutionary harness",
		promptGuidelines: [
			"Use population_evolution only when the user explicitly asks to run, inspect, or verify Agentvolve's fixed reference Population assay; never emulate its recurrence with bash or file-editing tools.",
		],
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
			const summary = await execute(params.action, ctx, signal);
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
		description:
			"Run or inspect Agentvolve's fixed Pi coding-harness and solution evolution using only the operator-approved METERING_EVOLUTION_TASK_PROFILE. It accepts no task text, command, evaluator, candidate, or output path.",
		promptSnippet: "Run independently evaluated Agentvolve coding evolution",
		promptGuidelines: [
			"Use darwinian_coding only after the user explicitly requests harness or solution evolution. Never substitute ordinary in-place edits for its immutable candidates and independent assays.",
		],
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
		return {
			systemPrompt: `${event.systemPrompt}\n\n[${MODE_NAME.toUpperCase()}]\nAgentvolve mode is active in ${activeModelMode} outer-session model mode (${activeModelLabel}). When the user explicitly asks for the reference assay, use population_evolution. For coding-harness or immutable solution evolution, use darwinian_coding; solution_run is valid only with an operator-approved METERING_EVOLUTION_TASK_PROFILE. Nested evolution calls remain bound to the provider, model, reasoning level, and budgets in the canonical runtime manifest; routed outer-session mode does not rewrite that evidence identity. Fixed code owns mutation transport, independent evaluation, exact Population recurrence, protected final assays, Docker isolation, receipts, and sealing. Never replace these authorities with ordinary in-place edits or describe an unevaluated edit as evolved.`,
		};
	});
}
