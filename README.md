# douyin-live-chat

抖音直播间弹幕采集器 —— 注入登录 cookie，无头浏览器之外的真实 Chrome 执行，增量游标轮询，输出纯净 JSONL。

```bash
python douyin_live_chat.py https://live.douyin.com/42107960039 --duration 60
```

```
[17:14:50] 缘在何方: 送出了 小心心 × 1          ← 礼物
[17:14:50] 午夜: 还是有些重庆大哥！               ← 弹幕
[17:14:50] ·系统: 花蕊🎤 （首播筹备中）：         ← 进场欢迎
[17:14:57] @摆烂了@: 勾魂的眼神
[17:15:19] 谭小晞¹²¹²: 好听好听
```

## 工作原理

```
登录 cookie(含 httpOnly) ──→ Playwright storageState 注入
                                │
                     Chrome 有头模式(channel="chrome")
                                │
              .webcast-chatroom___item + data-index 增量游标
                                │
                    控制台实时输出 + JSONL 落盘
```

关键技术点（都是实测踩出来的）：

- **抖音检测 headless**——必须 `headless=False` 且用本机真 Chrome（`channel="chrome"`），无头模式弹幕区永远不渲染
- `goto` 必须 `wait_until="domcontentloaded"`——直播页的 load 事件被推流挂起
- 弹幕条目锚点是 `.webcast-chatroom___item`（BEM 命名不参与混淆），父节点 `data-index` 是天然增量游标（React 列表序号，连续、不重、不漏）
- 直播间元数据白送：`window.__STORE__.roomStore.roomInfo`（roomId / webRid / 直播状态）
- 三类消息混在同一条目流，按特征零成本分类：礼物（`送出了 X × N`）、弹幕（正文）、进场欢迎（昵称后跟空 content）

## 安装

```bash
pip install playwright
python -m playwright install chromium   # 或直接用本机 Chrome, 见下
```

需要本机安装 Chrome（脚本用 `channel="chrome"` 走真实 Chrome 而非 Chromium）。

## 获取登录 Cookie（推荐插件方式）

弹幕区需要登录态。脚本把 cookie 缓存为 Playwright storageState 格式（默认 `~/.douyin-live-state.json`）。

### 方式 A：浏览器插件导出（推荐，零手动编辑）

1. Chrome 应用商店安装 **[Get cookies.txt LOCALLY](https://chromewebstore.google.com/detail/get-cookiestxt-locally/cclelndahbckbenkjhflpdbgdldlbecc)**（或同类 cookies.txt 导出插件）
2. 打开 `https://live.douyin.com/` 并确认已登录
3. 点插件图标导出 `cookies.txt`
4. 一条命令直接用：

```bash
python douyin_live_chat.py <直播间URL> --cookies-txt ~/Downloads/cookies.txt
```

脚本自动解析 Netscape 格式、过滤 `douyin.com` 域、转换注入——无需任何手动编辑。

### 方式 B：bsk 自动导出（进阶，可选）

[BrowserSkill (bsk)](https://github.com/Tencent/BrowserSkill) 驱动你日常登录着的 Chrome 自动导出，可定时刷新、无需人工点击：

```bash
python douyin_live_chat.py <直播间URL>            # 首跑自动导出并缓存, 6h 过期自动刷新
```

> 注：依赖 bsk 的 `cookies` 子命令（功能已提交上游 [PR #393](https://github.com/Tencent/BrowserSkill/pull/393)，合并前需自行编译含补丁的版本）。日常使用方式 A 更简单。

## 用法

```bash
python douyin_live_chat.py <URL或webRid> [选项]

  target               直播间完整 URL 或纯数字 webRid
  --duration N         采集秒数, 默认 60; 0 = 持续采集直到 Ctrl+C
  --out FILE           JSONL 输出文件, 默认 chat.jsonl
  --cookie-ttl-hours H cookie 缓存时效, 默认 6; 0 = 强制重新导出
  --cookies-txt FILE   Netscape cookies.txt(插件导出), 自动转换注入 ← 推荐
  --no-bsk             不走 bsk, 直接用现有 cookie 文件
  --state-file FILE    指定 storageState 路径
```

## 输出格式

每行一条 JSON（`ts` 本地时间 / `idx` 弹幕序号游标 / `user` 用户名 / `content` 内容）：

```json
{"ts": "17:14:50", "idx": 0, "user": "午夜", "content": "还是有些重庆大哥！"}
{"ts": "17:15:10", "idx": 3, "user": "用户5280548612748", "content": "送出了 Thuglife × 1"}
```

说明：部分用户名显示为 `多*****` 形式的服务端打码（与该用户的隐私设置有关，非全站统一）；礼物与进场消息和普通弹幕混在同一条目流，按 `送出了` 前缀 / 空 content 即可分类。

## 已知限制

- 虚拟列表有渲染上限——超高频房间（弹幕刷屏级）DOM 只保留最近条目，极端场景可能漏弹；对全量有刚需需走 WebSocket 逆向（protobuf + signature 轮换，不在本工具范围）
- 直播结束/场次切换时页面状态异常，脚本会给出提示退出
- 频繁冷启动同一 cookie 可能触发风控，请控制采集频率并尊重平台

## 合规声明

本工具仅输出浏览器页面公开展示的弹幕内容，用于学习研究与数据分析。使用者应遵守抖音平台服务条款与相关法律法规，控制请求频率，不得用于商业滥用或侵犯他人权益的场景。使用本工具产生的一切后果由使用者自行承担。

## License

MIT
