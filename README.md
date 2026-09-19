# 显式时区转换表的民用时间映射库

整数秒、纯标准库的离线时间映射组件。给定调用方提供的转换表（不读取系统时区、
不访问 IANA 数据库、不解析真实日历），在有限 UTC 半开域上处理时区回拨
（fold，本地时刻重复）与前拨（gap，本地时刻跳空）：

- 点查询：UTC ↔ 本地，fold 可取全部 / 最早 / 最晚候选或拒绝；
- 区间映射：本地区间 → UTC 区间；UTC 区间 → 本地“覆盖计数”恒定分段；
- 有限递推：`local_j = start + j*step`，可分别配置 gap / fold 策略。

仅依赖 Python 3.14 标准库，在 Windows 原生环境离线运行。

## 文件结构

```
tzmap/__init__.py    库实现（TimeMap 与异常类型）
tests/test_tzmap.py  单元测试 + 固定种子随机逐秒枚举对照
demo.py              演示：回拨三候选、跳空、区间与递推，并真实触发一次失败
TASK.md              完整规格
```

## 接口

### 构造

```python
from tzmap import TimeMap

tm = TimeMap(umin, umax, initial_offset, transitions=[(utc, new_offset), ...])
```

- 域为半开整数区间 `[umin, umax)`，要求 `umin < umax`；
- `transitions` 的 `utc` 必须严格递增且严格位于域内部 `(umin, umax)`，
  至多 1000 项；到达转换点的瞬间立即采用 `new_offset`；
- 处处有 `local = utc + offset(utc)`，全部为整数运算。

### 异常

`TZMapError` 为基类，子类：`OutOfDomainError`、`GapError`、
`FoldError`、`InvalidIntervalError`。

### 点查询

- `tm.utc_to_local(u)` — 越域抛 `OutOfDomainError`。
- `tm.local_to_utc(local, mode=...)` — 返回域内候选：
  - `"all"`（默认）：升序候选列表，无候选返回 `[]`（不假定 fold 至多 2 个）；
  - `"earliest"` / `"latest"`：最小 / 最大候选，无候选抛 `GapError`；
  - `"reject"`：恰好一个候选时返回它，零个抛 `GapError`，多个抛 `FoldError`。

### 区间映射

- `tm.local_interval_to_utc(l, r)` — 本地半开区间 `[l, r)` 映射为域内 UTC
  半开区间列表，逐段求交（不只转换端点），按 UTC 升序并合并相邻段。
  `l == r` 返回 `[]`，`l > r` 抛 `InvalidIntervalError`。
- `tm.utc_interval_to_local(a, b)` — UTC 半开区间先裁剪到域内，再在本地
  时间轴上输出“覆盖计数（该本地时刻对应的域内 UTC 时刻个数）恒定”的
  最大半开段 `(lo, hi, count)` 列表（仅 count > 0 的被覆盖部分，故 gap
  不出现在结果中），按本地时刻升序。空区间返回 `[]`，反向区间报错。

### 有限递推

```python
tm.recurrences(start, step, count, gap="skip", fold="earliest")
```

- `step > 0`、`0 <= count <= 10000`，枚举 `local_j = start + j*step`；
- `gap="skip" | "reject"`：跳过跳空项或抛 `GapError`；
- `fold="earliest" | "latest" | "all" | "reject"`：多候选时的策略；
- 返回 `(j, utc)` 列表，按 `(utc, j)` 升序排列（先按 UTC 重排）。
  `fold="all"` 时一个 j 可对应多个 UTC；由于 `utc -> local` 是函数而
  `local_j` 互不相同，同一 UTC 不可能对应两个 j，故不做跨 j 去重。

## 运行

```bat
python demo.py
python -m unittest discover -s tests -v
```

演示在约 8 秒内输出若干真实计算的正常结果（回拨三候选、跳空、
覆盖计数、按 UTC 重排的递推），并实际触发、捕获一次 `FoldError`。

## 测试

`tests/test_tzmap.py` 覆盖规格点名的场景：跳空、回拨三候选、30 秒变化、
转换点使用新 offset、域裁剪、空区间、反向区间拒绝、覆盖计数、
按 UTC 重排递推。此外使用固定种子（`random.Random(20260920)`）生成
少量小域随机转换表，用逐秒枚举参考实现对点查询、两类区间映射和递推
（各 gap/fold 策略）做全样本对照，不做长时间压力测试。
