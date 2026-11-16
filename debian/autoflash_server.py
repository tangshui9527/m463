#!/usr/bin/env python3
"""
魅蓝 Note (M463) 自动化刷机与 Web 实时监控服务
支持 SSE (Server-Sent Events) 实时流式推送日志
支持多方案一键切换与自动重载监听
"""
import http.server
import json
import os
import pty
import select
import subprocess
import sys
import threading
import time
import urllib.parse

PORT = 8080
LOG_HISTORY = []
SUBSCRIBERS = set()
LOCK = threading.Lock()

TARGETS = {
    "linux_v2": {
        "name": "🚀 目标 1: 修复版 Linux (boot-linux-v2 + lk-patched-v2)",
        "cmd": 'cd ~/mtkclient && echo 1122 | sudo -S python3 -u mtk.py multi "w lk lk-patched-v2.img;w boot boot-linux-v2.img;reset"',
        "desc": "自编内核(fbcon+DEVTMPFS) + 修复版MTK头/SHA-1 + 三重Patch版LK"
    },
    "linux_stock_lk": {
        "name": "🐧 目标 2: 修复版 Linux (boot-linux-v2 + 原厂LK)",
        "cmd": 'cd ~/mtkclient && echo 1122 | sudo -S python3 -u mtk.py multi "w lk lk-stock.img;w boot boot-linux-v2.img;reset"',
        "desc": "自编内核 + 修复版MTK头/SHA-1 + 原厂未动LK"
    },
    "diag_mixA": {
        "name": "🔬 诊断 A: 原厂内核 + Linux Ramdisk",
        "cmd": 'cd ~/mtkclient && echo 1122 | sudo -S python3 -u mtk.py multi "w lk lk-stock.img;w boot boot-mixA-fixed.img;reset"',
        "desc": "隔离测试: 验证 Debian initramfs 是否能被原厂内核正常引导"
    },
    "dump_ram_console": {
        "name": "📋 读取内核崩溃日志: dump DRAM RAM Console (0x43F00000)",
        "cmd": 'cd ~/mtkclient && echo 1122 | sudo -S python3 -u mtk.py da peek 0x43F00000 0x10000 --filename /tmp/ram_console_dump.bin && cp /tmp/ram_console_dump.bin /tmp/ram_console_saved.bin',
        "desc": "从 DRAM 0x43F00000 抓取内核 printk/panic 日志并解析"
    },
    "diag_mixB": {
        "name": "🔬 诊断 B: Linux 内核 + 原厂 Flyme Ramdisk",
        "cmd": 'cd ~/mtkclient && echo 1122 | sudo -S python3 -u mtk.py multi "w lk lk-stock.img;w boot boot-mixB-fixed.img;reset"',
        "desc": "隔离测试: 验证自编译内核是否能正常引导原厂系统"
    },
    "flyme_root": {
        "name": "🔑 诊断 C: 原厂 Flyme 破权版 (带 ADB Root & TCP 5555)",
        "cmd": 'cd ~/mtkclient && echo 1122 | sudo -S python3 -u mtk.py multi "w lk lk-stock.img;w boot boot-root-fixed.img;reset"',
        "desc": "开启 ADB root/调试，进入 Flyme 获取内核 dmesg 与硬件信息"
    },
    "restore_stock": {
        "name": "🛡️ 救砖回滚: 彻底恢复原厂 Flyme 官方系统",
        "cmd": 'cd ~/mtkclient && echo 1122 | sudo -S python3 -u mtk.py multi "w lk lk-stock.img;w boot boot-stock.img;reset"',
        "desc": "恢复原厂 lk-stock.img + boot-stock.img，开机进官方 Flyme"
    }
}

CURRENT_TARGET = "linux_v2"
CURRENT_PROC = None
RELOAD_EVENT = threading.Event()

HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>魅蓝 Note (M463) 自动刷机实时监控</title>
    <style>
        * { box-sizing: border-box; margin: 0; padding: 0; }
        body {
            background-color: #0d1117;
            color: #c9d1d9;
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, monospace;
            padding: 20px;
            display: flex;
            flex-direction: column;
            height: 100vh;
        }
        header {
            margin-bottom: 12px;
            display: flex;
            justify-content: space-between;
            align-items: center;
            border-bottom: 1px solid #30363d;
            padding-bottom: 10px;
        }
        h1 { font-size: 20px; color: #58a6ff; }
        .badge {
            padding: 6px 14px;
            border-radius: 20px;
            font-weight: bold;
            font-size: 14px;
            letter-spacing: 0.5px;
        }
        .badge-waiting { background: #d29922; color: #000; animation: pulse 2s infinite; }
        .badge-running { background: #1f6feb; color: #fff; }
        .badge-success { background: #238636; color: #fff; }
        .badge-failed { background: #da3633; color: #fff; }
        
        @keyframes pulse {
            0% { opacity: 0.6; }
            50% { opacity: 1; }
            100% { opacity: 0.6; }
        }

        .target-bar {
            display: flex;
            gap: 8px;
            margin-bottom: 12px;
            flex-wrap: wrap;
        }
        .btn-target {
            background: #21262d;
            border: 1px solid #30363d;
            color: #c9d1d9;
            padding: 8px 12px;
            border-radius: 6px;
            cursor: pointer;
            font-size: 13px;
            transition: all 0.2s;
        }
        .btn-target:hover {
            background: #30363d;
            border-color: #8b949e;
        }
        .btn-target.active {
            background: #238636;
            border-color: #2ea043;
            color: #fff;
            font-weight: bold;
        }
        .btn-danger.active {
            background: #da3633;
            border-color: #f85149;
        }

        .guide-box {
            background: #161b22;
            border: 1px solid #30363d;
            border-left: 4px solid #58a6ff;
            padding: 10px 16px;
            border-radius: 6px;
            margin-bottom: 12px;
            font-size: 13px;
            line-height: 1.5;
        }
        .guide-box strong { color: #f0883e; }

        .terminal-container {
            flex: 1;
            background: #000;
            border: 1px solid #30363d;
            border-radius: 8px;
            display: flex;
            flex-direction: column;
            overflow: hidden;
            box-shadow: 0 4px 12px rgba(0,0,0,0.5);
        }
        .terminal-header {
            background: #161b22;
            padding: 8px 14px;
            font-size: 12px;
            color: #8b949e;
            display: flex;
            justify-content: space-between;
            border-bottom: 1px solid #30363d;
        }
        .terminal-body {
            flex: 1;
            padding: 14px;
            overflow-y: auto;
            font-size: 13px;
            line-height: 1.45;
            font-family: ui-monospace, SFMono-Regular, "SF Mono", Menlo, Consolas, monospace;
        }
        .log-line { margin-bottom: 2px; white-space: pre-wrap; word-break: break-all; }
        .log-sys { color: #8b949e; }
        .log-ok { color: #3fb950; font-weight: bold; }
        .log-err { color: #f85149; font-weight: bold; }
        .log-info { color: #58a6ff; }
        .log-cmd { color: #d29922; }
    </style>
</head>
<body>
    <header>
        <div>
            <h1>魅蓝 Note (M463) 自动刷机终端</h1>
            <div id="target-desc" style="font-size: 12px; color: #8b949e; margin-top: 4px;">当前方案: 加载中...</div>
        </div>
        <div id="status-badge" class="badge badge-waiting">⏳ 等待设备连接 BROM...</div>
    </header>

    <div class="target-bar" id="target-buttons">
        <!-- Buttons injected dynamically -->
    </div>

    <div class="guide-box">
        <strong>操作指引（BROM 抓取方法）:</strong>
        手机拔掉 USB ➔ 长按电源键 10 秒彻底关机 ➔ <strong>按住音量减键不放</strong> ➔ 插上 USB 线 ➔ 屏幕亮起检测进度即松手。程序会自动执行刷入并发送重启指令！
    </div>

    <div class="terminal-container">
        <div class="terminal-header">
            <span>实时输出控制台 (SSE Stream)</span>
            <span id="conn-status">● 实时连接正常</span>
        </div>
        <div class="terminal-body" id="term"></div>
    </div>

    <script>
        const term = document.getElementById('term');
        const badge = document.getElementById('status-badge');
        const conn = document.getElementById('conn-status');
        const targetDesc = document.getElementById('target-desc');
        const targetButtons = document.getElementById('target-buttons');

        function appendLine(text) {
            const div = document.createElement('div');
            div.className = 'log-line';
            if (text.startsWith('[SYSTEM]')) {
                div.className += ' log-sys';
            } else if (text.includes('Successfully') || text.includes('100%') || text.includes('==> [OK]')) {
                div.className += ' log-ok';
            } else if (text.includes('failed') || text.includes('Error') || text.includes('DEVICE_NOT_FOUND')) {
                div.className += ' log-err';
            } else if (text.includes('Preloader') || text.includes('Kamakiri')) {
                div.className += ' log-info';
            }
            div.textContent = text;
            term.appendChild(div);
            term.scrollTop = term.scrollHeight;

            if (text.includes('Kamakiri') || text.includes('Connected')) {
                badge.className = 'badge badge-running';
                badge.textContent = '🚀 设备已捕获，正在注入 DA...';
            } else if (text.includes('Wrote') && text.includes('sector count')) {
                badge.className = 'badge badge-running';
                badge.textContent = '⚡ 写入成功，正在继续...';
            } else if (text.includes('Reset') || text.includes('Send reset')) {
                badge.className = 'badge badge-success';
                badge.textContent = '🔄 已发送重启指令！';
            }
        }

        function loadTargets() {
            fetch('/api/targets')
                .then(r => r.json())
                .then(data => {
                    targetButtons.innerHTML = '';
                    targetDesc.textContent = '当前方案: ' + data.targets[data.current].desc;
                    for (const [key, t] of Object.entries(data.targets)) {
                        const btn = document.createElement('button');
                        btn.className = 'btn-target' + (key === data.current ? ' active' : '') + (key === 'restore_stock' ? ' btn-danger' : '');
                        btn.textContent = t.name;
                        btn.onclick = () => selectTarget(key);
                        targetButtons.appendChild(btn);
                    }
                });
        }

        function selectTarget(key) {
            fetch('/api/set_target?target=' + encodeURIComponent(key), { method: 'POST' })
                .then(r => r.json())
                .then(data => {
                    loadTargets();
                });
        }

        loadTargets();

        const evtSource = new EventSource("/stream");
        evtSource.onmessage = function(e) {
            if (e.data === "[[PROCESS_COMPLETED_SUCCESS]]") {
                badge.className = 'badge badge-success';
                badge.textContent = '✅ 全部完成！设备已自动重启，请观察手机开机！';
                return;
            }
            if (e.data === "[[PROCESS_COMPLETED_FAILED]]") {
                badge.className = 'badge badge-failed';
                badge.textContent = '❌ 执行异常，3秒后自动重新监听，可重新插线';
                return;
            }
            appendLine(e.data);
        };
        evtSource.onerror = function() {
            conn.textContent = '○ 重连中...';
        };
        evtSource.onopen = function() {
            conn.textContent = '● 实时连接正常';
        };
    </script>
</body>
</html>
"""

def broadcast(msg):
    global LOG_HISTORY
    with LOCK:
        LOG_HISTORY.append(msg)
        if len(LOG_HISTORY) > 2000:
            LOG_HISTORY = LOG_HISTORY[-1000:]
        for q in list(SUBSCRIBERS):
            try:
                q.put(msg)
            except Exception:
                pass

import queue

class SSEHandler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        url = urllib.parse.urlparse(self.path)
        if url.path in ("/", "/index.html"):
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(HTML_TEMPLATE.encode("utf-8"))
        elif url.path == "/api/targets":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            resp = {"current": CURRENT_TARGET, "targets": TARGETS}
            self.wfile.write(json.dumps(resp).encode("utf-8"))
        elif url.path == "/stream":
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Connection", "keep-alive")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()

            q = queue.Queue()
            with LOCK:
                for line in LOG_HISTORY:
                    q.put(line)
                SUBSCRIBERS.add(q)

            try:
                while True:
                    try:
                        msg = q.get(timeout=20.0)
                        self.wfile.write(f"data: {msg}\n\n".encode("utf-8"))
                        self.wfile.flush()
                    except queue.Empty:
                        self.wfile.write(b": keepalive\n\n")
                        self.wfile.flush()
            except Exception:
                pass
            finally:
                with LOCK:
                    SUBSCRIBERS.discard(q)
        else:
            self.send_response(404)
            self.end_headers()

    def do_POST(self):
        global CURRENT_TARGET, CURRENT_PROC, RELOAD_EVENT
        url = urllib.parse.urlparse(self.path)
        if url.path == "/api/set_target":
            query = urllib.parse.parse_qs(url.query)
            target = query.get("target", [None])[0]
            if target in TARGETS:
                CURRENT_TARGET = target
                broadcast(f"\n[SYSTEM] 切换目标方案为 ➔ {TARGETS[target]['name']}")
                broadcast(f"[SYSTEM] 准备重新启动监听...")
                if CURRENT_PROC and CURRENT_PROC.poll() is None:
                    try:
                        subprocess.run("echo 1122 | sudo -S pkill -f mtk.py", shell=True)
                    except Exception:
                        pass
                RELOAD_EVENT.set()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(b'{"status": "ok"}')
                return
        self.send_response(400)
        self.end_headers()

    def log_message(self, format, *args):
        pass

def run_flashing_loop():
    global CURRENT_PROC, RELOAD_EVENT
    while True:
        target_info = TARGETS[CURRENT_TARGET]
        cmd = target_info["cmd"]

        broadcast(f"\n=======================================================")
        broadcast(f"[SYSTEM] 自动化监听启动 | 目标: {target_info['name']}")
        broadcast(f"[SYSTEM] 正在监听 USB 端口，等待设备进入 BROM 模式握手...")
        broadcast(f"[SYSTEM] 预设指令: {cmd}")
        broadcast(f"=======================================================")

        master, slave = pty.openpty()
        p = subprocess.Popen(
            cmd,
            shell=True,
            stdin=slave,
            stdout=slave,
            stderr=slave,
            close_fds=True,
            executable="/bin/bash"
        )
        os.close(slave)
        CURRENT_PROC = p
        RELOAD_EVENT.clear()

        buffer = ""
        while True:
            if RELOAD_EVENT.is_set():
                break
            r, _, _ = select.select([master], [], [], 0.2)
            if master in r:
                try:
                    data = os.read(master, 1024)
                    if not data:
                        break
                    text = data.decode("utf-8", errors="replace")
                    buffer += text
                    while "\n" in buffer:
                        line, buffer = buffer.split("\n", 1)
                        clean_line = line.replace("\r", "").strip()
                        if clean_line:
                            broadcast(clean_line)
                except OSError:
                    break
            if p.poll() is not None:
                break

        if buffer.strip():
            broadcast(buffer.strip())

        returncode = p.wait() if p.poll() is not None else -1
        try:
            os.close(master)
        except OSError:
            pass

        if RELOAD_EVENT.is_set():
            broadcast("[SYSTEM] 方案已切换，监听服务重新加载中...")
            time.sleep(1)
            continue

        if returncode == 0:
            if CURRENT_TARGET == "dump_ram_console":
                broadcast("[SYSTEM] ✅ RAM Console 读取成功！正在解析内容...")
                try:
                    if os.path.exists("/tmp/ram_console_saved.bin"):
                        d = open("/tmp/ram_console_saved.bin", "rb").read()
                        broadcast(f"[SYSTEM] 读取到文件大小: {len(d)} 字节")
                        lines = []
                        cur = ""
                        for b in d:
                            if 32 <= b <= 126 or b in (10, 13, 9):
                                cur += chr(b)
                            else:
                                if len(cur.strip()) > 3:
                                    lines.append(cur.strip())
                                cur = ""
                        if cur.strip():
                            lines.append(cur.strip())
                        
                        broadcast("========== 抓取到的内核日志 (前 30 行) ==========")
                        for l in lines[:30]:
                            broadcast(f"[KLOG] {l}")
                        if len(lines) > 30:
                            broadcast(f"========== 最新日志 (最后 40 行) ==========")
                            for l in lines[-40:]:
                                broadcast(f"[KLOG] {l}")
                except Exception as e:
                    broadcast(f"[SYSTEM] 解析日志出错: {e}")
                broadcast("[[PROCESS_COMPLETED_SUCCESS]]")
                broadcast("[SYSTEM] 日志提取完毕，等待切换方案。")
                while not RELOAD_EVENT.is_set():
                    time.sleep(1)
                continue

            broadcast("[SYSTEM] ✅ 刷机流水线执行完成 (exit 0)！设备已自动重启！")
            broadcast("[[PROCESS_COMPLETED_SUCCESS]]")
        else:
            broadcast(f"[SYSTEM] ⚠️ 进程结束 (exit code {returncode})")
            broadcast("[[PROCESS_COMPLETED_FAILED]]")

        broadcast("[SYSTEM] 3 秒后自动重新武装监听，准备下一次操作...\n")
        time.sleep(3)

def main():
    t = threading.Thread(target=run_flashing_loop, daemon=True)
    t.start()

    server = http.server.ThreadingHTTPServer(("0.0.0.0", PORT), SSEHandler)
    print(f"Autoflash Server started on http://0.0.0.0:{PORT}")
    server.serve_forever()

if __name__ == "__main__":
    main()
