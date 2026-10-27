# stock-tools

CAN SLIM(오닐) 방식 매매 공부용 개인 도구 모음.

사이트: https://ytigerk.github.io/stock-tools

## 도구
| 도구 | 경로 | 상태 |
|---|---|---|
| 매물 출회일 체커 | `distribution/` | 완성 |
| 과거 대장주 서칭 | | 예정 |
| 스크리너 + 차트 뷰어 | | 예정 |

## 매물 출회일 체커 규칙
- 매물 출회일: 전일 종가 대비 **-0.2% 이하** 하락 + 거래량 **증가**
- 개수: 최근 **25거래일** 안의 매물 출회일 (소멸 규칙 없음)
- 거래량 기준
  - NASDAQ 종합지수: 나스닥 거래소 거래량 (Yahoo `^IXIC`)
  - S&P 500: 구성종목 약 500개 거래량 합산
  - NYSE 종합지수: NYSE 거래량 (Yahoo `^NYA`)
- 데이터: Yahoo Finance (무료, 비공식)

## 자동 갱신
`.github/workflows/update-site.yml` 이 한국 시간 화~토 오전 7시쯤 실행되어 사이트를 새로 만든다.
Actions 탭 → "사이트 갱신" → **Run workflow** 로 직접 실행할 수도 있다.

## 폴더 구조
```
home/index.html               첫 화면 (도구 목록)
distribution/update_data.py   데이터 수집 + 매물 출회일 계산 + 페이지 만들기
distribution/template.html    매물 출회일 체커 화면
distribution/sp500_constituents.csv   S&P 500 구성종목 목록 (예비용)
.github/workflows/            자동 실행 설정
```
`site/` 폴더는 자동으로 만들어지는 결과물이라 저장소에 올리지 않는다.
