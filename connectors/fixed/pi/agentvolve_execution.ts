import { homedir } from "node:os";
import { isAbsolute, resolve } from "node:path";
import type { ExtensionAPI, ExtensionContext, SessionEntry } from "@earendil-works/pi-coding-agent";
import { decodeOutput, repositoryRoot, runsDirectory, runtimeManifest } from "./population_evolution_support.ts";

export interface ExecutionConfiguration {
	manifest: string;
	harness: string;
	configuration: string;
	runs: string;
}
export interface ExecutionReview extends ExecutionConfiguration {
	document: Record<string, unknown>;
	summary: string;
}
export type ExecutionInput = Partial<ExecutionConfiguration>;
export interface ExecutionInputDetails {
	status: "needs-configuration";
	missing: Array<keyof ExecutionConfiguration>;
	options: SetupOption[];
	issues: string[];
}
export class ExecutionInputRequired extends Error {
	constructor(message: string, readonly details: ExecutionInputDetails) {
		super(message);
		this.name = "ExecutionInputRequired";
	}
}
const SCHEMA = "agentvolve-execution-configuration-v2";
const PATH_KEYS = ["manifest", "harness", "configuration", "runs"] as const;
const EXECUTION_PATH_KEYS = ["manifest", "harness", "configuration"] as const;

export function executionDefaults(): Partial<ExecutionConfiguration> {
	return { manifest: runtimeManifest(), harness: process.env.METERING_EVOLUTION_HARNESS_DESCRIPTOR?.trim(),
		configuration: process.env.METERING_PI_CONFIG_DIR?.trim(),
		runs: process.env.METERING_EVOLUTION_RUNS_DIR?.trim() || resolve(homedir(), ".local/share/metering/agentvolve-runs") };
}

export function completeExecution(value: Partial<ExecutionConfiguration>): value is ExecutionConfiguration {
	return PATH_KEYS.every((key) => typeof value[key] === "string" && value[key]!.length > 0);
}

export function executionRecord(configuration: ExecutionConfiguration, sessionId: string): Record<string, unknown> {
	return { schema: SCHEMA, sessionId, manifest: configuration.manifest,
		harness: configuration.harness, configuration: configuration.configuration, runs: configuration.runs };
}

export function restoreExecution(entries: readonly SessionEntry[], sessionId: string): {
	configuration?: ExecutionConfiguration; invalid: boolean;
} {
	let result: { configuration?: ExecutionConfiguration; invalid: boolean } = { invalid: false };
	for (const entry of entries) {
		if (entry.type !== "custom" || entry.customType !== "agentvolve-execution-configuration") continue;
		const data = entry.data as Record<string, unknown> | null;
		if (!data || typeof data !== "object" || Array.isArray(data) || typeof data.sessionId !== "string" || !data.sessionId) {
			result = { invalid: true }; // Missing ownership is corruption, not permission to reuse an older selection.
			continue;
		}
		if (data.sessionId !== sessionId) continue;
		if (data.schema !== SCHEMA || Object.keys(data).sort().join() !== [...PATH_KEYS, "schema", "sessionId"].sort().join() ||
			!PATH_KEYS.every((key) => typeof data[key] === "string" && isAbsolute(data[key] as string) &&
				(data[key] as string).length <= 4096 && !/[\x00-\x1f\x7f]/.test(data[key] as string))) {
			result = { invalid: true }; // Never fall back to an older record/default on corruption.
		} else result = { invalid: false, configuration: { manifest: data.manifest as string,
			harness: data.harness as string, configuration: data.configuration as string, runs: data.runs as string } };
	}
	return result;
}

export async function reviewExecution(pi: ExtensionAPI, ctx: ExtensionContext, paths: ExecutionConfiguration,
	signal: AbortSignal): Promise<ExecutionReview> {
	signal.throwIfAborted();
	const document = decodeOutput(await pi.exec("uv", ["run", "python", "-m", "connectors.fixed.pi.runtime",
		"review-configured", paths.manifest, paths.harness, paths.configuration, paths.runs],
		{ cwd: repositoryRoot(), signal, timeout: 120_000 }));
	signal.throwIfAborted();
	if (document.review_schema !== "agentvolve-execution-review-v1" || document.authority !== "diagnostic-only" ||
		typeof document.runtime_id !== "string" || typeof document.harness_candidate_id !== "string" ||
		typeof document.worker_configuration !== "string" || document.runs_directory !== paths.runs || !Array.isArray(document.command) ||
		typeof document.model !== "object" || document.model === null) throw new Error("Unexpected worker execution review.");
	const interactive = ctx.model ? `${ctx.model.provider}/${ctx.model.id}` : "no model selected";
	const summary = `Interactive drafting only: ${interactive}\nDelegated worker execution (not the interactive model):\n${JSON.stringify(document, null, 2)}\nRuntime manifest: ${paths.manifest}\nReused verified harness: ${paths.harness}\nPrivate run registry: ${paths.runs}\nNo Level-2 search is authorized by this job. Worker calls use isolated Pi configuration and no host session/tools.\nAfter task validation, fixed code copies only models.json and optional auth.json into a private per-job directory. Recovery uses that job's command/configuration, not future session settings. Secrets are not stored in session records.\nNo main-Pi restart or global environment change is needed. Controller paths remain operator-managed: do not edit the live controller or job-owned configuration/evidence. Version isolation is not a host sandbox.`;
	return { ...paths, document, summary };
}

export interface SetupOption extends ExecutionConfiguration {
	runtime_id: string; harness_candidate_id: string; worker_models_sha256: string; provider: string; model: string;
	model_label: string; implementation_version: string; recorded_final_passed: number; recorded_final_total: number;
}

async function discoverSetup(pi: ExtensionAPI, suggested: Partial<ExecutionConfiguration>, signal: AbortSignal): Promise<{ options: SetupOption[]; issues: string[] }> {
	// Corrupt/ownerless restored configuration has no defaults. Require explicit repair.
	if (!suggested.manifest) return { options: [], issues: [] };
	const configuration = suggested.configuration || resolve(homedir(), ".config/metering/agentvolve-worker");
	const result = decodeOutput(await pi.exec("uv", ["run", "python", "-m", "connectors.fixed.pi.runtime", "discover-configured",
		runsDirectory(), suggested.manifest, configuration, ...(suggested.harness ? [suggested.harness] : [])],
		{ cwd: repositoryRoot(), signal, timeout: 30_000 }));
	signal.throwIfAborted();
	if (result.setup_schema !== "agentvolve-setup-discovery-v1" || result.authority !== "diagnostic-only" ||
		!Array.isArray(result.options) || result.options.length > 200 || !Array.isArray(result.issues) || result.issues.length > 10) throw new Error("Unexpected worker setup catalogue; nothing saved or started.");
	const options = result.options.map((value: unknown) => {
		if (!value || typeof value !== "object" || Array.isArray(value)) throw new Error("Invalid worker setup option.");
		const item = value as Record<string, unknown>;
		if (![...EXECUTION_PATH_KEYS, "runtime_id", "harness_candidate_id", "provider", "model", "model_label", "implementation_version"].every(key =>
			typeof item[key] === "string" && (item[key] as string).length > 0 && (item[key] as string).length <= 4096 && !/[\x00-\x1f\x7f]/.test(item[key] as string)) ||
			!EXECUTION_PATH_KEYS.every(key => isAbsolute(item[key] as string)) ||
			!["runtime_id", "harness_candidate_id", "worker_models_sha256"].every(key => /^[a-f0-9]{64}$/.test(item[key] as string)) ||
			!Number.isSafeInteger(item.recorded_final_total) || (item.recorded_final_total as number) <= 0 || item.recorded_final_passed !== item.recorded_final_total) throw new Error("Invalid worker setup option.");
		return { ...item, runs: suggested.runs || resolve(homedir(), ".local/share/metering/agentvolve-runs") } as unknown as SetupOption;
	});
	const issues = result.issues.map((value: unknown) => {
		if (!value || typeof value !== "object" || typeof (value as Record<string, unknown>).message !== "string") throw new Error("Invalid setup diagnosis.");
		return String((value as Record<string, unknown>).message).slice(0, 2048);
	});
	return { options, issues };
}

function configuredPath(value: string, key: keyof ExecutionConfiguration, cwd: string): string {
	let path = value.trim();
	if (path.length >= 2 && ((path[0] === '"' && path.at(-1) === '"') || (path[0] === "'" && path.at(-1) === "'"))) path = path.slice(1, -1);
	if (!path || path.length > 4096 || /[\x00-\x1f\x7f]/.test(path)) throw new Error(`Agentvolve ${key} must be a non-empty bounded path.`);
	return resolve(cwd, path === "~" ? homedir() : path.startsWith("~/") ? resolve(homedir(), path.slice(2)) : path);
}

export async function configureExecution(pi: ExtensionAPI, ctx: ExtensionContext, suggested: Partial<ExecutionConfiguration>,
	signal: AbortSignal, input: ExecutionInput = {}): Promise<ExecutionReview> {
	const proposed: Partial<ExecutionConfiguration> = { ...suggested };
	for (const key of PATH_KEYS) {
		const value = input[key];
		if (value !== undefined) proposed[key] = configuredPath(value, key, ctx.cwd);
	}
	let chosen: SetupOption | undefined;
	let paths: ExecutionConfiguration;
	if (completeExecution(proposed)) paths = proposed;
	else {
		const catalogue = await discoverSetup(pi, proposed, signal);
		if (catalogue.options.length === 1) {
			chosen = catalogue.options[0];
			paths = chosen;
		} else {
			const missing = PATH_KEYS.filter((key) => !proposed[key]);
			const choices = catalogue.options.map((option) => ({ ...option }));
			const summary = choices.length
				? `Found ${choices.length} compatible Agentvolve setups. Ask the user which worker/model to use, then call workflow_configure with that option's four paths.`
				: `Agentvolve needs these configuration fields: ${missing.join(", ")}. Ask the user for the missing paths and call workflow_configure again.`;
			throw new ExecutionInputRequired(
				catalogue.issues.length ? `${summary}\n${catalogue.issues.join("\n")}` : summary,
				{ status: "needs-configuration", missing, options: choices, issues: catalogue.issues },
			);
		}
	}
	// Explicit model-supplied configuration prepares only the selected empty
	// registry if absent. Discovery, restoration and ordinary review stay read-only.
	const registry = decodeOutput(await pi.exec("uv", ["run", "python", "-m", "connectors.fixed.pi.runtime",
		"prepare-registry", paths.runs], { cwd: repositoryRoot(), signal, timeout: 30_000 }));
	signal.throwIfAborted();
	if (registry.registry_schema !== "agentvolve-private-registry-v1" || registry.runs_directory !== paths.runs ||
		registry.mode !== "0700" || registry.inference_performed !== false) throw new Error("Private run registry preparation failed; no job started.");
	const reviewed = await reviewExecution(pi, ctx, paths, signal);
	if (chosen && (reviewed.document.runtime_id !== chosen.runtime_id || reviewed.document.harness_candidate_id !== chosen.harness_candidate_id || reviewed.document.worker_models_sha256 !== chosen.worker_models_sha256)) throw new Error("Selected setup changed during discovery; configure it again. No job started.");
	return reviewed;
}
