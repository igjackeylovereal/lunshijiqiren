#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""bobac 智能实训控制台（本机 Windows，无需 VNC）

通过 SSH 向机器人下发命令，所有按钮背后都是 `bash ~/practicum.sh <命令>`。
"""

import os
import sys
import shlex
import queue
import threading

import tkinter as tk
from tkinter import ttk, messagebox
from tkinter.scrolledtext import ScrolledText

try:
    import paramiko
except ImportError:
    paramiko = None

APP_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR = os.path.dirname(APP_DIR)
MAP_DIR = os.path.join(ROOT_DIR, "maps")
SNAP_PATH = os.path.join(ROOT_DIR, "snap.jpg")

CMD_TIMEOUT = 300


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("bobac 智能实训控制台")
        self.geometry("1020x780")
        self.minsize(920, 700)

        self.client = None
        self.sftp = None
        self.q = queue.Queue()

        self.var_ip = tk.StringVar(value="10.224.117.14")
        self.var_user = tk.StringVar(value="root")
        self.var_pwd = tk.StringVar(value="root")
        self.var_step = tk.StringVar(value="1.0")
        self.var_place = tk.StringVar(value="")
        self.var_x = tk.StringVar(value="0")
        self.var_y = tk.StringVar(value="0")
        self.var_yaw = tk.StringVar(value="0")
        self.var_say = tk.StringVar(value="你好，我是bobac")
        self.var_name = tk.StringVar(value="")
        self.var_count = tk.StringVar(value="30")
        self.var_raw = tk.StringVar(value="")

        self._build()
        self.after(100, self._poll)
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    # ------------------------------------------------------------------ UI
    def _build(self):
        self._build_conn()
        self._build_modes()
        self._build_control()
        self._build_tools()
        self._build_log()

    def _build_conn(self):
        f = ttk.Frame(self, padding=(10, 8, 10, 2))
        f.pack(fill="x")

        ttk.Label(f, text="机器人 IP").pack(side="left")
        ttk.Entry(f, textvariable=self.var_ip, width=15).pack(side="left", padx=(4, 12))
        ttk.Label(f, text="用户").pack(side="left")
        ttk.Entry(f, textvariable=self.var_user, width=8).pack(side="left", padx=(4, 12))
        ttk.Label(f, text="密码").pack(side="left")
        ttk.Entry(f, textvariable=self.var_pwd, width=9, show="*").pack(side="left", padx=(4, 12))

        self.btn_conn = ttk.Button(f, text="连接", width=8, command=self.on_connect)
        self.btn_conn.pack(side="left")
        self.lbl_conn = ttk.Label(f, text="● 未连接", foreground="#c0392b")
        self.lbl_conn.pack(side="left", padx=12)

    def _build_modes(self):
        wrap = ttk.Frame(self, padding=(10, 4))
        wrap.pack(fill="x")

        a = ttk.LabelFrame(wrap, text=" 模式 A · 还没有地图：先建图 ", padding=8)
        a.pack(side="left", fill="both", expand=True, padx=(0, 6))
        a.columnconfigure(0, weight=1)
        a.columnconfigure(1, weight=1)
        a.columnconfigure(2, weight=1)
        ttk.Button(a, text="① 开始建图", command=lambda: self.do_cmd("map", "开始建图")).grid(
            row=0, column=0, sticky="ew", pady=2)
        ttk.Button(a, text="② 保存地图并下载", command=self.do_save).grid(
            row=0, column=1, sticky="ew", pady=2, padx=6)
        ttk.Button(a, text="③ 结束建图", command=lambda: self.do_cmd("stopmap", "结束建图")).grid(
            row=0, column=2, sticky="ew", pady=2)
        ttk.Label(a, text="建图中用下方方向键遥控；绕场一圈后点②保存。",
                  foreground="#555").grid(row=1, column=0, columnspan=3, sticky="w", pady=(8, 0))

        b = ttk.LabelFrame(wrap, text=" 模式 B · 已有地图：直接开任务 ", padding=8)
        b.pack(side="left", fill="both", expand=True)
        b.columnconfigure(0, weight=1)
        b.columnconfigure(1, weight=1)
        ttk.Button(b, text="▶ 一键启动全部", command=self.do_run).grid(
            row=0, column=0, sticky="ew", pady=2)
        ttk.Button(b, text="■ 全部停止", command=lambda: self.do_cmd("stop", "全部停止")).grid(
            row=0, column=1, sticky="ew", pady=2, padx=6)
        ttk.Label(b, text="启动后先“设定初始位姿”，再走语音任务流程。",
                  foreground="#555").grid(row=1, column=0, columnspan=2, sticky="w", pady=(8, 0))

    def _build_control(self):
        wrap = ttk.Frame(self, padding=(10, 4))
        wrap.pack(fill="x")

        mv = ttk.LabelFrame(wrap, text=" 遥控 / 建图行走 ", padding=8)
        mv.pack(side="left", fill="y")
        ttk.Button(mv, text="↑ 前进", width=9,
                   command=lambda: self.do_move(0.15, 0.0)).grid(row=0, column=1, pady=1)
        ttk.Button(mv, text="← 左转", width=9,
                   command=lambda: self.do_move(0.0, 0.6)).grid(row=1, column=0, padx=1)
        ttk.Button(mv, text="■ 停", width=9,
                   command=lambda: self.do_move(0.0, 0.0, 0.2)).grid(row=1, column=1)
        ttk.Button(mv, text="→ 右转", width=9,
                   command=lambda: self.do_move(0.0, -0.6)).grid(row=1, column=2, padx=1)
        ttk.Button(mv, text="↓ 后退", width=9,
                   command=lambda: self.do_move(-0.12, 0.0)).grid(row=2, column=1, pady=1)
        ttk.Label(mv, text="每步时长(秒)").grid(row=3, column=0, columnspan=2, sticky="e", pady=(6, 0))
        ttk.Spinbox(mv, from_=0.2, to=3.0, increment=0.2, width=6,
                    textvariable=self.var_step).grid(row=3, column=2, sticky="w", pady=(6, 0))

        pl = ttk.LabelFrame(wrap, text=" 定点导航 ", padding=8)
        pl.pack(side="left", fill="y", padx=8)
        self.cmb_place = ttk.Combobox(pl, textvariable=self.var_place, width=16, state="readonly")
        self.cmb_place.grid(row=0, column=0, columnspan=2, sticky="ew")
        ttk.Button(pl, text="刷新地点", command=self.refresh_places).grid(
            row=1, column=0, sticky="ew", pady=3)
        ttk.Button(pl, text="前往", command=self.do_goto).grid(
            row=1, column=1, sticky="ew", pady=3, padx=4)

        ps = ttk.LabelFrame(wrap, text=" 初始位姿 ", padding=8)
        ps.pack(side="left", fill="y")
        for i, (lab, var) in enumerate((("x", self.var_x), ("y", self.var_y), ("yaw", self.var_yaw))):
            ttk.Label(ps, text=lab).grid(row=0, column=i * 2, sticky="e", padx=(4, 0))
            ttk.Entry(ps, textvariable=var, width=7).grid(row=0, column=i * 2 + 1, padx=(2, 6))
        ttk.Button(ps, text="设定初始位姿", command=self.do_pose).grid(
            row=1, column=0, columnspan=6, sticky="ew", pady=(6, 0))

    def _build_tools(self):
        f = ttk.Frame(self, padding=(10, 4))
        f.pack(fill="x")

        ttk.Button(f, text="系统体检", width=10,
                   command=lambda: self.do_cmd("check", "系统体检")).pack(side="left")
        ttk.Button(f, text="状态", width=8,
                   command=lambda: self.do_cmd("status", "状态")).pack(side="left", padx=6)
        ttk.Button(f, text="抓图", width=8, command=self.do_snap).pack(side="left")
        ttk.Button(f, text="看日志", width=8,
                   command=lambda: self.do_cmd("log full 80", "查看日志")).pack(side="left", padx=6)

        ttk.Label(f, text="语音").pack(side="left", padx=(12, 2))
        ttk.Entry(f, textvariable=self.var_say, width=24).pack(side="left")
        ttk.Button(f, text="播报", width=6, command=self.do_say).pack(side="left", padx=4)

        ttk.Label(f, text="姓名").pack(side="left", padx=(12, 2))
        ttk.Entry(f, textvariable=self.var_name, width=10).pack(side="left")
        ttk.Label(f, text="张数").pack(side="left", padx=(6, 2))
        ttk.Entry(f, textvariable=self.var_count, width=5).pack(side="left")
        ttk.Button(f, text="采集人脸", width=10, command=self.do_enroll).pack(side="left", padx=4)

    def _build_log(self):
        wrap = ttk.Frame(self, padding=(10, 4, 10, 10))
        wrap.pack(fill="both", expand=True)

        self.txt = ScrolledText(wrap, height=16, wrap="none", state="disabled",
                                font=("Consolas", 9))
        self.txt.pack(fill="both", expand=True)
        self.txt.tag_config("err", foreground="#c0392b")
        self.txt.tag_config("ok", foreground="#27ae60")
        self.txt.tag_config("warn", foreground="#d35400")
        self.txt.tag_config("cmd", foreground="#2980b9")
        self.txt.tag_config("info", foreground="#7f8c8d")

        bar = ttk.Frame(wrap)
        bar.pack(fill="x", pady=(6, 0))
        ttk.Label(bar, text="自定义命令").pack(side="left")
        e = ttk.Entry(bar, textvariable=self.var_raw)
        e.pack(side="left", fill="x", expand=True, padx=6)
        e.bind("<Return>", lambda _e: self.do_raw())
        ttk.Button(bar, text="发送", width=8, command=self.do_raw).pack(side="left")
        ttk.Button(bar, text="清空", width=8, command=self.clear_log).pack(side="left", padx=6)

    # ------------------------------------------------------------------ logging
    def _log(self, text, tag="info"):
        self.txt.configure(state="normal")
        self.txt.insert("end", text + "\n", tag)
        self.txt.see("end")
        self.txt.configure(state="disabled")

    def _poll(self):
        try:
            while True:
                kind, text = self.q.get_nowait()
                self._log(text, kind)
        except queue.Empty:
            pass
        self.after(100, self._poll)

    def clear_log(self):
        self.txt.configure(state="normal")
        self.txt.delete("1.0", "end")
        self.txt.configure(state="disabled")

    # ------------------------------------------------------------------ connection
    def on_connect(self):
        if paramiko is None:
            messagebox.showerror(
                "缺少依赖",
                "未安装 paramiko。\n\n请在命令行执行：\n"
                "pip install paramiko -i https://pypi.tuna.tsinghua.edu.cn/simple")
            return
        if self.client is not None:
            return
        ip = self.var_ip.get().strip()
        user = self.var_user.get().strip()
        pwd = self.var_pwd.get()
        self.btn_conn.configure(state="disabled")
        self.q.put(("info", "正在连接 %s ..." % ip))
        threading.Thread(target=self._connect_worker, args=(ip, user, pwd), daemon=True).start()

    def _connect_worker(self, ip, user, pwd):
        try:
            c = paramiko.SSHClient()
            c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            c.connect(ip, port=22, username=user, password=pwd,
                      timeout=8, banner_timeout=10, auth_timeout=10,
                      look_for_keys=False, allow_agent=False)
            self.client = c
            self.sftp = c.open_sftp()
            self.q.put(("ok", "已连接 %s" % ip))
            self.after(0, lambda: self.lbl_conn.configure(text="● 已连接", foreground="#27ae60"))
            self.after(0, lambda: self.btn_conn.configure(text="已连接"))
            self.run_bg("test -f ~/practicum.sh && echo SCRIPT_OK || echo SCRIPT_MISSING", "环境检查")
            self.run_bg("bash ~/practicum.sh check", "系统体检")
            self.refresh_places()
        except Exception as e:
            self.q.put(("err", "[连接失败] %s" % e))
            self.after(0, lambda: self.btn_conn.configure(state="normal"))

    # ------------------------------------------------------------------ ssh helpers
    def run_bg(self, cmd, title=None):
        if self.client is None:
            messagebox.showwarning("未连接", "请先点“连接”")
            return
        if title:
            self.q.put(("info", "\n=== %s ===" % title))
        self.q.put(("cmd", "$ " + cmd))
        threading.Thread(target=self._worker, args=(cmd,), daemon=True).start()

    def _worker(self, cmd):
        try:
            _in, out, _err = self.client.exec_command(cmd, timeout=CMD_TIMEOUT, get_pty=True)
            for raw in iter(out.readline, ""):
                line = raw.rstrip("\r\n")
                if line:
                    self.q.put(("out", line))
            rc = out.channel.recv_exit_status()
            if rc != 0:
                self.q.put(("warn", "[exit %d]" % rc))
        except Exception as e:
            self.q.put(("err", "[错误] %s" % e))

    def capture(self, cmd, timeout=60):
        _in, out, _err = self.client.exec_command(cmd, timeout=timeout)
        return out.read().decode("utf-8", "ignore")

    # ------------------------------------------------------------------ actions
    def do_cmd(self, args, title):
        self.run_bg("bash ~/practicum.sh %s" % args, title)

    def do_move(self, lx, az, step=None):
        try:
            dur = float(step if step is not None else self.var_step.get())
        except ValueError:
            dur = 1.0
        self.do_cmd("move %s %s %s" % (lx, az, dur), "移动")

    def do_pose(self):
        self.do_cmd("pose %s %s %s" % (self.var_x.get(), self.var_y.get(), self.var_yaw.get()),
                    "设定初始位姿")

    def do_goto(self):
        place = self.var_place.get().strip()
        if not place:
            messagebox.showinfo("提示", "先在下拉框选一个地点")
            return
        self.do_cmd("goto " + shlex.quote(place), "前往 %s" % place)

    def do_run(self):
        self.run_bg("bash ~/practicum.sh run", "一键启动全部")
        self.after(9000, self.refresh_places)

    def do_say(self):
        text = self.var_say.get().strip()
        if not text:
            return
        self.do_cmd("say " + shlex.quote(text), "语音播报")

    def do_enroll(self):
        name = self.var_name.get().strip()
        if not name:
            messagebox.showinfo("提示", "先填写姓名")
            return
        self.do_cmd("enroll %s %s" % (shlex.quote(name), self.var_count.get().strip() or "30"),
                    "采集人脸")

    def do_raw(self):
        cmd = self.var_raw.get().strip()
        if not cmd:
            return
        self.run_bg(cmd, "自定义命令")
        self.var_raw.set("")

    def refresh_places(self):
        if self.client is None:
            return

        def job():
            try:
                text = self.capture("bash ~/practicum.sh places")
                names = [l.strip() for l in text.splitlines() if l.strip()]
                self.after(0, lambda: self._set_places(names))
            except Exception as e:
                self.q.put(("warn", "读取地点失败：%s" % e))

        threading.Thread(target=job, daemon=True).start()

    def _set_places(self, names):
        self.cmb_place["values"] = names
        if names and (not self.var_place.get() or self.var_place.get() not in names):
            self.var_place.set(names[0])
        self.q.put(("ok", "地点：%s" % ("、".join(names) if names else "（position_info.txt 为空）")))

    # ------------------------------------------------------------------ files
    def do_save(self):
        if self.client is None:
            messagebox.showwarning("未连接", "请先点“连接”")
            return
        self.q.put(("info", "\n=== 保存地图并下载 ==="))
        threading.Thread(target=self._save_worker, daemon=True).start()

    def _save_worker(self):
        try:
            self.q.put(("cmd", "$ bash ~/practicum.sh save lab"))
            _in, out, _err = self.client.exec_command("bash ~/practicum.sh save lab",
                                                      timeout=120, get_pty=True)
            lines = []
            for raw in iter(out.readline, ""):
                line = raw.rstrip("\r\n")
                if line:
                    lines.append(line)
                    self.q.put(("out", line))
            out.channel.recv_exit_status()
            base = ""
            for line in lines:
                if line.startswith("MAPFILE="):
                    base = line.split("=", 1)[1].strip()
            if base:
                self._download_map(base)
            else:
                self.q.put(("warn", "没有拿到地图路径，检查机器人端 practicum.sh save 输出"))
        except Exception as e:
            self.q.put(("err", "[保存失败] %s" % e))

    def _download_map(self, base):
        os.makedirs(MAP_DIR, exist_ok=True)
        stem = os.path.basename(base)
        pgm = os.path.join(MAP_DIR, stem + ".pgm")
        yml = os.path.join(MAP_DIR, stem + ".yaml")
        self.sftp.get(base + ".pgm", pgm)
        self.sftp.get(base + ".yaml", yml)
        self.q.put(("ok", "地图已下载：%s" % pgm))
        self._open_file(pgm)

    def do_snap(self):
        if self.client is None:
            messagebox.showwarning("未连接", "请先点“连接”")
            return

        def job():
            try:
                text = self.capture("bash ~/practicum.sh snap", timeout=40)
                remote = ""
                for line in text.splitlines():
                    if line.strip().startswith("/"):
                        remote = line.strip()
                if not remote:
                    self.q.put(("warn", "抓图失败：%s" % text.strip()))
                    return
                self.sftp.get(remote, SNAP_PATH)
                self.q.put(("ok", "截图已保存：%s" % SNAP_PATH))
                self._open_file(SNAP_PATH)
            except Exception as e:
                self.q.put(("err", "[抓图失败] %s" % e))

        threading.Thread(target=job, daemon=True).start()

    def _open_file(self, path):
        try:
            if path.lower().endswith(".pgm"):
                try:
                    from PIL import Image
                    png = os.path.splitext(path)[0] + ".png"
                    Image.open(path).save(png)
                    path = png
                except Exception:
                    pass
            if hasattr(os, "startfile"):
                os.startfile(path)
        except Exception as e:
            self.q.put(("warn", "无法自动打开 %s（%s）" % (path, e)))

    # ------------------------------------------------------------------ close
    def _on_close(self):
        try:
            if self.sftp:
                self.sftp.close()
            if self.client:
                self.client.close()
        except Exception:
            pass
        self.destroy()


def main():
    app = App()
    if paramiko is None:
        app.q.put(("err", "未安装 paramiko，先执行：pip install paramiko"))
    app.mainloop()


if __name__ == "__main__":
    main()
