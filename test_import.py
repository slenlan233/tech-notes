"""Run with: python test_import.py after `python build.py`."""
from pathlib import Path
from bs4 import BeautifulSoup
root=Path(__file__).resolve().parent
pages=list((root / "site" / "posts").rglob("index.html"))
match=[p for p in pages if "LeetCode" in p.as_posix()]
assert match, "No LeetCode article built"
p=match[0]
soup=BeautifulSoup(p.read_text(encoding="utf-8"), "html.parser")
codes=soup.select("code.inline-code")
assert len(codes)>=100, len(codes)
assert any(t.get_text()=="cur.next" for t in codes)
assert soup.select("ol ol")
for image in soup.select(".article-content img"):
    assert (p.parent / image["src"]).exists(), image["src"]
print(f"OK: {len(codes)} inline code elements, all images exist, nested lists retained")
