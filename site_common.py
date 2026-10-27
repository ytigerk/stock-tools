"""
여러 페이지가 함께 쓰는 부분: 완전한 웹페이지로 감싸기, 왼쪽 메뉴
"""

MENU = [
    ("distribution", "매물 출회일 체커"),
    ("screener", "주식 스크리너"),
]

NAV_CSS = """
<style>
.sidenav {
  display: flex; flex-direction: column; gap: 2px; padding: 16px 10px; min-width: 0;
  background: var(--surface); border-right: 1px solid var(--line);
}
.sidenav .brand {
  font-weight: 700; font-size: 0.95rem; color: var(--ink); text-decoration: none;
  padding: 4px 10px 14px; letter-spacing: -0.01em;
}
.sidenav a.item {
  color: var(--muted); text-decoration: none; font-size: 0.86rem; padding: 8px 10px; border-radius: 8px;
}
.sidenav a.item:hover { color: var(--ink); background: var(--bg); }
.sidenav a.item[aria-current="page"] { color: var(--accent); background: var(--bg); font-weight: 600; }
.sidenav a:focus-visible { outline: 2px solid var(--accent); outline-offset: 1px; }
</style>
"""


def nav(active):
    """왼쪽 메뉴 HTML. 각 도구 폴더(distribution/, screener/) 안의 페이지에서 쓴다."""
    items = "".join(
        f'<a class="item" href="../{key}/index.html"{" aria-current=\"page\"" if key == active else ""}>{label}</a>'
        for key, label in MENU)
    return f'{NAV_CSS}<nav class="sidenav" aria-label="도구 메뉴"><a class="brand" href="../index.html">Stock Tools</a>{items}</nav>'


def wrap_page(body):
    """화면 파일(템플릿)을 완전한 웹페이지 형식으로 감싼다."""
    return ('<!doctype html>\n<html lang="ko">\n<head>\n<meta charset="utf-8">\n'
            '<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">\n'
            '<style>:root{padding-top:env(safe-area-inset-top,0px);padding-bottom:env(safe-area-inset-bottom,0px)}'
            'body{margin:0;font-size:14px}[hidden]{display:none!important}</style>\n'
            '</head>\n<body>\n' + body + '\n</body>\n</html>\n')
