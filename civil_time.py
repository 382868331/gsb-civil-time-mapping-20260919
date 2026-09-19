"""显式转换表的整数秒民用时间映射库。

只使用调用方提供的转换表，不读取系统时区或 IANA 数据库，不解析真实日历。

模型：
  - 有限 UTC 半开域 [umin, umax)，umin < umax，均为整数秒。
  - 初始 offset，加上若干严格递增的转换 (utc, new_offset)，
    转换点必须落在域内部（umin < utc < umax），点上即使用新 offset。
  - local = utc + offset（offset 在相邻转换点之间为常数）。

由此本地时间轴上可能出现 fold（一个本地时刻对应多个 UTC，可能超过 2 个）
和 gap（本地时刻没有对应 UTC）。
"""

from bisect import bisect_right

__all__ = [
    "CivilTimeMap",
    "CivilTimeError",
    "OutOfDomainError",
    "GapError",
    "FoldError",
]


class CivilTimeError(Exception):
    """本库所有领域错误的基类。"""


class OutOfDomainError(CivilTimeError):
    """UTC 越出有限域 [umin, umax)。"""


class GapError(CivilTimeError):
    """本地时刻落在跳空区间，没有任何候选 UTC。"""


class FoldError(CivilTimeError):
    """本地时刻有多个候选 UTC，但调用方要求唯一。"""


def _check_int(name, value):
    if not isinstance(value, int) or isinstance(value, bool):
        raise TypeError(f"{name} 必须是 int，得到 {value!r}")
    return value


class CivilTimeMap:
    """基于显式转换表的分段常数 offset 映射。"""

    def __init__(self, umin, umax, initial_offset, transitions=()):
        _check_int("umin", umin)
        _check_int("umax", umax)
        _check_int("initial_offset", initial_offset)
        if not umin < umax:
            raise ValueError(f"需要 umin < umax，得到 [{umin}, {umax})")

        trans = [(_check_int("utc", u), _check_int("new_offset", o))
                 for u, o in transitions]
        for i, (u, _o) in enumerate(trans):
            if not umin < u < umax:
                raise ValueError(f"转换点 {u} 必须在域内部 ({umin}, {umax})")
            if i and u <= trans[i - 1][0]:
                raise ValueError("转换点必须严格递增")

        self.umin = umin
        self.umax = umax
        # 段 i 覆盖 [starts[i], starts[i+1])（末段到 umax），offset 为 offsets[i]
        self._starts = [umin] + [u for u, _ in trans]
        self._offsets = [initial_offset] + [o for _, o in trans]
        self._ends = self._starts[1:] + [umax]

    # ---------------------------------------------------------------- 点查询

    def utc_to_local(self, utc):
        """UTC -> 本地时刻。越域抛 OutOfDomainError。"""
        _check_int("utc", utc)
        if not self.umin <= utc < self.umax:
            raise OutOfDomainError(
                f"utc={utc} 不在域 [{self.umin}, {self.umax}) 内")
        i = bisect_right(self._starts, utc) - 1
        return utc + self._offsets[i]

    def local_candidates(self, local):
        """本地时刻 -> 域内全部候选 UTC，升序唯一列表（可能为空）。"""
        _check_int("local", local)
        out = []
        for s, e, o in zip(self._starts, self._ends, self._offsets):
            c = local - o
            if s <= c < e:
                out.append(c)
        out.sort()
        return out

    def local_to_utc(self, local, mode="all"):
        """本地时刻 -> UTC。

        mode:
          "all"      返回升序唯一候选列表，无候选返回 []。
          "earliest" 返回最小候选，无候选抛 GapError。
          "latest"   返回最大候选，无候选抛 GapError。
          "reject"   恰好一个候选才返回，否则抛 FoldError / GapError。
        """
        cands = self.local_candidates(local)
        if mode == "all":
            return cands
        if mode == "earliest":
            if not cands:
                raise GapError(f"local={local} 落在跳空区间")
            return cands[0]
        if mode == "latest":
            if not cands:
                raise GapError(f"local={local} 落在跳空区间")
            return cands[-1]
        if mode == "reject":
            if not cands:
                raise GapError(f"local={local} 落在跳空区间")
            if len(cands) > 1:
                raise FoldError(
                    f"local={local} 有 {len(cands)} 个候选 {cands}")
            return cands[0]
        raise ValueError(f"未知 mode: {mode!r}")

    # -------------------------------------------------------------- 区间映射

    def map_local_interval(self, l, r):
        """本地 [l, r) -> 所有符合条件的域内 UTC 半开区间列表。

        逐段求交后映射回 UTC，升序排列并合并相邻（首尾相接）段。
        空区间返回 []，反向区间（l > r）抛 ValueError。
        """
        _check_int("l", l)
        _check_int("r", r)
        if l > r:
            raise ValueError(f"反向区间 [{l}, {r})")
        if l == r:
            return []
        pieces = []
        for s, e, o in zip(self._starts, self._ends, self._offsets):
            lo = max(l, s + o)
            hi = min(r, e + o)
            if lo < hi:
                pieces.append((lo - o, hi - o))
        pieces.sort()
        merged = []
        for a, b in pieces:
            if merged and a <= merged[-1][1]:
                if b > merged[-1][1]:
                    merged[-1] = (merged[-1][0], b)
            else:
                merged.append((a, b))
        return merged

    def map_utc_interval(self, u, v):
        """UTC [u, v) -> 本地覆盖计数恒定的最大半开段。

        先裁剪到域内；空结果返回 []。反向区间（u > v）抛 ValueError。
        返回 [(local_start, local_end, count), ...]，升序、互不重叠，
        每段内被裁剪后 UTC 区间覆盖的本地点计数恒定（count >= 1）。
        """
        _check_int("u", u)
        _check_int("v", v)
        if u > v:
            raise ValueError(f"反向区间 [{u}, {v})")
        a = max(u, self.umin)
        b = min(v, self.umax)
        if a >= b:
            return []
        events = {}
        for s, e, o in zip(self._starts, self._ends, self._offsets):
            lo = max(a, s)
            hi = min(b, e)
            if lo < hi:
                events[lo + o] = events.get(lo + o, 0) + 1
                events[hi + o] = events.get(hi + o, 0) - 1
        out = []
        count = 0
        prev = None
        for pos in sorted(events):
            if prev is not None and pos > prev and count > 0:
                if out and out[-1][1] == prev and out[-1][2] == count:
                    out[-1] = (out[-1][0], pos, count)
                else:
                    out.append((prev, pos, count))
            count += events[pos]
            prev = pos
        return out

    # -------------------------------------------------------------- 有限递推

    def recur(self, start, step, count, gap="skip", fold="earliest"):
        """有限递推 local_j = start + j*step，0 <= j < count，step > 0。

        gap:  "skip" 跳过无候选的 j；"reject" 遇跳空抛 GapError。
        fold: "earliest"/"latest" 取候选端点；"all" 保留全部候选；
              "reject" 遇多候选抛 FoldError。
        返回 [(j, utc), ...]，按 (utc, j) 升序。每个 UTC 最多对应一个 j
        （不同 j 的本地时刻不同，同一 UTC 的本地时刻唯一），
        一个 j 在 fold="all" 下可对应多个 UTC；不做跨 j 去重。
        """
        _check_int("start", start)
        _check_int("step", step)
        _check_int("count", count)
        if step <= 0:
            raise ValueError(f"step 必须为正，得到 {step}")
        if count < 0:
            raise ValueError(f"count 不能为负，得到 {count}")
        if gap not in ("skip", "reject"):
            raise ValueError(f"未知 gap 策略: {gap!r}")
        if fold not in ("earliest", "latest", "all", "reject"):
            raise ValueError(f"未知 fold 策略: {fold!r}")

        out = []
        for j in range(count):
            local = start + j * step
            cands = self.local_candidates(local)
            if not cands:
                if gap == "reject":
                    raise GapError(f"j={j} local={local} 落在跳空区间")
                continue
            if len(cands) > 1:
                if fold == "reject":
                    raise FoldError(
                        f"j={j} local={local} 有 {len(cands)} 个候选 {cands}")
                if fold == "earliest":
                    cands = cands[:1]
                elif fold == "latest":
                    cands = cands[-1:]
                # fold == "all" 保留全部
            for utc in cands:
                out.append((j, utc))
        out.sort(key=lambda p: (p[1], p[0]))
        return out
