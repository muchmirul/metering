import type { ExtensionContext, Theme } from "@earendil-works/pi-coding-agent";
import { matchesKey, truncateToWidth, visibleWidth } from "@earendil-works/pi-tui";

import {
	PROCESS_LABELS,
	type OperatorDiffView,
	type OperatorProgressView,
	type OperatorRoundView,
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
	private readonly close: () => void;
	private readonly requestRender: () => void;
	private readonly viewportRows: () => number;
	private progress: OperatorProgressView;
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
		close: () => void,
	) {
		this.theme = theme;
		this.operatorModel = operatorModel;
		this.progress = initial;
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
			const previousState = this.progress.state;
			this.progress = await this.load();
			if (
				!["completed", "verified"].includes(previousState) &&
				["completed", "verified"].includes(this.progress.state)
			) {
				this.scrollOffset = Number.MAX_SAFE_INTEGER;
			}
			this.error = undefined;
		} catch (error) {
			this.error = safeLine(String(error)).slice(-1000);
		} finally {
			this.refreshing = false;
			if (!this.disposed) this.requestRender();
		}
	}

	handleInput(data: string): void {
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
		if (!rounds.length) return [this.theme.fg("dim", "No committed generation exists yet.")];
		return rounds.slice(-7).map((round, index, shown) => {
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
		lines.push(row(` ${this.theme.fg("accent", this.theme.bold("🧬 Agentvolve live progress"))}`));
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
		lines.push(row(` ${safeLine(this.progress.activity)}`));
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
			if (evolution.rounds.length) {
				lines.push(row(` ${this.theme.fg("accent", "Committed lineage / evidence")}`));
				for (const line of this.graphLines(evolution.rounds)) lines.push(row(` ${line}`));
			}
		}
		if (this.progress.diff) {
			lines.push(row(` ${this.theme.fg("accent", "Latest immutable candidate diff")}`));
			for (const line of this.diffLines(this.progress.diff)) lines.push(row(` ${line}`));
		}
		const completedStages = this.progress.stages.filter((item) => ["complete", "reused"].includes(item.status));
		if (completedStages.length) {
			lines.push(row(` ${this.theme.fg("accent", "Completed-stage reports")}`));
			for (const stage of completedStages) lines.push(row(` [${stage.number}] ${safeLine(stage.summary)}`));
		}
		if (this.progress.result) {
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
		lines.push(row(` ${this.theme.fg("dim", "↑↓ scroll · r refresh · d expand/collapse diff · esc/q return to Pi")}`));
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
			row(` ${this.theme.fg("dim", `dashboard scroll ↑${this.scrollOffset} ↓${below} · use arrow keys`)}`),
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
): Promise<void> {
	if (ctx.mode !== "tui") {
		ctx.ui.notify("/view-progress requires interactive Pi", "error");
		return;
	}
	await ctx.ui.custom<void>((tui, theme, _keybindings, done) => {
		const dashboard = new AgentvolveDashboard(
			theme,
			operatorModel,
			initial,
			load,
			() => tui.requestRender(),
			() => tui.terminal.rows,
			() => done(undefined),
		);
		return dashboard;
	});
}
