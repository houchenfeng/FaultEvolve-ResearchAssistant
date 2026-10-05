/**
 * 运行环境补充说明（TODO 4.4 / PRD §7.5）。
 *
 * 自由文本，占位文案照 PRD。UI 明确标注「仅作为运行备注，不会作为命令执行」
 * —— 这是 TODO §6「自由文本不会成为命令参数」的前端半边；后端半边在
 * server_profiles / run_service（notes 只落库，永不进 argv）。
 */
export function NotesTextarea({
  value,
  onChange,
  disabled = false,
}: {
  value: string;
  onChange: (text: string) => void;
  disabled?: boolean;
}) {
  return (
    <div className="flex flex-col gap-1" data-notes-field="true">
      <label htmlFor="intake-notes" className="text-xs font-medium text-fg">
        运行环境补充说明
      </label>
      <textarea
        id="intake-notes"
        value={value}
        disabled={disabled}
        rows={3}
        onChange={(event) => onChange(event.target.value)}
        placeholder="例如：需要先激活 conda 环境；GPU 0 被其他进程占用；磁盘剩余空间告警……"
        className="fe-input fe-textarea disabled:opacity-50"
      />
      <p className="text-[11px] text-fg-subtle">仅作为运行备注保存，不会作为命令执行。</p>
    </div>
  );
}
