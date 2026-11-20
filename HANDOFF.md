# 인계 메모 (2026-11-20)

## 사용자 정보와 작업 방식
- 코딩을 모르는 초보자, Windows, QHD 모니터. 오닐 CAN SLIM 공부 중.
- 항상 한국어로, 쉽게 설명. 한 단계씩 진행.
- 변경 전에 채팅에서 미리보기를 먼저 보여주고, 사용자가 "승인"하면 GitHub에 반영.

## 사이트
- 주소: https://ytigerk.github.io/stock-tools (첫 화면이 매물 출회일 체커)
- 저장소: ytigerk/stock-tools (공개), GitHub Pages로 배포
- 스크리너는 2026-11-20에 삭제함. finviz와 트레이딩뷰로 대체. 코드는 git 기록에 남아 있음.

## 매물 출회일 규칙
- 지수 등락률 -0.2% 이하 + 거래량이 전날보다 증가 → 매물 출회일(O)
- 최근 5주(25거래일) 또는 6주(30거래일) 동안 개수를 셈. 화면에서 5주/6주 전환 가능. 만료 규칙 없음.
- 대상 지수: NASDAQ, S&P 500, NYSE

## 데이터
- 가격: Yahoo Finance 지수 일봉 (^IXIC, ^GSPC, ^NYA). 장중 미완성 봉은 제외.
- 거래량: Massive(무료 플랜) 종목별 일봉을 합산 (grouped daily, adjusted=false)
  - NASDAQ = 나스닥 상장 보통주 합계, NYSE = NYSE 상장 보통주 합계, S&P 500 = 구성종목 합계
  - 보통주 유형: CS, ADRC, OS, NYRS, GDR. 프리·애프터마켓 포함.
  - 무료 플랜 제약: 분당 5회 요청. 해당일 데이터는 뉴욕 자정 이후 확정이고, 그 전에는 403이 나서 그날은 건너뜀.
  - 마지막 2거래일은 매번 다시 받아서 확인.
  - 2025-10-01부터 기록이 쌓여 있음 (volume.csv).
- 트레이딩뷰나 영웅문의 거래량과 정의가 달라서 숫자가 다를 수 있음. 사용자가 "나만의 데이터"로 가기로 결정함.

## 자동 갱신
- GitHub Actions "사이트 갱신": 화~토 한국시간 오후 3:07 (UTC 06:07)
- 순서: massive_volume.py → update_data.py → 데이터 파일 커밋 → Pages 배포
- 비밀값: MASSIVE_API_KEY (GitHub Secrets). SEC_USER_AGENT는 더 이상 안 씀.
- 매일 커밋이 생기므로 60일 비활성 자동 중지에는 걸리지 않음.

## 파일 구조
- distribution/update_data.py: 지수 가격과 거래량을 계산해서 페이지와 data.json 생성
- distribution/massive_volume.py: Massive에서 거래량을 받아 volume.csv에 저장
- distribution/template.html: 화면 (왼쪽: 요약·달력·표 / 오른쪽: 차트 3개)
- distribution/history.csv, volume.csv, tickers.json, sp500_constituents.csv: 누적 데이터
- site_common.py: 공통 메뉴와 페이지 틀
- .github/workflows/update-site.yml: 자동 갱신 설정
- 차트: TradingView Lightweight Charts 4.2.0

## 화면 구성
- 왼쪽: 5주/6주 전환, 요약 카드, 6개월 달력, 상세 표("매물 출회일" O/X), 데이터 지연 경고
- 오른쪽: 지수별 일봉 차트 3개 (매물 출회일에 검은 화살표, 집계 구간 음영, 차트끼리 동기화)
- 달력 날짜를 클릭하면 차트가 이동하고, 차트를 클릭하면 달력에서 해당 날짜가 선택됨

## 보류 중인 아이디어 (사용자가 요청할 때만 진행)
- 과거 주도주 검색 기능
- 갱신 시각을 앞당기기 (Massive가 뉴욕 밤 9시쯤 데이터를 주는 경우가 있었음)
