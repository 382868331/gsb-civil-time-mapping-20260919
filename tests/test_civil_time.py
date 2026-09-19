"""civil_time 库的单元测试与逐秒枚举参考验证。"""

import random
import unittest

from civil_time import (
    CivilTimeMap,
    FoldError,
    GapError,
    OutOfDomainError,
)


def brute_offset(umin, initial_offset, transitions, utc):
    """逐秒参考：某 UTC 秒的 offset。"""
    off = initial_offset
    for u, o in transitions:
        if utc >= u:
            off = o
        else:
            break
    return off


def brute_local_map(umin, umax, initial_offset, transitions):
    """逐秒参考：local -> sorted [utc]。"""
    table = {}
    for utc in range(umin, umax):
        local = utc + brute_offset(umin, initial_offset, transitions, utc)
        table.setdefault(local, []).append(utc)
    return table


def merge_points(points):
    """把升序整数点集合并成半开区间列表。"""
    out = []
    for p in points:
        if out and p <= out[-1][1]:
            if p + 1 > out[-1][1]:
                out[-1] = (out[-1][0], p + 1)
        else:
            out.append((p, p + 1))
    return out


class TestPointQueries(unittest.TestCase):
    def setUp(self):
        # 三重 fold：offset 0 -> -3600 -> -7200
        self.m = CivilTimeMap(0, 10000, 0, [(6000, -3600), (7000, -7200)])

    def test_utc_to_local_basic(self):
        self.assertEqual(self.m.utc_to_local(0), 0)
        self.assertEqual(self.m.utc_to_local(5999), 5999)

    def test_transition_point_uses_new_offset(self):
        # 转换点上即用新 offset
        self.assertEqual(self.m.utc_to_local(6000), 2400)
        self.assertEqual(self.m.utc_to_local(7000), -200)
        self.assertEqual(self.m.utc_to_local(9999), 2799)

    def test_utc_to_local_out_of_domain(self):
        with self.assertRaises(OutOfDomainError):
            self.m.utc_to_local(-1)
        with self.assertRaises(OutOfDomainError):
            self.m.utc_to_local(10000)

    def test_fold_three_candidates(self):
        # 本地 2500 同时落在三段回拨影像上
        self.assertEqual(self.m.local_to_utc(2500, "all"), [2500, 6100, 9700])
        self.assertEqual(self.m.local_to_utc(2500, "earliest"), 2500)
        self.assertEqual(self.m.local_to_utc(2500, "latest"), 9700)
        with self.assertRaises(FoldError):
            self.m.local_to_utc(2500, "reject")

    def test_unique_candidate_reject_ok(self):
        self.assertEqual(self.m.local_to_utc(5000, "all"), [5000])
        self.assertEqual(self.m.local_to_utc(5000, "reject"), 5000)

    def test_gap(self):
        # offset 前跳制造跳空
        m = CivilTimeMap(0, 10000, 0, [(5000, 1800)])
        self.assertEqual(m.local_to_utc(5500, "all"), [])
        for mode in ("earliest", "latest", "reject"):
            with self.assertRaises(GapError):
                m.local_to_utc(5500, mode)

    def test_thirty_second_change(self):
        # 30 秒前跳：30 秒跳空；30 秒回拨：30 秒双候选 fold
        fwd = CivilTimeMap(0, 10000, 0, [(5000, 30)])
        self.assertEqual(fwd.local_to_utc(5000, "all"), [])
        self.assertEqual(fwd.local_to_utc(5029, "all"), [])
        self.assertEqual(fwd.local_to_utc(5030, "all"), [5000])
        back = CivilTimeMap(0, 10000, 0, [(5000, -30)])
        self.assertEqual(back.local_to_utc(4970, "all"), [4970, 5000])
        self.assertEqual(back.local_to_utc(4999, "all"), [4999, 5029])

    def test_bad_construction(self):
        with self.assertRaises(ValueError):
            CivilTimeMap(100, 100, 0)  # 空域
        with self.assertRaises(ValueError):
            CivilTimeMap(0, 100, 0, [(0, 5)])  # 转换点不在域内部
        with self.assertRaises(ValueError):
            CivilTimeMap(0, 100, 0, [(100, 5)])
        with self.assertRaises(ValueError):
            CivilTimeMap(0, 100, 0, [(50, 5), (50, 6)])  # 非严格递增
        with self.assertRaises(ValueError):
            CivilTimeMap(0, 100, 0, [(60, 5), (50, 6)])


class TestIntervals(unittest.TestCase):
    def setUp(self):
        self.m = CivilTimeMap(0, 10000, 0, [(6000, -3600), (7000, -7200)])

    def test_local_interval_not_just_endpoints(self):
        # 本地 [2400, 2800) 被三段 fold 覆盖，应得到三段 UTC 区间
        self.assertEqual(
            self.m.map_local_interval(2400, 2800),
            [(2400, 2800), (6000, 6400), (9600, 10000)],
        )

    def test_local_interval_merge_adjacent(self):
        # 无跳变时整段连续映射
        m = CivilTimeMap(0, 10000, 0, [(5000, 0)])
        self.assertEqual(m.map_local_interval(100, 9000), [(100, 9000)])

    def test_local_interval_empty_and_reversed(self):
        self.assertEqual(self.m.map_local_interval(100, 100), [])
        with self.assertRaises(ValueError):
            self.m.map_local_interval(200, 100)

    def test_utc_interval_clipped_to_domain(self):
        # 裁剪到域内：[−500, 1500) ∩ [0, 10000) = [0, 1500)
        self.assertEqual(
            self.m.map_utc_interval(-500, 1500), [(0, 1500, 1)])
        self.assertEqual(self.m.map_utc_interval(-500, -1), [])
        self.assertEqual(self.m.map_utc_interval(10000, 20000), [])

    def test_utc_interval_empty_and_reversed(self):
        self.assertEqual(self.m.map_utc_interval(500, 500), [])
        with self.assertRaises(ValueError):
            self.m.map_utc_interval(600, 500)

    def test_coverage_count(self):
        # 三段影像 [0,6000)、[2400,3400)、[-200,2800) 叠加，计数 1/2/3/2/1
        self.assertEqual(
            self.m.map_utc_interval(0, 10000),
            [(-200, 0, 1), (0, 2400, 2), (2400, 2800, 3),
             (2800, 3400, 2), (3400, 6000, 1)],
        )

    def test_coverage_count_subinterval(self):
        # 只取回拨段 [6000, 7000)：本地 [2400, 3400)，计数恒为 1
        self.assertEqual(self.m.map_utc_interval(6000, 7000), [(2400, 3400, 1)])


class TestRecurrence(unittest.TestCase):
    def test_recurrence_skip_gap(self):
        m = CivilTimeMap(0, 10000, 0, [(5000, 1800)])
        # 跳空区间为本地 [5000, 6800)：local 5400/6000/6600 均被跳过
        out = m.recur(4800, 600, 5, gap="skip", fold="earliest")
        self.assertEqual(out, [(0, 4800), (4, 5400)])

    def test_recurrence_reject_gap(self):
        m = CivilTimeMap(0, 10000, 0, [(5000, 1800)])
        with self.assertRaises(GapError):
            m.recur(4800, 600, 5, gap="reject")

    def test_recurrence_reordered_by_utc(self):
        # 回拨使 fold="all" 的候选按 j 递增时 utc 不递增，输出须按 utc 再 j 排序
        m = CivilTimeMap(0, 10000, 0, [(5000, -3600)])
        out = m.recur(4900, 100, 3, gap="skip", fold="all")
        # local 4900 -> [4900, 8500]；5000 -> [8600]；5100 -> [8700]
        self.assertEqual(out, [(0, 4900), (0, 8500), (1, 8600), (2, 8700)])
        self.assertEqual(out, sorted(out, key=lambda p: (p[1], p[0])))

    def test_recurrence_fold_policies(self):
        m = CivilTimeMap(0, 10000, 0, [(5000, -3600)])
        self.assertEqual(m.recur(4950, 1, 1, fold="earliest"), [(0, 4950)])
        self.assertEqual(m.recur(4950, 1, 1, fold="latest"), [(0, 8550)])
        with self.assertRaises(FoldError):
            m.recur(4950, 1, 1, fold="reject")

    def test_recurrence_validation(self):
        m = CivilTimeMap(0, 100, 0)
        with self.assertRaises(ValueError):
            m.recur(0, 0, 5)
        with self.assertRaises(ValueError):
            m.recur(0, 1, -1)
        self.assertEqual(m.recur(0, 1, 0), [])


class TestBruteForceReference(unittest.TestCase):
    """固定种子小样本：逐秒枚举参考对照。"""

    def test_random_tables(self):
        rng = random.Random(20260920)
        for trial in range(30):
            umin = rng.randint(-50, 0)
            umax = umin + rng.randint(30, 200)
            n_trans = rng.randint(0, 4)
            points = sorted(rng.sample(range(umin + 1, umax), min(n_trans, umax - umin - 1))) if umax - umin > 1 else []
            transitions = [(u, rng.randint(-10, 10)) for u in points]
            initial = rng.randint(-10, 10)
            m = CivilTimeMap(umin, umax, initial, transitions)
            ref = brute_local_map(umin, umax, initial, transitions)

            # 点查询：域内每个本地时刻的候选集合一致
            lo = umin + min(initial, 0) - 15
            hi = umax + max(initial, 0) + 15
            for local in range(lo, hi):
                self.assertEqual(
                    m.local_to_utc(local, "all"),
                    ref.get(local, []),
                    f"trial={trial} local={local}",
                )

            # 区间映射：本地区间 -> UTC 区间
            for _ in range(10):
                a = rng.randint(lo, hi)
                b = rng.randint(a, hi)
                want = merge_points(
                    [u for u in range(umin, umax)
                     if a <= u + brute_offset(umin, initial, transitions, u) < b]
                )
                self.assertEqual(m.map_local_interval(a, b), want,
                                 f"trial={trial} [{a},{b})")

            # 反向映射：UTC 区间 -> 覆盖计数恒定段
            for _ in range(10):
                a = rng.randint(umin - 20, umax + 20)
                b = rng.randint(a, umax + 20)
                cover = {}
                for u in range(max(a, umin), min(b, umax)):
                    local = u + brute_offset(umin, initial, transitions, u)
                    cover[local] = cover.get(local, 0) + 1
                want = []
                if cover:
                    for local in sorted(cover):
                        c = cover[local]
                        if want and want[-1][1] == local and want[-1][2] == c:
                            want[-1] = (want[-1][0], local + 1, c)
                        else:
                            want.append((local, local + 1, c))
                self.assertEqual(m.map_utc_interval(a, b), want,
                                 f"trial={trial} [{a},{b})")

    def test_recurrence_matches_reference(self):
        rng = random.Random(7)
        for _ in range(20):
            umin, umax = 0, rng.randint(50, 150)
            n = rng.randint(1, 3)
            points = sorted(rng.sample(range(1, umax), n))
            transitions = [(u, rng.randint(-8, 8)) for u in points]
            m = CivilTimeMap(umin, umax, rng.randint(-8, 8), transitions)
            start = rng.randint(-10, 10)
            step = rng.randint(1, 7)
            count = rng.randint(1, 40)
            out = m.recur(start, step, count, gap="skip", fold="all")
            want = []
            for j in range(count):
                for utc in m.local_candidates(start + j * step):
                    want.append((j, utc))
            want.sort(key=lambda p: (p[1], p[0]))
            self.assertEqual(out, want)
            # 每个 UTC 最多对应一个 j
            self.assertEqual(len({u for _, u in out}), len(out))


if __name__ == "__main__":
    unittest.main()
