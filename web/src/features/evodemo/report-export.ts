/**
 * 结果讲解页的“导出报告 / 下载最优代码”：报告在浏览器里由 `RunReport` 生成 Markdown；
 * 最优代码优先取后端制品 `program-<best.id>`，运行未被后端收录时导出最优方案定义（JSON）。
 */
import type { RunReport } from './report';
import { chapterTitles, formatMetric, narrate, operatorLabel, primaryDef } from './report';

function save(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  window.setTimeout(() => URL.revokeObjectURL(url), 1000);
}

export function reportMarkdown(report: RunReport): string {
  const { input, best, metricRows, confirmed, candidates } = report;
  const primary = primaryDef(input);
  const lines: string[] = [
    `# ${input.taskName} · 结果报告`,
    '',
    `- 运行：\`${input.runId}\``,
    `- 最优方案：${best.title}（\`${best.id}\`，${operatorLabel(best.operator)}）`,
    `- ${primary.label}：${formatMetric(primary, best.score)}`,
  ];
  if (input.formula) {
    lines.push('', '## 决策规则', '', '```', input.formula.expression, ...(input.formula.decision ? [input.formula.decision] : []), '```');
  }
  if (metricRows.length) {
    lines.push('', '## 指标对照', '', `| 指标 | ${report.baselines.map((b) => b.title).join(' | ')} | 最优方案 |`, `|---|${report.baselines.map(() => '---|').join('')}---|`);
    for (const row of metricRows) {
      lines.push(`| ${row.def.label} | ${row.baselines.map((v) => formatMetric(row.def, v)).join(' | ')} | ${formatMetric(row.def, row.best)} |`);
    }
  }
  chapterTitles(report).forEach((title, i) => lines.push('', `## ${i + 1}. ${title}`, '', narrate(report, i)));
  const claims = [...confirmed, ...candidates];
  if (claims.length) {
    lines.push('', '## 知识主张', '');
    for (const c of claims) {
      lines.push(`- **${c.title}**（${c.grade}）${c.boundary ? `：${c.boundary}` : ''}`);
      for (const f of c.falsifiers ?? []) lines.push(`  - 反证标准：${f}`);
    }
  }
  if (input.artifacts?.length) {
    lines.push('', '## 复现清单', '', ...input.artifacts.map((a) => `- ${a.label}：\`${a.path}\``));
  }
  return `${lines.join('\n')}\n`;
}

export function exportReport(report: RunReport) {
  save(new Blob([reportMarkdown(report)], { type: 'text/markdown;charset=utf-8' }), `${report.input.runId}_report.md`);
}

/** 返回实际下载的文件名，便于界面提示。 */
export async function downloadBestCode(report: RunReport): Promise<string> {
  const { runId } = report.input;
  const id = `program-${report.best.id}`;
  try {
    const res = await fetch(`/api/runs/${encodeURIComponent(runId)}/artifacts/${encodeURIComponent(id)}`);
    if (res.ok) {
      const filename = `${report.best.id}.py`;
      save(await res.blob(), filename);
      return filename;
    }
  } catch {
    // 后端不可达时落到下方的方案定义导出。
  }
  const filename = `${runId}_${report.best.id}.json`;
  const body = { runId, best: report.best, formula: report.input.formula, artifacts: report.input.artifacts };
  save(new Blob([JSON.stringify(body, null, 2)], { type: 'application/json' }), filename);
  return filename;
}
