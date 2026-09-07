import type { ExtensionContext, Theme } from "@earendil-works/pi-coding-agent";
import { matchesKey, truncateToWidth, visibleWidth, wrapTextWithAnsi } from "@earendil-works/pi-tui";

import {
	PROCESS_LABELS,
	type OperatorDiffView,
	type OperatorProgressView,
	type OperatorRoundView,
	type OperatorTraceView,
} from "./population_evolution_support.ts";

const REFRESH_INTERVAL_MS = 2000;

function shortId(value: string | null | undefined): string {
	return value ? value.slice(0, 10) : "unknown";
}

function count(value: number | null | undefined): string {
	return value === null || value === undefined ? "?" : String(value);
}

function safeLine(value: string): string {
	return [...value]
		.map((character) => {
			const code = character.codePointAt(0) ?? 0;
			const unsafeUnicode = /[\p{Cc}\p{Cf}\p{Cs}\p{Co}\p{Zl}\p{Zp}]/u.test(character);
			return character === "\t" || (code >= 32 && code !== 127 && !unsafeUnicode) ? character : "?";
		})
		.join("");
}

function stageMarker(status: string): string {
	switch (status) {
		case "complete":
			return "✓";
		case "reused":
			return "↺";
		case "running":
			return "▶";
		case "waiting-retry":
			return "?";
		case "failed":
			return "!";
		default:
			return "○";
	}
}

function stageColor(status: string): "dim" | "error" | "muted" | "success" | "warning" {
	switch (status) {
		case "complete":
			return "success";
		case "reused":
			return "muted";
		case "running":
		case "waiting-retry":
			return "warning";
		case "failed":
			return "error";
		default:
			return "dim";
	}
}

function decisionLabel(round: OperatorRoundView): string {
	if (round.decision === "promote_challenger") return "promote";
	if (round.decision === "retain_incumbent") return "retain";
	return round.decision || "recorded";
}

class AgentvolveDashboard {
	private readonly theme: Theme;
	private readonly operatorModel: string;
	private readonly load: () => Promise<OperatorProgressView>;
	private readonly close: (action?: "tree") => void;
	private readonly requestRender: () => void;
	private readonly viewportRows: () => number;
	private progress: OperatorProgressView;
	private trace: OperatorTraceView;
	private readonly loadTrace: (offset: number) => Promise<OperatorTraceView>;
	private paging = false;
	private timer: ReturnType<typeof setInterval> | undefined;
	private refreshing = false;
	private disposed = false;
	private expandedDiff = false;
	private error: string | undefined;
	private scrollOffset = 0;
	private lastContentLength = 0;
	private lastCapacity = 1;

	constructor(
		theme: Theme,
		operatorModel: string,
		initial: OperatorProgressView,
		load: () => Promise<OperatorProgressView>,
		requestRender: () => void,
		viewportRows: () => number,
		close: (action?: "tree") => void,
		trace: OperatorTraceView,
		loadTrace: (offset: number) => Promise<OperatorTraceView>,
	) {
		this.theme = theme;
		this.operatorModel = operatorModel;
		this.progress = initial;
		this.trace = trace;
		this.loadTrace = loadTrace;
		if (["completed", "verified"].includes(initial.state)) this.scrollOffset = Number.MAX_SAFE_INTEGER;
		this.load = load;
		this.requestRender = requestRender;
		this.viewportRows = viewportRows;
		this.close = close;
		this.timer = setInterval(() => void this.refresh(), REFRESH_INTERVAL_MS);
	}

	private async refresh(): Promise<void> {
		if (this.refreshing || this.disposed) return;
		this.refreshing = true;
		try {
			this.error = undefined;
			const previousState = this.progress.state;
			this.progress = await this.load();
			if (!this.paging) await this.changeTracePage(this.trace.offset, false);
			if (
				!["completed", "verified"].includes(previousState) &&
				["completed", "verified"].includes(this.progress.state)
			) {
				this.scrollOffset = Number.MAX_SAFE_INTEGER;
			}
		} catch (error) {
			this.error = safeLine(String(error)).slice(-1000);
		} finally {
			this.refreshing = false;
			if (!this.disposed) this.requestRender();
		}
	}

	private async changeTracePage(offset: number, resetScroll = true): Promise<void> {
		if (this.paging || this.disposed) return;
		this.paging = true;
		try {
			this.trace = await this.loadTrace(offset);
			if (resetScroll) this.scrollOffset = 0;
			this.error = undefined;
		} catch (error) {
			this.error = safeLine(String(error)).slice(-1000);
		} finally {
			this.paging = false;
			if (!this.disposed) this.requestRender();
		}
	}

	handleInput(data: string): void {
		if (data === "t" || data === "T") {
			this.dispose();
			this.close("tree");
			return;
		}
		if (data === "[" && this.trace.offset > 0) {
			void this.changeTracePage(Math.max(0, this.trace.offset - this.trace.page_size));
			return;
		}
		if (data === "]" && this.trace.next_offset !== null) {
			void this.changeTracePage(this.trace.next_offset);
			return;
		}
		if (matchesKey(data, "pageUp") || matchesKey(data, "pageDown")) {
			this.scrollOffset = Math.max(0, Math.min(this.lastContentLength - this.lastCapacity,
				this.scrollOffset + (matchesKey(data, "pageUp") ? -this.lastCapacity : this.lastCapacity)));
			this.requestRender();
			return;
		}
		if (matchesKey(data, "escape") || matchesKey(data, "ctrl+c") || data === "q" || data === "Q") {
			this.dispose();
			this.close();
			return;
		}
		if (data === "r" || data === "R") {
			void this.refresh();
			return;
		}
		if (data === "d" || data === "D") {
			this.expandedDiff = !this.expandedDiff;
			this.requestRender();
			return;
		}
		if (matchesKey(data, "up")) {
			this.scrollOffset = Math.max(0, this.scrollOffset - 1);
			this.requestRender();
			return;
		}
		if (matchesKey(data, "down")) {
			this.scrollOffset = Math.min(Math.max(0, this.lastContentLength - this.lastCapacity), this.scrollOffset + 1);
			this.requestRender();
		}
	}

	private styledStage(stage: OperatorProgressView["stages"][number]): string {
		const marker = stageMarker(stage.status);
		return this.theme.fg(stageColor(stage.status), `${marker} [${stage.number}/6] ${stage.label}`);
	}

	private graphLines(rounds: OperatorRoundView[]): string[] {
		if (!rounds.length) return [this.theme.fg("dim", "No committed generations for this experiment on this page.")];
		return rounds.map((round, index, shown) => {
			const branch = index === shown.length - 1 ? "└─" : "├─";
			const evidence = `${count(round.parent_passed)}→${count(round.challenger_passed)}`;
			const retry = round.retries ? ` · ${round.retries} retry` : "";
			return [
				this.theme.fg("dim", branch),
				` r${String(round.round ?? "?").padStart(2, "0")} `,
				this.theme.fg("muted", shortId(round.parent_candidate_id)),
				this.theme.fg("dim", " → "),
				this.theme.fg("accent", shortId(round.child_candidate_id)),
				` · pass ${evidence} · `,
				this.theme.fg(round.decision === "promote_challenger" ? "success" : "warning", decisionLabel(round)),
				this.theme.fg("dim", retry),
			].join("");
		});
	}

	private diffLines(diff: OperatorDiffView | null): string[] {
		if (!diff) return [this.theme.fg("dim", "No immutable child diff is available at this point.")];
		const lines = [
			`${this.theme.fg("accent", `round ${count(diff.round)}`)} · ${diff.summary} · ${shortId(diff.parent_candidate_id)} → ${shortId(diff.child_candidate_id)}`,
		];
		if (diff.truncated) lines.push(this.theme.fg("warning", "bounded preview is truncated"));
		const fileLimit = this.expandedDiff ? diff.files.length : 8;
		for (const file of diff.files.slice(0, fileLimit)) {
			lines.push(
				`${this.theme.fg("muted", "Δ")} ${safeLine(file.path)} ${this.theme.fg("success", `+${count(file.insertions)}`)} ${this.theme.fg("error", `-${count(file.deletions)}`)}`,
			);
		}
		if (!this.expandedDiff && diff.files.length > fileLimit) {
			lines.push(this.theme.fg("dim", `… ${diff.files.length - fileLimit} more changed files (D to expand)`));
		}
		const previewLimit = this.expandedDiff ? 40 : 8;
		for (const source of diff.preview_lines.slice(0, previewLimit)) {
			const line = safeLine(source);
			const color =
				line.startsWith("+") && !line.startsWith("+++")
					? "toolDiffAdded"
					: line.startsWith("-") && !line.startsWith("---")
						? "toolDiffRemoved"
						: "toolDiffContext";
			lines.push(this.theme.fg(color, line));
		}
		return lines;
	}

	render(width: number): string[] {
		if (width < 20) return [truncateToWidth("Agentvolve progress", Math.max(1, width), "")];
		const available = width;
		const boxWidth = Math.max(18, available - 2);
		const inner = Math.max(14, boxWidth - 2);
		const border = (text: string) => this.theme.fg("borderAccent", text);
		const row = (content = "") => {
			const clipped = truncateToWidth(content, inner, "…");
			return `${border("│")}${clipped}${" ".repeat(Math.max(0, inner - visibleWidth(clipped)))}${border("│")}`;
		};
		const lines: string[] = [border(`╭${"─".repeat(inner)}╮`)];
		const wrappedRows = (text: string) => wrapTextWithAnsi(safeLine(text), inner - 2).map((line) => row(` ${line}`));
		lines.push(row(` ${this.theme.fg("accent", this.theme.bold("🧬 Agentvolve progress / history"))}`));
		lines.push(row(" t candidate trees / child reports · [ ] generations · ↑↓ scroll · esc/q return"));
		lines.push(row(` operator  ${this.theme.fg("text", safeLine(this.operatorModel))}`));
		const workerModel = this.progress.worker.model;
		const workerLabel = workerModel
			? `${workerModel.provider}/${workerModel.model} · ${workerModel.reasoning}`
			: "unavailable";
		const workerState =
			this.progress.worker.alive === true
				? `pid ${this.progress.worker.pid} · alive`
				: this.progress.worker.alive === false
					? "not alive"
					: "external/unknown";
		lines.push(row(` worker    ${this.theme.fg("warning", workerLabel)} · ${workerState}`));
		const updatedMs = (this.progress.updated_unix_ns ?? 0) / 1_000_000;
		const freshness = updatedMs > 0 ? `${Math.max(0, Math.floor((Date.now() - updatedMs) / 1000))}s ago` : "unknown";
		lines.push(row(` run       ${safeLine(this.progress.workflow_root)} · updated ${freshness}`));
		lines.push(border(`├${"─".repeat(inner)}┤`));
		for (const stage of this.progress.stages) lines.push(row(` ${this.styledStage(stage)}`));
		lines.push(row());
		lines.push(
			row(
				` NOW ${this.theme.fg("warning", `[${this.progress.stage}/6] ${PROCESS_LABELS[this.progress.stage]}`)} · ${this.theme.fg(stageColor(this.progress.stages[this.progress.stage - 1]?.status ?? "pending"), this.progress.state)}`,
			),
		);
		lines.push(...wrappedRows(this.progress.activity));
		if (this.progress.task) lines.push(...wrappedRows(`Goal: ${this.progress.task.goal}`));
		if (this.progress.error) {
			const error = safeLine(this.progress.error);
			for (let offset = 0; offset < Math.min(error.length, inner * 3); offset += inner - 2) {
				lines.push(row(` ${this.theme.fg("error", error.slice(offset, offset + inner - 2))}`));
			}
		}
		if (this.progress.evolution) {
			const evolution = this.progress.evolution;
			lines.push(
				row(
					` ${evolution.kind} · round ${evolution.pending_round ?? evolution.completed_rounds}/${count(evolution.max_rounds)} · ` +
						`${evolution.proposal_calls} committed calls · archive ${evolution.archive_member_count}` +
						(evolution.pending_stage
							? ` · pending ${safeLine(evolution.pending_stage)} · attempts ${evolution.pending_attempts}`
							: ""),
				),
			);
			if (evolution.pending_parent_candidate_id) {
				lines.push(
					row(` pending parent ${shortId(evolution.pending_parent_candidate_id)} · no child is claimed before receipt`),
				);
			}
		}
		lines.push(row(` ${this.theme.fg("accent", `Evolution trace · ${this.trace.total_rounds ? this.trace.offset + 1 : 0}–${this.trace.offset + this.trace.rounds.length} of ${this.trace.total_rounds} generations`)}`));
		lines.push(row(` ${this.theme.fg("dim", "[ previous page · ] next page · all recorded generations, harness then solution")}`));
		for (const experiment of this.trace.experiments) {
			lines.push(...wrappedRows(`${experiment.kind}${experiment.reused ? " (reused; not evolved in this workflow)" : ""}: ${experiment.run_root}`));
			if (experiment.report) lines.push(...wrappedRows(`Stage result: ${JSON.stringify(experiment.report)}`));
			const rounds = this.trace.rounds.filter((round) => round.run_root === experiment.run_root && round.kind === experiment.kind);
			for (const line of this.graphLines(rounds)) lines.push(...wrapTextWithAnsi(line, inner - 2).map((part) => row(` ${part}`)));
			for (const round of rounds) {
				lines.push(...wrappedRows(`r${count(round.round)} parent ${round.parent_candidate_id} → child ${round.child_candidate_id}; selected ${round.selected_candidate_id}; attempts ${round.attempts}; archive ${round.archive_members}`));
			}
		}
		if (this.progress.diff) {
			lines.push(row(` ${this.theme.fg("accent", "Latest immutable candidate diff")}`));
			for (const line of this.diffLines(this.progress.diff)) lines.push(row(` ${line}`));
		}
		const completedStages = this.progress.stages.filter((item) => ["complete", "reused"].includes(item.status));
		if (completedStages.length) {
			lines.push(row(` ${this.theme.fg("accent", "Completed-stage reports")}`));
			for (const stage of completedStages) lines.push(...wrappedRows(`[${stage.number}] ${stage.summary}`));
		}
		if (this.progress.result) {
			lines.push(...wrappedRows(`Selected commit: ${String(this.progress.result.selected_commit ?? "unavailable")}`));
			lines.push(...wrappedRows(`Patch: ${String(this.progress.result.patch_path ?? "unavailable")}`));
			const finalPassed = this.progress.result.final_passed;
			const finalTasks = this.progress.result.final_tasks;
			lines.push(
				row(
					` ${this.theme.fg("success", "RESULT")} commit ${shortId(String(this.progress.result.selected_commit ?? ""))} · candidate ${shortId(String(this.progress.result.selected_candidate_id ?? ""))}`,
				),
			);
			lines.push(
				row(
					` protected ${count(typeof finalPassed === "number" ? finalPassed : null)}/${count(typeof finalTasks === "number" ? finalTasks : null)} · patch ${safeLine(String(this.progress.result.patch_path ?? "unavailable"))}`,
				),
			);
		}
		for (const warning of this.progress.warnings) {
			lines.push(row(` ${this.theme.fg("warning", `view warning: ${safeLine(warning)}`)}`));
		}
		if (this.error) lines.push(row(` ${this.theme.fg("error", `refresh error: ${this.error}`)}`));
		lines.push(row(` ${this.theme.fg("dim", "[ ] generations · ↑↓/PgUp/PgDn scroll · r refresh · d diff · esc/q return")}`));
		lines.push(border(`╰${"─".repeat(inner)}╯`));
		const maxLines = Math.max(10, Math.min(34, this.viewportRows() - 6));
		if (lines.length <= maxLines) {
			this.scrollOffset = 0;
			return lines;
		}
		const content = lines.slice(1, -1);
		const capacity = Math.max(1, maxLines - 3);
		this.lastContentLength = content.length;
		this.lastCapacity = capacity;
		this.scrollOffset = Math.min(Math.max(0, content.length - capacity), this.scrollOffset);
		const below = Math.max(0, content.length - capacity - this.scrollOffset);
		return [
			lines[0]!,
			row(` ${this.theme.fg("dim", `↑${this.scrollOffset} ↓${below} · t trees/reports · arrows scroll`)}`),
			...content.slice(this.scrollOffset, this.scrollOffset + capacity),
			lines.at(-1)!,
		];
	}

	invalidate(): void {}

	dispose(): void {
		this.disposed = true;
		if (this.timer) clearInterval(this.timer);
		this.timer = undefined;
	}
}

export async function showAgentvolveDashboard(
	ctx: ExtensionContext,
	operatorModel: string,
	initial: OperatorProgressView,
	load: () => Promise<OperatorProgressView>,
	trace: OperatorTraceView,
	loadTrace: (offset: number) => Promise<OperatorTraceView>,
): Promise<"tree" | undefined> {
	if (ctx.mode !== "tui") {
		ctx.ui.notify("/progress dashboard requires interactive Pi", "error");
		return;
	}
	return ctx.ui.custom<"tree" | undefined>((tui, theme, _keybindings, done) => {
		const dashboard = new AgentvolveDashboard(
			theme,
			operatorModel,
			initial,
			load,
			() => tui.requestRender(),
			() => tui.terminal.rows,
			(action) => done(action),
			trace,
			loadTrace,
		);
		return dashboard;
	});
}
