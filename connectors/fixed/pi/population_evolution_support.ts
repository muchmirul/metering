import { existsSync } from "node:fs";
import { readdir, readFile } from "node:fs/promises";
import { homedir } from "node:os";
import { dirname, isAbsolute, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

import type { ExecResult } from "@earendil-works/pi-coding-agent";

const WORKFLOW_RUN_NAME = /^workflow-pi-\d{8}T\d{9}Z(?:-\d+)?$/;
const MAX_DIAGNOSTIC_CHARS = 4000;
const DEFAULT_LLAMACPP_SERVICE = "llama-qwen38.service";
const DEFAULT_LLAMACPP_HEALTH_URL = "http://127.0.0.1:8080/v1/models";

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
export interface ProcessProjection {
	display: string;
	stage: number;
}

export interface ModeSummary {
	process?: string;
	runRoot: string;
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
	offset: number;
	page_size: number;
	total_runs: number;
	next_offset: number | null;
}

export interface OperatorTraceView {
	authority: "projection-only";
	trace_schema: "agentvolve-trace-view-v1";
	workflow_root: string;
	offset: number;
	page_size: number;
	total_rounds: number;
	next_offset: number | null;
	experiments: Array<{
		kind: CodingKind;
		run_root: string;
		reused: boolean;
		report: Record<string, unknown> | null;
	}>;
	rounds: Array<OperatorRoundView & { kind: CodingKind; run_root: string }>;
}

export interface InspectionItem extends Record<string, unknown> {
	label: string;
	kind: CodingKind;
	run_root: string;
	reused: boolean;
	parent_label: string | null;
	tree_prefix?: string;
	status?: string;
	state?: string;
}

export interface OperatorTreeView {
	view_schema: "agentvolve-tree-view-v1";
	authority: "projection-only";
	mode: "tree" | "loops";
	workflow_root: string;
	items: InspectionItem[];
	offset: number;
	page_size: number;
	next_offset: number | null;
	total_items: number;
	warnings: string[];
}

export interface OperatorCandidateReport {
	view_schema: "agentvolve-candidate-report-v1";
	authority: "projection-only";
	mode: "candidate" | "loop";
	workflow_root: string;
	node: InspectionItem;
	evidence: Record<string, unknown> | null;
	events: Array<Record<string, unknown> & { step: string; summary: string; record_id: string | null }>;
	offset: number;
	page_size: number;
	next_offset: number | null;
	total_events: number;
	diff: {
		available: boolean;
		base_commit: string | null;
		commit: string | null;
		lines: string[];
		offset: number;
		page_size: number;
		next_offset: number | null;
		total_lines: number;
		warning: string | null;
	} | null;
	warnings: string[];
	verification: string;
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

export async function latestSealedHarnessRoot(): Promise<string | undefined> {
	const pattern = /^harness-pi-\d{8}T\d{6}(?:\d{3})?Z(?:-\d+)?$/;
	try {
		const entries = await readdir(runsDirectory(), { withFileTypes: true });
		return entries
			.filter((entry) => entry.isDirectory() && pattern.test(entry.name))
			.map((entry) => join(runsDirectory(), entry.name))
			.filter((root) => existsSync(join(root, "selected-harness.json")))
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
	return {
		process: processProjection(stage).display,
		runRoot: root,
		status: state,
	};
}

export async function codingWorkflowStatus(): Promise<ModeSummary> {
	const workflow = await latestWorkerWorkflowRoot();
	if (workflow && existsSync(join(workflow, "worker-status.json"))) return workerWorkflowStatus(workflow);
	return {
		runRoot: runsDirectory(),
		status: "not started",
	};
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
		!validPage(value, "total_runs", 50) ||
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

function inspectionItem(value: unknown, loop: boolean): boolean {
	const item = requiredObject(value, "inspection item");
	return typeof item.label === "string" && (loop ? /^[HS]R[1-9][0-9]*$/ : /^[HS](?:0|[1-9][0-9]*)$/).test(item.label) &&
		["harness", "solution"].includes(String(item.kind)) && typeof item.run_root === "string" &&
		typeof item.reused === "boolean" && nullableString(item.parent_label) &&
		(loop ? typeof item.state === "string" : ["retained", "eliminated", "selected", "not-yet-archived"].includes(String(item.status)));
}

function inspectionBase(value: Record<string, unknown>): boolean {
	return value.authority === "projection-only" && typeof value.workflow_root === "string" &&
		Array.isArray(value.warnings) && value.warnings.every((item) => typeof item === "string");
}

export function decodeOperatorTree(value: Record<string, unknown>): OperatorTreeView {
	if (!inspectionBase(value) || value.view_schema !== "agentvolve-tree-view-v1" ||
		!["tree", "loops"].includes(String(value.mode)) || !validPage(value, "total_items", 20) ||
		!Array.isArray(value.items) || value.items.length > 20 || !value.items.every((item) => inspectionItem(item, value.mode === "loops"))) {
		throw new Error("operator tree returned an unexpected schema");
	}
	return value as unknown as OperatorTreeView;
}

export function decodeCandidateReport(value: Record<string, unknown>): OperatorCandidateReport {
	if (!inspectionBase(value) || value.view_schema !== "agentvolve-candidate-report-v1" ||
		!["candidate", "loop"].includes(String(value.mode)) || !inspectionItem(value.node, value.mode === "loop") ||
		!validPage(value, "total_events", 10) || typeof value.verification !== "string" ||
		!Array.isArray(value.events) || value.events.length > 10 || !value.events.every((item) => {
			const event = requiredObject(item, "candidate event");
			return typeof event.step === "string" && typeof event.summary === "string" && nullableString(event.record_id);
		})) throw new Error("candidate report returned an unexpected schema");
	if (value.evidence !== null) requiredObject(value.evidence, "candidate evidence");
	if (value.diff !== null) {
		const diff = requiredObject(value.diff, "candidate diff");
		if (!validPage(diff, "total_lines", 40) || typeof diff.available !== "boolean" ||
			!nullableString(diff.base_commit) || !nullableString(diff.commit) || !nullableString(diff.warning) ||
			!Array.isArray(diff.lines) || diff.lines.length > 40 || !diff.lines.every((line) => typeof line === "string")) {
			throw new Error("candidate report returned an invalid diff page");
		}
	}
	return value as unknown as OperatorCandidateReport;
}

function validPage(value: Record<string, unknown>, totalKey: string, pageSize: number): boolean {
	return [value.offset, value[totalKey]].every((item) => Number.isSafeInteger(item) && Number(item) >= 0) &&
		value.page_size === pageSize &&
		(value.next_offset === null || (Number.isSafeInteger(value.next_offset) && value.next_offset === Number(value.offset) + pageSize && Number(value.next_offset) < Number(value[totalKey])));
}

export function decodeOperatorTrace(value: Record<string, unknown>): OperatorTraceView {
	if (value.trace_schema !== "agentvolve-trace-view-v1" || value.authority !== "projection-only" ||
		typeof value.workflow_root !== "string" || !validPage(value, "total_rounds", 20) ||
		!Array.isArray(value.experiments) || value.experiments.length > 2 ||
		!value.experiments.every((item) => {
			const experiment = requiredObject(item, "trace experiment");
			return ["harness", "solution"].includes(String(experiment.kind)) && typeof experiment.run_root === "string" &&
				typeof experiment.reused === "boolean" && (experiment.report === null || !!requiredObject(experiment.report, "trace report"));
		}) || !Array.isArray(value.rounds) || value.rounds.length > 20 ||
		!value.rounds.every((item) => {
			const round = requiredObject(item, "trace round");
			return ["harness", "solution"].includes(String(round.kind)) && typeof round.run_root === "string" &&
				[round.archive_members, round.attempts, round.retries].every(Number.isInteger) &&
				[round.round, round.parent_passed, round.challenger_passed].every(nullableInteger) &&
				[round.child_candidate_id, round.parent_candidate_id, round.selected_candidate_id, round.decision].every((item) => typeof item === "string");
		})) throw new Error("operator trace returned an unexpected schema");
	return value as unknown as OperatorTraceView;
}
