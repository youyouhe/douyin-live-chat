# -*- coding: utf-8 -*-
"""抖音直播间弹幕采集 — bsk 注入 cookie + Playwright 无头执行 + DOM 增量轮询

用法:
    python douyin_live_chat.py <直播间URL或webRid> [--duration 60] [--out chat.jsonl]
                               [--cookie-ttl-hours 6] [--no-bsk]

链路: 登录 cookie(含 httpOnly) → Playwright storageState → 有头真 Chrome
     → .webcast-chatroom___item + data-index 增量游标 → JSONL/控制台输出

依赖: pip install playwright && python -m playwright install chromium
      本机 Chrome; cookie 获取: bsk(推荐, 需含 cookies 命令) 或手动导出(见 README)
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

DEFAULT_STATE = Path.home() / ".douyin-live-state.json"


# ---------------- 1. cookie 获取(bsk 补认证) ----------------
def _bsk(*args: str, timeout: int = 60) -> str:
    r = subprocess.run(["bsk", *args], capture_output=True, text=True,
                       encoding="utf-8", errors="replace", timeout=timeout)
    if r.returncode != 0:
        raise RuntimeError(f"bsk {args[0]} 失败: {r.stderr.strip()[:200]}")
    return r.stdout


def refresh_cookies(url: str = "https://live.douyin.com/") -> Path:
    """开 bsk 会话导出该站全量 cookie(含 httpOnly), 转 Playwright storageState 落盘。"""
    sid = _bsk("session", "start", "--no-focus").strip().splitlines()[0]
    try:
        _bsk("navigate", "--session", sid, url)
        time.sleep(3)                                  # 等 cookie 稳定
        data = json.loads(_bsk("cookies", "--session", sid, "--json"))
    finally:
        subprocess.run(["bsk", "session", "stop", "--all"],
                       capture_output=True, timeout=30)
    cookies = []
    for c in data.get("cookies", []):
        ck = {"name": c["name"], "value": c["value"], "domain": c["domain"],
              "path": c["path"], "secure": c["secure"], "httpOnly": c["http_only"]}
        if c.get("expires") and c["expires"] > 0:
            ck["expires"] = c["expires"]
        cookies.append(ck)
    if not cookies:
        raise RuntimeError("bsk 未导出任何 cookie(未登录?)")
    DEFAULT_STATE.write_text(json.dumps({"cookies": cookies, "origins": []},
                                     ensure_ascii=False), encoding="utf-8")
    print(f"[cookie] 已刷新 {len(cookies)} 条 → {DEFAULT_STATE}")
    return DEFAULT_STATE


def ensure_state(url: str, ttl_hours: float) -> Path:
    if (STATE_FILE.exists()
            and time.time() - STATE_FILE.stat().st_mtime < ttl_hours * 3600):
        return DEFAULT_STATE
    return refresh_cookies(url)


# ---------------- 2. Playwright 执行面 ----------------
POLL_JS = """
() => {
  const out = [];
  let cursor = window.__chatCursor ?? -1;
  for (const it of document.querySelectorAll('.webcast-chatroom___item')) {
    const idxEl = it.closest('[data-index]');
    const idx = idxEl ? +idxEl.dataset.index : -1;
    if (idx <= cursor) continue;
    cursor = idx;
    out.push({idx, text: (it.innerText || '').replace(/\\s+/g, ' ').trim()});
  }
  window.__chatCursor = cursor;
  return out;
}
"""


def run_live(url: str, duration: int, out_file: Path, state_file: Path) -> None:
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False, channel="chrome")  # 抖音检测 headless, 必须有头+真Chrome
        ctx = browser.new_context(storage_state=str(state_file),
                                  viewport={"width": 1380, "height": 860})
        page = ctx.new_page()
        print(f"[open ] {url}")
        page.goto(url, timeout=45_000, wait_until='domcontentloaded')
        # 等弹幕区出现(未登录/风控时超时)
        try:
            page.wait_for_selector(".webcast-chatroom___item", timeout=60_000)
        except Exception as e:
            try:
                hint = page.title()
            except Exception:
                hint = f"页面异常({type(e).__name__})"
            print(f"[error] 未见弹幕区 (title={hint!r}) — 可能: 直播结束/cookie 过期/"
                  f"风控。重跑加 --cookie-ttl-hours 0 强制刷新 cookie")
            browser.close()
            return
        # 直播间元数据
        try:
            meta = page.evaluate("""() => { const s = window.__STORE__?.roomStore || {};
                const i = s.roomInfo || {}; return { roomId: String(i.roomId ?? ''),
                webRid: i.web_rid ?? s.webRid ?? '', live: s.liveStatus ?? '' }; }""")
            print(f"[meta ] {json.dumps(meta, ensure_ascii=False)}")
        except Exception:
            meta = {}
        print("[chat ] 开始采集 (Ctrl+C 停止)")
        fout = open(out_file, "a", encoding="utf-8")
        deadline = time.time() + duration if duration > 0 else float("inf")
        seen = 0
        try:
            while time.time() < deadline:
                for item in page.evaluate(POLL_JS) or []:
                    text = (item["text"] or "").strip()
                    if not text:
                        continue                              # 动画占位/空白节点
                    user, _, content = text.partition("：")
                    user, content = user.strip(), content.strip()
                    if not content:
                        content = text                       # 无"："的系统消息整条为正文
                        user = ""
                    if not user and len(content) > 80:
                        continue                              # 超长免责声明类系统条
                    rec = {"ts": time.strftime("%H:%M:%S"), "idx": item["idx"],
                           "user": user, "content": content}
                    print(f"[{rec['ts']}] {user or '·系统'}: {content}")
                    fout.write(json.dumps(rec, ensure_ascii=False) + "\n")
                    seen += 1
                fout.flush()
                time.sleep(0.5)
        except KeyboardInterrupt:
            print("\n[stop ] 用户中断")
        finally:
            fout.close()
            print(f"[done ] 共 {seen} 条 → {out_file}")
            browser.close()


def main() -> int:
    ap = argparse.ArgumentParser(description="抖音直播间弹幕采集(bsk cookie 注入)")
    ap.add_argument("target", help="直播间 URL 或 webRid(纯数字)")
    ap.add_argument("--duration", type=int, default=60, help="采集秒数, 0=直到 Ctrl+C")
    ap.add_argument("--out", default="chat.jsonl", help="输出 JSONL 文件")
    ap.add_argument("--cookie-ttl-hours", type=float, default=6, help="cookie 缓存时效")
    ap.add_argument("--no-bsk", action="store_true",
                    help="不刷新 cookie, 直接用现有缓存(测试用)")
    ap.add_argument("--state-file", type=Path, default=DEFAULT_STATE,
                    help="storageState 文件路径(可手动放置, 见 README)")
    a = ap.parse_args()
    url = a.target if a.target.startswith("http") else f"https://live.douyin.com/{a.target}"
    if not a.no_bsk:
        ensure_state(url, a.cookie_ttl_hours)
    elif not args.state_file.exists():
        sys.exit("无 cookie 缓存, 先不带 --no-bsk 跑一次")
    run_live(url, a.duration, Path(a.out), a.state_file)
    return 0


if __name__ == "__main__":
    sys.exit(main())
