"""
스크리너 화면 만들기: site/screener/data.json 을 template.html 에 넣어 site/screener/index.html 을 만든다.

실행: python screener/render_page.py [미리보기파일.html]
"""
import json
import sys
from pathlib import Path

HERE = Path(__file__).parent
OUT = HERE.parent / "site" / "screener"


def wrap_page(body):
    return ('<!doctype html>\n<html lang="ko">\n<head>\n<meta charset="utf-8">\n'
            '<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">\n'
            '<style>:root{padding-top:env(safe-area-inset-top,0px);padding-bottom:env(safe-area-inset-bottom,0px)}'
            'body{margin:0;font-size:14px}[hidden]{display:none!important}</style>\n'
            '</head>\n<body>\n' + body + '\n</body>\n</html>\n')


def main():
    data = json.loads((OUT / "data.json").read_text(encoding="utf-8"))
    for r in data["rows"]:          # 화면에 필요 없는 값 빼기
        r.pop("cik", None)
        r.pop("date", None)
    body = (HERE / "template.html").read_text(encoding="utf-8")
    body = body.replace("/*__DATA__*/null", json.dumps(data, ensure_ascii=False, separators=(",", ":")))
    (OUT / "index.html").write_text(wrap_page(body), encoding="utf-8")
    if len(sys.argv) > 1:
        Path(sys.argv[1]).write_text(body, encoding="utf-8")
    print(f"화면 완성: {(OUT / 'index.html').stat().st_size / 1e6:.1f}MB")


if __name__ == "__main__":
    main()
