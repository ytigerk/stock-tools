# stock-tools

CAN SLIM(오닐) 방식 매매 공부용 개인 도구. PC 화면 기준.

사이트: https://ytigerk.github.io/stock-tools

## 도구
사이트 주소로 들어가면 바로 **매물 출회일 체커**가 뜬다. (예전 주소 `…/distribution/` 은 첫 화면으로 넘어감)

## 매물 출회일 체커 규칙
- 매물 출회일: 전일 종가 대비 **-0.2% 이하** 하락 + 거래량 **증가**
- 개수: 최근 **5주(25거래일) / 6주(30거래일)** 선택. 소멸 규칙 없음
- 거래량 기준: 세 지수 모두 **그날 구성 종목 거래량의 합계** (지수 자체는 거래되지 않으므로)
  - NASDAQ 종합지수: 그날 거래된 나스닥 상장 보통주 전체 (약 3,400개)
  - NYSE 종합지수: 그날 거래된 NYSE 상장 보통주 전체 (약 1,900개)
  - S&P 500: 구성종목 약 500개 (현재 구성 기준)
  - 신규 상장·상장폐지 종목도 그날 거래됐으면 그대로 포함
  - 출처: Massive 전 종목 일봉 (`adjusted=false`, 병합·분할 조정 전 원래 거래량. 프리·애프터마켓 포함)
  - 종목 거래량은 체결 장소(거래소, 장외)와 상관없이 전부 센 값. "나스닥 거래소 안 체결량"과는 다름
  - 기록: `distribution/volume.csv` (날짜별 합계와 합산 종목 수), 종목의 상장 거래소·종류: `distribution/tickers.json`
- 가격(시가·고가·저가·종가)은 Yahoo 지수 값
- 화면: 왼쪽에 지수별 개수(0~2 양호 / 3~4 주의 / 5 이상 경계), 캘린더 6개월, 날짜별 상세
- 오른쪽: 세 지수 일봉 차트 6개월. 매물 출회일 ▼, 집계 기간 칠하기, 세 차트 기간·십자선 연동, 캘린더와 날짜 연동
- 계산 결과: `distribution/history.csv`
- 미국 장중이나 애프터마켓 중에 실행하면 오늘은 빼고 계산

## 정리한 도구
- 주식 스크리너 (2026-11 삭제): 거르기는 finviz, 차트 검토는 TradingView 를 쓰기로 함. 코드는 GitHub 기록에 남아 있음

## 자동 갱신
`.github/workflows/update-site.yml` 이 한국 시간 화~토 **오후 3시쯤** 하루 한 번 실행되어 사이트를 새로 만든다 (약 3~5분).
Massive 무료 플랜은 미국 동부 시간 자정이 지나야 그 거래일 일봉을 주기 때문이다 (자정 전 요청은 403).
어떤 지수의 최신 날짜만 빠지면 매물 출회일 화면 위에 경고가 뜬다.
Actions 탭 → "사이트 갱신" → **Run workflow** 로 직접 실행할 수도 있다.

필요한 저장소 비밀값 (Settings → Secrets and variables → Actions)
- `MASSIVE_API_KEY`: Massive(구 Polygon) API 키 (무료 플랜. 분당 5회 제한)

## 폴더 구조
```
site_common.py                  공통: 페이지 감싸기, 왼쪽 메뉴
distribution/update_data.py     매물 출회일: 지수 가격(Yahoo) + 거래량 기록 → 계산 → 사이트 첫 화면
distribution/template.html      매물 출회일 화면
distribution/massive_volume.py  지수 거래량: Massive 전 종목 일봉 → 구성 종목 합계 (volume.csv)
distribution/volume.csv         날짜별 지수 거래량 기록 (자동 작업이 매일 추가)
distribution/tickers.json       종목별 상장 거래소·종류 (상장폐지 종목 포함, 계속 늘어남)
distribution/sp500_constituents.csv  S&P 500 구성종목 목록
distribution/history.csv        매물 출회일 계산 결과
.github/workflows/              자동 실행 설정
```
`site/` 폴더는 자동으로 만들어지는 결과물이라 저장소에 올리지 않는다.
