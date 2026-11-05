# SmartMem Linux 侧一条命令冒烟清单（2026-10-04）

用途：把这台的 Windows 交付物拿到服务器上验一次，**只做能一条命令跑完的事**。
每步都写清"跑什么"和"看什么"，任何一步与预期不符就把原样输出记下来，别改代码。
本地已实测的结论标 `本地已验`；只在 Windows 上成立、Linux 可能翻车的标 `需在服务器确认`。

先设两个变量，后面直接复制：

```bash
export DATA=/path/to/memory-predict/data      # 只读镜像，任何步骤都别往里写
export OUT=/home/hcf/smoke/slice              # 新建目录，不要复用旧产物
export PY=/home/hcf/faultevolve/.venv/bin/python
export SPLIT=$OUT/split.yaml                  # 边界文件：start/train_until/dev_until/val_until/
                                              # outcome_observed_until 五个键
```

## 0. 环境与大小写敏感（需在服务器确认）

```bash
$PY -V && $PY -c "import pandas, pyarrow; print(pandas.__version__, pyarrow.__version__)"
ls "$DATA/raw_tmp" | head            # 队列目录名到底是 type_A 还是 type_a
```

看：Python 3.12 上下、`pyarrow` 必须能 import（`--format feather` 依赖它）。
本地 venv 有 pyarrow 25.0.1，`--format feather` 直读已跑通，**服务器侧这一条还没当场确认过**。
目录名要原样抄进后面的命令：适配器认 `type_A` / `type_B` 拼写，Linux 文件系统区分大小写，
写成 `type_a` 会被当成未知队列。

## 1. 只描画像，不写产物

```bash
$PY benchmark/smartmem/prepare_data.py --raw-dir "$DATA/raw_tmp" --out-dir "$OUT/profile" \
  --format feather --timezone UTC --profile-only --max-files 400 --json
```

看：退出码 **0**。这一条**不加 `--error-types`** 也必须退 0 —— 默认取值域是本地在 460 个真实单元
文件（624 万余行事件）上实测出来的 `CE.READ,CE.SCRUB,CE` 三种拼写；若服务器上的全量数据里出现了
别的写法（例如事件流里真有 UE），这条会退 **1** 并列出前 5 个没被盖住的取值。那就是当场证伪默认值，
按它说的补 `--error-types`，别改代码里的常量。

## 2. 直读与排序树各跑一遍，比分区摘要

```bash
$PY benchmark/smartmem/prepare_data.py --raw-dir "$DATA/raw_tmp" --out-dir "$OUT/raw" \
  --format feather --timezone UTC --split-config "$SPLIT" \
  --epoch-unit s --max-files 200 --units-per-partition 4
$PY benchmark/smartmem/prepare_data.py --raw-dir "$DATA/raw_tmp" --out-dir "$OUT/sorted" \
  --format feather --timezone UTC --split-config "$SPLIT" \
  --epoch-unit s --max-files 200 --units-per-partition 4 --from-sorted "$OUT/sort"
```

看三件事（本地 200 单元切片已验：52 个分区 sha256 逐字节相同、`config_hash` 相同）：

```bash
diff <(cd "$OUT/raw/partitions" && find . -type f | sort | xargs sha256sum) \
     <(cd "$OUT/sorted/partitions" && find . -type f | sort | xargs sha256sum)
```

1. `diff` 为空；
2. 两份 `manifest.json` 的 `config_hash` 相同（侧表指纹也在里面）；
3. 人读输出的 `rows_beyond_coverage` 为 **0**，非 0 说明随访前沿又跑到工单覆盖之外了。

`--from-sorted` 的树要先用 `--sort-inputs --sort-dir "$OUT/sort"` 造；本地 200 单元耗时 149 分钟，
服务器上**别顺手全量造**，先拿 `--max-files` 的小切片试。

## 3. 侧表与工单交叉校验

```bash
wc -l "$OUT/raw/partitions/units/serial_type"
awk -F, 'NR>1 {print $3}' "$OUT/raw/partitions/units/serial_type" | sort | uniq -c
```

看：行数 = 切片单元数 + 1（表头）。`source` 计数本地是 `queue_directory` 200 / `ticket` 0 /
`unresolved` 0，因为真实包每个单元都在 `type_*` 目录下。若服务器上出现 `unresolved`，说明目录布局
和镜像不一致，先记下目录名再改适配器。

## 4. 评一份参考提交，确认能出数

```bash
$PY -c "
import pandas as pd, pathlib
p = pathlib.Path('$OUT/raw/partitions/samples')
t = pd.concat([pd.read_csv(f) for f in sorted(p.glob('*'))], ignore_index=True)
t.loc[t.split_key=='dev', ['sample_id','prediction_time']].to_csv('$OUT/pred-dev-all.csv', index=False)
"
$PY benchmark/smartmem/evaluator.py --run-dir "$OUT/raw" --ticket-file "$DATA/ticket.csv" \
  --predictions "$OUT/pred-dev-all.csv" --split dev --epoch-unit s --timezone UTC --json
```

看：退出码 **0**，stdout 恰好一个 JSON 对象，且带 `"metric_spec_status":"provisional"` 与
`"duplicate_alarm_rule":"sn-in-window"`（默认按官方页面原文：一台机器只计一次、命中必须落窗）。
再把同一条命令加 `--duplicate-alarm-rule each-alarm` 跑一遍：**同一份提交应该差出一个量级**
（本地 200 单元切片实测 `sn-in-window` 0.587302 对 `each-alarm` 0.023635）；服务器上如果两个数一样，
说明这里的样本表或命中窗跟本地不一样，值得追。
换成 `--split val` 若退 **4**，那是"该切片没有可评分告警"，**不是 0 分**，属预期行为。
`--ticket-file` 的文件名按镜像实际来（本地镜像是 `raw_tmp/ticket.csv`，另有一份
`failure_ticket.csv` 是同一份工单的拷贝）。

## 5. 知识包校验

```bash
$PY -m benchmark.smartmem.knowledge_check
```

看：退 0，23 张卡 + 11 条出处。这条与数据无关，纯防漂移。

## 6. 任务测试

```bash
$PY -m pytest tests/test_smartmem_evaluator.py tests/test_smartmem_prepare_cli.py -q
```

看：全绿。基线在本地是 `18 failed / 19 errors`（都与 SmartMem 无关的既有失败），通过数 **804**。
