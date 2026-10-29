"""
매물 출회일(distribution day) 체커 - 데이터 수집 + 계산 스크립트

하는 일
 1. 야후에서 NASDAQ 종합지수, S&P 500, NYSE 종합지수 일봉(가격)을 받는다.
 2. 거래량은 volume.csv (massive_volume.py 가 Massive 전 종목 일봉으로 만든 구성 종목 거래량 합계)를 쓴다.
 3. 매물 출회일 판단: 전일 종가 대비 변동률 <= -0.2%  그리고  거래량 > 전일 거래량
 4. 결과를 template.html 에 넣어서 site/distribution/index.html 을 만든다.

실행: python update_data.py
"""
import csv
import datetime as dt
import json
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from site_common import nav, unfinished_day, wrap_page  # noqa: E402

HERE = Path(__file__).parent
SITE = HERE.parent / "site" / "distribution"   # 완성된 웹페이지가 저장될 폴더
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/130 Safari/537.36"}

DIST_THRESHOLD = -0.2      # 변동률(%) 이 값 이하이면 하락으로 판단
WINDOW = 25                # 최근 몇 거래일 안의 매물 출회일을 셀지
SHOW_MONTHS = 6            # 화면(캘린더, 차트)에 보여줄 기간(개월)
HISTORY = HERE / "history.csv"   # 계산 결과 기록 (가격, 거래량, 변동률, 매물 출회일 여부)

INDICES = [
    # key, 야후 심볼, 화면 이름, 거래량 기준 설명
    ("nasdaq", "^IXIC", "NASDAQ", "나스닥 상장 보통주 거래량 합산"),
    ("sp500", "^GSPC", "S&P 500", "구성종목 약 500개 거래량 합산"),
    ("nyse", "^NYA", "NYSE", "NYSE 상장 보통주 거래량 합산"),
]


def fetch_chart(symbol, rng="6mo"):
    """야후에서 일봉을 받아 {날짜: {o,h,l,c,v}} 형태로 돌려준다. 실패하면 재시도."""
    url = (f"https://query2.finance.yahoo.com/v8/finance/chart/"
           f"{urllib.parse.quote(symbol)}?range={rng}&interval=1d")
    last_err = None
    for attempt in range(5):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=30) as r:
                res = json.load(r)["chart"]["result"][0]
            q = res["indicators"]["quote"][0]
            out = {}
            for i, ts in enumerate(res.get("timestamp") or []):
                # 야후 일봉 타임스탬프는 미국 장 시작 시각 기준 -> 날짜만 사용
                day = dt.datetime.fromtimestamp(ts + res["meta"].get("gmtoffset", 0), dt.UTC).date().isoformat()
                c, v = q["close"][i], q["volume"][i]
                if c is None or day == unfinished_day():  # 장중의 미완성 봉은 버림
                    continue
                out[day] = {"o": q["open"][i], "h": q["high"][i], "l": q["low"][i], "c": c, "v": v}
            return out
        except Exception as e:  # 네트워크 오류, 요청 제한 등
            last_err = e
            time.sleep(2 * (attempt + 1))
    raise RuntimeError(f"{symbol} 데이터를 받지 못했습니다: {last_err}")


def compute(bars):
    """날짜순 일봉 리스트에 변동률, 거래량 변화, 매물 출회일 여부를 붙인다."""
    days = sorted(d for d, b in bars.items() if b["v"])  # 거래량 없는 날 제외
    rows = []
    for prev, cur in zip(days, days[1:]):
        p, c = bars[prev], bars[cur]
        chg = (c["c"] / p["c"] - 1) * 100
        vchg = (c["v"] / p["v"] - 1) * 100
        rows.append({
            "date": cur,
            "open": round(c["o"], 2) if c["o"] else round(c["c"], 2),
            "high": round(c["h"], 2) if c["h"] else round(c["c"], 2),
            "low": round(c["l"], 2) if c["l"] else round(c["c"], 2),
            "close": round(c["c"], 2),
            "chg": round(chg, 2),
            "vol": c["v"],
            "prevVol": p["v"],
            "volChg": round(vchg, 2),
            "dist": chg <= DIST_THRESHOLD and c["v"] > p["v"],
        })
    return rows


VOLUME = HERE / "volume.csv"


def load_volume():
    """{지수 키: {날짜: 거래량}}"""
    with VOLUME.open(encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    return {k: {r["date"]: int(r[k]) for r in rows if int(r[k] or 0) > 0} for k in ("nasdaq", "nyse", "sp500")}


def load_history():
    """기록 파일 읽기 → {(지수, 날짜): 줄}"""
    if not HISTORY.exists():
        return {}
    with HISTORY.open(encoding="utf-8") as f:
        return {(r["index"], r["date"]): r for r in csv.DictReader(f)}


def save_history(hist):
    cols = ["date", "index", "open", "high", "low", "close", "volume", "chg", "volChg", "dist"]
    with HISTORY.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        for key in sorted(hist, key=lambda k: (k[1], k[0])):
            w.writerow({c: hist[key].get(c, "") for c in cols})


def main():
    rng = "1y"  # 6개월 표시 + 앞쪽 여유분
    out = {"generatedAt": dt.datetime.now(dt.UTC).isoformat(timespec="seconds"),
           "rule": {"threshold": DIST_THRESHOLD, "window": WINDOW}, "indices": []}

    hist = {}
    summed = load_volume()

    for key, sym, name, vol_basis in INDICES:
        bars = fetch_chart(sym, rng)
        vol = summed[key]
        # 가격은 지수, 거래량은 구성 종목 합계(volume.csv)
        bars = {d: {**b, "v": vol[d]} for d, b in bars.items() if d in vol}
        rows = compute(bars)
        for r in rows:
            hist[(key, r["date"])] = {"date": r["date"], "index": key, "open": r["open"], "high": r["high"],
                                      "low": r["low"], "close": r["close"], "volume": r["vol"], "chg": r["chg"],
                                      "volChg": r["volChg"], "dist": int(r["dist"])}
        out["indices"].append({"key": key, "name": name, "symbol": sym,
                               "volBasis": vol_basis, "rows": rows})

    # 화면에 보여줄 기간으로 자르기 (최근 25거래일 계산은 자르기 전에 끝나도록 rows 전체를 기준으로)
    last_day = max(r["date"] for ix in out["indices"] for r in ix["rows"])
    start = dt.date.fromisoformat(last_day).replace(day=1)  # 이번 달 1일부터
    for _ in range(SHOW_MONTHS - 1):                         # 앞 달로 (SHOW_MONTHS-1)번 이동
        start = (start - dt.timedelta(days=1)).replace(day=1)
    for ix in out["indices"]:
        recent = ix["rows"][-WINDOW:]
        ix["windowStart"] = recent[0]["date"]
        ix["lastDate"] = ix["rows"][-1]["date"]  # 지수마다 최신 날짜 (하나만 늦게 올라오는 경우 경고용)
        ix["count"] = sum(r["dist"] for r in recent)
        ix["rows"] = [r for r in ix["rows"] if r["date"] >= start.isoformat()]
    out["lastDate"] = last_day

    save_history(hist)
    SITE.mkdir(parents=True, exist_ok=True)
    (SITE / "data.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    body = (HERE / "template.html").read_text(encoding="utf-8")
    body = body.replace("/*__DATA__*/null", json.dumps(out, ensure_ascii=False))
    body = body.replace("<!--__NAV__-->", nav("distribution"))
    (SITE / "index.html").write_text(wrap_page(body), encoding="utf-8")
    if len(sys.argv) > 1:  # 미리보기용: python update_data.py 미리보기파일.html
        Path(sys.argv[1]).write_text(body, encoding="utf-8")
    print(f"완료: 마지막 거래일 {last_day}")
    for ix in out["indices"]:
        print(f"  {ix['name']}: 최근 {WINDOW}거래일 매물 출회일 {ix['count']}개")


if __name__ == "__main__":
    main()
