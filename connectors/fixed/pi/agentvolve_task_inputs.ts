import { mkdtemp, rm, stat, writeFile } from "node:fs/promises";
import { homedir, tmpdir } from "node:os";
import { basename, dirname, join, relative, resolve } from "node:path";

import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";

import { boundedDiagnostic, decodeOutput, repositoryRoot, runsDirectory, tasksDirectory } from "./population_evolution_support.ts";

export function parseDraftJson(text: string): unknown {
	if (Buffer.byteLength(text, "utf8") > 262_144) throw new Error("Task draft exceeds 256 KiB.");
	const value: unknown = JSON.parse(text);
	// JSON.parse alone silently accepts duplicate keys. Validate the lexical object
	// keys too, including escaped duplicates, before any task can be reviewed.
	const stack: Array<{ object: boolean; key: boolean; seen: Set<string> }> = [];
	for (const match of text.matchAll(/"(?:\\[\s\S]|[^"\\])*"|[{}\[\],:]/g)) {
		const token = match[0], frame = stack.at(-1);
		if (token === "{" || token === "[") stack.push({ object: token === "{", key: token === "{", seen: new Set() });
		else if (token === "}" || token === "]") stack.pop();
		else if (token === "," && frame?.object) frame.key = true;
		else if (token.startsWith('"') && frame?.object && frame.key) {
			const key = JSON.parse(token) as string;
			if (frame.seen.has(key)) throw new Error("Task draft contains duplicate JSON keys.");
			frame.seen.add(key); frame.key = false;
		}
	}
	return value;
}

export interface SourceSnapshot {
	uri: string;
	representation: "utf-8" | "html-text";
	sha256: string;
	content: string;
}

export function referenceTokens(text: string): string[] {
	// Literal user references only. No filesystem crawl or model-invented URLs.
	const urls = [...text.matchAll(/https?:\/\/[^\s<>"'`]+/g)].map((match) => match[0].replace(/[.,;!?)\]}]+$/, ""));
	const withoutUrls = text.replace(/https?:\/\/[^\s<>"'`]+/g, " ");
	const quoted = [...withoutUrls.matchAll(/[`"']([^`"'\n]+)[`"']/g)].map((match) => match[1]);
	const words = withoutUrls.replace(/[`"'][^`"'\n]+[`"']/g, " ").split(/\s+/);
	const paths = [...quoted, ...words].map((word) => word.replace(/^[([{]+|[),;!?:\]}]+$/g, "").replace(/\.$/, ""))
		.filter((word) => /^(?:\/|~\/|\.\/)[^\0]+$/.test(word) || /^(?:[\w .-]+\/)*[A-Za-z_][\w .-]*\.[A-Za-z][\w-]{0,15}$/.test(word));
	return [...new Set([...urls, ...paths])].slice(0, 64);
}

export function activeReferences(messages: string[]): string[] {
	for (const text of [...messages].reverse()) {
		const references = referenceTokens(text);
		if (references.length) return references;
	}
	return [];
}

export function localReference(reference: string, cwd: string): string | undefined {
	if (reference.startsWith("~/")) return resolve(homedir(), reference.slice(2));
	if (reference.startsWith("/") || reference.startsWith("./")) return resolve(cwd, reference);
	return undefined;
}

export async function mentionedRepositories(pi: ExtensionAPI, messages: string[], known: string[], cwd: string, signal: AbortSignal): Promise<string[]> {
	let inspected = 0;
	for (const text of [...messages].reverse()) {
		const matches = new Set<string>();
		for (const directory of known) {
			const name = basename(directory).replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
			if (new RegExp(`(?:\\b${name}\\s+(?:repo|repository)\\b|\\b(?:in|from|repo|repository)\\s+(?:the\\s+)?${name}\\b)`, "i").test(text)) matches.add(resolve(directory));
		}
		for (const reference of referenceTokens(text)) {
			const path = localReference(reference, cwd);
			if (!path) continue;
			let directory = path;
			try { if (!(await stat(path)).isDirectory()) directory = dirname(path); }
			catch { continue; }
			if (++inspected > 16) throw new Error("Too many referenced locations; narrow the task to at most sixteen inputs.");
			const result = await pi.exec("git", ["-C", directory, "rev-parse", "--show-toplevel"], { signal, timeout: 10_000 });
			signal.throwIfAborted();
			if (result.killed) throw new Error("Referenced repository discovery timed out; no workflow started.");
			if (result.code === 0) matches.add(resolve(result.stdout.trim()));
		}
		if (matches.size) return [...matches].sort();
	}
	return [];
}

export class TaskInputInspector {
	readonly snapshots = new Map<string, SourceSnapshot>();
	readonly readPaths = new Set<string>();
	readonly readUrls = new Set<string>();
	readonly readLocals = new Set<string>();
	readonly references: string[];
	readonly urls: string[];
	readonly localReferences = new Map<string, string>();

	constructor(private pi: ExtensionAPI, private repository: string, private commit: string | undefined,
		private files: string[], messages: string[], private cwd: string, private protectedPaths: string[] = []) {
		this.references = activeReferences(messages);
		const references = messages.flatMap(referenceTokens);
		this.urls = [...new Set(references.filter((ref) => /^https?:\/\//.test(ref)))];
		for (const ref of references) {
			const path = localReference(ref, cwd);
			if (path) this.localReferences.set(ref, path);
		}
	}

	get sources(): SourceSnapshot[] { return [...this.snapshots.values()].sort((a, b) => a.uri < b.uri ? -1 : a.uri > b.uri ? 1 : 0); }

	async prefetch(signal: AbortSignal): Promise<void> {
		const paths: string[] = [];
		for (const reference of this.references) {
			if (/^https?:\/\//.test(reference)) continue;
			const absolute = localReference(reference, this.cwd);
			const path = absolute ? relative(this.repository, absolute) : reference;
			const matches = this.files.filter((file) => file === path || (!absolute && !path.includes("/") && basename(file) === path));
			if (matches.length > 1) throw new Error(`Input ${JSON.stringify(reference)} is ambiguous: ${matches.map((file) => JSON.stringify(file)).join(", ")}. Specify which file; no workflow started.`);
			if (matches.length) {
				if (/\.(?:final|task)\.json$/.test(matches[0])) throw new Error("Task/evaluator profiles are not task-source inputs.");
				paths.push(matches[0]);
			}
		}
		// Outside-project paths and URLs may be examples or future outputs. Let the
		// drafter select required inputs from the literal allowlist; do not fetch a
		// URL or read an arbitrary host file merely because it was mentioned.
		await this.inspect([...new Set(paths)], [], [], signal);
	}

	async requested(document: Record<string, unknown>, signal: AbortSignal): Promise<void> {
		if (Object.keys(document).some((key) => !["read_files", "read_urls"].includes(key))) throw new Error("Source-read requests may contain only read_files and read_urls.");
		const paths = document.read_files ?? [], urls = document.read_urls ?? [];
		if (!Array.isArray(paths) || !Array.isArray(urls) || !paths.length && !urls.length ||
			new Set(paths).size !== paths.length || new Set(urls).size !== urls.length ||
			paths.some((path) => typeof path !== "string" || (!this.files.includes(path) && !this.localReferences.has(path)) || this.readPaths.has(path) || this.readLocals.has(this.localReferences.get(path) ?? path) || /\.(?:final|task)\.json$/.test(path)) ||
			urls.some((url) => typeof url !== "string" || !this.urls.includes(url) || this.readUrls.has(url))) {
			throw new Error("Drafting requested an unknown or already-read input. Only pinned tracked files and literal user file/URL references can be inspected; no workflow started.");
		}
		const tracked: string[] = [], local: string[] = [];
		for (const path of paths as string[]) {
			if (this.files.includes(path)) { tracked.push(path); continue; }
			const absolute = this.localReferences.get(path)!;
			const file = relative(this.repository, absolute);
			if (this.files.includes(file)) {
				if (this.readPaths.has(file)) throw new Error("That Git input was already read under its relative path.");
				tracked.push(file);
			} else local.push(absolute);
		}
		await this.inspect([...new Set(tracked)], [...new Set(local)], urls, signal);
		(paths as string[]).filter((path) => this.localReferences.has(path)).forEach((path) => this.readLocals.add(this.localReferences.get(path)!));
	}

	async ensureDraftInputs(document: Record<string, unknown>, signal: AbortSignal): Promise<boolean> {
		// A filename is not evidence. Inspect the declared entrypoint and known check
		// scripts, then require the drafter to reconsider its proposal with their bytes.
		const checks = Array.isArray(document.development_checks) ? document.development_checks : [];
		const names = [document.entrypoint, ...checks.flatMap((check) => Array.isArray(check?.argv) ? check.argv : [])];
		const paths = [...new Set(names.filter((path): path is string => typeof path === "string" && this.files.includes(path) && !this.readPaths.has(path)))];
		if (!paths.length) return false;
		await this.inspect(paths, [], [], signal);
		return true;
	}

	private async inspect(paths: string[], local_paths: string[], urls: string[], signal: AbortSignal): Promise<void> {
		if (!paths.length && !local_paths.length && !urls.length) return;
		if (paths.some((path) => /\.(?:final|task)\.json$/.test(path) || this.protectedPaths.some((protectedPath) => resolve(protectedPath) === resolve(this.repository, path)))) {
			throw new Error("Protected/operator profiles cannot be inspected as task-source inputs.");
		}
		const privateRoots = [tasksDirectory(), runsDirectory(), join(homedir(), ".pi"), join(homedir(), ".config", "metering"),
			join(homedir(), ".ssh"), join(homedir(), ".gnupg"), join(homedir(), ".aws")];
		if (local_paths.some((path) => this.protectedPaths.some((protectedPath) => resolve(protectedPath) === path) ||
			/\.(?:final|task)\.json$/.test(path) || /^(?:\.env(?:\..*)?|auth\.json|credentials(?:\.json)?|id_rsa|id_ed25519)$/.test(basename(path)) ||
			/\.(?:pem|key|p12|pfx)$/i.test(path) || privateRoots.some((root) => path === root || path.startsWith(root + "/")))) {
			throw new Error("Protected/operator or credential files cannot be used as task-source inputs. Supply a separate public or sanitized input document.");
		}
		if (this.snapshots.size + paths.length + local_paths.length + urls.length > 16) throw new Error("Preparation exceeds 16 source reads; narrow the task.");
		const temporary = await mkdtemp(join(tmpdir(), "agentvolve-inputs-"));
		try {
			const path = join(temporary, "request.json");
			await writeFile(path, JSON.stringify({ repository: this.repository, commit: this.commit ?? null, paths, local_paths, urls }), "utf8");
			const result = await this.pi.exec("uv", ["run", "python", "-m", "apps.coding_agent.task_sources", path], { cwd: repositoryRoot(), signal, timeout: 30_000 });
			signal.throwIfAborted();
			if (result.killed || result.code !== 0) throw new Error(result.killed ? "Source inspection timed out; narrow the input or try again explicitly." : boundedDiagnostic(result.stderr || result.stdout));
			const document = decodeOutput(result);
			if (document.source_schema !== "agentvolve-source-snapshots-v1" || !Array.isArray(document.sources)) throw new Error("Unexpected source inspection response.");
			for (const source of document.sources as SourceSnapshot[]) {
				if (this.snapshots.has(source.uri)) throw new Error("Input was already inspected; a task cannot silently replace a source snapshot.");
				this.snapshots.set(source.uri, source);
			}
			if (this.sources.reduce((total, source) => total + Buffer.byteLength(source.content, "utf8"), 0) > 131_072) throw new Error("Preparation exceeds 128 KiB of source content; narrow the task.");
			paths.forEach((path) => this.readPaths.add(path));
			urls.forEach((url) => this.readUrls.add(url));
		} finally { await rm(temporary, { recursive: true, force: true }); }
	}
}
