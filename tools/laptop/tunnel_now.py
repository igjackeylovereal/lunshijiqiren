# -*- coding: utf-8 -*-
"""本机 127.0.0.1:8765 -> 机器人 127.0.0.1:8765 的 SSH 隧道（可长期运行）。"""
import socket
import threading

import paramiko

ROBOT = "10.166.34.14"
USER = "bobac2"
PASSWORD = "root"
LPORT = 8765
RPORT = 8765


def pump(src, dst):
    try:
        while True:
            data = src.recv(65536)
            if not data:
                break
            dst.sendall(data)
    except Exception:
        pass
    finally:
        try:
            dst.shutdown(socket.SHUT_WR)
        except Exception:
            pass


def handle(client, transport):
    try:
        chan = transport.open_channel(
            "direct-tcpip", ("127.0.0.1", RPORT), client.getpeername(), timeout=10)
        chan.settimeout(None)
    except Exception as e:
        print("open_channel failed:", repr(e), flush=True)
        client.close()
        return
    t1 = threading.Thread(target=pump, args=(client, chan))
    t2 = threading.Thread(target=pump, args=(chan, client))
    t1.daemon = t2.daemon = True
    t1.start()
    t2.start()
    t1.join()
    t2.join()
    try:
        chan.close()
    except Exception:
        pass
    try:
        client.close()
    except Exception:
        pass


def main():
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(ROBOT, 22, USER, PASSWORD, timeout=15,
                   look_for_keys=False, allow_agent=False, compress=True)
    transport = client.get_transport()
    transport.set_keepalive(30)

    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind(("127.0.0.1", LPORT))
    server.listen(50)
    print("tunnel ready 127.0.0.1:%d -> %s:%d" % (LPORT, ROBOT, RPORT), flush=True)
    while True:
        conn, _ = server.accept()
        conn.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        threading.Thread(target=handle, args=(conn, transport)).start()


if __name__ == "__main__":
    main()
