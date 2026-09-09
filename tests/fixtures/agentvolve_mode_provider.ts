// Deterministic deployed-extension probe. Never calls a model or launches a worker.
import { appendFileSync } from "node:fs";
import { createAssistantMessageEventStream } from "@earendil-works/pi-ai";

export default function (pi: any) {
	pi.registerCommand("mode-test-legacy", { handler: async () => { pi.appendEntry("agentvolve-mode", { active: true, modelMode: "routed" }); } });
	pi.registerCommand("mode-test-reload", { handler: async (_args: string, ctx: any) => { await ctx.reload(); } });
	pi.registerCommand("mode-test-tree", { handler: async (id: string, ctx: any) => { await ctx.navigateTree(id, { summarize: false }); } });
	pi.registerProvider("mode-fixture", {
		baseUrl: "http://localhost.invalid", apiKey: "fixture", api: "mode-fixture-api",
		models: [{ id: "fixture", name: "Fixture", reasoning: false, input: ["text"],
			cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0 }, contextWindow: 200000, maxTokens: 1000 }],
		streamSimple(model: any, context: any) {
			appendFileSync(process.env.MODE_PROMPT_LOG!, JSON.stringify({ prompt: context.systemPrompt, tools: context.tools?.map((t: any) => t.name) }) + "\n");
			const stream = createAssistantMessageEventStream();
			queueMicrotask(() => {
				const message: any = { role: "assistant", content: [], api: model.api, provider: model.provider,
					model: model.id, timestamp: Date.now(), stopReason: "stop",
					usage: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0, totalTokens: 0,
						cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0, total: 0 } } };
				const last = context.messages.at(-1);
				const request = last?.role === "user" ? JSON.stringify(last.content) : "";
				const action = request.includes("Deactivate Agentvolve") ? "workflow_deactivate"
					: request.includes("Activate Agentvolve") ? "workflow_activate" : undefined;
				const sameTurnEdit = last?.role === "toolResult" && last.toolName === "darwinian_coding"
					&& JSON.stringify(context.messages.filter((m: any) => m.role === "user").at(-1)).includes("then edit normal file");
				if (sameTurnEdit && !context.systemPrompt.includes("workflow_deactivate immediately returns to normal coding")) {
					throw new Error("Turn-start operator instructions still forbid same-turn deactivation");
				}
				const tool = sameTurnEdit ? { name: "edit", arguments: { path: "normal.txt", edits: [{ oldText: "normal coding", newText: "normal edits" }] } }
					: action ? { name: "darwinian_coding", arguments: { action } }
					: request.includes("Write normal file") ? { name: "write", arguments: { path: "normal.txt", content: "normal coding\n" } }
					: request.includes("Edit normal file") ? { name: "edit", arguments: { path: "normal.txt", edits: [{ oldText: "normal coding", newText: "normal edits" }] } }
					: undefined;
				stream.push({ type: "start", partial: message });
				const calls = request.includes("Race mode calls")
					? ["workflow_activate", "workflow_deactivate"].map(action => ({ name: "darwinian_coding", arguments: { action } }))
					: tool ? [tool] : [];
				if (calls.length) {
					for (const [index, item] of calls.entries()) {
						const call = { type: "toolCall", id: `mode-${Date.now()}-${index}`, ...item };
						message.content.push(call);
						stream.push({ type: "toolcall_start", contentIndex: index, partial: message });
						stream.push({ type: "toolcall_end", contentIndex: index, toolCall: call, partial: message });
					}
					message.stopReason = "toolUse";
				} else {
					message.content.push({ type: "text", text: "Mode probe complete." });
					stream.push({ type: "text_start", contentIndex: 0, partial: message });
					stream.push({ type: "text_end", contentIndex: 0, content: "Mode probe complete.", partial: message });
				}
				stream.push({ type: "done", reason: message.stopReason, message });
				stream.end();
			});
			return stream;
		},
	});
}
