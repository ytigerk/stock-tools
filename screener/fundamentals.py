"""
SEC 실적 데이터(companyfacts) 정리 모듈

SEC 원본은 회사마다 항목 이름, 보고 방식(누적/분기), 회계연도, 정정, 주식 분할이 제각각이다.
이 모듈은 한 회사의 companyfacts JSON 을 받아 아래처럼 정리된 숫자로 바꾼다.

 - 분기 EPS (희석, 없으면 기본) : 4분기는 "연간 - 9개월 누적" 으로 계산
 - 분기 매출
 - 연간 EPS
 - ROE (최근 회계연도 순이익 / 평균 자기자본)
 - 영업이익 (분기, 연간) : "일회성 의심" 판단용
 - 주식 분할 보정 : 분할 이전에 제출된 숫자는 분할 비율로 나눠서 맞춘다
"""
import datetime as dt

FORMS = {"10-Q", "10-K", "10-Q/A", "10-K/A", "10-KT"}
EPS_TAGS = ["EarningsPerShareDiluted", "EarningsPerShareBasicAndDiluted", "EarningsPerShareBasic"]
REV_TAGS = ["Revenues", "RevenueFromContractWithCustomerExcludingAssessedTax",
            "RevenueFromContractWithCustomerIncludingAssessedTax", "SalesRevenueNet"]
NI_TAGS = ["NetIncomeLoss", "ProfitLoss", "NetIncomeLossAvailableToCommonStockholdersBasic"]
OP_TAGS = ["OperatingIncomeLoss"]
EQ_TAGS = ["StockholdersEquity", "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest"]


def d(s):
    return dt.date.fromisoformat(s)


def _facts(gaap, tags, unit):
    """여러 태그의 값을 기간별로 모은다. 같은 기간은 가장 최근에 제출된 값을 쓴다.
    태그 우선순위가 높은 쪽(앞쪽)을 먼저 채우고, 빈 기간만 뒤쪽 태그로 채운다."""
    out = {}
    for tag in tags:
        items = gaap.get(tag, {}).get("units", {}).get(unit, [])
        best = {}
        for f in items:
            if f.get("form") not in FORMS:
                continue
            key = (f.get("start"), f["end"])
            if key not in best or f["filed"] > best[key]["filed"]:
                best[key] = f
        for key, f in best.items():
            out.setdefault(key, f)
    return out


def _split_factor(filed, splits):
    """filed 날짜 이후에 일어난 분할 비율의 곱. (예: 10:1 분할 이전 제출 값은 10으로 나눠야 함)"""
    k = 1.0
    for day, ratio in splits:
        if day > filed:
            k *= ratio
    return k


def _days(f):
    return (d(f["end"]) - d(f["start"])).days


def quarterly(gaap, tags, unit, splits, per_share):
    """분기 값 사전 {분기말 날짜: {'v': 값, 'derived': 계산으로 만든 값인지}}"""
    facts = _facts(gaap, tags, unit)
    adj = lambda f: f["val"] / (_split_factor(f["filed"], splits) if per_share else 1.0)
    dur = {}
    for (start, end), f in facts.items():
        if not start:
            continue
        n = _days(f)
        kind = "Q" if 80 <= n <= 100 else "H" if 170 <= n <= 190 else "9M" if 260 <= n <= 285 else "FY" if 350 <= n <= 380 else None
        if kind:
            dur.setdefault(kind, []).append((start, end, adj(f)))
    q = {end: {"v": v, "start": start, "derived": False} for start, end, v in dur.get("Q", [])}

    def find_q(start, end):
        return next((x for e, x in q.items() if x["start"] == start and e == end), None)

    # 누적값에서 빠진 분기 만들기: 6개월-1분기, 9개월-6개월, 연간-9개월
    for longer, shorter in (("H", None), ("9M", "H"), ("FY", "9M")):
        for start, end, v in dur.get(longer, []):
            if end in q:
                continue
            prev_total = None
            if shorter is None:  # 6개월 누적 - 1분기
                first = [x for e, x in q.items() if x["start"] == start and e < end]
                if first:
                    prev_total, prev_end = first[0]["v"], max(e for e, x in q.items() if x["start"] == start and e < end)
            else:
                cands = [(e2, v2) for s2, e2, v2 in dur.get(shorter, []) if s2 == start and e2 < end]
                if cands:
                    prev_end, prev_total = max(cands)
            if prev_total is None and longer == "FY":
                # 9개월 누적이 없으면 1~3분기 합으로
                inside = sorted((e, x["v"]) for e, x in q.items() if x["start"] >= start and e < end)
                if len(inside) == 3:
                    prev_total, prev_end = sum(v2 for _, v2 in inside), inside[-1][0]
            if prev_total is not None:
                q[end] = {"v": v - prev_total, "start": (d(prev_end) + dt.timedelta(days=1)).isoformat(), "derived": True}
    return dict(sorted(q.items()))


def annual(gaap, tags, unit, splits, per_share):
    facts = _facts(gaap, tags, unit)
    out = {}
    for (start, end), f in facts.items():
        if start and 350 <= _days(f) <= 380 and f["form"].startswith("10-K"):
            v = f["val"] / (_split_factor(f["filed"], splits) if per_share else 1.0)
            out[end] = v
    return dict(sorted(out.items()))


def instant(gaap, tags, unit):
    facts = _facts(gaap, tags, unit)
    return dict(sorted((end, f["val"]) for (start, end), f in facts.items() if not start))


def _match(series, end, back_days):
    """end 에서 back_days 전후(±25일)에 끝나는 기간 찾기"""
    target = d(end) - dt.timedelta(days=back_days)
    best = None
    for e in series:
        gap = abs((d(e) - target).days)
        if gap <= 25 and (best is None or gap < best[0]):
            best = (gap, e)
    return best[1] if best else None


def growth(cur, prev):
    """증가율(%)과 상태. 상태: 'ok' / 'turnaround'(흑자 전환) / 'loss'(현재 적자) / None(비교 불가)"""
    if cur is None or prev is None:
        return None, None
    if cur <= 0:
        return None, "loss"
    if prev <= 0:
        return None, "turnaround"
    return round((cur / prev - 1) * 100, 1), "ok"


def summarize(companyfacts, splits=()):
    """한 회사의 정리된 실적 요약"""
    gaap = companyfacts.get("facts", {}).get("us-gaap", {})
    splits = sorted(splits)
    eps_q = quarterly(gaap, EPS_TAGS, "USD/shares", splits, True)
    rev_q = quarterly(gaap, REV_TAGS, "USD", splits, False)
    eps_y = annual(gaap, EPS_TAGS, "USD/shares", splits, True)
    ni_y = annual(gaap, NI_TAGS, "USD", splits, False)
    eq = instant(gaap, EQ_TAGS, "USD")
    op_q = quarterly(gaap, OP_TAGS, "USD", splits, False)
    op_y = annual(gaap, OP_TAGS, "USD", splits, False)

    quarters = []
    for end in list(eps_q)[-8:]:
        prev = _match(eps_q, end, 364)
        g, st = growth(eps_q[end]["v"], eps_q[prev]["v"] if prev else None)
        rprev = _match(rev_q, end, 364) if end in rev_q else None
        rg, _ = growth(rev_q[end]["v"], rev_q[rprev]["v"]) if end in rev_q and rprev else (None, None)
        oprev = _match(op_q, end, 364) if end in op_q else None
        og, ost = growth(op_q[end]["v"], op_q[oprev]["v"]) if end in op_q and oprev else (None, None)
        quarters.append({"end": end, "eps": round(eps_q[end]["v"], 4), "epsPrev": round(eps_q[prev]["v"], 4) if prev else None,
                         "epsG": g, "epsSt": st, "derived": eps_q[end]["derived"],
                         "rev": rev_q[end]["v"] if end in rev_q else None, "revG": rg,
                         "opG": og, "opSt": ost})

    out = {"quarters": quarters}
    if eps_y:
        last = list(eps_y)[-1]
        old = _match(eps_y, last, 3 * 365)
        out["epsY"] = {"end": last, "eps": round(eps_y[last], 4), "eps3y": round(eps_y[old], 4) if old else None}
        cur, base = eps_y[last], eps_y[old] if old else None
        if base is None:
            out["epsY"]["cagr"], out["epsY"]["st"] = None, None
        elif cur <= 0:
            out["epsY"]["cagr"], out["epsY"]["st"] = None, "loss"
        elif base <= 0:
            out["epsY"]["cagr"], out["epsY"]["st"] = None, "turnaround"
        else:
            out["epsY"]["cagr"], out["epsY"]["st"] = round(((cur / base) ** (1 / 3) - 1) * 100, 1), "ok"
    if op_y and "epsY" in out:
        last = out["epsY"]["end"]
        old = _match(op_y, last, 3 * 365)
        if last in op_y and old:
            cur, base = op_y[last], op_y[old]
            out["epsY"]["opCagr"] = round(((cur / base) ** (1 / 3) - 1) * 100, 1) if cur > 0 and base > 0 else None
    if ni_y:
        last = list(ni_y)[-1]
        e_end = eq.get(last)
        e_beg = eq.get(_match(eq, last, 365)) if _match(eq, last, 365) else None
        avg = (e_end + e_beg) / 2 if e_end and e_beg else e_end
        out["roe"] = {"end": last, "roe": round(ni_y[last] / avg * 100, 1) if avg and avg > 0 else None}
    return out
