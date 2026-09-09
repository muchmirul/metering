import { homedir } from "node:os";
import { isAbsolute, resolve } from "node:path";
import type { ExtensionAPI, ExtensionContext, SessionEntry } from "@earendil-works/pi-coding-agent";
import { decodeOutput, repositoryRoot, runsDirectory, runtimeManifest } from "./population_evolution_support.ts";

export interface ExecutionConfiguration {
	manifest: string;
	harness: string;
	configuration: string;
}
export interface ExecutionReview extends ExecutionConfiguration {
	document: Record<string, unknown>;
	summary: string;
}
const SCHEMA = "agentvolve-execution-configuration-v1";
const PATH_KEYS = ["manifest", "harness", "configuration"] as const;

export function executionDefaults(): Partial<ExecutionConfiguration> {
	return { manifest: runtimeManifest(), harness: process.env.METERING_EVOLUTION_HARNESS_DESCRIPTOR?.trim(),
		configuration: process.env.METERING_PI_CONFIG_DIR?.trim() };
}

export function completeExecution(value: Partial<ExecutionConfiguration>): value is ExecutionConfiguration {
	return PATH_KEYS.every((key) => typeof value[key] === "string" && value[key]!.length > 0);
}

export function executionRecord(configuration: ExecutionConfiguration, sessionId: string): Record<string, unknown> {
	return { schema: SCHEMA, sessionId, manifest: configuration.manifest,
		harness: configuration.harness, configuration: configuration.configuration };
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
			harness: data.harness as string, configuration: data.configuration as string } };
	}
	return result;
}

export async function reviewExecution(pi: ExtensionAPI, ctx: ExtensionContext, paths: ExecutionConfiguration,
	signal: AbortSignal): Promise<ExecutionReview> {
	signal.throwIfAborted();
	const document = decodeOutput(await pi.exec("uv", ["run", "python", "-m", "connectors.fixed.pi.runtime",
		"review-configured", paths.manifest, paths.harness, paths.configuration],
		{ cwd: repositoryRoot(), signal, timeout: 120_000 }));
	signal.throwIfAborted();
	if (document.review_schema !== "agentvolve-execution-review-v1" || document.authority !== "diagnostic-only" ||
		typeof document.runtime_id !== "string" || typeof document.harness_candidate_id !== "string" ||
		typeof document.worker_configuration !== "string" || !Array.isArray(document.command) ||
		typeof document.model !== "object" || document.model === null) throw new Error("Unexpected worker execution review.");
	const interactive = ctx.model ? `${ctx.model.provider}/${ctx.model.id}` : "no model selected";
	const summary = `Interactive drafting only: ${interactive}\nDelegated worker execution (not the interactive model):\n${JSON.stringify(document, null, 2)}\nRuntime manifest: ${paths.manifest}\nReused verified harness: ${paths.harness}\nNo Level-2 search is authorized by this job. Worker calls use isolated Pi configuration and no host session/tools.\nAfter task approval, fixed code copies only models.json and optional auth.json into a private per-job directory. Recovery uses that job's command/configuration, not future session settings. Secrets are not stored in session records.\nNo main-Pi restart or global environment change is needed. Controller paths remain operator-managed: do not edit the live controller or job-owned configuration/evidence. Version isolation is not a host sandbox.`;
	return { ...paths, document, summary };
}

async function inputPath(ctx: ExtensionContext, title: string, suggested: string | undefined, signal: AbortSignal): Promise<string | undefined> {
	for (;;) {
		signal.throwIfAborted();
		const input = await ctx.ui.input(title + (suggested ? " (blank keeps the suggested path)" : ""), suggested ?? "Existing path; cancel to ask the assistant for setup help", { signal });
		signal.throwIfAborted();
		if (input === undefined) return undefined;
		let path = input.trim() || suggested || "";
		if (path.length >= 2 && (path[0] === '"' && path.at(-1) === '"' || path[0] === "'" && path.at(-1) === "'")) path = path.slice(1, -1);
		if (!path || path.length > 4096 || /[\x00-\x1f\x7f]/.test(path)) {
			ctx.ui.notify(`${title} needs an existing path. Blank cannot choose an unknown file. Enter the path, or cancel and ask the assistant to prepare missing setup; nothing has been saved or started.`, "warning");
			continue;
		}
		return resolve(ctx.cwd, path.startsWith("~/") ? resolve(homedir(), path.slice(2)) : path);
	}
}

interface SetupOption extends ExecutionConfiguration {
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
		if (![...PATH_KEYS, "runtime_id", "harness_candidate_id", "provider", "model", "model_label", "implementation_version"].every(key =>
			typeof item[key] === "string" && (item[key] as string).length > 0 && (item[key] as string).length <= 4096 && !/[\x00-\x1f\x7f]/.test(item[key] as string)) ||
			!PATH_KEYS.every(key => isAbsolute(item[key] as string)) ||
			!["runtime_id", "harness_candidate_id", "worker_models_sha256"].every(key => /^[a-f0-9]{64}$/.test(item[key] as string)) ||
			!Number.isSafeInteger(item.recorded_final_total) || (item.recorded_final_total as number) <= 0 || item.recorded_final_passed !== item.recorded_final_total) throw new Error("Invalid worker setup option.");
		return item as unknown as SetupOption;
	});
	const issues = result.issues.map((value: unknown) => {
		if (!value || typeof value !== "object" || typeof (value as Record<string, unknown>).message !== "string") throw new Error("Invalid setup diagnosis.");
		return String((value as Record<string, unknown>).message).slice(0, 2048);
	});
	return { options, issues };
}

export async function configureExecution(pi: ExtensionAPI, ctx: ExtensionContext, suggested: Partial<ExecutionConfiguration>,
	signal: AbortSignal): Promise<ExecutionReview | undefined> {
	if (!ctx.hasUI) throw new Error("Worker configuration requires direct approval in interactive or RPC Pi.");
	const catalogue = await discoverSetup(pi, suggested, signal);
	let chosen: SetupOption | undefined;
	if (catalogue.options.length) {
		const labels = catalogue.options.map((option, index) => `${index + 1}. ${option.model_label} · ${option.provider}/${option.model} · Pi ${option.implementation_version} · harness ${option.harness_candidate_id.slice(0, 12)} (${option.recorded_final_passed}/${option.recorded_final_total}; verify on selection)`);
		const selected = await ctx.ui.select("Choose Agentvolve worker setup (no job starts)", [...labels, "Enter existing paths (advanced)"], { signal });
		signal.throwIfAborted();
		if (selected === undefined) return undefined;
		if (selected !== "Enter existing paths (advanced)") {
			chosen = catalogue.options[labels.indexOf(selected)];
			if (!chosen) throw new Error("Worker setup selection did not resolve.");
		}
	} else if (catalogue.issues.length) {
		const diagnosis = catalogue.issues.join("\n");
		ctx.ui.notify(diagnosis, "warning");
		const selected = await ctx.ui.select("Agentvolve setup needs preparation", ["Return diagnosis to the assistant", "Enter existing paths (advanced)"], { signal });
		signal.throwIfAborted();
		if (selected === undefined) return undefined;
		if (selected !== "Enter existing paths (advanced)") throw new Error(`Agentvolve setup needs preparation:\n${diagnosis}\nNo job started. Ordinary tools remain available for separately approved setup.`);
	}
	let paths: ExecutionConfiguration;
	if (chosen) paths = chosen;
	else {
		const manifest = await inputPath(ctx, "Agentvolve worker runtime manifest", suggested.manifest, signal);
		if (manifest === undefined) return undefined;
		const harness = await inputPath(ctx, "Agentvolve compatible sealed selected-harness.json", suggested.harness, signal);
		if (harness === undefined) return undefined;
		const configuration = await inputPath(ctx, "Agentvolve separate worker Pi configuration directory", suggested.configuration, signal);
		if (configuration === undefined) return undefined;
		paths = { manifest, harness, configuration };
	}
	const reviewed = await reviewExecution(pi, ctx, paths, signal);
	if (chosen && (reviewed.document.runtime_id !== chosen.runtime_id || reviewed.document.harness_candidate_id !== chosen.harness_candidate_id || reviewed.document.worker_models_sha256 !== chosen.worker_models_sha256)) throw new Error("Selected setup changed during discovery; select and review again. No job started.");
	if (!(await ctx.ui.confirm("Save Agentvolve worker configuration for this session?", reviewed.summary +
		"\n\nOnly these path selections are saved for future task reviews. This does not start a worker, fund harness setup, alter an existing job, copy credentials yet, or change ordinary Pi tools/model/configuration.", { signal }))) return undefined;
	signal.throwIfAborted();
	return reviewed;
}
