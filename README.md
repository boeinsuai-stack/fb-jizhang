# FB 记账 · Facebook Market 库存

把 Claude 里的「Marketplace 库存与财务」搬成独立的手机 App（PWA）。iPhone 上用 Safari 打开网址，选「添加到主屏幕」即可。

## 结构

| 文件 | 作用 |
|---|---|
| `public/index.html` | 原 App，业务代码一行没改；只改了 5 句提示文字（原来写「请在 claude.ai 打开」），加了 PWA 标签 |
| `public/shim.js` | 转接层：用 Firebase 提供原来 Claude 的 `db / user / downloads` 接口，并负责登录界面、离线缓存 |
| `public/firebase-config.js` | ⚠️ 待填 Firebase 项目配置 |
| `public/import.html` | 一次性导入旧数据，并逐字段核对 |
| `public/sw.js`、`manifest.webmanifest`、`icons/` | 让它能装到主屏幕、离线打开 |
| `firestore.rules` | 只允许名单里的邮箱读写数据 |
| `data-backup/backup-2026-11-03.json` | 2026-11-03 从 Claude 导出的全部数据（含客户信息，**不要上传到 GitHub**，已在 .gitignore 里） |

## 已经做过的检查（用模拟数据库）

- 原 App 在转接层上正常打开，库存、财务、客户页都能显示，无脚本错误
- 记一笔卖出：订单 +1、库存流水 +1、操作记录 +1，记录人显示为「我」
- 旧记录仍显示「我记的」（旧 Claude 用户 ID 已映射到登录账号；配置里只存邮箱的 SHA-256 指纹）

## 上线步骤

1. 在 console.firebase.google.com 用 Google 账号新建项目
2. Firestore Database → 创建数据库，区域选 `australia-southeast1`（悉尼）
3. Authentication → 启用「电子邮件/密码」→ 用户 → 手动添加你的账号；设置里关闭「允许注册」
4. 项目设置 → 添加 Web 应用 → 把配置填进 `public/firebase-config.js`
5. 电脑上：`npm i -g firebase-tools` → `firebase login` → `firebase use --add` → `firebase deploy`
6. 打开 `https://<项目>.web.app/import.html` → 登录 → 选备份文件 → 导入并核对，必须显示「✓ 全部记录逐字段一致」
7. iPhone Safari 打开 `https://<项目>.web.app` → 分享 → 添加到主屏幕
8. 新旧版本并行一周，数字一致后停用旧版

## 和旧版的差别

- 照片功能暂时不可用（旧数据里没有照片，不受影响）
- Google Drive 备份改为：数据自动存在云端数据库；需要留底时点「导出 Excel」（iPhone 上会弹出分享面板，可以存到「文件」）
- 注意：迁移那天在旧版里新记的账，要在导入之后补记到新版，或者在当天重新导出一次
