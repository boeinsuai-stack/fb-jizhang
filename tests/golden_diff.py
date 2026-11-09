"""比较两份标准答案（golden.py 的输出）：逐项列出不一样的地方。用法：python3 tests/golden_diff.py 旧.json 新.json"""
import json, sys
A, B = (json.load(open(f, encoding="utf8")) for f in sys.argv[1:3])
diffs = []
def walk(a, b, p):
    if isinstance(a, dict) and isinstance(b, dict):
        for k in sorted(set(a) | set(b)): walk(a.get(k, "<没有>"), b.get(k, "<没有>"), p + "." + str(k))
    elif isinstance(a, list) and isinstance(b, list) and len(a) == len(b):
        for i, (x, y) in enumerate(zip(a, b)): walk(x, y, p + f"[{i}]")
    elif isinstance(a, (int, float)) and isinstance(b, (int, float)) and not isinstance(a, bool):
        if abs(a - b) > 1e-9: diffs.append((p, a, b))
    elif a != b: diffs.append((p, a, b))
walk(A, B, "")
for p, a, b in diffs[:30]: print("❌", p, ":", json.dumps(a, ensure_ascii=False)[:90], "→", json.dumps(b, ensure_ascii=False)[:90])
print(f"{'✅ 完全一致' if not diffs else '共 %d 处不一致' % len(diffs)}")
sys.exit(1 if diffs else 0)
