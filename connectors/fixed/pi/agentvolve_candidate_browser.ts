import type { ExtensionContext } from "@earendil-works/pi-coding-agent";
import { matchesKey, truncateToWidth, wrapTextWithAnsi } from "@earendil-works/pi-tui";

import type { InspectionItem, OperatorCandidateReport, OperatorTreeView } from "./population_evolution_support.ts";

export interface InspectionLoaders {
	tree: (offset: number, loops: boolean) => Promise<OperatorTreeView>;
	report: (label: string, eventOffset: number, diffOffset: number, loop: boolean) => Promise<OperatorCandidateReport>;
	record: (view: OperatorTreeView | OperatorCandidateReport) => void;
	openGraph?: () => Promise<void>;
}

type ReportAction = "events-next" | "events-previous" | "diff-next" | "diff-previous" | "refresh" | "back";

function safe(value: string): string {
	return value.replace(/[\p{Cc}\p{Cf}\p{Cs}\p{Co}\p{Zl}\p{Zp}]/gu, "?");
}

export function candidateReportLines(report: OperatorCandidateReport): string[] {
	const node = report.node;
	const lines = [
		`${node.label} · ${node.kind}${node.reused ? " (reused source; not evolved in this workflow)" : ""}`,
		`Source: ${node.run_root}`,
		`Status: ${String(node.status ?? node.state)} · parent: ${node.parent_label ?? "seed"}`,
		...(node.candidate_id ? [`Candidate: ${node.candidate_id}`, `Git commit: ${node.commit ?? "unavailable"}`,
			`Git tree: ${node.git_tree ?? "unavailable"}`, `Entrypoint: ${node.entrypoint ?? "unavailable"}`,
			`Archive: ${node.archive_status}${node.exclusion_reason ? ` (${node.exclusion_reason})` : ""}`] : []),
		"Pairwise Selection Gate decisions are NOT current Population archive membership.",
		...(report.evidence ? ["EVALUATION SUMMARY (recorded replicates)", ...JSON.stringify(report.evidence, null, 2).split("\n")] : []),
		`LOOP STEPS / ARCHIVE HISTORY · ${report.total_events ? report.offset + 1 : 0}–${report.offset + report.events.length} of ${report.total_events}`,
	];
	for (const event of report.events) {
		lines.push(`── ${event.step}: ${event.summary}`);
		const { step: _step, summary: _summary, ...detail } = event;
		lines.push(...JSON.stringify(detail, null, 2).split("\n"));
	}
	if (report.diff) {
		const diff = report.diff;
		lines.push(`CHANGES VS PARENT · ${diff.base_commit ?? "none"} → ${diff.commit ?? "unavailable"}`);
		if (diff.warning) lines.push(diff.warning);
		if (diff.available) {
			lines.push(`Diff display fragments ${diff.total_lines ? diff.offset + 1 : 0}–${diff.offset + diff.lines.length} of ${diff.total_lines}; long lines wrap into 200-character fragments.`);
			lines.push(...diff.lines);
		}
	}
	lines.push(...report.warnings, report.verification);
	return lines.map(safe);
}

export async function showCandidateReport(ctx: ExtensionContext, report: OperatorCandidateReport): Promise<ReportAction> {
	if (ctx.mode !== "tui") {
		ctx.ui.notify(candidateReportLines(report).join("\n"), "info");
		const options: Array<[string, ReportAction]> = [
			...(report.offset > 0 ? [["Previous loop steps", "events-previous"] as [string, ReportAction]] : []),
			...(report.next_offset !== null ? [["Next loop steps", "events-next"] as [string, ReportAction]] : []),
			...(report.diff && report.diff.offset > 0 ? [["Previous diff page", "diff-previous"] as [string, ReportAction]] : []),
			...(report.diff?.next_offset != null ? [["Next diff page", "diff-next"] as [string, ReportAction]] : []),
			["Refresh report", "refresh"], ["Back to tree / loops", "back"],
		];
		const choice = await ctx.ui.select(`${report.node.label} report`, options.map(([label]) => label));
		return options.find(([label]) => label === choice)?.[1] ?? "back";
	}
	return ctx.ui.custom<ReportAction>((tui, theme, _keys, done) => {
		let scroll = 0;
		let maxScroll = 0;
		let capacity = 1;
		const content = candidateReportLines(report);
		return {
			render(width: number): string[] {
				width = Math.max(1, width);
				capacity = Math.max(1, Math.min(38, tui.terminal.rows - 6));
				const wrapped = content.flatMap((line) => wrapTextWithAnsi(line, width));
				maxScroll = Math.max(0, wrapped.length - capacity);
				scroll = Math.min(scroll, maxScroll);
				return [
					truncateToWidth(theme.fg("accent", `${report.node.label} · ↑↓/PgUp/PgDn scroll · n/p steps · ]/[ diff · r refresh · Esc back`), width),
					...wrapped.slice(scroll, scroll + capacity).map((line) => truncateToWidth(line, width)),
					truncateToWidth(theme.fg("dim", `scroll ${scroll}/${maxScroll} · read-only evidence projection`), width),
				];
			},
			handleInput(data: string): void {
				if (matchesKey(data, "escape") || matchesKey(data, "ctrl+c") || data === "q") return done("back");
				if (data === "n" && report.next_offset !== null) return done("events-next");
				if (data === "p" && report.offset > 0) return done("events-previous");
				if (data === "]" && report.diff?.next_offset != null) return done("diff-next");
				if (data === "[" && report.diff && report.diff.offset > 0) return done("diff-previous");
				if (data === "r") return done("refresh");
				if (matchesKey(data, "up")) scroll = Math.max(0, scroll - 1);
				if (matchesKey(data, "down")) scroll = Math.min(maxScroll, scroll + 1);
				if (matchesKey(data, "pageUp")) scroll = Math.max(0, scroll - capacity);
				if (matchesKey(data, "pageDown")) scroll = Math.min(maxScroll, scroll + capacity);
				if (matchesKey(data, "home")) scroll = 0;
				if (matchesKey(data, "end")) scroll = maxScroll;
				tui.requestRender();
			},
			invalidate() {},
		};
	});
}

export function candidateLabel(node: InspectionItem): string {
	// Preserve IDs even when a long lineage exceeds the terminal's width.
	const rawPrefix = node.tree_prefix ?? "";
	const prefix = rawPrefix.length > 9 ? `… ${rawPrefix.slice(-6)}` : rawPrefix;
	return safe(`${prefix}${node.label} [${node.status ?? node.state}]` +
		` · parent ${node.parent_label ?? "seed"}${node.reused ? " · REUSED" : ""}${node.exclusion_reason ? ` · ${node.exclusion_reason}` : ""}`);
}

export async function showCandidateBrowser(ctx: ExtensionContext, loaders: InspectionLoaders): Promise<void> {
	let offset = 0;
	let loops = false;
	for (;;) {
		const tree = await loaders.tree(offset, loops);
		loaders.record(tree);
		for (const warning of tree.warnings) ctx.ui.notify(warning, "warning");
		const labels = tree.items.map(candidateLabel);
		// Pi's built-in selector supports keyboard selection and fullscreen mouse clicks.
		const selected = await ctx.ui.select(`Agentvolve ${loops ? "loops / attempts" : "candidate trees"} · ${tree.total_items ? offset + 1 : 0}–${offset + tree.items.length} of ${tree.total_items}`, [
			...labels, ...(offset > 0 ? ["Previous page"] : []), ...(tree.next_offset !== null ? ["Next page"] : []),
			loops ? "Show candidate trees" : "Show loops / attempts", ...(loaders.openGraph ? ["Open Trace Viewer"] : []), "Refresh tree", "Back to progress",
		]);
		if (!selected || selected === "Back to progress") return;
		if (selected === "Next page" && tree.next_offset !== null) { offset = tree.next_offset; continue; }
		if (selected === "Previous page") { offset = Math.max(0, offset - tree.page_size); continue; }
		if (selected.startsWith("Show ")) { loops = !loops; offset = 0; continue; }
		if (selected === "Open Trace Viewer") { await loaders.openGraph?.(); continue; }
		if (selected === "Refresh tree") continue;
		const item = tree.items[labels.indexOf(selected)];
		if (!item) throw new Error("Candidate selection did not resolve");
		let eventOffset = 0;
		let diffOffset = 0;
		for (;;) {
			const report = await loaders.report(item.label, eventOffset, diffOffset, loops);
			loaders.record(report);
			const action = await showCandidateReport(ctx, report);
			if (!action || action === "back") break;
			if (action === "events-next" && report.next_offset !== null) eventOffset = report.next_offset;
			if (action === "events-previous") eventOffset = Math.max(0, eventOffset - report.page_size);
			if (action === "diff-next" && report.diff?.next_offset != null) diffOffset = report.diff.next_offset;
			if (action === "diff-previous" && report.diff) diffOffset = Math.max(0, diffOffset - report.diff.page_size);
		}
	}
}
