"""civil-time-mapping 演示。

构造两张小的整数秒转换表（不读取系统时区）：
  1) 两次回拨，制造本地时刻的三候选 fold；
  2) 一次前拨，制造本地时间轴上的跳空。

演示点查询、两类区间映射与有限递推的正常结果，并实际触发一次
fold reject 失败（捕获真实异常并展示）。运行：python demo.py
"""

import sys
import time

from tzmap import TimeMap, FoldError

# Windows 原生控制台可能使用 GBK 代码页，统一改为 UTF-8 输出，
# 保证离线环境下中文不错乱（仅标准库，重配置失败时静默忽略）。
try:
    sys.stdout.reconfigure(encoding="utf-8")
except (AttributeError, ValueError):
    pass


def main():
    start = time.perf_counter()

    # 表 A：域 [0,100)，offset 0 -> -30 -> -60，两次回拨。
    #   段1 UTC [0,40)  -> 本地 [0,40)
    #   段2 UTC [40,70) -> 本地 [10,40)
    #   段3 UTC [70,100)-> 本地 [10,40)
    # 本地 [10,40) 同时对应三个 UTC 区间（三候选 fold）。
    fold_map = TimeMap(0, 100, 0, [(40, -30), (70, -60)])

    # 表 B：域 [0,100)，offset 0 -> +30，一次前拨。
    #   段1 -> 本地 [0,40)，段2 -> 本地 [70,130)；本地 [40,70) 为跳空。
    gap_map = TimeMap(0, 100, 0, [(40, 30)])

    print("=" * 66)
    print("正常结果 1：回拨三候选点查询（表 A，本地时刻 25）")
    print("-" * 66)
    print("  all      ->", fold_map.local_to_utc(25, "all"))
    print("  earliest ->", fold_map.local_to_utc(25, "earliest"))
    print("  latest   ->", fold_map.local_to_utc(25, "latest"))
    print("  转换点新 offset：UTC 40 -> 本地", fold_map.utc_to_local(40),
          "；UTC 70 -> 本地", fold_map.utc_to_local(70))

    print("=" * 66)
    print("正常结果 2：本地区间 [10,30) -> UTC 区间（逐段求交后合并）")
    print("-" * 66)
    print(" ", fold_map.local_interval_to_utc(10, 30))

    print("=" * 66)
    print("正常结果 3：UTC [0,100) 反向映射为本地覆盖计数恒定段")
    print("-" * 66)
    for lo, hi, count in fold_map.utc_interval_to_local(0, 100):
        print(f"  本地 [{lo:3d},{hi:3d})  覆盖计数 = {count}")

    print("=" * 66)
    print("正常结果 4：跳空点查询（表 B）")
    print("-" * 66)
    print("  本地 55 落在跳空 [40,70)，all 候选 ->",
          gap_map.local_to_utc(55, "all"))
    print("  本地 80 唯一候选 ->", gap_map.local_to_utc(80, "reject"))

    print("=" * 66)
    print("正常结果 5：有限递推 local_j = 20 + 15j, j=0..7（表 B）")
    print("-" * 66)
    pairs = gap_map.recurrences(20, 15, 8)  # j=2,3 落入跳空，默认 skip
    print("  gap=skip, fold=earliest：")
    print("  ", pairs)
    print("  输出按 (utc, j) 排序；j=2,3 因跳空被跳过")
    pairs_all = fold_map.recurrences(15, 10, 2, fold="all")
    print("  表 A 上 local=15,25 的 fold=all 递推（按 UTC 重排）：")
    print("  ", pairs_all)

    print("=" * 66)
    print("实际触发的失败：对三候选 fold 使用 mode='reject'")
    print("-" * 66)
    try:
        fold_map.local_to_utc(25, "reject")
    except FoldError as exc:
        print(f"  捕获 {type(exc).__name__}: {exc}")
    else:  # pragma: no cover - 演示不应走到这里
        raise RuntimeError("预期的 FoldError 没有触发，转换表构造有误")

    elapsed = time.perf_counter() - start
    print("=" * 66)
    print(f"演示完成，实际耗时 {elapsed:.3f} 秒（要求约 8 秒内）")


if __name__ == "__main__":
    main()
