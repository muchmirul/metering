// Deterministic provider for the deployed extension; no network or live model.
import { appendFileSync, readFileSync } from "node:fs";
import { createAssistantMessageEventStream } from "@earendil-works/pi-ai";

export default function (pi: any) {
	pi.registerCommand("job-test-legacy", { handler: async () => {
		pi.appendEntry("agentvolve-mode", { active: true, modelMode: "routed" });
		pi.sendMessage({ customType: "agentvolve-mode", content: "Agentvolve operator mode is active. Never solve by ordinary edits instead of Agentvolve.", display: true });
	} });
	pi.registerCommand("job-test-record", { handler: async (args: string, ctx: any) => {
		pi.appendEntry("agentvolve-submission", { ...JSON.parse(args), sessionId: ctx.sessionManager.getSessionId() });
	} });
	pi.registerCommand("job-test-configuration-record", { handler: async (args: string) => {
		pi.appendEntry("agentvolve-execution-configuration", JSON.parse(args));
	} });
	pi.registerCommand("job-test-reload", { handler: async (_args: string, ctx: any) => { await ctx.reload(); } });
	pi.registerCommand("job-test-tree", { handler: async (id: string, ctx: any) => { await ctx.navigateTree(id, { summarize: false }); } });
	pi.registerCommand("job-test-tools", { handler: async () => { pi.appendEntry("job-test-tools", pi.getAllTools()); } });
	pi.registerProvider("job-fixture", {
		baseUrl: "http://localhost.invalid", apiKey: "fixture", api: "job-fixture-api",
		models: ["fixture", "other"].map(id => ({ id, name: id, reasoning: false, input: ["text"],
			cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0 }, contextWindow: 200000, maxTokens: 8000 })),
		streamSimple(model: any, context: any) {
			appendFileSync(process.env.JOB_PROMPT_LOG!, JSON.stringify({ prompt: context.systemPrompt, tools: context.tools?.map((t: any) => t.name), model: model.id, environment: Object.fromEntries(["PI_CODING_AGENT_DIR", "METERING_PI_CONFIG_DIR", "METERING_EVOLUTION_RUNTIME_MANIFEST", "METERING_EVOLUTION_HARNESS_DESCRIPTOR"].map(key => [key, process.env[key] ?? null])) }) + "\n");
			const stream = createAssistantMessageEventStream();
			queueMicrotask(() => {
				const message: any = { role: "assistant", content: [], api: model.api, provider: model.provider,
					model: model.id, timestamp: Date.now(), stopReason: "stop",
					usage: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0, totalTokens: 0,
						cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0, total: 0 } } };
				const last = context.messages.at(-1);
				const request = last?.role === "user" ? JSON.stringify(last.content) : "";
				const drafting = context.systemPrompt.startsWith("You create an Agentvolve task draft");
				const action = request.includes("Job status") ? "workflow_status" : request.includes("Verify job") ? "workflow_verify"
					: request.includes("Prepare job") ? "workflow_from_session" : request.includes("Configure worker") ? "workflow_configure" : undefined;
				const tool = drafting ? undefined : action ? { name: "darwinian_coding", arguments: { action } }
					: request.includes("Write normal file") ? { name: "write", arguments: { path: "normal.txt", content: "normal coding\n" } }
					: request.includes("Edit normal file") ? { name: "edit", arguments: { path: "normal.txt", edits: [{ oldText: "normal coding", newText: "normal edits" }] } }
					: request.includes("Read normal file") ? { name: "read", arguments: { path: "normal.txt" } }
					: request.includes("Bash normal file") ? { name: "bash", arguments: { command: "printf 'ordinary bash\\n' > bash.txt" } } : undefined;
				stream.push({ type: "start", partial: message });
				if (tool) {
					const call = { type: "toolCall", id: `job-${Date.now()}`, ...tool };
					message.content.push(call);
					stream.push({ type: "toolcall_start", contentIndex: 0, partial: message });
					stream.push({ type: "toolcall_end", contentIndex: 0, toolCall: call, partial: message });
					message.stopReason = "toolUse";
				} else {
					const text = drafting ? readFileSync(process.env.JOB_DRAFT!, "utf8") : "Job probe complete.";
					message.content.push({ type: "text", text });
					stream.push({ type: "text_start", contentIndex: 0, partial: message });
					stream.push({ type: "text_end", contentIndex: 0, content: text, partial: message });
				}
				stream.push({ type: "done", reason: message.stopReason, message });
				stream.end();
			});
			return stream;
		},
	});
}
