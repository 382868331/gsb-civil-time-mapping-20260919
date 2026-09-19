# 显式时区转换表的民用时间映射库

离线日志归一化组件：只使用调用方提供的转换表解释重复（fold）或缺失（gap）的本地时刻。不读取系统时区 / IANA 数据库，不解析真实日历，全部整数秒精确运算，分段区间算法，不逐秒扫描。

## 模型

- 有限 UTC 半开域 `[umin, umax)`（`umin < umax`，整数秒）。
- 初始 offset 加若干严格递增的转换 `(utc, new_offset)`；转换点必须在域内部，点上即使用新 offset。
- `local = utc + offset`，offset 在相邻转换点之间为常数。
- 回拨产生 fold（一个本地时刻对应多个 UTC，可能超过 2 个），前跳产生 gap（无对应 UTC）。

## 接口（`civil_time.py`）

```python
from civil_time import CivilTimeMap, OutOfDomainError, GapError, FoldError

m = CivilTimeMap(umin, umax, initial_offset, transitions=[(utc, new_offset), ...])
```

- `m.utc_to_local(utc) -> int`：越域抛 `OutOfDomainError`。
- `m.local_to_utc(local, mode="all")`：
  - `"all"`：域内升序唯一候选列表，无候选返回 `[]`；
  - `"earliest"` / `"latest"`：取候选端点，无候选抛 `GapError`；
  - `"reject"`：恰好一个候选才返回，多候选抛 `FoldError`，无候选抛 `GapError`。
- `m.local_candidates(local) -> list[int]`：升序候选列表（`"all"` 的内部形式）。
- `m.map_local_interval(l, r) -> [(u, v), ...]`：本地 `[l, r)` 映射为所有符合条件的域内 UTC 半开区间，升序并合并相邻段（逐段求交，不是只转换端点）。空区间返回 `[]`，反向区间抛 `ValueError`。
- `m.map_utc_interval(u, v) -> [(local_start, local_end, count), ...]`：先裁剪到域内，再输出本地覆盖计数恒定的最大半开段（`count >= 1`）。空结果返回 `[]`，反向区间抛 `ValueError`。
- `m.recur(start, step, count, gap="skip", fold="earliest") -> [(j, utc), ...]`：有限递推 `local_j = start + j*step`（`step > 0`，`0 <= j < count`）。`gap` 取 `"skip"` / `"reject"`；`fold` 取 `"earliest"` / `"latest"` / `"all"` / `"reject"`。输出按 `(utc, j)` 升序；每个 UTC 最多对应一个 j，一个 j 在 `fold="all"` 下可对应多个 UTC，不做跨 j 去重。

约束：转换表 ≤ 1000 项，`count <= 10000`。

## 环境与运行

Windows 原生 Python 3.14.7，仅标准库，无第三方依赖、外部服务或 Docker。

演示（数秒内完成，展示正常结果与实际触发的 `FoldError` / `GapError`）：

```
python demo.py
```

测试（含固定种子逐秒枚举参考验证：多重 fold、区间覆盖计数、边界、递推重排）：

```
python -m unittest discover -s tests -v
```

## 文件

- `civil_time.py` — 库本体。
- `tests/test_civil_time.py` — 单元测试与逐秒枚举参考对照。
- `demo.py` — 演示：回拨三候选、跳空、区间映射、递推与真实失败。
