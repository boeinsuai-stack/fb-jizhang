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
  - 登录：1.5 秒内 Firebase 还没确认登录，就用 localStorage `fb-last-user`（上次登录的人）先打开；确认后换人则刷新；确认是退出状态则取消
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
- `public/sw.js`：安装时预存 App + vendor；页面网络优先、3 秒超时用缓存；vendor 缓存优先；字体先用缓存
- 推送到 main 自动发布到 GitHub Pages；改动后把 `public/sw.js` 的 CACHE 版本号加一

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
- **读不到 ≠ 没有**（2026-11-10）：数据结构版本 `readSchema()` 先问云端（没网时 SDK 用缓存），读不到用 localStorage `fb-schema`（这台手机上次看到的），都没有才当旧结构；
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
- 预定的「编辑」= saleForm(null, true, null, null, 订单)：口味/数量/行都能改。已从合伙人拿到、但口味换掉或数量减少的流水：order_id 清空、备注「预定改了，拿到的货留作库存」，拿货支出不动
- 已卖出的单仍走 orderEditForm（数量锁住）

## 对账单改往来单价（feat13，2026-11-14）
- 对账单（ledgerSheet）有没结账的往来时多一个「改单价」→ `xferPriceForm(w)`：列出没结账的往来每一行（调出、调入分开），每个系列一个「整系列每根」框，边改边显示改完后的应付/应收
- 保存：`transfers/<id>.update({out, in})`；调入那几根同时改流水 `cost`（= 进价，库存成本/利润跟着变）。已结账的往来不出现。随客户订单拿的货不在这里改（库存页「系列价格」）
- 旧结构、新结构都走同样的写法（新结构由翻译层收进 v2_transfers，不存流水）。测试 `tests/test_xfer_price.py` 22/22（编的数据，GitHub 上也跑）

## 合伙人对账「互抵」（feat14，2026-11-14，Bowen 定的规则）
- 同一个合伙人、同一个系列：调入（随单拿的 + 往来他给我的）和调出（他拿走的）**一根抵一根，不管单价**。抵掉根数 = 两边小的那个；抵掉的钱按那一边的平均单价从两边各减掉，剩下的照原价。订货不参加
- 一个函数 `xOffset(gs, ts)`，所有算余额的地方都用它：`ledgerFrom`（对账单、财务页应付行 ledgerNet、复制给合伙人的文字）、合伙人页 `ptBal = -ledgerNet`、记往来的「之前/之后」、结账弹窗（只在勾选的里面抵）、改单价的预览
- 对账单多一栏「互抵」（列系列和根数，$0），调入/调出金额是扣掉互抵后的；结账记的 amount 也是互抵后的
- 当场换货：`xferEff(t)`（一笔往来自己算互抵）= 0 就自动关单（以前要两边钱一样）；往来列表/记录里一笔的金额也用 xferEff
- 纯计算，不改数据，新旧结构一样。测试 `tests/test_offset.py` 29/29（编的数据，GitHub 上也跑）

## 已知问题
- （已修，feat12）以前每个集合 `limit(1000)` 没有 orderBy，按文档 ID 取前 1000 条：超过后先丢 t- 开头的合伙人往来流水，再丢最新的。库存流水 2026-11 每天约 18 条，原本 12 月中旬就会超
- 一单的几条写入还不是一个 batch（中途关掉 App 理论上可能只存一半）—— v2 下一单只写一条源头，基本解决
- （已查，2026-11-10）约 60 处 catch：大部分是记住界面设置（localStorage）、删照片、复制文字的退路，吞掉没事；
  会让账出错的 5 处已改（数据结构版本 ×2、确认迁移、迁移后旧结构改动、中转站「写入过没有」）。写入失败本来就由 shim 的红字计数兜底
