#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import ipaddress
import os
import socket
import subprocess
import sys
import threading
import time
from datetime import datetime


class UDPClient:
    def __init__(self, client_domain_name, server_domain_names, log_file=None):
        self._my_domain = client_domain_name
        self._target_servers = [value.strip() for value in server_domain_names.split(",") if value.strip()] if server_domain_names else []
        if log_file is None:
            script_dir = os.path.dirname(os.path.abspath(__file__))
            log_file = os.path.join(script_dir, "udp_client.log")
        self._log_file = log_file
        self._can_connect = 0
        self._connected_server = "-"
        self._connected_server_ip = "-"
        self._max_log_size_bytes = 10 * 1024 * 1024
        self._log_cooldown = {}
        self._last_observed_public_ip = None
        self._last_upload_success_ip = None
        self._connect_fail_count = 0
        self._connect_fail_threshold = max(1, int(os.environ.get("CONNECTIVITY_FAIL_THRESHOLD", "3")))
        self._disconnect_start_time = None
        self._disconnect_window_seconds = max(1, int(os.environ.get("DISCONNECT_WINDOW_SECONDS", "300")))
        self._ping_interval_seconds = max(5, int(os.environ.get("PING_INTERVAL_SECONDS", "5")))
        update_interval_minutes = os.environ.get("UPDATE_INTERVAL_MINUTES")
        if update_interval_minutes is not None:
            try:
                update_interval_seconds = int(float(update_interval_minutes) * 60)
            except Exception:
                update_interval_seconds = 60
        else:
            update_interval_seconds = int(os.environ.get("UPDATE_INTERVAL_SECONDS", "60"))
        self._update_interval_seconds = max(60, update_interval_seconds)
        self._udp_port = int(os.environ.get("UDP_SERVER_PORT", "7171"))
        initial_dns_ip, initial_dns_status = self._get_dns_client_ip()
        self.__log(f"client_domain_name={client_domain_name}, server_domain_names={server_domain_names}, Initial DNS IP={initial_dns_ip}, dns_status={initial_dns_status}")

    def __log(self, message):
        with open(self._log_file, "a+") as file_handle:
            file_handle.write(message + "\n")
        if os.path.getsize(self._log_file) > self._max_log_size_bytes:
            os.remove(self._log_file)

    def _log_with_cooldown(self, key, message, cooldown_seconds):
        now = time.time()
        last_time = self._log_cooldown.get(key, 0)
        if now - last_time >= cooldown_seconds:
            self.__log(message)
            self._log_cooldown[key] = now

    def _normalize_ipv4(self, ip_text):
        try:
            return str(ipaddress.IPv4Address(ip_text.strip()))
        except Exception:
            return None

    def _normalize_global_ipv4(self, ip_text):
        normalized_ip = self._normalize_ipv4(ip_text) if ip_text else None
        if normalized_ip and ipaddress.IPv4Address(normalized_ip).is_global:
            return normalized_ip
        return None

    def ping_server(self):
        while True:
            reachable = 0
            connected_server = "-"
            connected_server_ip = "-"
            for server in self._target_servers:
                try:
                    server_ip = socket.gethostbyname(server)
                    process = subprocess.Popen(f"ping -c 1 {server_ip}", stdout=subprocess.PIPE, universal_newlines=True, shell=True)
                    process.wait()
                    if process.returncode == 0:
                        reachable = 1
                        connected_server = server
                        connected_server_ip = server_ip
                        break
                except Exception as error:
                    self._log_with_cooldown(f"ping-error-{server}", f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}][ping] Error pinging {server}: {error}", 600)
            stable_reachable = self._next_connectivity_state(reachable)
            if reachable == 1:
                stable_server = connected_server
                stable_server_ip = connected_server_ip
            elif stable_reachable == 1:
                stable_server = self._connected_server
                stable_server_ip = self._connected_server_ip
            else:
                stable_server = "-"
                stable_server_ip = "-"
            if stable_reachable != self._can_connect:
                before_state = "connected" if self._can_connect == 1 else "disconnected"
                after_state = "connected" if stable_reachable == 1 else "disconnected"
                self.__log(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}][ping] Connectivity status changed: {before_state} -> {after_state}, target={stable_server}@{stable_server_ip}, fail_count={self._connect_fail_count}/{self._connect_fail_threshold}")
            self._can_connect = stable_reachable
            self._connected_server = stable_server
            self._connected_server_ip = stable_server_ip
            time.sleep(self._ping_interval_seconds)

    def _next_connectivity_state(self, reachable):
        if reachable == 1:
            self._connect_fail_count = 0
            self._disconnect_start_time = None
            return 1
        self._connect_fail_count += 1
        if self._can_connect == 1 and self._connect_fail_count < self._connect_fail_threshold:
            self._disconnect_start_time = None
            return 1
        if self._disconnect_start_time is None:
            self._disconnect_start_time = time.time()
        return 0

    def _format_connectivity_text(self):
        if self._can_connect == 1:
            return f"connected({self._connected_server}@{self._connected_server_ip})"
        if self._disconnect_start_time is None:
            return f"disconnected(0/{self._disconnect_window_seconds})"
        elapsed_seconds = int(max(0, time.time() - self._disconnect_start_time))
        elapsed_seconds = min(elapsed_seconds, self._disconnect_window_seconds)
        return f"disconnected({elapsed_seconds}/{self._disconnect_window_seconds})"

    def _resolve_domain_ipv4(self, domain_name):
        if not domain_name:
            return "", "not_set"
        try:
            infos = socket.getaddrinfo(domain_name, None, socket.AF_INET)
            for info in infos:
                resolved_ip = info[4][0]
                if resolved_ip:
                    return resolved_ip, "ok"
        except Exception:
            return "", "fail"
        return "", "fail"

    def _get_dns_client_ip(self):
        dns_ip, dns_status = self._resolve_domain_ipv4(self._my_domain)
        normalized_dns_ip = self._normalize_global_ipv4(dns_ip) if dns_status == "ok" else None
        if normalized_dns_ip:
            return normalized_dns_ip, "ok"
        if dns_status == "ok":
            return "0.0.0.0", "non_global_dns_ip"
        return "0.0.0.0", dns_status

    def _format_update_log(self, client_ip, connectivity_text, send_status):
        normalized_client_ip = self._normalize_ipv4(client_ip) or client_ip
        merged_domain = f"{self._my_domain if self._my_domain else '-'}@{normalized_client_ip if normalized_client_ip else '-'}"
        base_log = f"[client={normalized_client_ip if normalized_client_ip else '-'}] [domain={merged_domain}] [connectivity={connectivity_text}]"
        if send_status == "success":
            return f"{base_log}||"
        return f"{base_log} [send={send_status}]||"

    def update_server(self):
        udp_client = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        udp_client.settimeout(5)
        while True:
            ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            try:
                connectivity_payload = str(self._can_connect)
                connectivity_text = self._format_connectivity_text()
                ip_value, dns_status = self._get_dns_client_ip()
                self._last_observed_public_ip = ip_value
                should_send = True
                if ip_value == "0.0.0.0":
                    should_send = False
                sent_servers = []
                if should_send:
                    message = f"{self._my_domain},v4,{ip_value},{connectivity_payload}"
                    for server in self._target_servers:
                        try:
                            addr = socket.gethostbyname(server)
                        except socket.gaierror:
                            continue
                        try:
                            udp_client.sendto(message.encode("utf-8"), (addr, self._udp_port))
                            sent_servers.append(server)
                        except Exception:
                            pass
                    if sent_servers:
                        self._last_upload_success_ip = ip_value
                total_servers = len(self._target_servers)
                failed_servers = total_servers - len(sent_servers)
                if should_send:
                    if total_servers == 0:
                        send_status = "failed 0/0"
                    elif failed_servers == 0:
                        send_status = "success"
                    else:
                        send_status = f"{failed_servers}/{total_servers} failed"
                else:
                    send_status = f"skipped:{dns_status}"
                self.__log(f"[{ts}] {self._format_update_log(ip_value, connectivity_text, send_status)}")
            except Exception as error:
                self.__log(f"[{ts}][update] cycle_error={error}")
            time.sleep(self._update_interval_seconds)


if __name__ == "__main__":
    while True:
        client_domain_name = (os.environ.get("CLIENT_DOMAIN_NAME_OVERRIDE") or os.environ.get("CLIENT_DOMAIN_NAME", "")).strip()
        server_domain_names = (os.environ.get("SERVER_DOMAIN_NAME_OVERRIDE") or os.environ.get("SERVER_DOMAIN_NAME", "")).strip()
        ddns_client = UDPClient(client_domain_name, server_domain_names)
        threading.Thread(target=ddns_client.ping_server, daemon=True).start()
        threading.Thread(target=ddns_client.update_server, daemon=True).start()
        start = time.time()
        while True:
            time.sleep(1)
            if time.time() - start > 600:
                os.execv(sys.executable, ["python"] + sys.argv)
