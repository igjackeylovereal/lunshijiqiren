#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""bobac 笔记本启动台

一键完成：SSH 连接 → 检查/启动机器人上的运行栈 → 建立本机端口转发 → 打开网页。
网页仍然是机器人上的 app.py（登录、配置、地图、建图、导航），
本程序只负责“连接 + 生命周期 + 隧道”，所以机器人端不需要再开终端敲命令。
"""

import os
import json
import time
import queue
import socket
import logging
import threading
import subprocess
import webbrowser
import urllib.request

import tkinter as tk
from tkinter import ttk, messagebox
from tkinter.scrolledtext import ScrolledText

try:
    import paramiko
except ImportError:
    paramiko = None

# 屏蔽 paramiko 在隧道失败时刷屏的 “Secsh channel N open FAILED”
for _name in ("paramiko", "paramiko.transport", "paramiko.transport.sftp"):
    logging.getLogger(_name).setLevel(logging.CRITICAL)

APP_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(os.path.expanduser("~"), ".bobac_launcher.json")
CTL = "bash ~/bobac_practicum_ctl.sh"


class Tunnel(object):
    """将本机 127.0.0.1:port 转发到机器人 127.0.0.1:port。"""

    def __init__(self, transport, local_port, target_host="127.0.0.1", target_port=8765):
        self.transport = transport
        self.local_port = local_port
        self.target = (target_host, target_port)
        self.sock = None
        self.stop_evt = threading.Event()
        self.thread = None
        self.error = ""
        self.failures = 0

    def start(self):
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        s.bind(("127.0.0.1", self.local_port))
        s.listen(32)
        s.settimeout(0.5)
        self.sock = s
        self.thread = threading.Thread(target=self._accept_loop, daemon=True)
        self.thread.start()
        return self.local_port

    def _accept_loop(self):
        while not self.stop_evt.is_set():
            try:
                client, addr = self.sock.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            threading.Thread(target=self._serve, args=(client,), daemon=True).start()

    def _serve(self, client):
        try:
            client.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        except Exception:
            pass
        chan = None
        try:
            chan = self.transport.open_channel(
                "direct-tcpip", self.target, client.getpeername(), timeout=10)
        except Exception as e:
            self.error = "隧道建立失败: %s" % e
            self.failures += 1
            client.close()
            return

        try:
            chan.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        except Exception:
            pass

        remaining = [2]
        lock = threading.Lock()

        def finish():
            with lock:
                remaining[0] -= 1
                if remaining[0] > 0:
                    return
            try:
                client.close()
            except Exception:
                pass
            try:
                chan.close()
            except Exception:
                pass

        def chan_to_client():
            # 关键：服务端先发完再关连接，这里必须半关，不能直接 close，
            # 否则浏览器会收到 RST（Failed to fetch / 10054）
            try:
                while True:
                    data = chan.recv(65536)
                    if not data:
                        break
                    client.sendall(data)
            except Exception:
                pass
            finally:
                try:
                    client.shutdown(socket.SHUT_WR)
                except Exception:
                    pass
                finish()

        def client_to_chan():
            try:
                while True:
                    data = client.recv(65536)
                    if not data:
                        break
                    chan.sendall(data)
            except Exception:
                pass
            finally:
                try:
                    chan.shutdown_write()
                except Exception:
                    pass
                finish()

        threading.Thread(target=chan_to_client, daemon=True).start()
        threading.Thread(target=client_to_chan, daemon=True).start()

    def close(self):
        self.stop_evt.set()
        try:
            if self.sock:
                self.sock.close()
        except Exception:
            pass
        try:
            self.transport.close()
        except Exception:
            pass


class Launcher(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("bobac 启动台")
        self.geometry("900x640")
        self.minsize(820, 560)

        self.client = None
        self.tunnel = None
        self.port = None
        self.q = queue.Queue()
        self.busy = False

        cfg = self._load_cfg()
        self.var_ip = tk.StringVar(value=cfg.get("ip", "reinovo.local"))
        self.var_user = tk.StringVar(value=cfg.get("user", "bobac2"))
        self.var_pwd = tk.StringVar(value="")
        self.var_remember = tk.BooleanVar(value=bool(cfg.get("remember", False)))
        self.var_mode = tk.StringVar(value=cfg.get("mode", "nav"))
        self.var_map = tk.StringVar(value="")
        self.var_x = tk.StringVar(value=cfg.get("pose_x", "0"))
        self.var_y = tk.StringVar(value=cfg.get("pose_y", "0"))
        self.var_a = tk.StringVar(value=cfg.get("pose_a", "0"))

        self._build()
        self.after(100, self._poll)
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    # ---------------- config ----------------
    def _load_cfg(self):
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}

    def _save_cfg(self):
        data = {
            "ip": self.var_ip.get().strip(),
            "user": self.var_user.get().strip(),
            "mode": self.var_mode.get(),
            "remember": bool(self.var_remember.get()),
            "pose_x": self.var_x.get().strip(),
            "pose_y": self.var_y.get().strip(),
            "pose_a": self.var_a.get().strip(),
        }
        try:
            with open(CONFIG_PATH, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception:
            pass

    # ---------------- UI ----------------
    def _build(self):
        top = ttk.Frame(self, padding=(10, 8, 10, 2))
        top.pack(fill="x")

        ttk.Label(top, text="IP").pack(side="left")
        ttk.Entry(top, textvariable=self.var_ip, width=15).pack(side="left", padx=(4, 10))
        ttk.Label(top, text="用户").pack(side="left")
        ttk.Entry(top, textvariable=self.var_user, width=10).pack(side="left", padx=(4, 10))
        ttk.Label(top, text="密码").pack(side="left")
        ttk.Entry(top, textvariable=self.var_pwd, width=10, show="*").pack(side="left", padx=(4, 10))
        ttk.Checkbutton(top, text="记住", variable=self.var_remember).pack(side="left")

        self.lbl = ttk.Label(top, text="● 未连接", foreground="#c0392b")
        self.lbl.pack(side="left", padx=12)

        main = ttk.Frame(self, padding=(10, 6))
        main.pack(fill="x")

        self.btn_start = ttk.Button(main, text="一键启动并打开", command=self.start_all, width=18)
        self.btn_start.grid(row=0, column=0, padx=2, pady=2, sticky="ew")
        ttk.Button(main, text="打开网页", command=self.open_page, width=10).grid(row=0, column=1, padx=2)
        ttk.Button(main, text="测试声音", command=self.test_sound, width=10).grid(row=0, column=2, padx=2)
        ttk.Button(main, text="停止", command=self.stop_all, width=8).grid(row=0, column=3, padx=2)
        ttk.Button(main, text="重启", command=self.restart_all, width=8).grid(row=0, column=4, padx=2)
        ttk.Button(main, text="状态", command=self.refresh_status, width=8).grid(row=0, column=5, padx=2)
        ttk.Button(main, text="日志", command=self.show_log, width=8).grid(row=0, column=6, padx=2)

        mode = ttk.LabelFrame(self, text=" 运行模式 ", padding=8)
        mode.pack(fill="x", padx=10, pady=4)
        row1 = ttk.Frame(mode)
        row1.pack(fill="x")
        ttk.Radiobutton(row1, text="导航（已有地图）", value="nav",
                        variable=self.var_mode).pack(side="left")
        ttk.Radiobutton(row1, text="建图", value="mapping",
                        variable=self.var_mode).pack(side="left", padx=10)
        ttk.Radiobutton(row1, text="静态（不运动）", value="static",
                        variable=self.var_mode).pack(side="left")
        self.cmb_map = ttk.Combobox(row1, textvariable=self.var_map, width=48, state="readonly")
        self.cmb_map.pack(side="left", padx=12)
        ttk.Button(row1, text="刷新地图", command=self.refresh_maps, width=10).pack(side="left")

        row2 = ttk.Frame(mode)
        row2.pack(fill="x", pady=(6, 0))
        ttk.Label(row2, text="初始位姿  x").pack(side="left")
        ttk.Entry(row2, textvariable=self.var_x, width=12).pack(side="left", padx=(2, 10))
        ttk.Label(row2, text="y").pack(side="left")
        ttk.Entry(row2, textvariable=self.var_y, width=12).pack(side="left", padx=(2, 10))
        ttk.Label(row2, text="yaw").pack(side="left")
        ttk.Entry(row2, textvariable=self.var_a, width=12).pack(side="left", padx=(2, 10))
        ttk.Label(row2, text="（启动导航时传给 AMCL；刷新状态会自动填入当前值）",
                  foreground="#7f8c8d").pack(side="left")

        self.txt = ScrolledText(self, height=18, wrap="none", state="disabled",
                                font=("Consolas", 9))
        self.txt.pack(fill="both", expand=True, padx=10, pady=(4, 10))
        self.txt.tag_config("err", foreground="#c0392b")
        self.txt.tag_config("ok", foreground="#27ae60")
        self.txt.tag_config("warn", foreground="#d35400")
        self.txt.tag_config("cmd", foreground="#2c3e50")

    # ---------------- logging ----------------
    def log(self, text, tag="cmd"):
        self.txt.configure(state="normal")
        self.txt.insert("end", text + "\n", tag)
        self.txt.see("end")
        self.txt.configure(state="disabled")

    def _poll(self):
        try:
            while True:
                kind, text = self.q.get_nowait()
                self.log(text, kind)
        except queue.Empty:
            pass
        self.after(100, self._poll)

    # ---------------- ssh ----------------
    def connect(self):
        if paramiko is None:
            messagebox.showerror("缺少依赖", "未安装 paramiko，请运行 启动控制台.bat 自动安装")
            return False
        if self.client is not None:
            return True
        ip = self.var_ip.get().strip()
        user = self.var_user.get().strip()
        pwd = self.var_pwd.get()
        if not pwd:
            messagebox.showinfo("提示", "请输入密码")
            return False
        # 机器人 IP 会随网络变化：优先用输入的地址，失败再试 mDNS 名字和历史地址
        candidates = []
        for host in [ip, "reinovo.local", "10.109.40.14", "10.224.117.14"]:
            if host and host not in candidates:
                candidates.append(host)
        last_err = None
        for host in candidates:
            try:
                c = paramiko.SSHClient()
                c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
                c.connect(host, 22, user, pwd, timeout=8, banner_timeout=10,
                          auth_timeout=10, look_for_keys=False, allow_agent=False)
                self.client = c
                self.lbl.configure(text="● 已连接", foreground="#27ae60")
                self.log("已连接 %s@%s" % (user, host), "ok")
                if host != ip:
                    self.var_ip.set(host)
                self._save_cfg()
                self._ensure_ctl()
                return True
            except Exception as e:
                last_err = e
                self.log("连接 %s 失败：%s" % (host, e), "warn")
        self.log("[连接失败] %s" % last_err, "err")
        messagebox.showerror("连接失败", "已尝试：%s\n\n最后错误：%s" % (", ".join(candidates), last_err))
        return False

    def run_cmd(self, cmd, timeout=180):
        _in, out, err = self.client.exec_command(cmd, timeout=timeout, get_pty=True)
        text = out.read().decode("utf-8", "ignore")
        out.channel.recv_exit_status()
        return text

    def _ensure_ctl(self):
        """每次连接都覆盖上传，避免机器人上残留旧脚本导致行为不一致。"""
        local = os.path.join(os.path.dirname(APP_DIR), "deploy", "bobac_practicum_ctl.sh")
        if not os.path.isfile(local):
            self.log("本地缺少 deploy/bobac_practicum_ctl.sh，跳过上传", "warn")
            return
        remote = "/home/bobac2/bobac_practicum_ctl.sh"
        try:
            sftp = self.client.open_sftp()
            sftp.put(local, remote)
            sftp.chmod(remote, 0o755)
            sftp.close()
            self.log("控制脚本已上传（%d 字节）" % os.path.getsize(local), "ok")
        except Exception as e:
            self.log("上传控制脚本失败：%s" % e, "err")

    # ---------------- actions ----------------
    def start_all(self):
        if self.busy:
            return
        if not self.connect():
            return
        self.busy = True
        self.btn_start.configure(state="disabled")
        threading.Thread(target=self._start_worker, daemon=True).start()

    def _start_worker(self):
        try:
            self._ensure_ctl()
            self.log("\n=== 检查机器人运行栈 ===")
            st = self.run_cmd(CTL + " status")
            self.log(st.strip())
            app_up = "APP=up" in st
            port_up = "PORT=up" in st

            if not app_up:
                mode = self.var_mode.get()
                if mode == "nav":
                    mapyaml = self.var_map.get().strip()
                    cmd = CTL + " up nav"
                    if mapyaml:
                        cmd += " %s %s %s %s" % (mapyaml, self.var_x.get().strip() or "0",
                                                 self.var_y.get().strip() or "0",
                                                 self.var_a.get().strip() or "0")
                elif mode == "mapping":
                    cmd = CTL + " up mapping"
                else:
                    cmd = CTL + " up static"
                self.log("\n=== 启动：%s ===" % cmd)
                self.log(self.run_cmd(cmd, timeout=180).strip(), "ok")
            else:
                self.log("应用已在运行，直接建立隧道", "ok")

            self.log("\n=== 建立本地隧道 ===")
            self._ensure_tunnel()
            self.log("隧道就绪：http://127.0.0.1:%d/" % self.port, "ok")
            self._wait_http()
            self.open_page()
            self.refresh_status()
        except Exception as e:
            self.log("[启动失败] %s" % e, "err")
        finally:
            self.busy = False
            self.after(0, lambda: self.btn_start.configure(state="normal"))

    def _ensure_tunnel(self):
        if self.tunnel is not None and self.tunnel.thread and self.tunnel.thread.is_alive():
            return
        transport = self.client.get_transport()
        # 服务端校验 Host 必须等于 127.0.0.1:8765，所以本机端口也必须是 8765
        port = 8765
        try:
            t = Tunnel(transport, port)
            t.start()
            self.tunnel = t
            self.port = port
        except OSError as e:
            if self._http_ok(port):
                self.port = port
                self.log("检测到 8765 已有可用隧道，直接复用", "warn")
                return
            raise RuntimeError(
                "本机 8765 端口被占用（%s）。请关闭占用它的程序（可能是上一次的 ssh -L 隧道）后重试。" % e)

    def _http_ok(self, port):
        try:
            with urllib.request.urlopen("http://127.0.0.1:%d/" % port, timeout=3) as r:
                return r.status == 200
        except Exception:
            return False

    def _wait_http(self, timeout=40):
        url = "http://127.0.0.1:%d/" % self.port
        start = time.time()
        while time.time() - start < timeout:
            try:
                with urllib.request.urlopen(url, timeout=3) as r:
                    if r.status == 200:
                        self.log("网页可访问（HTTP 200）", "ok")
                        return True
            except Exception:
                time.sleep(1)
        self.log("网页暂时无法访问，自动读取 app 日志：", "warn")
        try:
            self.log(self.run_cmd(CTL + " log app 20").strip(), "err")
        except Exception:
            pass
        self.log("提示：若日志显示 ValueError/端口未监听，点「状态」确认 MODE 是否正确，再点「重启」。", "warn")
        return False

    def open_page(self):
        if self.port is None:
            messagebox.showinfo("提示", "先点“一键启动并打开”")
            return
        url = "http://127.0.0.1:%d/" % self.port
        # 用独立配置目录启动，确保 --autoplay-policy 生效（否则浏览器会拦截语音自动播放）
        profile = os.path.join(os.environ.get("LOCALAPPDATA", os.path.expanduser("~")), "bobac_chrome")
        candidates = [
            r"C:\Program Files\Google\Chrome\Application\chrome.exe",
            r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
            r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
        ]
        for exe in candidates:
            if os.path.isfile(exe):
                try:
                    subprocess.Popen([exe,
                                      "--autoplay-policy=no-user-gesture-required",
                                      "--user-data-dir=" + profile,
                                      url])
                    self.log("已用浏览器打开（允许语音自动播放）：" + url, "ok")
                    return
                except Exception as e:
                    self.log("浏览器启动失败：%s" % e, "warn")
        webbrowser.open(url)

    def stop_all(self):
        if not self.client:
            return
        self.log("\n=== 停止运行栈（保留 roscore）===")
        threading.Thread(target=lambda: self.log(self.run_cmd(CTL + " stop").strip(), "warn"),
                         daemon=True).start()

    def restart_all(self):
        if not self.client:
            return
        self.log("\n=== 重启 ===")

        def job():
            mode = self.var_mode.get()
            self.log(self.run_cmd(CTL + " stop").strip(), "warn")
            time.sleep(2)
            if mode == "nav":
                cmd = CTL + " up nav"
                if self.var_map.get().strip():
                    cmd += " %s %s %s %s" % (self.var_map.get().strip(),
                                             self.var_x.get().strip() or "0",
                                             self.var_y.get().strip() or "0",
                                             self.var_a.get().strip() or "0")
            else:
                cmd = CTL + " up " + mode
            self.log(self.run_cmd(cmd, timeout=180).strip(), "ok")
            self._ensure_tunnel()
            self._wait_http()
            self.open_page()
        threading.Thread(target=job, daemon=True).start()

    def refresh_status(self):
        if not self.client:
            messagebox.showinfo("提示", "先连接")
            return

        def job():
            try:
                st = self.run_cmd(CTL + " status")
                self.log("\n=== 状态 ===\n" + st.strip())
                for line in st.splitlines():
                    if line.startswith("POSE_X=") and line.split("=", 1)[1].strip():
                        self.after(0, lambda v=line.split("=", 1)[1].strip(): self.var_x.set(v))
                    elif line.startswith("POSE_Y=") and line.split("=", 1)[1].strip():
                        self.after(0, lambda v=line.split("=", 1)[1].strip(): self.var_y.set(v))
                    elif line.startswith("POSE_A=") and line.split("=", 1)[1].strip():
                        self.after(0, lambda v=line.split("=", 1)[1].strip(): self.var_a.set(v))
                    elif line.startswith("MAP_YAML=") and line.split("=", 1)[1].strip():
                        self.after(0, lambda v=line.split("=", 1)[1].strip(): self.var_map.set(v))
                if "APP=up" in st:
                    self.lbl.configure(text="● 运行中", foreground="#27ae60")
                else:
                    self.lbl.configure(text="● 已连接（应用未运行）", foreground="#d35400")
            except Exception as e:
                self.log("状态读取失败: %s" % e, "err")

        threading.Thread(target=job, daemon=True).start()

    def test_sound(self):
        """在本机直接播放机器人合成的 /reply.wav，用来区分“电脑没声音”和“页面自动播放被拦”。"""
        if self.port is None:
            messagebox.showinfo("提示", "先点“一键启动并打开”")
            return

        def job():
            try:
                data = urllib.request.urlopen(
                    "http://127.0.0.1:%d/reply.wav" % self.port, timeout=15).read()
                path = os.path.join(os.environ.get("TEMP", "."), "bobac_reply_test.wav")
                with open(path, "wb") as f:
                    f.write(data)
                self.log("已下载语音 %.1f KB，开始在本机播放" % (len(data) / 1024.0), "ok")
                import winsound
                winsound.PlaySound(path, winsound.SND_FILENAME)
                self.log("本机播放结束；如果刚才没听到，请检查 Windows 音量/输出设备", "warn")
            except Exception as e:
                self.log("[测试声音失败] %s" % e, "err")

        threading.Thread(target=job, daemon=True).start()

    def show_log(self):
        if not self.client:
            return

        def job():
            self.log("\n=== app 日志（最后 60 行）===")
            self.log(self.run_cmd(CTL + " log app 60").strip())

        threading.Thread(target=job, daemon=True).start()

    def refresh_maps(self):
        if not self.client:
            messagebox.showinfo("提示", "先连接")
            return

        def job():
            try:
                out = self.run_cmd(CTL + " maps")
                maps = [l.strip() for l in out.splitlines() if l.strip().endswith(".yaml")]
                self.after(0, lambda: self._set_maps(maps))
            except Exception as e:
                self.log("地图列表失败: %s" % e, "err")

        threading.Thread(target=job, daemon=True).start()

    def _set_maps(self, maps):
        self.cmb_map["values"] = maps
        if maps and not self.var_map.get():
            self.var_map.set(maps[0])
        self.log("地图 %d 个" % len(maps))

    # ---------------- close ----------------
    def _on_close(self):
        self._save_cfg()
        try:
            if self.tunnel:
                self.tunnel.close()
            if self.client:
                self.client.close()
        except Exception:
            pass
        self.destroy()


def main():
    app = Launcher()
    if paramiko is None:
        app.log("未安装 paramiko：请双击 启动控制台.bat 自动安装", "err")
    app.mainloop()


if __name__ == "__main__":
    main()
