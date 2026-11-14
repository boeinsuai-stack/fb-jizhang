#!/usr/bin/env python3
"""从 App 的真代码生成「镜像」页（发布成 Claude artifact，给 Bowen 在 Claude 里看、给 Claude 读数据、预览新功能）。

镜像 = public/index.html 的业务代码原样 + 页头里 App 自己的脚本（v2.js 等）+ 一小段镜像外壳：
  - 外壳打开就从 Google Drive「FB 记账中转站/最新数据.json」读 App 最新上传的数据，只把变了的记录写进镜像的数据库；
    开着时每 30 秒、切回来时再查一次
  - App 业务代码拿到的数据库是只读的：保存/删除会提示「镜像只读」，不会改到任何数据
  - 备份、数据结构升级这类只在手机上有意义的部分隐藏
业务代码一个字不改，只做机械替换：window.claude.use → 外壳的 __M.use；#settings → #shezhi（claude.ai 保留了 settings）。

用法：python3 tools/build_mirror.py <输出.html> [--preview "预览说明（还没同步到 App 的改动）"] [--hook]
  --hook：测试用，把计算函数借到 window.__GM（跟 tests/golden.py 一样）
"""
import re, sys, pathlib, json

ROOT = pathlib.Path(__file__).resolve().parent.parent
args = sys.argv[1:]
if not args or args[0].startswith("-"):
    sys.exit(__doc__)
out = pathlib.Path(args[0])
preview = args[args.index("--preview") + 1] if "--preview" in args else ""
hook = "--hook" in args

html = (ROOT / "public/index.html").read_text(encoding="utf8")
shell = (ROOT / "tools/mirror_shell.js").read_text(encoding="utf8")

head_end = html.index("</head><body>")
head, body = html[:head_end], html[head_end + len("</head><body>"):]
# 页头只留 App 自己的样式（重置样式由外壳给），去掉 Firebase / 登录 / PWA 那些
styles = "".join(re.findall(r"<style>.*?</style>", head, flags=re.S)[1:])  # 第一个是重置样式，外壳自己带
assert "<script" not in styles
# 页头的脚本：App 自己的（v2.js、orderparse.js…）原样内嵌；Firebase、Google 登录、firebase-config、shim 不要
SKIP = ("vendor/firebasejs/", "accounts.google.com", "firebase-config.js", "shim.js")
srcs = re.findall(r'<script src="([^"]+)"', head)
own = [x for x in srcs if not any(k in x for k in SKIP)]
assert "v2.js" in own and not any(x.startswith("http") for x in own), srcs
own_js = "".join("<script>\n" + (ROOT / "public" / x).read_text(encoding="utf8") + "\n</script>" for x in own)

def sub1(s, a, b, count=None):
    n = s.count(a)
    assert n and (count is None or n == count), f"找不到或次数不对：{a!r}（{n} 次）"
    return s.replace(a, b)

body, n = re.subn(r'window\.claude && window\.claude\.use \? await window\.claude\.use\(("[a-z]+")\) : null', r'await __M.use(\1)', body)
assert n == 2, n
body = sub1(body, "window.claude.use(", "__M.use(")
assert "window.claude" not in body, "业务代码里还有别的 window.claude 用法，外壳没接住"
assert "window.firebase" in body  # 只在隐藏掉的「数据结构升级」里用到
body = sub1(body, 'href="#settings"', 'href="#shezhi"', 1)
body = sub1(body, 'settings: ["set-view"', 'shezhi: ["set-view"', 1)
if hook:
    gm = re.search(r'window\.__GM = \{.*?\};', (ROOT / "tests/golden.py").read_text(encoding="utf8"), flags=re.S).group(0)
    i = body.rindex("  })();\n})();\n</script>")
    body = body[:i] + "  " + gm + "\n" + body[i:]

banner = """<div id="mirror-bar" data-s="busy" role="status" aria-live="polite">
  <span class="mb-dot" aria-hidden="true"></span>
  <span class="mb-main"><b>镜像 · 只读</b><span id="mb-text">正在连接…</span></span>
  <button id="mb-go" type="button" hidden>重新读取</button>
</div>"""
if preview:
    esc = preview.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    banner += f'<div id="mirror-preview"><b>预览</b><span>{esc}</span><small>这些改动还没同步到 App，只在这里能看到。</small></div>'

mirror_css = """<style>
#mirror-bar{position:sticky;top:env(safe-area-inset-top,0px);z-index:40;display:flex;align-items:center;gap:8px;padding:7px max(16px,env(safe-area-inset-right,0px)) 7px max(16px,env(safe-area-inset-left,0px));background:var(--surface);border-bottom:1px solid var(--line);font-size:.8rem;color:var(--muted);font-family:var(--font-body)}
#mirror-bar .mb-dot{flex:none;width:8px;height:8px;border-radius:50%;background:var(--muted)}
#mirror-bar[data-s="ok"] .mb-dot{background:var(--accent)}
#mirror-bar[data-s="warn"] .mb-dot{background:var(--warn)}
#mirror-bar[data-s="warn"]{color:var(--warn)}
#mirror-bar[data-s="busy"] .mb-dot{animation:mbPulse 1s ease-in-out infinite}
@keyframes mbPulse{50%{opacity:.25}}
@media (prefers-reduced-motion:reduce){#mirror-bar[data-s="busy"] .mb-dot{animation:none}}
#mirror-bar .mb-main{flex:1;min-width:0;display:flex;flex-wrap:wrap;gap:0 8px;overflow-wrap:anywhere}
#mirror-bar .mb-main b{color:var(--fg);font-weight:600}
#mirror-bar button{flex:none;font:inherit;font-size:.78rem;background:none;border:0;padding:2px 0;color:var(--accent);cursor:pointer;text-decoration:underline;text-underline-offset:2px}
#mirror-bar.flash{background:var(--warn-soft);color:var(--warn)}
#mirror-preview{display:flex;flex-wrap:wrap;gap:2px 8px;align-items:baseline;padding:8px max(16px,env(safe-area-inset-right,0px)) 8px max(16px,env(safe-area-inset-left,0px));background:var(--warn-soft);color:var(--warn);font-size:.84rem;font-family:var(--font-body)}
#mirror-preview b{font-size:.72rem;padding:1px 7px;border-radius:5px;background:var(--warn);color:var(--surface)}
#mirror-preview small{flex-basis:100%;font-size:.74rem;opacity:.85}
#mig-sec,#set-view section:has(.backup){display:none!important}
</style>"""

page = (
    "<!DOCTYPE html><html lang=\"zh\"><head><meta charset=\"utf-8\">"
    "<meta name=\"viewport\" content=\"width=device-width,initial-scale=1,viewport-fit=cover\">"
    "<title>FB 记账镜像</title>"
    "<style>:root{color-scheme:light;box-sizing:border-box;padding-top:env(safe-area-inset-top,0px);padding-bottom:env(safe-area-inset-bottom,0px)}"
    "body{margin:0;padding:0;font:14px -apple-system,BlinkMacSystemFont,sans-serif}img{max-width:100%}[hidden]:not([hidden=until-found i]){display:none!important}</style>"
    + styles + mirror_css
    + own_js
    + "<script>\n" + shell + "\n</script>"
    + "</head><body>" + banner + body
)
out.write_text(page, encoding="utf8")
print(f"镜像页：{out}（{len(page) // 1024} KB）" + ("，预览：" + preview if preview else ""))
