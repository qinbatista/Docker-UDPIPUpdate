#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import threading
import time
import ipaddress
from datetime import datetime
from socket import AF_INET, AF_INET6, SOCK_DGRAM, gethostbyname, socket

import pytz
import requests

from LightSailManager import LightSail


class UDPServer:
    def __init__(self, port=7171, log_file=None):
        self.port = port
        self.server_socket = socket(AF_INET, SOCK_DGRAM)
        if not log_file:
            script_dir = os.path.dirname(os.path.abspath(__file__))
            log_file = os.path.join(script_dir, "udp_server.log")
        self.log_file = log_file
        self._max_log_size_bytes = 20 * 1024 * 1024
        self._log_cooldown = {}
        self._log_state = {}
        self._receive_log_interval_seconds = max(1, int(os.environ.get("RECEIVE_LOG_INTERVAL_SECONDS", "5")))
        self.timezone = pytz.timezone("Asia/Shanghai")
        self.lambda_url = os.environ.get("IPV4_DOMAIN_UPDATE_LAMBDA", "")
        if not self.lambda_url:
            self.log("IPV4_DOMAIN_UPDATE_LAMBDA not set.")
        self.running = True
        self._ipv4_services = ["https://checkip.amazonaws.com", "https://api.ipify.org", "https://ifconfig.me/ip", "https://ipinfo.io/ip"]
        self._ipv6_services = ["https://api6.ipify.org", "https://ifconfig.co/ip", "https://ipv6.icanhazip.com", "https://ip6.seeip.org"]
        self.log(f"Initial IPv4={self.get_ipv4()}, Initial IPv6={self.get_ipv6()}")
        self.__light_sail = LightSail()
        self.excluded_domains = ["la.qinyupeng.com", "timov4.qinyupeng.com"]
        self.excluded_ips_cache = {"ips": set(), "last_updated": 0}

    def log(self, msg):
        ts = datetime.now(self.timezone).strftime("%Y-%m-%d %H:%M:%S")
        formatted_msg = f"[{ts}] {msg}"

        # Print log message to console
        print(formatted_msg)

        with open(self.log_file, "a+") as f:
            f.write(formatted_msg + "\n")

        # Ensure log file does not exceed 20MB
        if os.path.getsize(self.log_file) > self._max_log_size_bytes:
            os.remove(self.log_file)

    def _log_with_cooldown(self, key, msg, cooldown_seconds):
        now = time.time()
        last_time = self._log_cooldown.get(key, 0)
        if now - last_time >= cooldown_seconds:
            self.log(msg)
            self._log_cooldown[key] = now

    def _log_on_change(self, key, msg):
        if self._log_state.get(key) != msg:
            self.log(msg)
            self._log_state[key] = msg

    def _log_periodic_state(self, key, msg, interval_seconds):
        now = time.time()
        if self._log_state.get(key) != msg:
            self.log(msg)
            self._log_state[key] = msg
            self._log_cooldown[key] = now
            return
        if now - self._log_cooldown.get(key, 0) >= interval_seconds:
            self.log(msg)
            self._log_cooldown[key] = now

    def _normalize_global_ipv4(self, ip_value):
        try:
            normalized_ip = str(ipaddress.IPv4Address(ip_value.strip()))
            if ipaddress.IPv4Address(normalized_ip).is_global:
                return normalized_ip
        except Exception:
            pass
        return None

    def _request_ip(self, url):
        try:
            r = requests.get(url, timeout=5)
            r.raise_for_status()
            ip = r.text.strip()
            if ip:
                return ip, None
            return None, "empty_response"
        except Exception as e:
            return None, str(e)

    def _get_public_ip(self, services, label):
        errors = []
        for url in services:
            ip, error = self._request_ip(url)
            if ip:
                if errors:
                    self._log_on_change(f"{label}-lookup-state", f"[IP lookup] {label} recovered via {url}")
                return ip
            if error:
                errors.append(f"{url}:{error}")
        if errors:
            self._log_with_cooldown(f"{label}-lookup-failed", f"[IP lookup] {label} unavailable ({len(errors)}/{len(services)} failed), first={errors[0]}", 600)
        return None

    def get_public_ipv4(self):
        return self._get_public_ip(self._ipv4_services, "IPv4")

    def get_public_ipv6(self):
        return self._get_public_ip(self._ipv6_services, "IPv6")

    def get_local_ipv4(self):
        try:
            s = socket(AF_INET, SOCK_DGRAM)
            s.connect(("8.8.8.8", 80))
            ip = s.getsockname()[0]
            s.close()
            return ip
        except Exception as e:
            self._log_with_cooldown("local-ipv4-failed", f"[local_ipv4] unavailable: {e}", 600)
        return "0.0.0.0"

    def get_local_ipv6(self):
        try:
            s = socket(AF_INET6, SOCK_DGRAM)
            s.connect(("2001:4860:4860::8888", 80))
            ip = s.getsockname()[0]
            s.close()
            return ip
        except Exception as e:
            self._log_with_cooldown("local-ipv6-failed", f"[local_ipv6] unavailable: {e}", 600)
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

    def _get_excluded_ips(self):
        now = time.time()
        # Update cache every 5 minutes (300 seconds)
        if now - self.excluded_ips_cache["last_updated"] > 300:
            previous_ips = set(self.excluded_ips_cache["ips"])
            current_ips = set()
            for domain in self.excluded_domains:
                try:
                    ip = gethostbyname(domain)
                    current_ips.add(ip)
                except Exception as e:
                    self._log_with_cooldown(f"excluded-resolve-{domain}", f"Error resolving excluded domain {domain}: {e}", 600)
            self.excluded_ips_cache["ips"] = current_ips
            self.excluded_ips_cache["last_updated"] = now
            if current_ips != previous_ips:
                self.log(f"Updated excluded IPs: {current_ips}")
        return self.excluded_ips_cache["ips"]

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
        self.last_logged_times = {}
        self.last_dns_update_states = {}

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
                log_key = f"{sender_ip}:invalid"

                if len(msg) >= 4:
                    domain_name = msg[0]
                    protocol = msg[1].lower()  # e.g., "v4" or "v6"
                    reported_ip = msg[2]
                    connectivity = msg[3]

                    log_key = f"{sender_ip}:{domain_name}"
                    current_state = (reported_ip, connectivity)
                    now = time.time()

                    # Log immediately on state change, otherwise at most once per receive interval.
                    if log_key not in self.last_logged_states or self.last_logged_states[log_key] != current_state or now - self.last_logged_times.get(log_key, 0) >= self._receive_log_interval_seconds:
                        log_msg = f"client={sender_ip} domain={domain_name} protocol={protocol} reported_ip={reported_ip} connectivity={connectivity}"
                        self.log(log_msg)
                        self.last_logged_states[log_key] = current_state
                        self.last_logged_times[log_key] = now

                    match protocol:
                        case "v4":
                            update_ip = self._normalize_global_ipv4(reported_ip) or self._normalize_global_ipv4(sender_ip)
                            decision_key = f"dns-update:{sender_ip}:{domain_name}"
                            if not update_ip:
                                self._log_periodic_state(decision_key, f"dns_update domain={domain_name} action=not_updated reason=invalid_non_global_ip sender_ip={sender_ip} reported_ip={reported_ip}", self._receive_log_interval_seconds)
                                self._log_with_cooldown(f"invalid-update-ip-{domain_name}", f"Skip DNS update for {domain_name}: sender_ip={sender_ip}, reported_ip={reported_ip} not global IPv4", 60)
                                continue
                            excluded_ips = self._get_excluded_ips()
                            if sender_ip in excluded_ips or update_ip in excluded_ips:
                                self._log_periodic_state(decision_key, f"dns_update domain={domain_name} action=not_updated reason=excluded_ip sender_ip={sender_ip} update_ip={update_ip}", self._receive_log_interval_seconds)
                                log_msg = f"Skipping DNS update for excluded IP: sender={sender_ip}, update_ip={update_ip} ({domain_name})"
                                if log_key not in self.last_logged_states or self.last_logged_states[log_key] != "SKIPPED":
                                    self.log(log_msg)
                                    self.last_logged_states[log_key] = "SKIPPED"
                                continue

                            dns_update_key = f"{domain_name}:v4"
                            dns_update_state = (update_ip, connectivity)
                            if self.last_dns_update_states.get(dns_update_key) != dns_update_state:
                                self.update_client_ip_via_lambda(update_ip, connectivity, domain_name=domain_name)
                                self.last_dns_update_states[dns_update_key] = dns_update_state
                                self._log_periodic_state(decision_key, f"dns_update domain={domain_name} action=updated reason=state_changed update_ip={update_ip} connectivity={connectivity}", self._receive_log_interval_seconds)
                            else:
                                self._log_periodic_state(decision_key, f"dns_update domain={domain_name} action=not_updated reason=same_state update_ip={update_ip} connectivity={connectivity}", self._receive_log_interval_seconds)
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
                    invalid_log_msg = f"Invalid message format from {sender_ip}:{sender_port}: {msg}"
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
