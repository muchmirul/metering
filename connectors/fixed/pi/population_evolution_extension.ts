import { existsSync } from "node:fs";
import { mkdir, readdir, readFile } from "node:fs/promises";
import { homedir } from "node:os";
import { dirname, isAbsolute, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

import { StringEnum } from "@earendil-works/pi-ai";
import {
	BorderedLoader,
	type ExecResult,
	type ExtensionAPI,
	type ExtensionContext,
} from "@earendil-works/pi-coding-agent";
import { Type } from "typebox";

const MODE_NAME = "Population Evolution Mode";
const STATUS_KEY = "population-evolution";
const WIDGET_KEY = "population-evolution";
const RUN_NAME = /^pi-\d{8}T\d{6}(?:\d{3})?Z$/;
const COMMAND_TIMEOUT_MS = 2 * 60 * 60 * 1000;
const MAX_DIAGNOSTIC_CHARS = 4000;

interface ModeSummary {
	action: "run" | "status" | "verify";
	candidateId?: string;
	finalPassed?: number;
	finalTasks?: number;
	runRoot: string;
	runtimeId?: string;
	status: string;
}

interface LoaderResult {
	error?: string;
	summary?: ModeSummary;
}

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

function runsDirectory(): string {
	return configuredAbsolutePath(
		"METERING_EVOLUTION_RUNS_DIR",
		resolve(repositoryRoot(), "..", "metering-live-runs"),
	);
}

function newRunRoot(): string {
	const timestamp = new Date().toISOString().replaceAll(/[-:.]/g, "");
	return join(runsDirectory(), `pi-${timestamp}`);
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

function boundedDiagnostic(value: string): string {
	const text = value.trim();
	return text.length <= MAX_DIAGNOSTIC_CHARS
		? text
		: `…${text.slice(-MAX_DIAGNOSTIC_CHARS)}`;
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
		runRoot,
		runtimeId: text(report.runtime_id),
		status: text(report.status) ?? "unknown",
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

function setModeStatus(ctx: ExtensionContext, state: "failed" | "ready" | "running"): void {
	const color = state === "failed" ? "error" : state === "running" ? "warning" : "accent";
	ctx.ui.setStatus(
		STATUS_KEY,
		ctx.ui.theme.fg(color, `population: ${state}`),
	);
}

function setModeWidget(ctx: ExtensionContext, summary?: ModeSummary): void {
	const lines = [
		ctx.ui.theme.fg("accent", `🧬 ${MODE_NAME}`) +
			ctx.ui.theme.fg("dim", " · /evolve · /evolve-status · /evolve-verify"),
	];
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
	const fields = [
		`${MODE_NAME}: ${summary.status}`,
		`run: ${summary.runRoot}`,
	];
	if (summary.finalPassed !== undefined && summary.finalTasks !== undefined) {
		fields.push(`protected final assay: ${summary.finalPassed}/${summary.finalTasks}`);
	}
	if (summary.candidateId) fields.push(`candidate: ${summary.candidateId}`);
	if (summary.runtimeId) fields.push(`runtime: ${summary.runtimeId}`);
	return fields.join("\n");
}

export default function populationEvolutionExtension(pi: ExtensionAPI): void {
	let running = false;

	async function execute(
		action: "run" | "status" | "verify",
		ctx: ExtensionContext,
		signal?: AbortSignal,
	): Promise<ModeSummary> {
		if (action === "status") return statusSummary();
		if (running) throw new Error("a Population evolution command is already running in this Pi session");

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
					? [
							"run",
							"python",
							"apps/harness/experiment.py",
							"pi",
							runRoot,
							runtime,
						]
					: ["run", "python", "apps/harness/experiment.py", "verify", runRoot];
			const result = await pi.exec("uv", args, {
				cwd: repositoryRoot(),
				signal,
				timeout: COMMAND_TIMEOUT_MS,
			});
			const report = decodeOutput(result);
			const summary =
				action === "run"
					? runSummary(runRoot, report)
					: verificationSummary(runRoot, report);
			setModeStatus(ctx, "ready");
			setModeWidget(ctx, summary);
			return summary;
		} catch (error) {
			setModeStatus(ctx, "failed");
			throw error;
		} finally {
			running = false;
		}
	}

	async function commandWithLoader(
		action: "run" | "verify",
		ctx: ExtensionContext,
	): Promise<void> {
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
				setModeWidget(ctx, summary);
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

	pi.registerTool({
		name: "population_evolution",
		label: "Population Evolution",
		description:
			"Run, inspect, or offline-verify the fixed mutation-only Population experiment. The run action can take several minutes. It returns only bounded sealed results and accepts no task, candidate, evaluator, or command input.",
		promptSnippet: "Run or verify the fixed isolated Population evolutionary harness",
		promptGuidelines: [
			"Use population_evolution only when the user explicitly asks to run, inspect, or verify Population Evolution Mode; never emulate its recurrence with bash or file-editing tools.",
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

	pi.on("session_start", async (_event, ctx) => {
		setModeStatus(ctx, "ready");
		try {
			const latest = await statusSummary();
			setModeWidget(ctx, latest);
		} catch {
			setModeWidget(ctx);
		}
		ctx.ui.notify(`${MODE_NAME} active. Use /evolve to start a sealed run.`, "info");
	});

	pi.on("before_agent_start", async (event) => ({
		systemPrompt: `${event.systemPrompt}\n\n[${MODE_NAME.toUpperCase()}]\nThe project-local Population control plane is active. When the user explicitly asks to run, inspect, or verify evolution, use population_evolution. Fixed code owns mutation transport, independent evaluation, exact Population recurrence, protected final assays, Docker isolation, receipts, and sealing. Do not replace those authorities with ordinary coding tools and do not describe an unevaluated edit as evolved.`,
	}));
}
