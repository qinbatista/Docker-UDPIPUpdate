#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os, time, threading, subprocess, pytz, requests
from socket import socket, AF_INET, SOCK_DGRAM, AF_INET6
from datetime import datetime
from LightSailManager import LightSail


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
        self.__light_sail = LightSail()

    def log(self, msg):
        ts = datetime.now(self.timezone).strftime("%Y-%m-%d %H:%M:%S")
        formatted_msg = f"[{ts}] {msg}"

        # Print log message to console
        print(formatted_msg)

        with open(self.log_file, "a+") as f:
            f.write(formatted_msg + "\n")

        # Ensure log file does not exceed 10MB
        if os.path.getsize(self.log_file) > 10 * 1024 * 1024:
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
            self.__light_sail.replace_ip("ap-northeast-1", "Debian-1")
        except Exception as e:
            self.log(f"Error replacing instance IP: {e}")

    def update_client_ip_via_lambda(self, client_ip, connectivity, domain_name=None):
        try:
            payload = {"client_ip": client_ip, "connectivity": connectivity, "domain_name": domain_name}
            response = requests.post(self.lambda_url, json=payload, timeout=10)

            try:
                response_json = response.json()
                if response_json.get("message") != "DNS record updated successfully!":
                    self.log(f"Lambda update response: {response.text}")
            except ValueError:
                self.log(f"Lambda update response (non-JSON): {response.text}")

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
        # Dictionary to store the start time of continuous "0" connectivity per domain
        self.connectivity_0_start_time = {}
        # Dictionary to track the last logged state per sender IP and domain
        self.last_logged_states = {}

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

                if len(msg) >= 4:
                    domain_name = msg[0]
                    protocol = msg[1].lower()  # e.g., "v4" or "v6"
                    reported_ip = msg[2]
                    connectivity = msg[3]

                    log_key = f"{sender_ip}:{domain_name}"
                    current_state = (reported_ip, connectivity)

                    # Log only if the state (reported_ip + connectivity) has changed
                    if log_key not in self.last_logged_states or self.last_logged_states[log_key] != current_state:
                        log_msg = f"{sender_ip}:{sender_port} -> {domain_name}, {protocol}, {reported_ip}, {connectivity}"
                        self.log(log_msg)
                        self.last_logged_states[log_key] = current_state

                    match protocol:
                        case "v4":
                            self.update_client_ip_via_lambda(sender_ip, connectivity, domain_name=domain_name)
                            if connectivity == "0":
                                if domain_name not in self.connectivity_0_start_time:
                                    self.connectivity_0_start_time[domain_name] = time.time()
                                else:
                                    elapsed = time.time() - self.connectivity_0_start_time[domain_name]
                                    if elapsed >= 300:
                                        self.replace_instance_ip()
                                        self.connectivity_0_start_time[domain_name] = time.time()
                            else:
                                self.connectivity_0_start_time.pop(domain_name, None)
                        case "v6":
                            pass  # No need to log or handle
                        case _:
                            unknown_log_msg = f"Unknown protocol: {protocol}"
                            if log_key not in self.last_logged_states or self.last_logged_states[log_key] != unknown_log_msg:
                                self.log(unknown_log_msg)
                                self.last_logged_states[log_key] = unknown_log_msg
                else:
                    invalid_log_msg = f"Invalid message format: {msg}"
                    if log_key not in self.last_logged_states or self.last_logged_states[log_key] != invalid_log_msg:
                        self.log(invalid_log_msg)
                        self.last_logged_states[log_key] = invalid_log_msg

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
                # On first run (initial) or when the IP changes:
                if last_ip is None or current_ip != last_ip:
                    if last_ip is None:
                        self.log(f"Initial public IP: {current_ip}")
                    else:
                        self.log(f"Public IP changed from {last_ip} to {current_ip}.")
                    # Update Lambda using domain from SERVER_DOMAIN_NAME env var
                    self.update_client_ip_via_lambda(current_ip, "1", domain_name=os.environ.get("SERVER_DOMAIN_NAME", ""))
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
