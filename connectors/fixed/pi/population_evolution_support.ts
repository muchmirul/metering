import { existsSync } from "node:fs";
import { readdir, readFile } from "node:fs/promises";
import { homedir } from "node:os";
import { dirname, isAbsolute, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

import type { ExecResult } from "@earendil-works/pi-coding-agent";

const RUN_NAME = /^pi-\d{8}T\d{6}(?:\d{3})?Z$/;
const WORKFLOW_RUN_NAME = /^workflow-pi-\d{8}T\d{9}Z(?:-\d+)?$/;
const MAX_DIAGNOSTIC_CHARS = 4000;
const DEFAULT_LLAMACPP_SERVICE = "llama-qwen38.service";
const DEFAULT_LLAMACPP_HEALTH_URL = "http://127.0.0.1:8080/v1/models";

export const COMMAND_TIMEOUT_MS = 2 * 60 * 60 * 1000;
export const LOCAL_RUNTIME_TIMEOUT_MS = 3 * 60 * 1000;
export const WORKFLOW_MONITOR_INTERVAL_MS = 2000;
export const PROCESS_LABELS: Record<number, string> = {
	1: "Task and runtime configured",
	2: "Evolving harness",
	3: "Harness sealed",
	4: "Evolving solution",
	5: "Protected final assay",
	6: "Result ready for review",
};

export type ThinkingLevel = "off" | "minimal" | "low" | "medium" | "high" | "xhigh" | "max";
export type CodingKind = "harness" | "solution";
export type CodingAction =
	| "harness"
	| "harness-resume"
	| "harness-retry"
	| "harness-status"
	| "solution"
	| "solution-resume"
	| "solution-retry"
	| "solution-status"
	| "solution-verify";

export interface ProcessProjection {
	display: string;
	stage: number;
}

export interface ModeSummary {
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

export interface RuntimeSelection {
	model: string;
	provider: string;
	reasoning: ThinkingLevel;
}

export interface DiscoveredTaskProfile {
	entrypoint: string;
	goal: string;
	name: string;
	path: string;
	repository: string;
}

export interface OperatorStageView {
	label: string;
	number: number;
	status: "complete" | "failed" | "pending" | "reused" | "running" | "waiting-retry";
	summary: string;
}

export interface OperatorRoundView {
	archive_members: number;
	attempts: number;
	challenger_passed: number | null;
	child_candidate_id: string;
	decision: string;
	parent_candidate_id: string;
	parent_passed: number | null;
	retries: number;
	round: number | null;
	selected_candidate_id: string;
}

export interface OperatorDiffView {
	child_candidate_id: string;
	deletions: number;
	files: Array<{ deletions: number | null; insertions: number | null; path: string }>;
	insertions: number;
	parent_candidate_id: string;
	preview_lines: string[];
	round: number | null;
	summary: string;
	truncated: boolean;
}

export interface OperatorProgressView {
	activity: string;
	authority: "projection-only";
	diff: OperatorDiffView | null;
	error: string | null;
	evolution: {
		activity: string | null;
		archive_member_count: number;
		completed_rounds: number;
		kind: CodingKind;
		max_rounds: number | null;
		pending_attempts: number;
		pending_parent_candidate_id: string | null;
		pending_round: number | null;
		pending_stage: string | null;
		proposal_calls: number;
		rounds: OperatorRoundView[];
	} | null;
	progress_schema: "agentvolve-progress-view-v1";
	result: Record<string, unknown> | null;
	stage: number;
	stage_label: string;
	stages: OperatorStageView[];
	state: string;
	task: { goal: string; max_rounds: number | null; repository: string | null; task_id: string | null } | null;
	updated_unix_ns: number | null;
	warnings: string[];
	worker: {
		alive: boolean | null;
		effect_pid: number | null;
		model: { connector: string; model: string; provider: string; reasoning: string } | null;
		pid: number | null;
		separation: string;
	};
	workflow_id: string;
	workflow_root: string;
}

export interface OperatorHistoryView {
	authority: "projection-only";
	history_schema: "agentvolve-history-view-v1";
	runs: Array<{
		goal: string | null;
		id: string;
		name: string;
		stage: number | null;
		stage_label: string;
		state: string;
		updated_unix_ns: number;
		warning?: string;
	}>;
	runs_directory: string;
}

export function repositoryRoot(): string {
	return resolve(dirname(fileURLToPath(import.meta.url)), "../../..");
}

function configuredAbsolutePath(name: string, fallback: string): string {
	const value = process.env[name];
	if (value !== undefined && !isAbsolute(value)) {
		throw new Error(`${name} must be an absolute path`);
	}
	return value ?? fallback;
}

export function runtimeManifest(): string {
	return configuredAbsolutePath(
		"METERING_EVOLUTION_RUNTIME_MANIFEST",
		join(homedir(), ".config", "metering", "harness", "runtime.pi.local.json"),
	);
}

export async function configuredRuntimeSelection(): Promise<RuntimeSelection> {
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

export function llamaCppService(): string {
	return process.env.METERING_EVOLUTION_LLAMACPP_SERVICE?.trim() || DEFAULT_LLAMACPP_SERVICE;
}

function llamaCppHealthUrl(): string {
	return process.env.METERING_EVOLUTION_LLAMACPP_HEALTH_URL?.trim() || DEFAULT_LLAMACPP_HEALTH_URL;
}

export async function llamaCppModelReady(selection: RuntimeSelection, signal?: AbortSignal): Promise<boolean> {
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

export function runsDirectory(): string {
	return configuredAbsolutePath("METERING_EVOLUTION_RUNS_DIR", resolve(repositoryRoot(), "..", "metering-live-runs"));
}

export function tasksDirectory(): string {
	return configuredAbsolutePath("METERING_EVOLUTION_TASKS_DIR", resolve(repositoryRoot(), "..", "metering-live-tasks"));
}

export async function discoverTaskProfiles(): Promise<DiscoveredTaskProfile[]> {
	let entries: Array<{ isFile(): boolean; name: string }>;
	try {
		entries = await readdir(tasksDirectory(), { withFileTypes: true });
	} catch {
		return [];
	}
	const profiles: DiscoveredTaskProfile[] = [];
	for (const entry of entries
		.filter((candidate) => candidate.isFile() && candidate.name.endsWith(".task.json"))
		.sort((left, right) => left.name.localeCompare(right.name))
		.slice(0, 200)) {
		const path = join(tasksDirectory(), entry.name);
		try {
			const value: unknown = JSON.parse(await readFile(path, "utf8"));
			if (typeof value !== "object" || value === null || Array.isArray(value)) continue;
			const document = value as Record<string, unknown>;
			const repositoryValue = document.repository;
			if (
				document.task_schema !== "darwinian-coding-task-v1" ||
				document.schema_version !== 1 ||
				typeof document.goal !== "string" ||
				typeof repositoryValue !== "object" ||
				repositoryValue === null ||
				Array.isArray(repositoryValue)
			) {
				continue;
			}
			const repository = repositoryValue as Record<string, unknown>;
			if (typeof repository.path !== "string" || typeof repository.entrypoint !== "string") continue;
			profiles.push({
				entrypoint: repository.entrypoint,
				goal: document.goal,
				name: entry.name.slice(0, -".task.json".length),
				path,
				repository: repository.path,
			});
		} catch {
			// Invalid files are not selectable; fixed profile validation still runs before execution.
		}
	}
	return profiles;
}

function timestamp(): string {
	return new Date().toISOString().replaceAll(/[-:.]/g, "");
}

export function newRunRoot(): string {
	return join(runsDirectory(), `pi-${timestamp()}`);
}

export function newCodingRunRoot(kind: CodingKind): string {
	return join(runsDirectory(), `${kind}-pi-${timestamp()}`);
}

export async function latestRunRoot(): Promise<string | undefined> {
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

export async function latestWorkerWorkflowRoot(): Promise<string | undefined> {
	try {
		const entries = await readdir(runsDirectory(), { withFileTypes: true });
		return entries
			.filter((entry) => entry.isDirectory() && WORKFLOW_RUN_NAME.test(entry.name))
			.map((entry) => join(runsDirectory(), entry.name))
			.sort()
			.reverse()[0];
	} catch {
		return undefined;
	}
}

export async function latestCodingRoot(kind: CodingKind, requireCompleted = true): Promise<string | undefined> {
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

export function configuredTaskProfile(argument: string): string {
	const supplied = argument.trim() || process.env.METERING_EVOLUTION_TASK_PROFILE;
	if (!supplied) {
		throw new Error("provide an absolute darwinian-coding-task-v1 path or set METERING_EVOLUTION_TASK_PROFILE");
	}
	if (!isAbsolute(supplied)) throw new Error("coding task profile must be an absolute path");
	if (!existsSync(supplied)) throw new Error(`coding task profile is unavailable: ${supplied}`);
	return supplied;
}

export function processProjection(stage: number): ProcessProjection {
	const label = PROCESS_LABELS[stage];
	if (!label) throw new Error(`unsupported Darwinian coding process stage: ${stage}`);
	return { display: `[${stage}/6] ${label}`, stage };
}

function integer(value: unknown): number | undefined {
	return Number.isInteger(value) ? (value as number) : undefined;
}

export async function readProcessProjection(
	runRoot: string,
	runKind: CodingKind,
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

export function boundedDiagnostic(value: string): string {
	const text = value.trim();
	return text.length <= MAX_DIAGNOSTIC_CHARS ? text : `…${text.slice(-MAX_DIAGNOSTIC_CHARS)}`;
}

export function decodeOutput(result: ExecResult): Record<string, unknown> {
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

export function runSummary(runRoot: string, report: Record<string, unknown>): ModeSummary {
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

export function verificationSummary(runRoot: string, report: Record<string, unknown>): ModeSummary {
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

export function codingSolutionSummary(
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

export async function codingStatusAtRoot(kind: CodingKind, root: string): Promise<ModeSummary> {
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

export async function codingStatus(kind: CodingKind): Promise<ModeSummary> {
	const root = await latestCodingRoot(kind, false);
	if (!root) throw new Error(`no coding ${kind} runs exist under ${runsDirectory()}`);
	return codingStatusAtRoot(kind, root);
}

export async function latestUnfinishedCodingRun(): Promise<{ kind: CodingKind; root: string } | null> {
	const runs: Array<{ kind: CodingKind; root: string }> = [];
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

async function projectedWorkerAlive(root: string, status: Record<string, unknown>): Promise<boolean> {
	const pid = integer(status.worker_pid);
	const token = text(status.worker_start_token);
	if (pid === undefined || pid <= 0 || token === undefined) return false;
	try {
		const stat = await readFile(join("/proc", String(pid), "stat"), "ascii");
		if (stat.trim().split(/\s+/)[21] !== token) return false;
		const command = await readFile(join("/proc", String(pid), "cmdline"));
		const fields = command.toString("utf8").split("\0");
		return fields.includes("apps.coding_agent.agentvolve_worker") && fields.includes(root);
	} catch {
		return false;
	}
}

async function workerWorkflowStatus(root: string): Promise<ModeSummary> {
	const statusValue: unknown = JSON.parse(await readFile(join(root, "worker-status.json"), "utf8"));
	if (typeof statusValue !== "object" || statusValue === null || Array.isArray(statusValue)) {
		throw new Error("Agentvolve worker status is malformed");
	}
	const status = statusValue as Record<string, unknown>;
	const stage = integer(status.stage);
	if (
		status.authority !== "projection-only" ||
		status.status_schema !== "agentvolve-worker-status-v1" ||
		stage === undefined ||
		!PROCESS_LABELS[stage] ||
		status.stage_label !== PROCESS_LABELS[stage] ||
		typeof status.state !== "string" ||
		typeof status.workflow_id !== "string"
	) {
		throw new Error("Agentvolve worker status has an unexpected identity");
	}
	let state = text(status.state) ?? "unknown";
	if (["queued", "running"].includes(state)) {
		const updated = integer(status.updated_unix_ns);
		const heartbeatAge = updated === undefined ? Number.POSITIVE_INFINITY : Date.now() - updated / 1_000_000;
		const alive = await projectedWorkerAlive(root, status);
		if (heartbeatAge >= 10_000 || (!alive && heartbeatAge >= 5_000)) state = "stalled";
	}
	let report: Record<string, unknown> | undefined;
	const reportPath = join(root, "workflow-report.json");
	if (existsSync(reportPath)) {
		const reportValue: unknown = JSON.parse(await readFile(reportPath, "utf8"));
		if (typeof reportValue === "object" && reportValue !== null && !Array.isArray(reportValue)) {
			report = reportValue as Record<string, unknown>;
			if (report.report_schema !== "agentvolve-workflow-report-v1" || report.workflow_id !== status.workflow_id) {
				throw new Error("Agentvolve workflow report does not match worker status");
			}
		}
	}
	return {
		action: "status",
		candidateId: text(report?.candidate_id),
		finalPassed: integer(report?.final_passed),
		finalTasks: integer(report?.final_tasks),
		kind: stage <= 3 ? "coding-harness" : "coding-solution",
		patchPath: text(report?.patch_path),
		process: processProjection(stage).display,
		runRoot: root,
		status: state,
	};
}

export async function codingWorkflowStatus(): Promise<ModeSummary> {
	const workflow = await latestWorkerWorkflowRoot();
	if (workflow && existsSync(join(workflow, "worker-status.json"))) return workerWorkflowStatus(workflow);
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

export async function workflowHistory(limit = 50): Promise<ModeSummary[]> {
	let entries: Array<{ isDirectory(): boolean; name: string }>;
	try {
		entries = await readdir(runsDirectory(), { withFileTypes: true });
	} catch {
		return [];
	}
	const names = entries
		.filter((entry) => entry.isDirectory() && /^(?:harness|solution)-pi-\d{8}T\d{6}(?:\d{3})?Z$/.test(entry.name))
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

function requiredObject(value: unknown, label: string): Record<string, unknown> {
	if (typeof value !== "object" || value === null || Array.isArray(value)) {
		throw new Error(`${label} must be an object`);
	}
	return value as Record<string, unknown>;
}

function nullableInteger(value: unknown): boolean {
	return value === null || Number.isInteger(value);
}

function nullableString(value: unknown): boolean {
	return value === null || typeof value === "string";
}

export function decodeOperatorProgress(value: Record<string, unknown>): OperatorProgressView {
	if (value.progress_schema !== "agentvolve-progress-view-v1" || value.authority !== "projection-only") {
		throw new Error("operator progress returned an unexpected schema");
	}
	const stage = integer(value.stage);
	const stages = value.stages;
	const stageStatuses = new Set(["complete", "failed", "pending", "reused", "running", "waiting-retry"]);
	if (
		stage === undefined ||
		!PROCESS_LABELS[stage] ||
		!Array.isArray(stages) ||
		stages.length !== 6 ||
		!stages.every((item, index) => {
			if (typeof item !== "object" || item === null || Array.isArray(item)) return false;
			const projected = item as Record<string, unknown>;
			return (
				projected.number === index + 1 &&
				projected.label === PROCESS_LABELS[index + 1] &&
				typeof projected.status === "string" &&
				stageStatuses.has(projected.status) &&
				typeof projected.summary === "string"
			);
		})
	) {
		throw new Error("operator progress returned an invalid stage projection");
	}
	const worker = requiredObject(value.worker, "operator progress worker");
	const model = worker.model === null ? null : requiredObject(worker.model, "operator progress worker model");
	const warnings = value.warnings;
	if (
		typeof value.activity !== "string" ||
		!nullableString(value.error) ||
		typeof value.state !== "string" ||
		typeof value.workflow_id !== "string" ||
		typeof value.workflow_root !== "string" ||
		!nullableInteger(value.updated_unix_ns) ||
		!Array.isArray(warnings) ||
		!warnings.every((warning) => typeof warning === "string") ||
		(worker.alive !== null && typeof worker.alive !== "boolean") ||
		!nullableInteger(worker.effect_pid) ||
		!nullableInteger(worker.pid) ||
		typeof worker.separation !== "string" ||
		(model !== null &&
			![model.connector, model.model, model.provider, model.reasoning].every((item) => typeof item === "string"))
	) {
		throw new Error("operator progress returned malformed summary fields");
	}
	if (value.evolution !== null) {
		const evolution = requiredObject(value.evolution, "operator progress evolution");
		if (
			(evolution.kind !== "harness" && evolution.kind !== "solution") ||
			!nullableString(evolution.activity) ||
			!Number.isInteger(evolution.archive_member_count) ||
			!Number.isInteger(evolution.completed_rounds) ||
			!nullableInteger(evolution.max_rounds) ||
			!Number.isInteger(evolution.pending_attempts) ||
			!nullableString(evolution.pending_parent_candidate_id) ||
			!nullableInteger(evolution.pending_round) ||
			!nullableString(evolution.pending_stage) ||
			!Number.isInteger(evolution.proposal_calls) ||
			!Array.isArray(evolution.rounds) ||
			!evolution.rounds.every((item) => {
				if (typeof item !== "object" || item === null || Array.isArray(item)) return false;
				const round = item as Record<string, unknown>;
				return (
					Number.isInteger(round.archive_members) &&
					Number.isInteger(round.attempts) &&
					nullableInteger(round.challenger_passed) &&
					typeof round.child_candidate_id === "string" &&
					typeof round.decision === "string" &&
					typeof round.parent_candidate_id === "string" &&
					nullableInteger(round.parent_passed) &&
					Number.isInteger(round.retries) &&
					nullableInteger(round.round) &&
					typeof round.selected_candidate_id === "string"
				);
			})
		) {
			throw new Error("operator progress returned malformed evolution fields");
		}
	}
	if (value.diff !== null) {
		const diff = requiredObject(value.diff, "operator progress diff");
		if (
			typeof diff.child_candidate_id !== "string" ||
			!Number.isInteger(diff.deletions) ||
			!Array.isArray(diff.files) ||
			!diff.files.every((item) => {
				if (typeof item !== "object" || item === null || Array.isArray(item)) return false;
				const file = item as Record<string, unknown>;
				return nullableInteger(file.deletions) && nullableInteger(file.insertions) && typeof file.path === "string";
			}) ||
			!Number.isInteger(diff.insertions) ||
			typeof diff.parent_candidate_id !== "string" ||
			!Array.isArray(diff.preview_lines) ||
			!diff.preview_lines.every((line) => typeof line === "string") ||
			!nullableInteger(diff.round) ||
			typeof diff.summary !== "string" ||
			typeof diff.truncated !== "boolean"
		) {
			throw new Error("operator progress returned malformed diff fields");
		}
	}
	if (value.result !== null) requiredObject(value.result, "operator progress result");
	if (value.task !== null) requiredObject(value.task, "operator progress task");
	return value as unknown as OperatorProgressView;
}

export function decodeOperatorHistory(value: Record<string, unknown>): OperatorHistoryView {
	if (
		value.history_schema !== "agentvolve-history-view-v1" ||
		value.authority !== "projection-only" ||
		!Array.isArray(value.runs) ||
		typeof value.runs_directory !== "string" ||
		!value.runs.every((item) => {
			if (typeof item !== "object" || item === null || Array.isArray(item)) return false;
			const run = item as Record<string, unknown>;
			return (
				nullableString(run.goal) &&
				typeof run.id === "string" &&
				typeof run.name === "string" &&
				nullableInteger(run.stage) &&
				typeof run.stage_label === "string" &&
				typeof run.state === "string" &&
				Number.isInteger(run.updated_unix_ns) &&
				(run.warning === undefined || typeof run.warning === "string")
			);
		})
	) {
		throw new Error("operator history returned an unexpected schema");
	}
	return value as unknown as OperatorHistoryView;
}

export async function statusSummary(): Promise<ModeSummary> {
	const runRoot = await latestRunRoot();
	if (!runRoot) throw new Error(`no Population runs exist under ${runsDirectory()}`);
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
