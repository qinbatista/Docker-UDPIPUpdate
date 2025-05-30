#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os, time, requests, threading, subprocess
import socket
import traceback
import random
from datetime import datetime
import sys


class UDPClient:
    def __init__(self, client_domain_name, server_domain_names, log_file=None):
        self._my_domain = client_domain_name
        self._target_servers = server_domain_names.split(",") if server_domain_names else []
        if log_file is None:
            script_dir = os.path.dirname(os.path.abspath(__file__))
            log_file = os.path.join(script_dir, "udp_client.log")
        self._log_file = log_file
        self._can_connect = 0
        self._ipv4_services = ["https://checkip.amazonaws.com", "https://api.ipify.org", "https://ifconfig.me/ip", "https://ipinfo.io/ip"]

        self.__log(f"client_domain_name={client_domain_name}, server_domain_names={server_domain_names}, Initial IP={self.get_public_ip()}")

    def __log(self, message):
        with open(self._log_file, "a+") as f:
            f.write(message + "\n")
        if os.path.getsize(self._log_file) > 1024 * 128:
            os.remove(self._log_file)

    def get_public_ip(self):
        services = random.sample(self._ipv4_services, len(self._ipv4_services))  # shuffle to avoid per‑service rate limits
        for url in services:
            try:
                r = requests.get(url, timeout=5)
                r.raise_for_status()
                ip = r.text.strip()
                if ip:
                    return ip
            except Exception as e:
                self.__log(f"[IP lookup] {url} failed: {e}")
        self.__log("[IP lookup] All services failed, returning 0.0.0.0")
        return "0.0.0.0"

    def ping_server(self):
        while True:
            reachable = 0
            for server in self._target_servers:
                try:
                    proc = subprocess.Popen(f"ping -c 1 {server}", stdout=subprocess.PIPE, universal_newlines=True, shell=True)
                    proc.wait()
                    if proc.returncode == 0:
                        reachable = 1
                        break
                except Exception as e:
                    self.__log(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}][ping] Error pinging {server}: {e}")
            if reachable != self._can_connect:
                self.__log(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}][ping] Connectivity status changed: {self._can_connect} -> {reachable}")
            self._can_connect = reachable
            time.sleep(60)

    def update_server(self):
        udp_client = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        udp_client.settimeout(5)
        while True:
            ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            try:
                ip = self.get_public_ip()
                message = f"{self._my_domain},v4,{ip},{self._can_connect}"
                for server in self._target_servers:
                    try:
                        addr = socket.gethostbyname(server)
                    except socket.gaierror as e:
                        self.__log(f"[{ts}][dns] Failed to resolve {server}: {e}")
                        continue
                    try:
                        udp_client.sendto(message.encode("utf-8"), (addr, 7171))
                        self.__log(f"[{ts}][update] Sent: {message} to {server} ({addr})")
                    except Exception as e:
                        self.__log(f"[{ts}][update] sendto error to {server} ({addr}): {e}")
            except Exception:
                self.__log(f"[{ts}][update] Unexpected error:\n{traceback.format_exc()}")
            time.sleep(60)


if __name__ == "__main__":
    while True:
        client_domain_name = os.environ.get("CLIENT_DOMAIN_NAME", "")
        server_domain_names = os.environ.get("SERVER_DOMAIN_NAME", "")

        ddns_client = UDPClient(client_domain_name, server_domain_names)
        threading.Thread(target=ddns_client.ping_server, daemon=True).start()
        threading.Thread(target=ddns_client.update_server, daemon=True).start()

        start = time.time()
        while True:
            time.sleep(1)
            if time.time() - start > 600:  # 10 minutes
                os.execv(sys.executable, ["python"] + sys.argv)
