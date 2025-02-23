#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os, time, threading, subprocess, pytz, requests
from socket import socket, AF_INET, SOCK_DGRAM, AF_INET6
from datetime import datetime


class UDPServer:
    def __init__(self, port=7171, log_file=None):
        self.port = port
        self.server_socket = socket(AF_INET, SOCK_DGRAM)
        if not log_file:
            script_dir = os.path.dirname(os.path.abspath(__file__))
            log_file = os.path.join(script_dir, "udp_server.log")
        self.log_file = log_file
        self.timezone = pytz.timezone("Asia/Shanghai")
        self.lambda_url = os.environ.get("IPV4_DOMAIN_UPDATE_LAMBDA", "")
        if not self.lambda_url:
            self.log("IPV4_DOMAIN_UPDATE_LAMBDA not set.")
        self.running = True
        self._ipv4_services = ["https://checkip.amazonaws.com", "https://api.ipify.org", "https://ifconfig.me/ip", "https://ipinfo.io/ip"]
        self._ipv6_services = ["https://api6.ipify.org", "https://ifconfig.co/ip", "https://ipv6.icanhazip.com", "https://ip6.seeip.org"]
        self.log(f"Initial IPv4={self.get_ipv4()}, Initial IPv6={self.get_ipv6()}")

    def log(self, msg):
        ts = datetime.now(self.timezone).strftime("%Y-%m-%d %H:%M:%S")
        with open(self.log_file, "a+") as f:
            f.write(f"[{ts}] {msg}\n")
        if os.path.getsize(self.log_file) > 1024 * 128:
            os.remove(self.log_file)

    def _request_ip(self, url):
        try:
            r = requests.get(url, timeout=5)
            r.raise_for_status()
            ip = r.text.strip()
            if ip:
                return ip
        except Exception as e:
            self.log(f"[IP lookup] {url} failed: {e}")
        return None

    def _get_public_ip(self, services):
        for url in services:
            ip = self._request_ip(url)
            if ip:
                return ip
        return None

    def get_public_ipv4(self):
        return self._get_public_ip(self._ipv4_services)

    def get_public_ipv6(self):
        return self._get_public_ip(self._ipv6_services)

    def get_local_ipv4(self):
        try:
            s = socket(AF_INET, SOCK_DGRAM)
            s.connect(("8.8.8.8", 80))
            ip = s.getsockname()[0]
            s.close()
            return ip
        except Exception as e:
            self.log(f"[local_ipv4] Error: {e}")
        return "0.0.0.0"

    def get_local_ipv6(self):
        try:
            s = socket(AF_INET6, SOCK_DGRAM)
            s.connect(("2001:4860:4860::8888", 80))
            ip = s.getsockname()[0]
            s.close()
            return ip
        except Exception as e:
            self.log(f"[local_ipv6] Error: {e}")
        return "::"

    def get_ipv4(self):
        return self.get_public_ipv4() or self.get_local_ipv4()

    def get_ipv6(self):
        return self.get_public_ipv6() or self.get_local_ipv6()

    def replace_instance_ip(self):
        self.log("Ping failed. Replacing instance IP...")
        try:
            subprocess.run("python replace_ip.py", shell=True, check=True)
            self.log("Replacement script executed successfully.")
        except Exception as e:
            self.log(f"Error replacing instance IP: {e}")

    def update_client_ip_via_lambda(self, client_ip, connectivity, domain_name=None):
        try:
            payload = {"client_ip": client_ip, "connectivity": connectivity, "domain_name": domain_name}
            response = requests.post(self.lambda_url, json=payload, timeout=10)
            self.log(f"Lambda update response: {response.text}")
        except Exception as e:
            self.log(f"Error calling lambda: {e}")

    def restart_udp_server(self):
        self.log("Restarting UDP server...")
        self.running = False
        try:
            self.server_socket.close()
        except Exception as e:
            self.log(f"Error closing socket: {e}")
        time.sleep(2)
        self.server_socket = socket(AF_INET, SOCK_DGRAM)
        self.running = True
        self.start_receive_thread()
        self.log("UDP server restarted.")

    def receive_loop(self):
        try:
            self.server_socket.bind(("", self.port))
            self.log(f"UDP server started on port {self.port}.")
        except Exception as e:
            self.log(f"Failed to bind on port {self.port}: {e}")
            return
        while self.running:
            try:
                data, addr = self.server_socket.recvfrom(1024)
                sender_ip, sender_port = addr
                msg = data.decode("utf-8").strip().split(",")
                self.log(f"Received from {sender_ip}:{sender_port} -> {msg}")
                # Expecting message format: domain, protocol, reported_ip, connectivity
                if len(msg) >= 4:
                    domain_name = msg[0]
                    protocol = msg[1]  # e.g., "v4" or "v6"
                    reported_ip = msg[2]
                    connectivity = msg[3]
                    self.update_client_ip_via_lambda(reported_ip, connectivity, domain_name=domain_name)
                    if connectivity == "0":
                        self.replace_instance_ip()
                else:
                    self.log(f"Invalid message format: {msg}")
            except Exception as e:
                self.log(f"Error handling message: {e}")
                time.sleep(1)

    def start_receive_thread(self):
        t = threading.Thread(target=self.receive_loop, name="UDPServerThread")
        t.daemon = True
        t.start()
        self.log("UDP server receive thread started.")
        return t

    def ip_monitor_loop(self):
        last_ip = None
        while True:
            current_ip = self.get_ipv4()
            if current_ip:
                if not last_ip:
                    last_ip = current_ip
                    self.log(f"Initial public IP: {current_ip}")
                elif current_ip != last_ip:
                    self.log(f"Public IP changed from {last_ip} to {current_ip}.")
                    # For local updates, use domain name from SERVERDOMAIN.
                    self.update_client_ip_via_lambda(current_ip, "1", domain_name=os.environ.get("SERVER_DOMAIN_NAME", "127.0.0.1"))
                    self.restart_udp_server()
                    last_ip = current_ip
            time.sleep(60)

    def start_ip_monitor_thread(self):
        t = threading.Thread(target=self.ip_monitor_loop, name="IPMonitorThread")
        t.daemon = True
        t.start()
        self.log("IP monitor thread started.")
        return t

    def start(self):
        self.start_receive_thread()
        self.start_ip_monitor_thread()


if __name__ == "__main__":
    server = UDPServer()
    server.start()
    while True:
        time.sleep(1)
