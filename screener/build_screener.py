"""
스크리너 데이터 만들기

1. SEC 종목 목록(거래소 포함)에서 나스닥, NYSE, 기타 거래소 종목을 고른다 (OTC 제외)
2. 야후에서 1년치 일봉을 받아 주가, 50일 평균 거래량을 계산한다
3. 주가 10달러 이상, 50일 평균 거래량 5만 주 이상만 남긴다 (화면에서 조건을 바꿀 수 있도록 넉넉하게)
4. 남은 종목의 SEC 실적을 정리한다 (분기·연간 EPS, 영업이익, ROE, 분할 보정)
5. site/screener/data.json 으로 저장한다. 실제 조건 판정은 화면(브라우저)에서 한다.

실행: SEC_USER_AGENT="이름 이메일" python screener/build_screener.py [companyfacts.zip 경로]
"""
import datetime as dt
import http.cookiejar
import json
import threading
import os
import sys
import time
import urllib.parse
import urllib.error
import urllib.request
import zipfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from fundamentals import summarize  # noqa: E402
sys.path.insert(0, str(Path(__file__).parent.parent))
from site_common import unfinished_day  # noqa: E402

ROOT = Path(__file__).parent.parent
OUT = ROOT / "site" / "screener"
EXCHANGE_VOLUME = ROOT / ".cache" / "exchange_volume.json"   # 매물 출회일 체커가 쓰는 거래소별 상장 보통주 거래량 합계
YAHOO_UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/130 Safari/537.36"}
SEC_UA = {"User-Agent": os.environ.get("SEC_USER_AGENT", "")}
EXCHANGES = {"Nasdaq", "NYSE", "CBOE", "TXSE"}
MIN_PRICE, MIN_VOL = 10, 50_000      # 저장 대상 바닥값 (화면 기본 조건보다 넉넉하게)
PRICE_RANGE = "2y"                   # 야후에서 받을 일봉 기간 (주봉 차트 2년용)
# 보통주가 아닌 것 걸러내기
#  - 나스닥 5글자 코드의 마지막 글자: M/N/O/P 우선주, R 권리, U 유닛, W 워런트, Z 기타
NON_COMMON_5TH = set("MNOPRUWZ")
NON_COMMON_WORDS = ("preferred", "depositary share", "warrant", " units", " rights", "notes due", "debenture")


def is_common(ticker, exchange, long_name, kind):
    if kind and kind != "EQUITY":          # ETF, 펀드 등
        return False
    if "-P" in ticker:                       # NYSE 우선주 (예: ALL-PH)
        return False
    if exchange == "Nasdaq" and len(ticker) == 5 and ticker[-1] in NON_COMMON_5TH:
        return False
    name = (long_name or "").lower()
    return not any(w in name for w in NON_COMMON_WORDS)


def http_json(url, headers, timeout=30, tries=4):
    err = None
    for a in range(tries):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=timeout) as r:
                return json.load(r)
        except Exception as e:
            err = e
            time.sleep(2 * (a + 1))
    raise RuntimeError(f"{url}: {err}")


def yahoo_daily(sym):
    """2년치 일봉, 종목 이름, 상장일"""
    q = urllib.parse.quote(sym)
    r = http_json(f"https://query2.finance.yahoo.com/v8/finance/chart/{q}?range={PRICE_RANGE}&interval=1d", YAHOO_UA)["chart"]["result"][0]
    off = r["meta"].get("gmtoffset", 0)
    long_name = r["meta"].get("longName") or r["meta"].get("shortName")
    first_trade = r["meta"].get("firstTradeDate")  # 상장(첫 거래)일, 상장 3년 미만 판단용
    kind = r["meta"].get("instrumentType")          # EQUITY(주식), ETF 등
    qt = r["indicators"]["quote"][0]
    bars = []
    for i, ts in enumerate(r.get("timestamp") or []):
        if qt["close"][i] is None or qt["open"][i] is None:
            continue
        day = dt.datetime.fromtimestamp(ts + off, dt.UTC).date().isoformat()
        if day == unfinished_day():  # 장중의 미완성 봉은 버림
            continue
        bars.append([day, round(qt["open"][i], 4), round(qt["high"][i], 4), round(qt["low"][i], 4),
                     round(qt["close"][i], 4), qt["volume"][i] or 0])
    ipo = dt.datetime.fromtimestamp(first_trade, dt.UTC).date().isoformat() if first_trade else None
    return bars, long_name, ipo, kind


class YahooEarnings:
    """야후 실적 발표 기록에서 '가장 최근에 발표된 분기'를 알아낸다 (새 실적 반영 대기 표시용).
    야후의 숫자는 계산에 쓰지 않고 날짜만 쓴다."""

    def __init__(self):
        self.opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
        self.opener.addheaders = list(YAHOO_UA.items())
        self.lock = threading.Lock()
        self.crumb = None
        self.refresh()

    def refresh(self):
        """접속 허가표(crumb) 받기. 야후가 거절하면(429 등) 천천히 몇 번 다시 시도하고, 끝내 안 되면 None.
        이 기능은 표시용이라 실패해도 전체 작업을 멈추지 않는다."""
        with self.lock:
            try:
                self.opener.open("https://fc.yahoo.com", timeout=20)
            except Exception:
                pass  # 쿠키만 받으면 되므로 오류 응답은 무시
            self.crumb = None
            for attempt in range(6):
                host = ("query2", "query1")[attempt % 2]
                try:
                    crumb = self.opener.open(f"https://{host}.finance.yahoo.com/v1/test/getcrumb", timeout=20).read().decode()
                    if crumb and "<" not in crumb:
                        self.crumb = crumb
                        return
                except Exception:
                    pass
                time.sleep(5 * (attempt + 1))

    def latest_quarter(self, sym):
        if not self.crumb:
            return None
        for attempt in range(3):
            try:
                u = (f"https://query2.finance.yahoo.com/v10/finance/quoteSummary/{urllib.parse.quote(sym)}"
                     f"?modules=earningsHistory&crumb={urllib.parse.quote(self.crumb)}")
                with self.opener.open(u, timeout=20) as r:
                    res = json.load(r)["quoteSummary"]["result"][0]
                hist = res.get("earningsHistory", {}).get("history", [])
                ends = [h["quarter"]["fmt"] for h in hist if h.get("quarter", {}).get("fmt") and h.get("epsActual", {}).get("raw") is not None]
                return max(ends) if ends else None
            except urllib.error.HTTPError as e:
                if e.code == 401:
                    self.refresh()
                elif e.code == 404:
                    return None
                time.sleep(2 * (attempt + 1))
            except Exception:
                time.sleep(2 * (attempt + 1))
        return None


def weekly(bars):
    """일봉 [날짜, 시, 고, 저, 종, 거래량] → 주봉. 날짜는 그 주의 월요일"""
    out = []
    for day, o, h, l, c, v in bars:
        dd = dt.date.fromisoformat(day)
        monday = (dd - dt.timedelta(days=dd.weekday())).isoformat()
        if out and out[-1][0] == monday:
            w = out[-1]
            w[2], w[3], w[4], w[5] = max(w[2], h), min(w[3], l), c, w[5] + v
        else:
            out.append([monday, o, h, l, c, v])
    return out


def yahoo_splits(sym):
    q = urllib.parse.quote(sym)
    r = http_json(f"https://query2.finance.yahoo.com/v8/finance/chart/{q}?range=10y&interval=3mo&events=split", YAHOO_UA)
    ev = (r["chart"]["result"][0].get("events") or {}).get("splits", {})
    return [(dt.datetime.fromtimestamp(e["date"], dt.UTC).date().isoformat(), e["numerator"] / e["denominator"])
            for e in ev.values() if e.get("denominator")]


def main():
    zip_path = sys.argv[1] if len(sys.argv) > 1 else None
    t0 = time.time()

    # 1. 종목 목록
    tk = http_json("https://www.sec.gov/files/company_tickers_exchange.json", SEC_UA)
    universe = [dict(zip(tk["fields"], r)) for r in tk["data"] if r[3] in EXCHANGES]
    for u in universe:
        u["ysym"] = u["ticker"].replace(".", "-")
    print(f"[1] 종목 목록 {len(universe)}개")

    # 2. 주가
    def price(u):
        try:
            return u, yahoo_daily(u["ysym"])
        except Exception:
            return u, None
    with ThreadPoolExecutor(8) as ex:
        priced = list(ex.map(price, universe))
    rows, failed, skipped = [], 0, 0
    ex_sum = {"Nasdaq": {}, "NYSE": {}}   # 날짜별 거래량 합계
    ex_cnt = {"Nasdaq": {}, "NYSE": {}}   # 날짜별 합산된 종목 수 (일부 종목 자료가 아직 없는 날을 알아내기 위해)
    for u, res in priced:
        if res is None:
            failed += 1
            continue
        bars, long_name, ipo, kind = res
        if not is_common(u["ticker"], u["exchange"], long_name, kind):
            skipped += 1
            continue
        if u["exchange"] in ex_sum:   # 주가·거래량 조건과 상관없이 상장 보통주 전부 합산 (= 지수 구성 종목)
            for b in bars:
                ex_sum[u["exchange"]][b[0]] = ex_sum[u["exchange"]].get(b[0], 0) + b[5]
                ex_cnt[u["exchange"]][b[0]] = ex_cnt[u["exchange"]].get(b[0], 0) + 1
        if len(bars) < 50:
            continue
        last = bars[-1]
        vol50 = sum(b[5] for b in bars[-50:]) / 50
        if last[4] < MIN_PRICE or vol50 < MIN_VOL:
            continue
        rows.append({"t": u["ticker"], "ysym": u["ysym"], "name": u["name"], "ex": u["exchange"], "cik": u["cik"],
                     "price": round(last[4], 2), "vol50": round(vol50), "date": last[0],
                     "hi52": round(max(b[2] for b in bars[-252:]), 2), "ipo": ipo, "weeks": weekly(bars)})
    print(f"[2] 주가 수신 실패 {failed}개, 보통주 아님 {skipped}개, 바닥 조건 통과 {len(rows)}개 ({time.time() - t0:.0f}초)")
    EXCHANGE_VOLUME.parent.mkdir(exist_ok=True)
    EXCHANGE_VOLUME.write_text(json.dumps({"volume": ex_sum, "count": ex_cnt}), encoding="utf-8")
    last = {k: max(v) for k, v in ex_sum.items() if v}
    print("    거래소별 거래량 합계:", {k: f"{d} {ex_sum[k][d] / 1e9:.2f}B ({ex_cnt[k][d]}종목)" for k, d in last.items()})

    # 3. 분할 기록
    def sp(r):
        try:
            return yahoo_splits(r["ysym"])
        except Exception:
            return []
    with ThreadPoolExecutor(8) as ex:
        for r, s in zip(rows, ex.map(sp, rows)):
            r["splits"] = s
    print(f"[3] 분할 기록 ({time.time() - t0:.0f}초)")

    # 4. SEC 실적
    if zip_path is None:
        zip_path = ROOT / "companyfacts.zip"
        req = urllib.request.Request("https://www.sec.gov/Archives/edgar/daily-index/xbrl/companyfacts.zip", headers=SEC_UA)
        with urllib.request.urlopen(req, timeout=600) as r, open(zip_path, "wb") as f:
            while chunk := r.read(1 << 20):
                f.write(chunk)
    nofund = 0
    with zipfile.ZipFile(zip_path) as z:
        names = set(z.namelist())
        for r in rows:
            name = f"CIK{r['cik']:010d}.json"
            if name not in names:
                r["f"] = None
                nofund += 1
                continue
            try:
                r["f"] = summarize(json.loads(z.read(name)), r["splits"])
            except Exception as e:
                r["f"] = None
                nofund += 1
    print(f"[4] 실적 정리 완료, 실적 없음 {nofund}개 ({time.time() - t0:.0f}초)")

    # 5. 야후 실적 발표 기록 (실적이 있는 종목만)
    ye = YahooEarnings()
    targets = [r for r in rows if r["f"]]
    if ye.crumb:
        with ThreadPoolExecutor(4) as ex:
            for r, yq in zip(targets, ex.map(lambda r: ye.latest_quarter(r["ysym"]), targets)):
                r["yq"] = yq
        got = sum(1 for r in targets if r.get("yq"))
        print(f"[5] 야후 실적 발표 기록 {got}/{len(targets)}개 ({time.time() - t0:.0f}초)")
    else:
        print("[5] 야후가 실적 발표 기록 접속을 거절해서 '새 실적 반영 대기' 확인은 건너뜀")

    # 6. 저장 (주봉 차트 자료는 종목별 파일로 따로)
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "charts").mkdir(exist_ok=True)
    for r in rows:
        (OUT / "charts" / f"{r['ysym']}.json").write_text(json.dumps(r.pop("weeks"), separators=(",", ":")), encoding="utf-8")
        r.pop("splits")
    data = {"generatedAt": dt.datetime.now(dt.UTC).isoformat(timespec="seconds"),
            "priceDate": max(r["date"] for r in rows), "rows": rows}
    (OUT / "data.json").write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"[6] 저장: {len(rows)}개 종목, data.json {(OUT / 'data.json').stat().st_size / 1e6:.1f}MB ({time.time() - t0:.0f}초)")


if __name__ == "__main__":
    main()
