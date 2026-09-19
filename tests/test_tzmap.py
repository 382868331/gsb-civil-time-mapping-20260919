"""TimeMap 单元测试。

包含规格点名的场景（跳空、回拨三候选、30 秒变化、转换点、域裁剪、
空区间、反向区间拒绝、覆盖计数、按 UTC 重排递推），并用小 UTC 域
逐秒枚举作为参考实现，校验点查询与两类区间映射；随机用例使用固定种子、
少量小样本。
"""

import random
import unittest

from tzmap import (
    TimeMap,
    OutOfDomainError,
    GapError,
    FoldError,
    InvalidIntervalError,
)


# ----------------------------------------------------------------------
# 参考实现：对小域逐秒枚举
# ----------------------------------------------------------------------

def reference_offset(tm, u):
    off = tm.initial_offset
    for i in range(1, len(tm._offsets)):
        if u >= tm._bounds[i]:
            off = tm._offsets[i]
    return off


def reference_local_candidates(tm, local):
    out = []
    for u in range(tm.umin, tm.umax):
        if u + reference_offset(tm, u) == local:
            out.append(u)
    return out


def reference_local_interval(tm, l, r):
    if l > r:
        raise InvalidIntervalError
    hits = [
        u for u in range(tm.umin, tm.umax)
        if l <= u + reference_offset(tm, u) < r
    ]
    merged = []
    for u in hits:
        if merged and u == merged[-1][1]:
            merged[-1] = (merged[-1][0], u + 1)
        else:
            merged.append((u, u + 1))
    return merged


def reference_utc_interval(tm, a, b):
    if a > b:
        raise InvalidIntervalError
    a = max(a, tm.umin)
    b = min(b, tm.umax)
    counts = {}
    for u in range(a, b):
        key = u + reference_offset(tm, u)
        counts[key] = counts.get(key, 0) + 1
    if not counts:
        return []
    result = []
    run_start = min(counts)
    run_count = counts[run_start]
    prev = run_start
    for t in range(run_start + 1, max(counts) + 1):
        c = counts.get(t, 0)
        if c != run_count:
            if run_count > 0:
                result.append((run_start, t, run_count))
            run_start = t
            run_count = c
        prev = t
    if run_count > 0:
        result.append((run_start, prev + 1, run_count))
    return result


def make_random_map(rng):
    umin = rng.randint(-20, 0)
    umax = umin + rng.randint(2, 40)
    initial = rng.randint(-15, 15)
    interior = list(range(umin + 1, umax))
    rng.shuffle(interior)
    ntrans = rng.randint(0, min(4, len(interior)))
    points = sorted(interior[:ntrans])
    trans = [(t, rng.randint(-15, 15)) for t in points]
    return TimeMap(umin, umax, initial, trans)


# ----------------------------------------------------------------------
# 构造与基础语义
# ----------------------------------------------------------------------

class ConstructionTests(unittest.TestCase):

    def test_requires_umin_lt_umax(self):
        with self.assertRaises(ValueError):
            TimeMap(0, 0, 0)
        with self.assertRaises(ValueError):
            TimeMap(10, 5, 0)

    def test_transitions_must_be_inside_domain(self):
        with self.assertRaises(ValueError):
            TimeMap(0, 10, 0, [(0, 5)])       # 等于 umin
        with self.assertRaises(ValueError):
            TimeMap(0, 10, 0, [(10, 5)])      # 等于 umax
        with self.assertRaises(ValueError):
            TimeMap(0, 10, 0, [(-1, 5)])

    def test_transitions_must_be_strictly_increasing(self):
        with self.assertRaises(ValueError):
            TimeMap(0, 100, 0, [(10, 1), (10, 2)])
        with self.assertRaises(ValueError):
            TimeMap(0, 100, 0, [(20, 1), (10, 2)])

    def test_too_many_transitions(self):
        trans = [(i + 1, 0) for i in range(1001)]
        with self.assertRaises(ValueError):
            TimeMap(0, 2000, 0, trans)

    def test_integer_required(self):
        with self.assertRaises(TypeError):
            TimeMap(0, 10, 0.5)
        tm = TimeMap(0, 10, 0)
        with self.assertRaises(TypeError):
            tm.utc_to_local(1.5)


# ----------------------------------------------------------------------
# 点查询：转换点、跳空、三候选 fold
# ----------------------------------------------------------------------

class PointQueryTests(unittest.TestCase):

    def setUp(self):
        # 两次回拨：offset 0 -> -10 -> -20，三个段在本地时间轴上完全重叠。
        self.triple = TimeMap(0, 30, 0, [(10, -10), (20, -20)])
        # 一次前拨：offset 0 -> +10，本地 [10,20) 为跳空。
        self.gap = TimeMap(0, 30, 0, [(10, 10)])

    def test_transition_point_uses_new_offset(self):
        # 转换点“点上即用新 offset”
        self.assertEqual(self.gap.utc_to_local(9), 9)
        self.assertEqual(self.gap.utc_to_local(10), 20)
        self.assertEqual(self.triple.utc_to_local(10), 0)   # 10 + (-10)
        self.assertEqual(self.triple.utc_to_local(20), 0)   # 20 + (-20)
        self.assertEqual(self.triple.utc_to_local(29), 9)

    def test_utc_to_local_out_of_domain(self):
        tm = self.gap
        with self.assertRaises(OutOfDomainError):
            tm.utc_to_local(-1)
        with self.assertRaises(OutOfDomainError):
            tm.utc_to_local(30)
        with self.assertRaises(OutOfDomainError):
            tm.utc_to_local(100)

    def test_fold_three_candidates(self):
        self.assertEqual(self.triple.local_to_utc(5, "all"), [5, 15, 25])
        self.assertEqual(self.triple.local_to_utc(0, "all"), [0, 10, 20])
        self.assertEqual(self.triple.local_to_utc(9, "all"), [9, 19, 29])

    def test_fold_modes(self):
        self.assertEqual(self.triple.local_to_utc(5, "earliest"), 5)
        self.assertEqual(self.triple.local_to_utc(5, "latest"), 25)
        with self.assertRaises(FoldError):
            self.triple.local_to_utc(5, "reject")

    def test_unique_local_accepted_by_reject(self):
        # 三段完全重叠的模型里所有可映射本地时刻都是三候选；
        # 用部分重叠模型验证 reject 接受唯一候选：
        # seg1 [0,10) off 0 -> 本地 [0,10)；seg2 [10,30) off -5 -> [5,25)。
        tm = TimeMap(0, 30, 0, [(10, -5)])
        self.assertEqual(tm.local_to_utc(12, "reject"), 17)
        self.assertEqual(tm.local_to_utc(24, "reject"), 29)
        # 重叠区 [5,10) 为 fold，reject 仍然报错
        with self.assertRaises(FoldError):
            tm.local_to_utc(7, "reject")
        # 三候选模型在边界整点上同样是三候选
        self.assertEqual(self.triple.local_to_utc(0, "all"), [0, 10, 20])

    def test_gap_returns_empty_for_all(self):
        # 跳空本地区间 [10, 20)
        self.assertEqual(self.gap.local_to_utc(10, "all"), [])
        self.assertEqual(self.gap.local_to_utc(15, "all"), [])
        self.assertEqual(self.gap.local_to_utc(19, "all"), [])

    def test_gap_modes(self):
        with self.assertRaises(GapError):
            self.gap.local_to_utc(15, "earliest")
        with self.assertRaises(GapError):
            self.gap.local_to_utc(15, "latest")
        with self.assertRaises(GapError):
            self.gap.local_to_utc(15, "reject")

    def test_normal_points_gap_map(self):
        self.assertEqual(self.gap.local_to_utc(5, "reject"), 5)
        self.assertEqual(self.gap.local_to_utc(20, "reject"), 10)
        self.assertEqual(self.gap.local_to_utc(39, "all"), [29])
        self.assertEqual(self.gap.local_to_utc(40, "all"), [])

    def test_thirty_second_change(self):
        # 30 秒粒度的偏移变化（+30s 与 -30s）
        tm = TimeMap(0, 120, 0, [(60, 30)])
        self.assertEqual(tm.utc_to_local(60), 90)
        self.assertEqual(tm.local_to_utc(90, "reject"), 60)
        # 跳空 [60, 90)
        self.assertEqual(tm.local_to_utc(75, "all"), [])
        tm2 = TimeMap(0, 120, 0, [(60, -30)])
        self.assertEqual(tm2.utc_to_local(60), 30)
        # 回拨后本地 [30,60) 有两个候选，相隔 60 秒
        self.assertEqual(tm2.local_to_utc(45, "all"), [45, 75])

    def test_bad_mode(self):
        with self.assertRaises(ValueError):
            self.gap.local_to_utc(0, "soonest")


# ----------------------------------------------------------------------
# 本地区间 -> UTC 区间
# ----------------------------------------------------------------------

class LocalIntervalTests(unittest.TestCase):

    def setUp(self):
        self.triple = TimeMap(0, 30, 0, [(10, -10), (20, -20)])
        self.gap = TimeMap(0, 30, 0, [(10, 10)])

    def test_triple_fold_interval_is_whole_utc_domain(self):
        # 本地 [0,10) 在三个段中各对应整个段，合并后为整个 UTC 域
        self.assertEqual(
            self.triple.local_interval_to_utc(0, 10),
            [(0, 30)],
        )

    def test_interval_is_not_endpoint_only(self):
        # 本地 [0,5)：三段分别贡献 [0,5) [10,15) [20,25)，互不相邻，
        # 若只转换端点会错误地得到一段。
        self.assertEqual(
            self.triple.local_interval_to_utc(0, 5),
            [(0, 5), (10, 15), (20, 25)],
        )

    def test_gap_interval_pieces_merged_when_adjacent(self):
        # 本地 [0,20)：仅段1 [0,10) 有贡献；[10,20) 是跳空
        self.assertEqual(self.gap.local_interval_to_utc(0, 20), [(0, 10)])
        # 本地 [0,25)：段1贡献 [0,10)，段2贡献 [10,15)，
        # 两段 UTC 相邻 -> 合并为 [0,15)（不能因本地跳空而漏算段2）
        self.assertEqual(self.gap.local_interval_to_utc(0, 25), [(0, 15)])
        # 本地 [0,40) 覆盖整个域 -> 合并为整段
        self.assertEqual(self.gap.local_interval_to_utc(0, 40), [(0, 30)])
        # 只覆盖跳空后的部分
        self.assertEqual(self.gap.local_interval_to_utc(20, 25), [(10, 15)])

    def test_empty_interval(self):
        self.assertEqual(self.gap.local_interval_to_utc(5, 5), [])
        self.assertEqual(self.triple.local_interval_to_utc(100, 100), [])

    def test_reversed_interval_rejected(self):
        with self.assertRaises(InvalidIntervalError):
            self.gap.local_interval_to_utc(10, 5)

    def test_interval_with_no_coverage(self):
        # 完全落在跳空
        self.assertEqual(self.gap.local_interval_to_utc(11, 19), [])
        # 本地时间轴远端
        self.assertEqual(self.gap.local_interval_to_utc(1000, 2000), [])


# ----------------------------------------------------------------------
# UTC 区间 -> 本地覆盖计数分段
# ----------------------------------------------------------------------

class UTCIntervalTests(unittest.TestCase):

    def setUp(self):
        self.triple = TimeMap(0, 30, 0, [(10, -10), (20, -20)])
        self.gap = TimeMap(0, 30, 0, [(10, 10)])

    def test_coverage_count_triple(self):
        # 整个 UTC 域映到本地：[0,10) 计数恒为 3
        self.assertEqual(
            self.triple.utc_interval_to_local(0, 30),
            [(0, 10, 3)],
        )

    def test_coverage_count_partial_clip_and_split(self):
        # 取 UTC [5,25)：段1残余 [5,10)->本地[5,10)，段2整段->本地[0,10)，
        # 段3残余 [20,25)->本地[0,5)。
        # 本地 [0,10) 计数恒为 2（[0,5) 是段2+段3，[5,10) 是段1+段2；
        # 身份在 5 处交换但计数恒定，故最大恒计数段为整个 [0,10)）。
        self.assertEqual(
            self.triple.utc_interval_to_local(5, 25),
            [(0, 10, 2)],
        )
        # UTC [0,20) -> 段1整段+段2整段 -> 本地 [0,10) 计数 2
        self.assertEqual(
            self.triple.utc_interval_to_local(0, 20),
            [(0, 10, 2)],
        )
        # 只取段1一部分：UTC [0,5) -> 本地 [0,5)，计数 1
        self.assertEqual(
            self.triple.utc_interval_to_local(0, 5),
            [(0, 5, 1)],
        )
        # 段1残余与段3残余，本地不相连：
        self.assertEqual(
            self.triple.utc_interval_to_local(20, 25),
            [(0, 5, 1)],
        )
        self.assertEqual(
            self.triple.utc_interval_to_local(5, 10),
            [(5, 10, 1)],
        )

    def test_coverage_count_transitions_split_runs(self):
        # UTC [0,30) 在 gap 模型：本地 [0,10) 计数1，[20,40) 计数1
        self.assertEqual(
            self.gap.utc_interval_to_local(0, 30),
            [(0, 10, 1), (20, 40, 1)],
        )
        # 局部：UTC [5,15) -> 本地 [5,10) 与 [20,25)
        self.assertEqual(
            self.gap.utc_interval_to_local(5, 15),
            [(5, 10, 1), (20, 25, 1)],
        )

    def test_domain_clipping(self):
        # 查询区间超出域，先裁剪到域内
        self.assertEqual(
            self.triple.utc_interval_to_local(-100, 100),
            [(0, 10, 3)],
        )
        self.assertEqual(
            self.gap.utc_interval_to_local(-5, 5),
            [(0, 5, 1)],
        )
        self.assertEqual(
            self.gap.utc_interval_to_local(25, 100),
            [(35, 40, 1)],
        )

    def test_completely_outside_domain_is_empty(self):
        self.assertEqual(self.gap.utc_interval_to_local(30, 40), [])
        self.assertEqual(self.gap.utc_interval_to_local(-10, -5), [])
        self.assertEqual(self.gap.utc_interval_to_local(100, 200), [])

    def test_empty_interval(self):
        self.assertEqual(self.gap.utc_interval_to_local(5, 5), [])

    def test_reversed_interval_rejected(self):
        with self.assertRaises(InvalidIntervalError):
            self.gap.utc_interval_to_local(10, 3)


# ----------------------------------------------------------------------
# 有限递推
# ----------------------------------------------------------------------

class RecurrenceTests(unittest.TestCase):

    def setUp(self):
        self.gap = TimeMap(0, 60, 0, [(20, 10)])

    def test_basic_recurrence_ordered_by_utc(self):
        # 本地 0,15,30,45（跳空为本地 [20,30)，故 0/15 走段1，30/45 走段2）
        pairs = self.gap.recurrences(0, 15, 4)
        self.assertEqual(pairs, [(0, 0), (1, 15), (2, 20), (3, 35)])

    def test_recurrence_reordered_by_utc(self):
        # 回拨模型：offset 0 -> -15，回拨不产生跳空；本地 [15,30) 为 fold。
        tm = TimeMap(0, 60, 0, [(30, -15)])
        # 本地 15,20,25,30：
        #   15 -> u=15（段1）与 u=30（段2）
        #   20 -> u=20 与 u=35
        #   25 -> u=25 与 u=40
        #   30 -> 仅 u=45（段1 在 u=30 处已结束）
        pairs = tm.recurrences(15, 5, 4, fold="all")
        self.assertEqual(
            pairs,
            [(0, 15), (1, 20), (2, 25), (0, 30), (1, 35), (2, 40), (3, 45)],
        )
        # 每个 UTC 最多对应一个 j（无跨 j 去重的必要），UTC 相同时按 j 排
        utcs = [u for _, u in pairs]
        self.assertEqual(len(utcs), len(set(utcs)))
        self.assertEqual(pairs, sorted(pairs, key=lambda ju: (ju[1], ju[0])))

    def test_gap_skip_default(self):
        # 本地序列 0,10,20,30：20 与 30 落在跳空 [20,30)？前拨在 u=20：
        # 本地跳空为 [20,30)。j=2 local=20 gap；j=3 local=30 -> u=20。
        tm = self.gap
        self.assertEqual(
            tm.recurrences(0, 10, 4),
            [(0, 0), (1, 10), (3, 20)],
        )

    def test_gap_reject(self):
        with self.assertRaises(GapError):
            self.gap.recurrences(0, 10, 4, gap="reject")

    def test_fold_modes(self):
        tm = TimeMap(0, 30, 0, [(10, -10), (20, -20)])
        # 本地 5 有三候选
        self.assertEqual(
            tm.recurrences(5, 100, 1, fold="all"),
            [(0, 5), (0, 15), (0, 25)],
        )
        self.assertEqual(tm.recurrences(5, 100, 1, fold="earliest"), [(0, 5)])
        self.assertEqual(tm.recurrences(5, 100, 1, fold="latest"), [(0, 25)])
        with self.assertRaises(FoldError):
            tm.recurrences(5, 100, 1, fold="reject")

    def test_validation(self):
        with self.assertRaises(ValueError):
            self.gap.recurrences(0, 0, 3)
        with self.assertRaises(ValueError):
            self.gap.recurrences(0, -1, 3)
        with self.assertRaises(ValueError):
            self.gap.recurrences(0, 1, 10001)
        self.assertEqual(self.gap.recurrences(0, 1, 0), [])
        with self.assertRaises(ValueError):
            self.gap.recurrences(0, 1, 3, gap="ignore")
        with self.assertRaises(ValueError):
            self.gap.recurrences(0, 1, 3, fold="middle")


# ----------------------------------------------------------------------
# 固定种子随机逐秒枚举对照
# ----------------------------------------------------------------------

class EnumerativeTests(unittest.TestCase):

    SEED = 20260920
    N_MAPS = 60

    def test_against_second_by_second_reference(self):
        rng = random.Random(self.SEED)
        tested_points = tested_intervals = 0
        for _ in range(self.N_MAPS):
            tm = make_random_map(rng)
            # 点查询：覆盖段内与域外的本地/UTC 值
            for local in range(tm.umin - 20, tm.umax + 21):
                ref = reference_local_candidates(tm, local)
                self.assertEqual(
                    tm.local_to_utc(local, "all"), ref,
                    msg=f"local={local}, map=({tm.umin},{tm.umax})",
                )
                tested_points += 1
            for u in range(tm.umin, tm.umax):
                self.assertEqual(
                    tm.utc_to_local(u), u + reference_offset(tm, u)
                )

            # 区间查询：随机端点（含越域、空、反向）
            coords = [tm.umin, tm.umax]
            coords += [rng.randint(tm.umin - 5, tm.umax + 5) for _ in range(6)]
            for l in coords:
                for r in coords:
                    if l <= r:
                        self.assertEqual(
                            tm.local_interval_to_utc(l, r),
                            reference_local_interval(tm, l, r),
                        )
                        self.assertEqual(
                            tm.utc_interval_to_local(l, r),
                            reference_utc_interval(tm, l, r),
                        )
                    else:
                        with self.assertRaises(InvalidIntervalError):
                            tm.local_interval_to_utc(l, r)
                        with self.assertRaises(InvalidIntervalError):
                            tm.utc_interval_to_local(l, r)
                    tested_intervals += 1

        # 确认参考校验确实跑了足够多样本
        self.assertGreater(tested_points, 1000)
        self.assertGreater(tested_intervals, 2000)

    def test_recurrence_against_reference(self):
        rng = random.Random(self.SEED + 1)
        for _ in range(30):
            tm = make_random_map(rng)
            start = rng.randint(tm.umin - 10, tm.umax + 10)
            step = rng.randint(1, 7)
            count = rng.randint(0, 12)
            for fold_mode in ("earliest", "latest", "all"):
                got = tm.recurrences(start, step, count, fold=fold_mode)
                # 参考构造
                expect = []
                for j in range(count):
                    cands = reference_local_candidates(tm, start + j * step)
                    if not cands:
                        continue
                    if fold_mode == "earliest":
                        cands = cands[:1]
                    elif fold_mode == "latest":
                        cands = cands[-1:]
                    expect.extend((j, u) for u in cands)
                expect.sort(key=lambda ju: (ju[1], ju[0]))
                self.assertEqual(got, expect)

            # reject 语义：存在多候选时必须抛 FoldError，否则与 all 一致
            saw_fold = False
            expect = []
            for j in range(count):
                cands = reference_local_candidates(tm, start + j * step)
                if len(cands) > 1:
                    saw_fold = True
                    break
                if cands:
                    expect.append((j, cands[0]))
            expect.sort(key=lambda ju: (ju[1], ju[0]))
            if saw_fold:
                with self.assertRaises(FoldError):
                    tm.recurrences(start, step, count, fold="reject")
            else:
                self.assertEqual(
                    tm.recurrences(start, step, count, fold="reject"),
                    expect,
                )


if __name__ == "__main__":
    unittest.main()
