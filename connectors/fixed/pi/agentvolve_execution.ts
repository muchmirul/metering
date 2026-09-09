import { homedir } from "node:os";
import { isAbsolute, resolve } from "node:path";
import type { ExtensionAPI, ExtensionContext, SessionEntry } from "@earendil-works/pi-coding-agent";
import { decodeOutput, repositoryRoot, runtimeManifest } from "./population_evolution_support.ts";

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
	signal.throwIfAborted();
	const input = await ctx.ui.input(title + (suggested ? " (blank keeps the suggested path)" : ""), suggested ?? "Existing path; no shell command or secret", { signal });
	signal.throwIfAborted();
	if (input === undefined) return undefined;
	let path = input.trim() || suggested || "";
	if (path.length >= 2 && (path[0] === '"' && path.at(-1) === '"' || path[0] === "'" && path.at(-1) === "'")) path = path.slice(1, -1);
	if (!path || path.length > 4096 || /[\x00-\x1f\x7f]/.test(path)) throw new Error("Enter a non-empty path of at most 4096 characters without controls. Worker configuration was not saved.");
	return resolve(ctx.cwd, path.startsWith("~/") ? resolve(homedir(), path.slice(2)) : path);
}

export async function configureExecution(pi: ExtensionAPI, ctx: ExtensionContext, suggested: Partial<ExecutionConfiguration>,
	signal: AbortSignal): Promise<ExecutionReview | undefined> {
	if (!ctx.hasUI) throw new Error("Worker configuration requires direct approval in interactive or RPC Pi.");
	const manifest = await inputPath(ctx, "Agentvolve worker runtime manifest", suggested.manifest, signal);
	if (manifest === undefined) return undefined;
	const harness = await inputPath(ctx, "Agentvolve compatible sealed selected-harness.json", suggested.harness, signal);
	if (harness === undefined) return undefined;
	const configuration = await inputPath(ctx, "Agentvolve separate worker Pi configuration directory", suggested.configuration, signal);
	if (configuration === undefined) return undefined;
	const reviewed = await reviewExecution(pi, ctx, { manifest, harness, configuration }, signal);
	if (!(await ctx.ui.confirm("Save Agentvolve worker configuration for this session?", reviewed.summary +
		"\n\nOnly these path selections are saved for future task reviews. This does not start a worker, fund harness setup, alter an existing job, copy credentials yet, or change ordinary Pi tools/model/configuration.", { signal }))) return undefined;
	signal.throwIfAborted();
	return reviewed;
}
