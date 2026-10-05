/**
 * 执行环境结构化配置（TODO 4.4 / PRD §7.5）。
 *
 * 这些是 ServerProfileRequest 的环境字段：python / conda、CPU、内存、
 * GPU 数量+设备号+型号、并发与超时。GPU 型号是「期望值」，探测结果在
 * 「测试连接」里对照（PRD 标注期望/检测）。
 */
import type { ProfileDraft } from '@/features/intake/ServerProfileForm';

function NumberField({
  label,
  value,
  onChange,
  placeholder,
  min,
  max,
}: {
  label: string;
  value: string;
  onChange: (text: string) => void;
  placeholder: string;
  min?: number;
  max?: number;
}) {
  return (
    <label className="flex flex-col gap-1 text-[11px]">
      <span className="text-fg-subtle">{label}</span>
      <input
        type="number"
        value={value}
        min={min}
        max={max}
        onChange={(event) => onChange(event.target.value)}
        placeholder={placeholder}
        className="fe-input fe-input-sm"
      />
    </label>
  );
}

function TextField({
  label,
  value,
  onChange,
  placeholder,
}: {
  label: string;
  value: string;
  onChange: (text: string) => void;
  placeholder: string;
}) {
  return (
    <label className="flex flex-col gap-1 text-[11px]">
      <span className="text-fg-subtle">{label}</span>
      <input
        type="text"
        value={value}
        onChange={(event) => onChange(event.target.value)}
        placeholder={placeholder}
        className="fe-input fe-input-sm"
      />
    </label>
  );
}

export function EnvConfigForm({
  draft,
  onChange,
  detected,
}: {
  draft: ProfileDraft;
  onChange: (patch: Partial<ProfileDraft>) => void;
  /** 「测试连接」探测到的真实环境（期望 vs 检测）。 */
  detected?: { python_version?: string | null; gpu_summary?: string | null } | null;
}) {
  return (
    <section className="flex flex-col gap-2" data-env-config="true">
      <h3 className="text-sm font-semibold text-fg">执行环境</h3>
      <div className="grid gap-3 fe-card p-3 sm:grid-cols-2 xl:grid-cols-3">
        <TextField
          label="Python 可执行文件（期望）"
          value={draft.python_executable}
          onChange={(text) => onChange({ python_executable: text })}
          placeholder="python / /opt/env/bin/python"
        />
        <TextField
          label="conda 环境"
          value={draft.conda_env}
          onChange={(text) => onChange({ conda_env: text })}
          placeholder="例如 faultevolve"
        />
        <NumberField
          label="CPU 核数上限"
          value={draft.cpu_limit}
          onChange={(text) => onChange({ cpu_limit: text })}
          placeholder="不填 = 不限制"
          min={1}
        />
        <NumberField
          label="内存上限（GB）"
          value={draft.memory_gb}
          onChange={(text) => onChange({ memory_gb: text })}
          placeholder="不填 = 不限制"
          min={1}
        />
        <NumberField
          label="GPU 数量"
          value={draft.gpu_count}
          onChange={(text) => onChange({ gpu_count: text })}
          placeholder="0"
          min={0}
        />
        <TextField
          label="GPU 设备号（逗号分隔）"
          value={draft.gpu_devices}
          onChange={(text) => onChange({ gpu_devices: text })}
          placeholder="例如 0,1"
        />
        <TextField
          label="GPU 型号（期望值）"
          value={draft.gpu_model}
          onChange={(text) => onChange({ gpu_model: text })}
          placeholder="例如 RTX 4090"
        />
        <NumberField
          label="最大并发"
          value={draft.max_concurrency}
          onChange={(text) => onChange({ max_concurrency: text })}
          placeholder="1"
          min={1}
        />
        <NumberField
          label="单次执行超时（秒）"
          value={draft.timeout_s}
          onChange={(text) => onChange({ timeout_s: text })}
          placeholder="600"
          min={1}
        />
      </div>
      {detected ? (
        <p className="text-[11px] text-fg-subtle">
          检测结果：Python {detected.python_version ?? '未知'}
          {detected.gpu_summary ? ` · GPU ${detected.gpu_summary}` : ''}
          （以上与「期望」不一致时以检测为准，请更新期望值。）
        </p>
      ) : null}
    </section>
  );
}
