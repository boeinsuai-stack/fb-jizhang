# CLAUDE.md — FB 记账

给以后在这个仓库里工作的 Claude 看。用户说中文，回复用中文。

## 结构
- `public/index.html`：业务代码（原 Claude artifact「Marketplace 库存与财务」），尽量不改
- `public/shim.js`：转接层，实现原 artifact 用到的 `window.claude.use("db"|"user"|"downloads"|"mcp")`
  - db → Firebase Firestore（compat SDK 10.12.2），开启离线缓存、ignoreUndefinedProperties
  - user → Firebase Auth（邮箱/密码）；用户按邮箱 SHA-256 指纹映射显示名和旧 ID
  - mcp → 只实现 `Google Drive / create_file`，用 Google Identity Services token（drive.file）
  - 同步状态小圆点：包住 DocumentReference.set/update/delete 和 WriteBatch.commit，用 waitForPendingWrites 判断已保存
  - **没网也能记账（2026-11-08）**：Firestore 写入的 promise 要等云端确认，没网时永远不完成 → 包装后改成「写进本地缓存就完成」
    （读一次 cache 排在写入后面当标记 + 等一拍让 onSnapshot 跑完）。云端拒收另外计数，右上角红字显示。不要去掉这层
  - 登录：0.3 秒内（2026-11-16 以前 1.5 秒）Firebase 还没确认登录，就用 localStorage `fb-last-user`（上次登录的人）先打开；确认后换人则刷新；确认是退出状态则取消
  - **增量同步（feat12，2026-11-09，替代 limit(1000)）**：业务代码拿到的 db 是 shim 的 `dbApi`，不是原始 Firestore
    - 账本集合 SYNCED（items movements orders expenses purchases settlements transfers customers followups log）：
      页面用 `onSnapshot({source:"cache"})` 读手机本地数据库的**全部**记录（不计费）；业务代码写的 `limit(1000)` 被忽略，`orderBy().limit(n)`（操作记录 200 条）照旧
    - 另开云端监听 `where("_u", ">", 上次看到的最大 _u − 10 分钟)` 把别的手机的改动拉进本地；进度存 localStorage `fb-sync:<uid>:<集合>`
    - 每台手机每 24 小时（或本地是空的时候）整份读一次云端 = 对账
    - 写入：DocumentReference / WriteBatch 的 set/update 自动加 `_u: serverTimestamp()`；**delete 改成写 `{_deleted:true,_u}` 标记**（软删除），页面过滤掉
    - 中转站上传、核对 Claude 版改动、撤销都用 `live()`：已删除 = 不存在，去掉 `_u`。Claude 版看到的数据格式不变
    - 本地数据库不可用（隐私模式）时退回直接订阅云端（不限条数）
    - settings 里 `cacheSizeBytes: CACHE_SIZE_UNLIMITED`，不让 SDK 清掉本地旧记录
- `public/firebase-config.js`：Firebase 配置 + APP_CONFIG（只放指纹，不放邮箱）
- `public/vendor/`：Firebase compat SDK 10.12.2（app/auth/firestore）和 xlsx 0.18.5，从 npm 包复制（去掉 sourceMappingURL）。
  **不要改回 CDN**：<script> 跨域加载是不透明响应，Service Worker 存不住，没网时 App 会空白
- `public/sw.js`：安装时预存 App + vendor；**SHELL 里的文件（App 本身）先用存的**（2026-11-16，以前网络优先 3 秒超时，信号差白屏 3 秒 × 2）；带 `cache:"reload"/"no-store"` 的照旧走网络；其他本站文件网络优先 3 秒；vendor 缓存优先；字体先用缓存。
  新版只靠 CACHE 版本号：不加一，手机就一直用存的旧版
- 推送到 main 自动发布到 GitHub Pages；改动后把 `public/sw.js` 的 CACHE 版本号加一，**`public/index.html` 开头的 `<meta name="app-version">` 改成一样的**（test_update 会查；2026-11-20 线上 fb-app-v30，分支 feat-place-fu 是 v31）

## v2 数据结构：每件事只记一次（分支 v2，2026-11-10；上线 = 店主在设置页迁移后 meta/schema.version = 2）
- `public/v2.js`：`migrate(旧各集合)` → v2；`project(v2)` → App 原来的样子（流水、支出、结账反向指针），**内存里现算，不存**；`createStore(db, getItems, onChange)` = 读写翻译层
- 源头：`v2_orders`（lines + picks[{sku,qty,cost,who?,key?,note?,date?,meta}]）、`v2_purchases`（lines + receipts[{id,date,lines{sku:qty},meta}]）、`v2_transfers`（in/out）、
  `v2_batches`（早期整批进货的支出）、`v2_settlements`（只存正向列表）、`v2_movements` / `v2_expenses`（只剩独立的事：盘点、早期整批进货流水、手动支出、从订单上拿下来的货……）。items/customers/followups/log/meta 不变
- 源头上的 `v2:{}` = 对齐老记录的补丁（备注原文、out/pick/pay 元数据、skip、no_out…），`"\u2205无"` 表示「旧记录没有这个字段」
- 翻译层写入：业务代码照旧写旧样子 → 找源头（`_v` 或编号/字段规则）→ 在源头那一组上应用 → `migrate()` 重新生成源头 → 只写源头。本机刚写的先挂着（pend），写完再收到一次通知才放下
- index.html：启动读 `meta/schema`，=2 才走 v2；版本变了自动刷新；`wrapDb` 把 orders/movements/expenses/purchases/transfers/settlements 交给 `v2ref`；`window.__fbV2store` 给 shim 中转站用
- 设置页「数据结构升级」（店主）：检查迁移 → 确认迁移（写 v2_* + meta/schema=2，旧集合不动）→ 迁移后旧结构又有改动会提示「补进新结构」→ 退回旧结构（现算的旧样子写回旧集合 + 版本改回 1）
- 测试（真实数据放仓库外，fixture 用 ArtifactData 或备份 json 生成）：`node tests/v2_roundtrip.js <fixture>`（往返逐字段）、`tests/golden.py` + `tests/golden_diff.py`（旧版计算结果当标准答案）、
  `tests/test_v2_diff.py <fixture> <v2种子>`（界面上旧版/新版各做一遍逐条比）、`node tests/v2_fuzz.js <fixture> 2000 <种子>`（随机写入压力测试）、`tests/test_v2_migrate.py <fixture>`（迁移/补进/退回端到端）。种子：`node tests/v2_seed.js`
- **读不到 ≠ 没有**（2026-11-10）：数据结构版本**启动时先用 localStorage `fb-schema`**（2026-11-16 起，见「打开要快」），这台手机没记过才 `readSchema()`：先问云端（没网时 SDK 用缓存），读不到用 localStorage `fb-schema`（这台手机上次看到的），都没有才当旧结构；
  meta/schema 的监听收到「本地没有」（`!exists && fromCache`）不当真（不然没网时一直刷新）。确认迁移、迁移后查旧结构改动都用 `get({source:"server"})`，读不到就停/写明「还没能检查」，联网后自动再查。
  测试 `tests/test_v2_failsafe.py`（编的小数据，GitHub 上也跑）；真 SDK 的对应行为在 test_realsdk.py 里实测过
- 中转站 v2：`tests/test_v2_relay.py <fixture> <v2种子>`（Drive 用 page.route 内存模拟；预放没过期的 token）旧版/新版各走一遍 上传 → 写入 Claude 改动 → 撤销，8/8。注意 page.route 后注册的先生效；种子要有 meta/backfill.done

## 中转站（App ↔ Claude 版 的同步，2026-11 起）
- Claude 版不能直连 Firebase（artifact 网络被拦，已实测），所以用 Google Drive 当中转站
- App → 中转站：只有 owner 的手机上传；每次云端确认保存后 4 秒，把所有集合（读手机缓存，不耗额度）打包成
  `FB 记账中转站/最新数据.json`（格式 fb-jizhang-relay/1，整份覆盖，不是增量）；授权过期则标记「中转站待更新 ↻」，点一下补传
- Google token 存在 localStorage 到过期为止（约 1 小时）
- 中转站 → Claude 版（已完成，代码在 Claude artifact 里，不在本仓库）：Claude 版每次打开用 Google Drive 连接器读 `最新数据.json`，
  三方对照合并（基准 = Claude 版数据库 `meta/relay_import.seen` 里的记录指纹）。所以**不要改中转站文件格式**（fb-jizhang-relay/1）而不同步改 Claude 版
- Claude 版 → 中转站（已完成）：Claude 版「同步到 App」在中转站文件夹新建 `Claude改动-YYYYMMDD-HHMM.json`，格式 fb-jizhang-changes/1：
  `{id, created_at, based_on, supersedes, count, summary[], changes[{col,id,op:"set"|"delete",data,base}], log[]}`；base = 当时 App 的版本（新增为 null）；只认最新一份
- 中转站 → App（已完成，shim.js「中转站 → App」一节）：Google 授权范围加了 drive.readonly（drive.file 看不到 Claude 建的文件）；
  打开 App 0.8 秒后 / 从后台切回时（10 秒节流）/ 开着时每 45 秒 / 每次拿到授权时，列出中转站里最新的 `Claude改动-*.json`；和 Firestore `meta/relay_applied.last_file_id` 不同就在标题下显示「Claude 版发来 N 条改动 · 查看并确认」
  - 核对：Firebase 现在的记录 == base → 可写；== 目标 → 跳过；都不是 → 冲突（默认保留 App 的，可勾选覆盖）
  - 写入：一个 batch 里先写 `relay_undo/<清单id>`（before/after），再写数据、log（`l-c-…`，「（Claude 版同步）」）、`meta/relay_applied`
  - 撤销：标题下「已写入 N 条 · 撤销」，24 小时内可点；把 before 写回
  - 授权过期或旧授权没有读取权限时，右上角显示「中转站待更新 ↻」，点一下 = 重新授权 + 上传 + 检查改动

## 一单分开找不同合伙人拿（2026-11-05）
- 拿货流水 movements 可带 `partner`；订单可带 `pick_split {sku:{人:根数}}`（还没拿的部分怎么分）
- 分开拿的单结账记在订单 `partner_settlements {人: 结账id}`；只找一个人的单照旧 `partner_settlement_id`
- 没有这些字段的旧数据按订单 `pick_from` 算。代码：gWho、oSidFor、oSids、splitPick、pickSplitter；pickups()/resvAlloc() 按「单+人」分组

## 规则
- 公开仓库：不要提交邮箱、人名、金额、客户数据、备份文件
- 记账流程要快：快速下单在最上面，记一笔不能强制填客户信息
- 定价策略不进 App
- 改完先跑测试再推送：`tests/run_all.sh [真实 fixture] [v2 种子]`（Playwright + /usr/bin/google-chrome，别的路径用环境变量 CHROME）；新功能把测试加进 tests/
  - GitHub Actions `.github/workflows/test.yml`：推送到任何分支自动跑不需要真实数据的几套；推到 main 时 pages.yml 先跑测试，**不过就不发布**
  - mockfb.js 没网时读本地没有的记录会报 unavailable、`source:"server"` 没网报错（照真 SDK，test_realsdk 实测）
  - tests/mockfb.js 分「云端 + 手机本地数据库」两层，按条计费（`__reads`），`__remoteWrite` 模拟另一台手机。照真 Firestore：本地马上更新，`__MOCK_OFFLINE` 时 set/update 的 promise 永远不完成。**不要改成立刻返回成功**，那样测不出离线问题
  - test_realsdk.py 用 public/vendor 里真的 Firestore SDK + Chrome 真 IndexedDB、断网跑（只把登录换成假的）
  - 测试数据里合伙人用「合伙人甲/乙」，不要用真名

## 编辑预定（feat11，2026-11-09）
- 预定的「编辑」= saleForm(null, true, null, null, 订单)：口味/数量/行都能改。已从合伙人拿到、但口味换掉或数量减少的货留作库存：都改记成往来调入（见下面「预定的货拿到以后再改 / 取消」）
- 已卖出的单仍走 orderEditForm（数量锁住）

## 备份和恢复（fix-backup-restore，2026-11-15）
- 设置页「备份到 Google Drive」现在存两份：Excel（给人看的报表，**导不回去**）+ `FB记账 整份数据 <时间>.json`（格式 fb-jizhang-backup/1，`{format, saved_at, counts, data}`，data = 旧样子的全部集合，跟中转站 `最新数据.json` 的 data 一样）
  - 数据来自 shim 的 `snapshotAll()`（中转站上传也用它），页面用 `window.__fbSnapshot()`；`mcp.callTool` 的 create_file 多了 `ext`（默认 .xlsx）
  - JSON 没存上不影响 Excel，设置页会写明；`meta/sync.files.data` 记最近一份
- `public/import.html` = 恢复页（以前自 feat12 起一按就报错：shim 给页面的 db 只能订阅、没有 get）：
  - 认上面那份 JSON 和中转站的 `最新数据.json`；直接用 `firebase.firestore()` 读写（批量写会自动带 `_u`、删除留标记，另一台手机能同步到）
  - 「只核对」：云端现在的账（新结构下用 `FBV2.project` 现算）跟备份逐字段比
  - 「恢复」：9 类账本记录整份换成备份的样子（备份里没有的删掉），`meta/schema.version` 改回 1 → App 回到旧结构 → 设置页「数据结构升级」再迁移一次（`migGo` 会把 v2_* 整份换掉）
  - 空的或不认识的文件不让恢复；写完要 `waitForPendingWrites()` 再核对（shim 的写入是「写进手机就算完成」）
- 测试 `tests/test_restore.py [真实 fixture]` 31/31：备份 → 把云端弄坏 → 恢复 → 数字一样 → 升级回新结构还一样（旧结构/新结构各开始一遍；GitHub 上跑编的数据）
## 预定的货拿到以后再改 / 取消（fix-resv-picks，2026-11-15）
- `releasePicks(o, ms, why)`：预定上已经从合伙人拿到的货不再属于这单时（编辑预定换口味/减数量、取消预定）：
  改记成一笔「他给我货」的往来（`transfers` + `t-…-in-SKU` 流水，删掉原来的拿货流水，拿货支出减掉这部分）；已经结过账的 → 这笔往来带 `partner_settlement_id`、加进那次结账的 `transfer_ids`（撤销那次结账时欠款会回来）；取消预定时把订单从结账的 `order_ids` 里拿掉
  - 以前只清 `order_id`（取消预定时直接删流水）→ `pickups()` 找不到 → 应付从对账单里消失。**不要再把拿货流水的 order_id 清空**
- `pickSplitLeft(o)`：分开拿的预定已经拿到一部分时，剩下的只按 `pick_split` 里还没拿够的人分（`resvAlloc`、`commitSale` 结算预定时都用它）
- 测试 `tests/test_resv_release.py` 53/53（编的数据，GitHub 上也跑）

## 体检第二批（fix-batch2-20261115）
- **弹出页聚焦**：记一笔 / 预定 / 编辑预定、跟合伙人结账 `openSheet(..., { focus: false })`；`openSheet` 自动聚焦跳过口味搜索框 `.pick-q`
  （feat15 跳过勾选框以后光标落到口味框 → 一打开就弹口味下拉）。test_sheet
- **下单表付款方式**：一排小标签（radio `name="f-payr"`，`curPay()` 本来就两种都认），再点一下已选的 = 取消；（2026-11-17 起别的弹窗也都是小标签，见「付款方式统一」）
- **结账少勾**：`#f-part` 写明「没勾的里有同系列的货……分开结合计会多付/少付 $X」（= 勾的 + 没勾的各自互抵 − 全部一起互抵）。test_offset
- **合伙人页**：余额 0 但 `pendingPicks(w)` 不空的人也列出来
- **有新版提示**（shim.js 最后）：打开 8 秒后 / 切回前台（5 分钟节流）/ 每半小时 fetch `sw.js`（no-store）取 CACHE，跟 `<meta name="app-version">` 不一样 → 标题下 `#update-bar`「有新版 · 点一下更新」→ 先 `cache:"reload"` 拿新文件再刷新。test_update
- **成本账不漂**：`fifoBook` 出库时账上不够的先欠着（DEF），下一批到货先补它、按那批的价；一直没补上的最后才按口味默认成本。真实数据 golden 不变（现在没有这种情况）。test_fifo_gap

## 复制口味带售价（fix-copy-price2，2026-11-15）
- 库存页「复制口味」= `plainFlavours()`：只列能卖的（库存减预定 > 0）；一个系列都是一个价 → 写在标题右边「【Ali】$60」，同系列有不同价 → 每行后面写价钱；
  系列按最低价从低到高（同价按 SERIES 顺序），系列里按价钱、再按名字；没填售价（price_aud 空或 0）的排最后、不写价。
  名字看不出是什么水果的：香型字段 `fruits`（编辑香型「里面是什么水果」）有值就写在名字后面括号里「FTP (Blackberry Dragon Fruit)」，不改英文名（订货识别、搜索照旧用英文名）。测试 `tests/test_copy_flavours.py`

## 对账单改往来单价（feat13，2026-11-14）
- 对账单（ledgerSheet）有没结账的往来时多一个「改单价」→ `xferPriceForm(w)`：列出没结账的往来每一行（调出、调入分开），每个系列一个「整系列每根」框，边改边显示改完后的应付/应收
- 保存：`transfers/<id>.update({out, in})`；调入那几根同时改流水 `cost`（= 进价，库存成本/利润跟着变）。已结账的往来不出现。随客户订单拿的货不在这里改（库存页「系列价格」）
- 旧结构、新结构都走同样的写法（新结构由翻译层收进 v2_transfers，不存流水）。测试 `tests/test_xfer_price.py` 22/22（编的数据，GitHub 上也跑）

## 合伙人对账「互抵」（feat14，2026-11-14，Bowen 定的规则）
- 同一个合伙人、同一个系列：调入（随单拿的 + 往来他给我的）和调出（他拿走的）**一根抵一根，不管单价**。抵掉根数 = 两边小的那个；抵掉的钱按那一边的平均单价从两边各减掉，剩下的照原价。订货不参加
- 一个函数 `xOffset(gs, ts)`，所有算余额的地方都用它：`ledgerFrom`（对账单、财务页应付行 ledgerNet、复制给合伙人的文字）、合伙人页 `ptBal = -ledgerNet`、记往来的「之前/之后」、结账弹窗（只在勾选的里面抵）、改单价的预览
- 对账单（Bowen 说「互抵」一栏看不清抵完还剩什么 → 改版）：钱都在「按系列算」：每个系列一行「调入 3 · 调出 2 · 抵 2」+「调入/调出 还要结 N 根 ±$」（xOffset 的 rows，serIO/serRest）→ 订货 → 合计 → 「明细 · 按日期（只记货）」不写钱 → 预定。复制给合伙人的文字同样结构；结账弹窗逐行写「抵完还要结」。结账记的 amount 是互抵后的
- 当场换货：`xferEff(t)`（一笔往来自己算互抵）= 0 就自动关单（以前要两边钱一样）；往来列表/记录里一笔的金额也用 xferEff
- 纯计算，不改数据，新旧结构一样。测试 `tests/test_offset.py` 33/33（编的数据，GitHub 上也跑）

## 对账单写「谁欠谁」+ 结账付款方式（fix-ledger-words，2026-11-16）
- Bowen：「还要结 N 根」「+/−」看不出是他欠我还是我欠他 → 钱一律写「你欠 X」「X 欠你」，不写正负号
  - `owedTxt` = 「你欠 X」/「X 欠你」/「跟 X 两清」（财务页、合伙人页、对账单、改单价都用它；以前是 应付/应收）
  - 对账单**排法不变**（Bowen 试过两组大色框，嫌杂，要回以前的小标签 + 带颜色的数字）：按系列算每行小字「你拿他 3 根 · 他拿你 2 根 · 抵掉 2 根」，
    下面［你欠他］橙 /［他欠你］绿 小标签 +「N 根」+ 带颜色的钱；合计框「你欠他 · 拿的货 / 你欠他 · 订货 / 他欠你 · 拿的货 → 你欠 X」。明细的「调入/调出」标签照旧（只记货）
  - `debtSplit(xOffset rows)`、`serIO(r, me)`、`serLeft(r)`；结账弹窗分「你欠 X」「X 欠你」两行 +「= 你给 X $」/「= X 给你 $」
  - 复制给合伙人的文字是 Bowen 的口吻：「我欠你 / 你欠我 / 两边一抵：你给我 $」；一次复制几个人时写名字
- 结账付款方式：以前是最下面的下拉框、不能分开付 → 一排小标签（跟下单一样，`name="f-payr"`，再点取消）+「现金+转账」（`mixRowHtml`/`readPay`，存 `payment/pay_cash/pay_other`，
  pay_cash 是实付里的现金）；记录上用 `settlePay(s)` 写「现金 $10 + PayID $20」（合伙人页、导出）。不强制选
- 钱怎么算没动。测试 test_offset（53）、test_xfer_price
## 订货单「点口味 + 粘贴清单」（feat15，2026-11-15）
- 新建/编辑订货（2026-11-15 去掉了「供货人 / 备注」框和底部长说明，以前的 note 保存时照旧保留）：先「指定口味」：按系列的口味格子（跟快速下单一样，点一下 +1、「−」减一、格子上显示已选根数和现在库存，可搜中英文）→ 下面每行「根数 / 单根成本 $」→「选中的每种都订 N 根」→「整系列每根」成本。「只知道系列，口味到货再分」收进折叠（有系列行时展开）
- 「粘贴清单」：`public/orderparse.js`（`FBParse.parseOrder(text, items, {series})`，浏览器 + node 都能用，sw.js SHELL 里有）。认出来的按清单根数加进来（已选的改成清单的数），系列是猜的、没写根数、没认出的分别列出来
  - 规则：一行只写系列 = 下面几行的系列，只在这个系列里找（对不上宁可认不出）；英文逐词比（拼错一处/两个字母打反算对）、中文名包含或差一个字；长名字优先；有词对不上又有更长的名字包含其余词 → 不猜；同名口味跨系列 → 上文系列 > 这段文字多数口味的系列 > 界面当前系列，标「猜的」
  - 测试 `node tests/orderparse_test.js [真实 fixture]`（写法逐条 + 300 份随机订单盲测，认错必须 0）；`tests/test_po_quick.py` 26/26（旧/新结构）。真实口味表盲测 5×500 份 100%；加重噪声（错两处、漏一个词、夹废话）认对 93%、认错 0.3–0.4%（都是漏词后正好变成另一个真口味）

## 弹出页（2026-11-15）
- `openSheet` 打开时 `lockPage()`（body position:fixed + top=-scrollY），`closeSheet` 时 `unlockPage()` 回到原位；`.sheet-card`/`.sheet` 加 `overscroll-behavior: contain`。以前弹出页滑到底会带着一级页面一起滑
- 自动聚焦跳过日期框/下拉框/勾选框（iPhone 上一聚焦就弹滚轮）；`openSheet(..., { focus: false })` 整页不聚焦（订货单用）
- 订货单日期默认今天，不显示框：底下「订货日期：今天 · 改」。测试 `tests/test_sheet.py` 10/10（旧代码 5 项不过：后面页面 600 → 3025）
- Bowen 说弹出页「质感」以后再优化，先落实功能

## 镜像（Claude 里看 App 界面，2026-11-15，替代 Claude 版）
- artifact「FB 记账镜像」https://claude.ai/artifact/5adhRecZNQHzxdv8zs8gP3（slug 2516b6e0-e04e-4ea9-afc7-e4415ffde092；能力 db + user + mcp Google Drive search_files/download_file_content）
- **自动生成，不是第二份代码**：`python3 tools/build_mirror.py <out.html> [--preview "说明"]` = public/index.html 原样 + v2.js + `tools/mirror_shell.js`；
  只做机械替换（window.claude.use → __M.use；#settings → #shezhi，claude.ai 保留了 settings）。用 claude-artifacts 的 publish_files 发布到上面的 slug
- 外壳：店主打开就从中转站 `最新数据.json` 同步（开着时每 30 秒、切回页面时再查，文件没变不下载），只写变了的记录（指纹 meta/fp_<集合>，含 log）；
  **不抄 meta**（文件里 meta/schema=2，抄了会去读 v2_*），镜像里 App 走旧样子；写 meta/backfill done 免得补操作记录
- 业务代码拿到的 db 只读：写入一律 reject（code read_only），顶上提示「镜像只读」；备份、数据结构升级隐藏
- **每次「同步到 App」后重新生成并发布镜像**（不带 --preview）。**预览新功能**：在功能分支上 `--preview "这次改了什么"` 生成、发布到镜像，
  顶上黄条写明「还没同步到 App」；Bowen 看完说「同步到 App」→ 上线 main → 再发布一次不带预览的
- 测试 `tests/test_mirror.py [fixture]`：同一份数据，镜像里 App 代码算出的所有数字 == 手机 App（golden.py）算的；只读；增量同步只写变了的；GitHub 上用编的数据跑

## 打开要快、读到一半不显示（fix-fast-start，2026-11-16）
- Bowen：打开先白屏、等很久（数据明明在手机里）；没读完就去库存「复制口味」，复制出来的数字不对；客户里找不到老客人 Valentine（数据里在：11-02 有他一单）
- 实测（真 SDK + 真本地数据库 + 真 Service Worker，信号很差）以前 5 秒以上才出数字：sw.js 页面网络优先 3 秒超时 + 登录等 1.5 秒 + 启动先问云端数据结构版本（Firebase 等云端最长 10 秒）。现在 0.5–0.8 秒
- 读到一半：以前口味一到 `S.loaded` 就是真，v2 的 onChange 没 ready 也把一半的结果交给页面 → 库存显示 0 / 少算、客户缺人、复制口味复制错。
  现在 `mark()` 记 9 类（口味、流水、订单、支出、订货、结账、往来、客户、跟进）都到了 `S.loaded` 才 = 15；v2 没 ready 不换 S；「复制口味」没读完就拦住
- shim `listen()`：本地应该有、却是空的（新手机 / iPhone 清过存储：本地 0 条但上次整份对账有 n>0 条，或从没对过账）→ 先不交「空」，等云端整份读完一起给（最多 20 秒，没网不等）
- **跟云端对上没有**：这次打开后每类记录都收到过云端回应 = 对上了，记 localStorage `fb-synced:<uid>`。还没对上且上次对上在 10 分钟前 → 标题下 `#stale-bar`「正在跟云端对 / 没网 · 现在显示的是这台手机 HH:MM 存的数据」；本地数据库用不了时写明「每次都要从云端整份下载（所以慢）」。`window.__fbSyncInfo()` 排查用
- 「有新版 · 点一下更新」：App 本身从存的打开，所以点了以后等新的 Service Worker 生效（最多 8 秒）再刷新
- 测试 `tests/test_fast_start.py` 12/12（编的数据，GitHub 上也跑；旧代码 5/12）：假 Firebase 让订单/流水晚 1.5 秒到；真 SDK 用 `--host-resolver-rules` 把 Google 指到「连得上不回应」的端口（**不要用 Playwright 拦请求**：一拦就带 cache:no-store，Service Worker 的「先用存的」测不出来）
  `tests/mockfb.js` 加了 `__MOCK_SLOW = {集合: 毫秒}`

## 口味排行 + 客户名字候选（feat-rank，2026-11-16）
- **口味排行**（库存页「补货建议」下面的折叠块 `#rk-sec`）：`flavourRank(days, ser, by)` 只看 `S.orders`：已卖出的单（预定不算）、日期在最近 N 天；每个口味「被几单买过」（一单里同口味只算一单）和「一共几根」。
  默认按单数排（Bowen：不能只看根数；真实数据里一个批发客人两单 110 根，按根数排前几名全是他），可改按根数；7/14/30 天、按系列；一单 ≥5 根且占这个口味一半以上 → 写「其中一单 N 根（客人）」；右边写现在能卖的根数 / 没货。
  选的天数、系列、排序记在 localStorage `mk-rank`。纯计算，不改数据
- **客户名字候选**：`wireCustSug`/`custSuggest`：下单表、记跟进的客户框打字时，输入框**上面**列出以前的客人（`customerBook()`，名字包含就算、不分大小写，最多 4 个，写买过几次），点一下填上并触发「回头客」。
  以前是 datalist：iPhone 上常常不显示（合伙人框早就因为这个改成按钮了）。放上面是因为 iPhone 键盘弹出时输入框贴着键盘，放下面会被挡；候选冒出来时用 visualViewport 把输入框留在键盘上面
- 顺手：预定后的提示、「只是预定」那行字缩短；shim 没有本地数据库又没网时 20 秒后把空结果交出去（以前会一直「正在读取」）
- 查过没问题、所以没动的：①「常用」格子按库存多少排：用 11-03 以来 150 次点选回放，改成按卖得多少排并不更好（平均第 9.7 格 vs 10.4 格）②点口味、切页面的反应时间（电脑慢 4 倍模拟：点口味 52 ms、切页 ~110 ms）③320/375/390 宽度没有横向溢出 ④真实数据独立重算 1720 项一致、守恒成立 ⑤两个人改同一条记录：266 条里只有 1 条
- 测试 `tests/test_rank.py` 38/38（编的数据，旧/新结构，GitHub 上也跑）

## 财务「每周」（feat-weeks，2026-11-17）
- Bowen：财务要能看每一周，不只是本周。period 多了 `"w:<周一日期>"`（以前的某一周），`"week"` 仍是本周；`inPeriod`、`plabel()`（标题文字，以前是 PERIOD_LABEL[period]）都认它
- 试过两版 Bowen 都不要：竖着的一周一行列表、左右滑的柱子条——都在净赚和「每天」之间多出一大块。他要的是：一点开就是本周总数，往下一划就是每天每一单
- 现在**不加新的一行**：选「本周」时，净赚那一块（`#f-hero`）右上角 ‹ ›（`#f-wkarr`，本周时 › 灰着）；在这一块上左右滑也能换（往左滑 = 下一周，跟翻页一样；横向 >50px 且比竖向大 1.5 倍才算）
  - `stepWeek(dir)`：换 period、重算、`haptic()`、这一块轻轻滑进来（prefers-reduced-motion 时不动）
  - `haptic()`：安卓 `navigator.vibrate(8)`；iPhone 没有 vibrate，点一个隐藏的 `<input type=checkbox switch>`（iOS 18 Safari 会轻震；没在真机上验过）
  - 欠合伙人的那一块（`#f-owe`）试过挤成一行，Bowen 说不好点 → 一个人一行（跟以前一样）
  - 数字就是 `finBook(inPeriod)`，跟别的时间范围一个算法
- localStorage `mk-period` 只记 week/month/…，选了以前某一周下次打开回到本周
- 测试 `tests/test_weeks.py` 26/26（编的数据，旧/新结构，GitHub 上也跑；has_touch + 合成 TouchEvent 模拟滑动，stub navigator.vibrate 数震了几下——stub 的 evaluate 字符串末尾要加 `; 0`，不然 Playwright 会把那个函数执行一次）
- 同时给 Bowen 看过三个苹果风格预览（iOS 原生 / 玻璃 / Bento），他说都不如现在清楚，不用。他要「清晰且好看」：在现在这版上改，保留框线、粗数字和对比度

## 客人少给 / 多给（feat-cust-bal，2026-11-17）
- Bowen：客人结账时少给了（比如忘了配送费）或多给了，要记下来；下次跟这个客人有单时提醒收回来 / 少收
- 订单字段 `bal = [{ amt, why, kind, date }]`：amt > 0 = 这单之后客人还欠你，< 0 = 你欠客人；kind：`diff` 这单少给/多给、`back` 这单收回/抵掉上次的、`waive` 不追了。
  一个客人欠多少 = `custBal(name)` = 他所有单（名字不分大小写）的 amt 加起来。**收入、净赚照订单合计算，不受影响**（应收/应付的思路：少给的那 $30 算在那单收入里，下次收回来不算新收入）
- 界面（`balHtml` + `wireBal(o, getName, canTake)`，放在客户名字下面）：
  - 「客人少给 / 多给了钱？」展开：少给/多给 + 差多少 + 为什么（配送费没给 / 没有零钱 / 抹零）；没写客户名字不让存
  - 这个客人有没两清的：提醒框「X 上次少给你 $30 / 上次多给了你 $20」+ 日期和原因 +「这单一起收回来 / 这单少收抵掉」，勾上后合计下面写「这次实际收 $90（合计 $60 + 上次少给的 $30）」
  - 记一笔卖出、编辑已卖出的单（事后补记）、结算预定（选付款那页 `payPickSettle` 和要填价的 `settleForm`）都有；预定还没付钱：上次的只提醒，不能当场抵
  - **预定上也能记**（feat-bal-resv，11-17 Bowen：「在预定那里点编辑看不到」）：编辑预定有「客人少给 / 多给了钱？」，存在预定的 bal 上；卡片标「这单少给 $10：…」；
    合计下面写「这次实际收 $50（合计 $60 − 这单少给的 $10）」（`wireBal` 的 tot 现在 = 合计 − 这单的 diff + 收回上次的）；`custBal` 不算预定上的（结算了才算这个客人欠的）；这单记了 diff 时点「结算」也先弹出选付款那页
  - 预定已经选好付款方式时点「结算」本来是直接结；这个客人有没两清的 → 改成先弹出选付款那页（不然提醒看不到）
  - 客户页：那一行标「少给你 $X / 多给了 $X」；点开有原因 +「不追了」（点两下，不用浏览器确认框）= 在他最后一单上记 waive；历史里每单写「少给 $30：配送费没给 / 收回 $30」；预定卡片标「上次少给 $30」
- 新结构：订单上的额外字段原样存进 v2_orders，测试里迁移再算回来一字不差
- **多给的原因 + 送我的**（feat-gift，11-18 Bowen：选了多给，下面那些还是少给的；有的客人多给就是送我的）：原因小标签分两组 `data-for="1"`（配送费没给 / 没有零钱 / 抹零）和 `data-for="-1"`（转多了 / 没零钱找，`BAL_WHY_OVER`），跟着少给/多给换，提示、占位字也换（`syncK`）。
  选多给多一行「这钱要还他吗：下次还他（默认）/ 送我的，不用还」→ diff 条目加 `gift: true`：`custBal` 跳过（不算你欠他、不提醒、客户页不标），卡片写「这单多给 $10 · 送你的」，买过什么写「多给 $10（送你的）」。收入、净赚照旧不受影响。测试 `tests/test_gift.py` 30/30
- 测试 `tests/test_cust_bal.py` 65/65（编的数据，旧/新结构，GitHub 上也跑）

## 付款方式统一 + 订货单「一起改」放下面（feat-pay-po，2026-11-17）
- Bowen：「结款的时候为什么没有一部分现金、一部分转账」——订货结款还是下拉框、只有 4 种。查下来还有 6 处同样（代送费、改已卖出的单、结算要填价的预定、合伙人拿货·卖出、记往来当场付、合伙人拿货/我拿货当场付）
- 现在**所有**收钱/付钱的弹窗用同一个：`payPick(o)`（一排小标签 + 现金+转账 + `mixRowHtml`，`id="f-paychips"`）+ `wirePay(getTotal)`（再点取消、现金框跟着显示「现金 $X + PayID $Y」）；存的时候一律 `readPay(required, total)` → `payment / pay_cash / pay_other`。
  不再有 `<select id="f-pay">`、`needPay`、`payOptions`（test_pay_mix 会查）。下单、选付款结算预定、跟合伙人结账那三处是早先自己写的小标签，行为一样，没动
- 订货单存 `payment/pay_cash/pay_other`，列表写「已付 11月17日 · 现金 $100 + PayID $200」（`payWords(x, total)`）；新结构订货单的额外字段原样存得住（测试迁移再算回来一样）
- 订货单：以前「整系列每根 $」在每个系列框头上、「选中的每种都订 N 根」在最下面，Bowen 说应该放一起 → 系列框头只剩系列名 + 根数；所有口味下面一块「选中的一起改」（`#f-bulk`）：
  每种都订 N 根（选了 2 种以上）+ 每个有 2 种以上口味的系列一个「Bar Pro 每根 $」（`#f-serp`，系列没变不重画，免得打字时丢焦点）
- 测试 `tests/test_pay_mix.py` 49/49（编的数据，旧/新结构，GitHub 上也跑）；test_po_quick 改用 `#f-bulk input[data-sr]`

## 预定备注写在概览上、客户资料不填区（feat-resv-note，2026-11-17）
- Bowen：预定里写了备注（什么时间、什么地方见面），回到预定概览看不到 → 以前备注只在点开卡片后才显示。现在没点开的卡片上就有一行 `.rv-note`（整段、能换行）；点开后不再重复。
  没写客人名字、备注被拿来当名字的，不再多写一行。编辑有备注 / 跟进的预定时「更多」直接展开
- 「客人信息里各种区、各种地方没必要」：记单 / 编辑 / 结算的折叠只剩「下次跟进」（以前「客户资料：区、来源、跟进」），记跟进、客户资料也拿掉「区」。
  查真实数据：154 单里只有 2 单填过区；「从哪来的」33 单全是自动填的「回头客」。以前填过的区 / 来源**照旧留在记录上**（`readCust(o)` 从原记录带过去，客户资料、跟进同样），只是不再显示；来源照旧自动：这个名字以前有单 → 「回头客」
- 测试 `tests/test_resv_note.py` 40/40（编的数据，旧/新结构，GitHub 上也跑）

## 打开先用上次存的、复制口味放标题右边（feat-fast-open，2026-11-18）
- Bowen：打开最常做的就是复制口味，可每次白屏 3–4 秒，按钮还要往下找。
- 实测（`/home/claude/audit/bench/startup.py`：真 SDK + 真本地数据库 + 真 Service Worker + 真实数据量 900 多条，CPU 降速）：以前降速 4 倍出数字 2.0–2.2 秒、8 倍 4.2 秒（信号差时偶尔 9 秒）——
  时间主要花在 Firebase 启动本地数据库、读出全部记录；页面本身算一遍只要 0.3 秒（8 倍降速）
- **快照**：数据读完、之后每次变了（2 秒防抖，切到后台时马上）把页面用的 9 类（S.items/orders/moves/expenses/purchases/settles/transfers/customers/followups，旧样子，新结构下是现算好的）存进 localStorage `fb-snap:<uid>`（uid 取 `fb-last-user`；真实数据约 330 KB）。
  下次打开在 data 那段之前同步读出来，`S.loaded = 15`、`snapOn = true`，马上 render → 能看、能复制口味。Firebase 读到的先放 `R`，9 类都到了 `Object.assign(S, R)` 一次换掉（`mark()`），不会一半新一半旧。
  `snapOn` 时 `needDb()` 拦住保存（「正在读手机里的数据，一两秒后再点保存」）、`migCheck`、补操作记录也等。快照的数据结构版本跟 `fb-schema` 对不上就不用。存不下就删掉，照旧等 Firebase
  - 结果（同一台电脑）：降速 4 倍 1.0–1.1 秒、8 倍 1.7–2.0 秒出数字；不降速 0.3 秒。新手机 / 清过数据第一次打开照旧
- xlsx（近 1 MB）不再每次打开都加载：`needXLSX()` 点备份 / 导出时才加；sw.js 照旧预存。Firebase、shim 等脚本从 `<head>` 挪到 `<body>` 最后（build_mirror.py 跟着改成页头页尾都找）
- 「复制口味」：从库存一览那一栏（快速下单格子下面）挪到标题右边 `header.top #inv-copy`，只在库存页显示
- 测试 `tests/test_snapshot.py` 22/22（编的数据，旧/新结构，GitHub 上也跑：第二次打开时假 Firebase 每类慢 2.5 秒，先显示上次的 7，读完一次换成 10）

## 跟进重做、按节奏自动提醒、客户买过什么竖着排（feat-followup，2026-11-18）
- Bowen：①跟进只能「已发信息 / 不用跟了」一次，客人说下次再说就没法往后排 ②有的客人不知道几号跟进 ③「这个客人很热情、每几天来一次」——时间到了 App 要自己提醒 ④客户点开买过什么格式很乱，要跟合伙人对账单一样按系列竖着排 ⑤客户页除了预定，别的都没用
- **往后排** `laterForm(kind, id)`（kind：o 订单上的跟进 / f 单独的跟进 / a 自动提醒）：「这次怎么说的」+ 下次哪天（`whenHtml/readWhen`：不定 / 明天 / 3 天后 / 一周后 / 两周后 / 选日期；自动提醒的多一个「按他的节奏」、没有「不定」）。
  联系记录 `touches: [{date, what}]`（最多 20 笔，在跟进 / follow_up / 客户资料上），列表写「上次联系 11月16日：他说下周」；往后排会清掉 contacted_at（「已发信息」也记一笔）。记跟进的日期默认「不定」，记了 7 天还没定会写出来
- **按节奏自动提醒**（`rhythmOf / autoFUs / autoRow`，跟进列表 `#fu-list` 下面，标题改「要联系的客户」）：节奏 = 客户资料 `every`（天；0 = 不用提醒）；没设就按他的记录：买过 3 天以上，相邻间隔中位数（最少 3 天）。
  只买过 2 次不算（真实数据里两天连着买的人会被算成「3 天一次」）。上次 + 节奏 − 1 天起出现；有预定 / 有跟进的不出现；按记录算的、超过 30 天也超过 3 个周期没来的不出现（你设的照样提醒）。
  往后排存在客户资料 `next`；他之后又买了（上次买 ≥ 最后一次联系）就不管 next。行上写：该来了 · 比平时晚了 N 天 / 节奏和上次哪天 / 常买前 3 种 + 现在有几根 / 你在资料里写的「关于这个人」。按钮：他要了·记预定 / 联系过了·往后排 / 不用提醒他 / 改节奏
  - 拿真实记录回测（11-18）：照每个人自己的中位数猜下一次，10 次里 6 次差 2 天以内，照所有人的平均（8 天）4 次
- 客户资料加「大概多久买一次」：按他的记录（大概 N 天）/ 每 3 天 / 每周 / 每两周 / 每月 / 不用提醒 / 自己填；保存时带上 next、touches（节奏改了清掉 next）
- **custPatch(c, patch)**：改客户资料几个字段要整份写回——`wrapRef` 的 set 不认 `{merge:true}`（只给几个字段会把备注、类型冲掉，测试抓到的）
- 客户点开：买过什么 = `.cu-hist2`：日期 + 金额一行，下面每个系列「Bar Pro 3 根」，再下面每个口味「Grape Ice ×2」（缩进）；顶上「一共 Bar Pro 6 根 · Ali 3 根」+ 节奏、下次大概哪天。不再显示来源
- 客户页：4 个统计框缩成一行「N 个客户 · 回头客 N（%）· 平均每人 $」，放在「全部客户」标题下
- 测试 `tests/test_followup.py` 44/44（编的数据，旧/新结构，GitHub 上也跑）

## 预定卡片上「配送 / 自取」（feat-handoff，2026-11-18）
- Bowen：预定板块每个客人边上要有配送或自取的小标签。订单字段 `handoff`（"配送" / "自取"）；`handoffOf(o)`：有记就用；没记的有配送费 = 配送、备注里「自取 / 自提 / 来拿 / 来取 / pick up」= 自取、「送到 / 送货 / 配送 / deliver」= 配送；都没有 = 不知道
- 卡片：客人名字右边一个小按钮（配送 = 绿底白字，自取 = 白底黑框，不知道 = 虚线「配送/自取？」），点一下就换（没写 → 配送 → 自取 → 配送），`preventDefault` 不展开卡片
- 记单 / 编辑预定：配送费上面「配送还是自取」两个小标签（`hoChips/readHo/wireHo`，再点取消）；填了配送费、还没选的自动选「配送」。不强制选
- 测试 `tests/test_handoff.py` 24/24（编的数据，旧/新结构，GitHub 上也跑）

## 预定交货时间 + 按时间排（feat-meet，2026-11-18）
- Bowen：时间别写在备注里，单独一栏放在客户下面；预定页按时间排好
- 记预定 / 编辑预定：客户那一栏下面「什么时候交货（见面）」（`meetHtml/readMeet/wireMeet`）：今天 / 明天 / 后天 / 选日期（再点取消）+ `<input type=time>` 几点；都可以不填，只填几点 = 今天。没勾「只是预定」时藏起来、不存
- 订单字段 `meet_date`（YYYY-MM-DD）/ `meet_time`（HH:MM）；卡片 `.l-date` 写 `meetTxt(o)`：「今天 18:00」「明天 15:00」「11月20日 周四」「已过 · 11月17日 10:00」（今天绿、过了橙），没定的写「11月17日 记 · 没定时间」
- 预定列表排序：定了时间的按 `meetKey`（日期 + 时间，没写几点排当天最后）从早到晚，没定的在后（新记的在前）。`resvAlloc`（库存先给哪单）没改，还是按记单日期
- 以前写在备注里的时间没自动搬过来（备注里只写了「下午四点」没写哪天），要 Bowen 点编辑选一下
- 测试 `tests/test_meet.py` 22/22（编的数据，旧/新结构，GitHub 上也跑）

## 记单表单精简（feat-simple-form，2026-11-18）
- Bowen：少给 / 多给是交货时临时发生的，记单时不可能知道 → 新记的单（记一笔 / 记预定）不放「客人少给 / 多给了钱？」（`balHtml(o, noDiff)`），只在编辑预定、结算、改已卖出的单里有；「上次少给 / 多给」的提醒照旧
- 「更多」里东西太多：备注直接放在合计下面（两行框，占位「在哪见面、其他说明」）；「更多：日期、下次跟进」只在记卖出时有，记预定 / 编辑预定藏起来（日期照旧存，编辑时原来的下次跟进照旧保留）
- 测试：test_cust_bal 67、test_resv_note 42、test_meet 24

## 少给的「不用收了」+ 收款按实际收到的（feat-bal-cash，2026-11-19）
- Bowen：①预定里只看到少给，看不到「送我的」（之前只有选了多给才出现）②有时客人少给 $20 是因为上次我多收了他 $20，下次不用再收 ③少给 $20，财务「收款」里现金还写 $60，应该写 $40；利润不用砍（下次会还）
- 少给 / 多给选了任一边就出现一行（`#f-giftrow`，问题 `#f-giftq`、两个选项文字跟着换）：少给「下次要收回来吗：下次收回来 / 不用收了（比如抵上次多收的）」，多给「这钱要还他吗：下次还他 / 送我的，不用还」。选第二个都存 `gift: true`（不算谁欠谁、不提醒），卡片写「· 不用收了 / · 送你的」
- `balCash(o)` = 这单实际收到的钱跟合计差多少 = −Σ(diff + back 的 amt)（waive 不动钱）。`payParts(o, amt)` 用它：财务「收款」、每天的收款、单子上的付款标签（`payBadgeO` 有差额时写「现金 $40」）都按实际收到的；现金+转账的差额先从转账那部分扣。**收入、净赚照旧按合计**
- 测试 test_gift 48/48

## 预定表单再整理（feat-form-tidy，2026-11-20）
- Bowen：按钮重复、太土；页面要整洁。改成：
  - **配送 / 自取不用选**：`handoffOf(o)` = 有配送费 → 配送，没有 → 自取（以前的 handoff 字段、按备注猜都不要了）；卡片上的标签只显示、不能点；表单里没有这两个按钮
  - **交货**：去掉今天 / 明天 / 后天那一排，日期框默认今天 + 几点（并排）；下面**见面地点**小标签（`placeList()` = 以前订单上用过的 `place`，用得多的在前，最多 10 个；再点取消；「＋ 地点」打新的，存在这单上以后就有了，两台手机都看得到，不用另外设置）。卡片名字旁边写地点（`.rv-place`）
  - **少给 / 多给**：去掉「下次要收回来吗 / 这钱要还他吗」两选一，只剩一个「下次核对」小按钮（`#f-track` 勾选框，点亮变绿），**默认不亮** = `gift: true`（只记在这一单上，不算谁欠谁、不提醒）；点亮才找回。卡片：点亮的写「· 下次核对」。以前存的没有 gift 的照旧算要找回
  - 新记单（记一笔 / 记预定 / 库存页购物车预定）都不放少给多给，只在编辑预定、结算、改已卖出的单里有（v29 就是这样，Bowen 11-20 又强调了一遍）
- 测试：test_handoff 10、test_meet 32、test_gift 46、test_cust_bal 67（diff 助手点亮下次核对）

## 合伙人名字按钮重复（fix-pname-dup，2026-11-20）
- Bowen：合伙人拿货那边选名字的按钮出现两次。原因：`enhancePartnerInputs()` 已经给每个 `input[list="f-pnames"]` 下面加一排名字按钮（`data-pname`），我拿货 / 他拿货（`partnerTakeForm/partnerGiveForm`）又自己加了一排 `#f-pchips` → 拿掉自己那排，高亮改用 `inp.__syncChips()`。**以后新弹窗的合伙人框只要 `list="f-pnames"`，别再自己加按钮**
- 测试 `tests/test_pnames.py` 16/16（订货、记往来、合伙人拿货·卖出、我拿货、他拿货每个名字只出现一次；旧代码 12/16）

## 订货换货（feat-po-swap，2026-11-20）
- Bowen：订的货有些没到，供货人会换成别的口味或别的系列。还没到齐的订货单上多一个「换货」→ `swapForm(pid)`：
  上面列还没到的每一行（只能换没到的部分，「没到的全换掉」一键填满）；下面搜口味 / 选系列（「只知道系列，口味到货再分」）填换成几根；每根成本默认 = 换掉那几根的平均，可改；底下写「换掉 N 根 → 换成 M 根」和订货单金额多/少多少
- 保存：lines 换掉的减掉（没到过的减到 0 就拿掉，到过的留着）；换成的已有同一口味/系列就合并（单价按根数加权）；total 重算；`swaps:[{date,at,out:[{k,t,qty}],in:[{k,t,qty}],unit_cost}]`；旧结构 po_id 那笔支出跟着改；已到货的成本不动
- 订货单上一行「11月20日 换货：A ×10 → B ×4、C ×6」；在途、登记到货跟着变。新结构 swaps 跟着订货单源头存
- 测试 `tests/test_po_swap.py` 24/24（编的数据，旧/新结构，GitHub 上也跑）

## 要联系的客户重排、重点客户、见面地点（feat-place-fu，2026-11-21）
- Bowen：跟进的顺序要按日期从近到远；跟进板块很难用；要见面地点（标签打在客人身上、写好地址和停哪一点就复制）；客人说「下午几点到几点联系」也要体现在预定上；一次买过一盒（8 根以上）的零售客要重点跟
- **要联系的客户**（renderFuResv / fuRow）：手动跟进（openFUs）+ 自动提醒（autoFUs）合成一个列表，**离今天近的在上面**：今天 → 明天 → 后天 → 过了的（刚过的在前，「已过 N 天」橙）→ 没定日子的；三天以后的收进「以后要找的 · N 个」，到了前两天自己出来。
  （第一版按日子从早到晚，过期几周的重点客户把上面占满了，Bowen 看不到今天明天要找的 → 改成 near()）
  每条是收起来的 details：哪天 · 名字 · 重点 · 地点 + 一行为什么找他（+ 几点方便联系）；点开才有四个按钮：记预定 / 联系过了 / 不用跟了 / 改（data-fu-* / data-au-* 跟以前一样）。「已发信息」并进「联系过了」（laterForm：常用说法 发了信息没回 / 他说过几天 / 他说下周 / 现在不要）
  - 不列：这个客人现在有预定，或记跟进以后他又买过（按订单 at 比 created_at / 订单上的跟进比那一单的 at）。只是不显示，数据不改
  - 自动提醒约好了哪天再问（customers.next）还没到的也列（在「以后」里），以前是不显示
- **重点客户**：customerBook 的 box = 一单最多几根（已付款），vip = 资料 vip true，或（vip 不是 false 且不是批发且 box ≥ 8）。客户资料「重点客户」勾选跟自动算的一样就不存（vip 只存跟自动不一样的）。
  没有自己的节奏（没设、买过不到 3 天）的重点客户按 14 天提醒（rhythmOf.boxDef，BOX_EVERY；真实记录：用得最快一天 0.5–0.67 根，一盒约 3 周）。客户页「重点客户」最久没买的在上面
- **见面地点**：`meta/places = {list:[{name,text}]}`（中转站、备份都带着；镜像 mirror_shell 单独抄 meta/places；import.html 恢复时一起恢复；快照 SNAPF 有 places）。
  标题右边「地点」（库存、客户页）→ 每个地点「复制」= 复制 text（发给客人的地址、停哪），点名字改 / 删；改名字时客户资料 place、还没结算的预定 place 跟着改
  - 客户资料：place（一般在哪见面）、call = "16:00-18:00"（一般几点方便联系，哪头都可以空，callTxt →「下午 4–6 点」，18 点还叫下午）
  - 记预定 / 编辑预定：写了客人名字自动带上他的地点、联系时间（自己点过地点就不动）；存预定后新地点进地点库、客人没有地点标签就打上、联系时间记到客户资料（afterMeet）。预定字段 call_win
  - 预定卡片：没写几点 =「今天 · 暂未确定时间」，下面一行绿字「下午 4–6 点联系」；地点 = 预定的，没有就用客人的；点开有「复制地点」
- 测试 `tests/test_place_fu.py` 72/72（编的数据，旧/新结构）；test_followup / test_meet / test_mirror 跟着改

## 已知问题
- （已修，feat12）以前每个集合 `limit(1000)` 没有 orderBy，按文档 ID 取前 1000 条：超过后先丢 t- 开头的合伙人往来流水，再丢最新的。库存流水 2026-11 每天约 18 条，原本 12 月中旬就会超
- 一单的几条写入还不是一个 batch（中途关掉 App 理论上可能只存一半）—— v2 下一单只写一条源头，基本解决
- （已查，2026-11-10）约 60 处 catch：大部分是记住界面设置（localStorage）、删照片、复制文字的退路，吞掉没事；
  会让账出错的 5 处已改（数据结构版本 ×2、确认迁移、迁移后旧结构改动、中转站「写入过没有」）。写入失败本来就由 shim 的红字计数兜底
