"""첫 화면 만들기: home/template.html → site/index.html

실행: python home/build_home.py [미리보기파일.html]
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from site_common import wrap_page  # noqa: E402

HERE = Path(__file__).parent
body = (HERE / "template.html").read_text(encoding="utf-8")
out = HERE.parent / "site"
out.mkdir(exist_ok=True)
(out / "index.html").write_text(wrap_page(body), encoding="utf-8")
if len(sys.argv) > 1:
    Path(sys.argv[1]).write_text(body, encoding="utf-8")
print("첫 화면 완성")
