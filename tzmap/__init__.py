"""civil-time-mapping

整数秒、显式转换表的民用时间映射库。

给定有限 UTC 半开域 ``[umin, umax)``、初始 offset 与严格递增的转换点
``(utc, new_offset)``（转换点必须严格位于域内部，点上立即采用新 offset），
本地时刻定义为 ``local = utc + offset``。本模块不读取系统时区或 IANA 数据库，
不解析真实日历，全部运算使用整数。
"""

from bisect import bisect_right

__all__ = [
    "TimeMap",
    "TZMapError",
    "OutOfDomainError",
    "GapError",
    "FoldError",
    "InvalidIntervalError",
]

MAX_TRANSITIONS = 1000
MAX_RECURRENCE_COUNT = 10000


class TZMapError(Exception):
    """本库所有异常的基类。"""


class OutOfDomainError(TZMapError):
    """UTC 时刻落在域 ``[umin, umax)`` 之外。"""


class GapError(TZMapError):
    """本地时刻落在跳空区间，没有任何 UTC 候选。"""


class FoldError(TZMapError):
    """本地时刻对应多个 UTC 候选，但策略要求唯一（reject）。"""


class InvalidIntervalError(TZMapError):
    """区间参数非法，例如左端大于右端。"""


def _is_int(x):
    # bool 是 int 的子类，这里一并接受，整数语义不受影响。
    return isinstance(x, int)


class TimeMap:
    """基于显式转换表的整数秒 UTC/本地时间映射。

    Parameters
    ----------
    umin, umax:
        UTC 半开域 ``[umin, umax)`` 的端点，要求 ``umin < umax``。
    initial_offset:
        域起点处生效的 UTC->本地偏移（秒，可为负）。
    transitions:
        ``(utc, new_offset)`` 序列，``utc`` 必须严格递增且全部严格位于
        ``(umin, umax)`` 内；到达 ``utc`` 的瞬间立即采用 ``new_offset``。
        至多 1000 项。
    """

    def __init__(self, umin, umax, initial_offset, transitions=()):
        if not all(_is_int(x) for x in (umin, umax, initial_offset)):
            raise TypeError("umin / umax / initial_offset 必须为整数")
        if umin >= umax:
            raise ValueError(f"要求 umin < umax，得到 [{umin}, {umax})")

        trans = list(transitions)
        if len(trans) > MAX_TRANSITIONS:
            raise ValueError(
                f"转换表至多 {MAX_TRANSITIONS} 项，收到 {len(trans)} 项"
            )

        bounds = [umin]
        offsets = [initial_offset]
        prev_utc = None
        for item in trans:
            try:
                t, new_offset = item
            except (TypeError, ValueError):
                raise TypeError(
                    "每个转换必须是 (utc, new_offset) 二元组"
                ) from None
            if not _is_int(t) or not _is_int(new_offset):
                raise TypeError("转换点 utc 与 new_offset 必须为整数")
            if not (umin < t < umax):
                raise ValueError(f"转换点 {t} 必须严格位于域 ({umin}, {umax}) 内")
            if prev_utc is not None and t <= prev_utc:
                raise ValueError(
                    f"转换点必须严格递增：{t} 排在 {prev_utc} 之后"
                )
            prev_utc = t
            bounds.append(t)
            offsets.append(new_offset)
        bounds.append(umax)

        self.umin = umin
        self.umax = umax
        self.initial_offset = initial_offset
        # 段 k：UTC 半开区间 [_bounds[k], _bounds[k+1]) 内使用 _offsets[k]。
        self._bounds = bounds
        self._offsets = offsets

    # ------------------------------------------------------------------
    # 基础工具
    # ------------------------------------------------------------------

    def _segment_index(self, u):
        """返回 u 所在段的下标；u 越界时返回 -1。"""
        i = bisect_right(self._bounds, u) - 1
        if i < 0 or i >= len(self._offsets):
            return -1
        return i

    def offset_at(self, u):
        """UTC 时刻 u 处生效的偏移；越域抛出 OutOfDomainError。"""
        i = self._segment_index(u)
        if i < 0:
            raise OutOfDomainError(
                f"UTC {u} 不在域 [{self.umin}, {self.umax}) 内"
            )
        return self._offsets[i]

    # ------------------------------------------------------------------
    # 点查询
    # ------------------------------------------------------------------

    def utc_to_local(self, u):
        """UTC -> 本地，``local = u + offset(u)``。

        转换点上使用转换后的新 offset。越域抛出 OutOfDomainError。
        """
        if not _is_int(u):
            raise TypeError("u 必须为整数")
        return u + self.offset_at(u)

    def local_to_utc(self, local, mode="all"):
        """本地 -> UTC 候选。

        mode:
            ``"all"``:     返回域内全部候选（升序 list），无候选返回 ``[]``；
            ``"earliest"``:仅返回最小候选，无候选抛 GapError；
            ``"latest"``:  仅返回最大候选，无候选抛 GapError；
            ``"reject"``:  恰好一个候选时返回该候选，零个抛 GapError、
                           多个抛 FoldError。

        不假定 fold 至多两个候选。
        """
        if not _is_int(local):
            raise TypeError("local 必须为整数")
        if mode not in ("all", "earliest", "latest", "reject"):
            raise ValueError(f"未知 mode: {mode!r}")

        candidates = []
        for i, off in enumerate(self._offsets):
            u = local - off
            if self._bounds[i] <= u < self._bounds[i + 1]:
                candidates.append(u)
        # 段按 UTC 升序排列且互不相交，候选天然升序。

        if mode == "all":
            return candidates
        if not candidates:
            raise GapError(f"本地时刻 {local} 落在跳空区间，无 UTC 候选")
        if mode == "earliest":
            return candidates[0]
        if mode == "latest":
            return candidates[-1]
        if len(candidates) > 1:
            raise FoldError(
                f"本地时刻 {local} 有 {len(candidates)} 个 UTC 候选: "
                f"{candidates}（mode=reject）"
            )
        return candidates[0]

    # ------------------------------------------------------------------
    # 区间映射
    # ------------------------------------------------------------------

    def local_interval_to_utc(self, l, r):
        """把本地半开区间 ``[l, r)`` 映射为域内 UTC 半开区间列表。

        逐段求交（不能只转换端点），结果按 UTC 升序，并合并相邻段。
        空区间 ``l == r`` 返回 ``[]``；``l > r`` 抛 InvalidIntervalError。
        """
        if not _is_int(l) or not _is_int(r):
            raise TypeError("区间端点必须为整数")
        if l > r:
            raise InvalidIntervalError(f"本地区间左端 {l} 大于右端 {r}")
        if l == r:
            return []

        pieces = []
        for i, off in enumerate(self._offsets):
            lo = max(self._bounds[i], l - off)
            hi = min(self._bounds[i + 1], r - off)
            if lo < hi:
                pieces.append((lo, hi))

        # 各 UTC 段互不相交且按升序排列，piece 之间只会相邻、不会重叠。
        merged = []
        for lo, hi in pieces:
            if merged and lo <= merged[-1][1]:
                if hi > merged[-1][1]:
                    merged[-1] = (merged[-1][0], hi)
            else:
                merged.append((lo, hi))
        return merged

    def utc_interval_to_local(self, a, b):
        """把 UTC 半开区间 ``[a, b)`` 反向映射到本地时间轴。

        先裁剪到域内，再在本地时间轴上输出“覆盖计数（该本地时刻对应的
        域内 UTC 时刻个数）恒定”的最大半开段 ``(lo, hi, count)`` 列表，
        按本地时刻升序。只输出 count > 0 的被覆盖部分；跳空（count==0）
        自然不出现在结果中。空区间 ``a == b`` 返回 ``[]``；``a > b``
        抛 InvalidIntervalError。
        """
        if not _is_int(a) or not _is_int(b):
            raise TypeError("区间端点必须为整数")
        if a > b:
            raise InvalidIntervalError(f"UTC 区间左端 {a} 大于右端 {b}")
        if a == b:
            return []

        a = max(a, self.umin)
        b = min(b, self.umax)
        if a >= b:
            return []

        # 每个 UTC 段与 [a, b) 的交集映射到本地，都是权重为 1 的半开段；
        # fold 时多个段在本地时间轴上重叠，覆盖计数需要叠加，故做事件扫描。
        events = {}
        for i, off in enumerate(self._offsets):
            u_lo = max(self._bounds[i], a)
            u_hi = min(self._bounds[i + 1], b)
            if u_lo < u_hi:
                ls = u_lo + off
                le = u_hi + off
                events[ls] = events.get(ls, 0) + 1
                events[le] = events.get(le, 0) - 1

        coords = sorted(events)
        result = []
        active = 0
        run_start = None
        run_count = 0
        prev = coords[0]
        for c in coords:
            if c > prev:
                if active > 0:
                    if run_start is None:
                        run_start, run_count = prev, active
                    elif active != run_count:
                        result.append((run_start, prev, run_count))
                        run_start, run_count = prev, active
                elif run_start is not None:
                    result.append((run_start, prev, run_count))
                    run_start = None
            active += events[c]
            prev = c
        if run_start is not None:
            result.append((run_start, prev, run_count))
        return result

    # ------------------------------------------------------------------
    # 有限递推
    # ------------------------------------------------------------------

    def recurrences(self, start, step, count, *, gap="skip", fold="earliest"):
        """有限本地递推 ``local_j = start + j * step``（``0 <= j < count``）。

        Parameters
        ----------
        start, step, count:
            起点整数、正整数步长、递推次数（``0 <= count <= 10000``）。
        gap:
            ``"skip"`` 跳过落在跳空的 j；``"reject"`` 抛 GapError。
        fold:
            ``"earliest"`` / ``"latest"`` 取最小/最大 UTC；
            ``"all"`` 保留该 j 的全部候选；
            ``"reject"`` 遇到多个候选抛 FoldError。

        返回 ``(j, utc)`` 列表，按 ``(utc, j)`` 升序排列（即先按 UTC 重排，
        UTC 相同时再按 j）。因为 ``utc -> local`` 是函数而 local_j 互不相同，
        同一个 UTC 不可能对应两个 j，故无需也不会做跨 j 去重；但一个 j
        在 ``fold="all"`` 时可以对应多个 UTC。
        """
        if not _is_int(start) or not _is_int(step) or not _is_int(count):
            raise TypeError("start / step / count 必须为整数")
        if step <= 0:
            raise ValueError(f"step 必须为正整数，得到 {step}")
        if not (0 <= count <= MAX_RECURRENCE_COUNT):
            raise ValueError(
                f"count 必须满足 0 <= count <= {MAX_RECURRENCE_COUNT}，"
                f"得到 {count}"
            )
        if gap not in ("skip", "reject"):
            raise ValueError(f"未知 gap 策略: {gap!r}")
        if fold not in ("earliest", "latest", "all", "reject"):
            raise ValueError(f"未知 fold 策略: {fold!r}")

        pairs = []
        for j in range(count):
            local = start + j * step
            candidates = self.local_to_utc(local, "all")
            if not candidates:
                if gap == "reject":
                    raise GapError(
                        f"第 j={j} 个本地时刻 {local} 落在跳空区间"
                    )
                continue
            if len(candidates) > 1:
                if fold == "reject":
                    raise FoldError(
                        f"第 j={j} 个本地时刻 {local} 有 "
                        f"{len(candidates)} 个 UTC 候选: {candidates}"
                    )
                if fold == "earliest":
                    candidates = candidates[:1]
                elif fold == "latest":
                    candidates = candidates[-1:]
                # fold == "all" 保留全部
            pairs.extend((j, u) for u in candidates)

        pairs.sort(key=lambda ju: (ju[1], ju[0]))
        return pairs
