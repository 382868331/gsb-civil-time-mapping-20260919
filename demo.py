"""演示：回拨三候选、跳空、区间映射、递推，以及一个实际触发的失败。

运行：python demo.py（数秒内完成，所有输出均由库实际计算）。
"""

from civil_time import CivilTimeMap, FoldError, GapError


def main():
    # Windows 中文控制台默认 GBK，显式切到 UTF-8 以免中文输出乱码
    try:
        import sys
        sys.stdout.reconfigure(encoding="utf-8")
    except (AttributeError, OSError):
        pass
    # 转换表：offset 0 -> -3600（UTC 6000 回拨）-> -7200（UTC 7000 再回拨）
    # 本地 [2400, 2800) 被三段影像同时覆盖，产生三候选 fold。
    m = CivilTimeMap(0, 10000, 0, [(6000, -3600), (7000, -7200)])

    print("== 点查询：回拨三候选 ==")
    print("utc_to_local(7000) =", m.utc_to_local(7000), "（转换点上即用新 offset）")
    local = 2500
    cands = m.local_to_utc(local, "all")
    print(f"local_to_utc({local}, 'all') = {cands}  （三候选 fold）")
    print(f"local_to_utc({local}, 'earliest') = {m.local_to_utc(local, 'earliest')}")
    print(f"local_to_utc({local}, 'latest')  = {m.local_to_utc(local, 'latest')}")

    print("\n== 跳空 ==")
    g = CivilTimeMap(0, 10000, 0, [(5000, 1800)])  # 前跳 30 分钟
    print("local_to_utc(5500, 'all') =", g.local_to_utc(5500, "all"), "（跳空无候选）")

    print("\n== 区间映射 ==")
    print("map_local_interval(2400, 2800) =", m.map_local_interval(2400, 2800))
    print("map_utc_interval(0, 10000)     =", m.map_utc_interval(0, 10000),
          " （覆盖计数 1/2/3/2/1）")
    print("map_utc_interval(-500, 1500)   =", m.map_utc_interval(-500, 1500),
          " （裁剪到域内）")

    print("\n== 有限递推（fold='all'，按 utc 再 j 排序）==")
    r = CivilTimeMap(0, 10000, 0, [(5000, -3600)])
    print("recur(4900, 100, 3, fold='all') =", r.recur(4900, 100, 3, fold="all"))

    print("\n== 实际触发的失败 ==")
    try:
        m.local_to_utc(2500, "reject")
    except FoldError as exc:
        print(f"local_to_utc(2500, 'reject') 触发 FoldError: {exc}")
    try:
        g.local_to_utc(5500, "earliest")
    except GapError as exc:
        print(f"local_to_utc(5500, 'earliest') 触发 GapError: {exc}")


if __name__ == "__main__":
    main()
