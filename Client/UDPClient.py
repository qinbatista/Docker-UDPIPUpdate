#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import ipaddress
import os
import random
import socket
import subprocess
import sys
import threading
import time
import traceback
from collections import Counter
from datetime import datetime

import requests


class UDPClient:
    def __init__(self, client_domain_name, server_domain_names, log_file=None):
        self._my_domain = client_domain_name
        self._target_servers = [value.strip() for value in server_domain_names.split(",") if value.strip()] if server_domain_names else []
        if log_file is None:
            script_dir = os.path.dirname(os.path.abspath(__file__))
            log_file = os.path.join(script_dir, "udp_client.log")
        self._log_file = log_file
        self._can_connect = 0
        self._ipv4_services = ["https://checkip.amazonaws.com", "https://api.ipify.org", "https://ifconfig.me/ip", "https://ipinfo.io/ip"]
        self._geoip_country_services = ["https://ipinfo.io/{ip}/country", "https://ipapi.co/{ip}/country/"]
        self._accepted_country_code = "CN"
        self._geoip_country_cache = {}
        self._geoip_country_cache_ttl = 1800
        self._vpn_domains = ["timov4.qinyupeng.com", "la.qinyupeng.com"]
        self._vpn_ip_map = {}
        self._vpn_ips_last_refresh = 0
        self._vpn_refresh_interval = 300
        self._last_good_public_ip = None
        self._max_log_size_bytes = 10 * 1024 * 1024
        self._log_cooldown = {}
        self._dns_failed_servers = set()
        self._send_failed_servers = set()
        self._last_rejection_summary = ""
        self._last_sent_state = None
        self._last_observed_public_ip = None
        self.__log(f"client_domain_name={client_domain_name}, server_domain_names={server_domain_names}, Initial IP={self.get_public_ip()}")

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

    def _lookup_public_ip_candidates(self):
        candidates = []
        services = random.sample(self._ipv4_services, len(self._ipv4_services))
        for url in services:
            try:
                response = requests.get(url, timeout=5)
                response.raise_for_status()
                candidate = self._normalize_ipv4(response.text)
                if candidate:
                    candidates.append(candidate)
            except Exception:
                pass
        return candidates

    def _country_code_for_ip(self, ip_value):
        now = time.time()
        cached = self._geoip_country_cache.get(ip_value)
        if cached and now - cached["timestamp"] < self._geoip_country_cache_ttl:
            return cached["country"]
        for url_template in self._geoip_country_services:
            url = url_template.format(ip=ip_value)
            try:
                response = requests.get(url, timeout=5)
                response.raise_for_status()
                country_code = response.text.strip().upper()
                if len(country_code) == 2 and country_code.isalpha():
                    self._geoip_country_cache[ip_value] = {"country": country_code, "timestamp": now}
                    return country_code
            except Exception:
                pass
        self._geoip_country_cache[ip_value] = {"country": "", "timestamp": now}
        return ""

    def _is_allowed_public_ip(self, ip_value):
        normalized_ip = self._normalize_ipv4(ip_value)
        if not normalized_ip:
            return False, f"{ip_value}=invalid"
        if not ipaddress.IPv4Address(normalized_ip).is_global:
            return False, f"{normalized_ip}=non-global"
        vpn_domain = self._vpn_domain_for_ip(normalized_ip)
        if vpn_domain:
            return False, f"{normalized_ip}=vpn({vpn_domain})"
        country_code = self._country_code_for_ip(normalized_ip)
        if country_code != self._accepted_country_code:
            if country_code:
                return False, f"{normalized_ip}=country({country_code})"
            return False, f"{normalized_ip}=country(unknown)"
        return True, ""

    def get_public_ip(self):
        candidates = self._lookup_public_ip_candidates()
        rejections = []
        for ip_value, _ in Counter(candidates).most_common():
            allowed, reason = self._is_allowed_public_ip(ip_value)
            if allowed:
                self._last_good_public_ip = ip_value
                self._last_rejection_summary = ""
                return ip_value
            rejections.append(reason)
        rejection_summary = ",".join(sorted(set(rejections))) if rejections else ""
        if self._last_good_public_ip:
            if rejection_summary and rejection_summary != self._last_rejection_summary:
                self.__log(f"[IP lookup] Using last good IP due to candidate rejection: {rejection_summary}")
                self._last_rejection_summary = rejection_summary
            self._log_with_cooldown("ip-fallback", f"[IP lookup] Fallback to last good IP: {self._last_good_public_ip}", 600)
            return self._last_good_public_ip
        if not candidates:
            self._log_with_cooldown("no-ip-candidates", "[IP lookup] No IPv4 candidates from lookup services.", 600)
        else:
            if rejection_summary != self._last_rejection_summary:
                self.__log(f"[IP lookup] No allowed IPv4 candidate: {rejection_summary}")
                self._last_rejection_summary = rejection_summary
            self._log_with_cooldown("no-allowed-ip", "[IP lookup] No valid public CN IPv4 available.", 600)
        return "0.0.0.0"

    def ping_server(self):
        while True:
            reachable = 0
            for server in self._target_servers:
                try:
                    process = subprocess.Popen(f"ping -c 1 {server}", stdout=subprocess.PIPE, universal_newlines=True, shell=True)
                    process.wait()
                    if process.returncode == 0:
                        reachable = 1
                        break
                except Exception as error:
                    self._log_with_cooldown(f"ping-error-{server}", f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}][ping] Error pinging {server}: {error}", 600)
            if reachable != self._can_connect:
                self.__log(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}][ping] Connectivity status changed: {self._can_connect} -> {reachable}")
            self._can_connect = reachable
            time.sleep(60)

    def _refresh_vpn_ip_cache(self, force=False):
        now = time.time()
        if not force and self._vpn_ips_last_refresh and now - self._vpn_ips_last_refresh < self._vpn_refresh_interval:
            return
        new_map = {}
        for domain in self._vpn_domains:
            try:
                infos = socket.getaddrinfo(domain, None, socket.AF_INET)
                for info in infos:
                    new_map[info[4][0]] = domain
            except Exception as error:
                self._log_with_cooldown(f"vpn-resolve-{domain}", f"[vpn-resolve] Failed to resolve {domain}: {error}", 1800)
        if new_map:
            self._vpn_ip_map = new_map
        self._vpn_ips_last_refresh = now

    def _vpn_domain_for_ip(self, ip_value):
        if not ip_value or ip_value == "0.0.0.0":
            return None
        self._refresh_vpn_ip_cache()
        return self._vpn_ip_map.get(ip_value)

    def update_server(self):
        udp_client = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        udp_client.settimeout(5)
        while True:
            ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            try:
                ip_value = self.get_public_ip()
                if ip_value != self._last_observed_public_ip:
                    if self._last_observed_public_ip and ip_value != "0.0.0.0":
                        self.__log(f"[{ts}][ip] Public IPv4 changed: {self._last_observed_public_ip} -> {ip_value}")
                    elif ip_value != "0.0.0.0":
                        self.__log(f"[{ts}][ip] Current public CN IPv4: {ip_value}")
                    else:
                        self.__log(f"[{ts}][ip] Valid public CN IPv4 unavailable.")
                    self._last_observed_public_ip = ip_value
                if ip_value == "0.0.0.0":
                    self._log_with_cooldown("update-skip-no-valid-ip", f"[{ts}][update] Skip sending update: no valid public CN IPv4 available.", 600)
                    time.sleep(60)
                    continue
                vpn_domain = self._vpn_domain_for_ip(ip_value)
                connectivity = str(self._can_connect)
                if vpn_domain and connectivity == "0":
                    connectivity = "or failed"
                    self._log_with_cooldown("vpn-route-connectivity", f"[{ts}][update] Local traffic routed via {vpn_domain} ({ip_value}); reporting connectivity as '{connectivity}' to avoid VPN false-alarm.", 600)
                message = f"{self._my_domain},v4,{ip_value},{connectivity}"
                sent_servers = []
                for server in self._target_servers:
                    try:
                        addr = socket.gethostbyname(server)
                    except socket.gaierror as error:
                        if server not in self._dns_failed_servers:
                            self.__log(f"[{ts}][dns] Resolve failed for {server}, suppressing repeats until recovery: {error}")
                            self._dns_failed_servers.add(server)
                        continue
                    if server in self._dns_failed_servers:
                        self.__log(f"[{ts}][dns] Resolve recovered for {server}: {addr}")
                        self._dns_failed_servers.remove(server)
                    try:
                        udp_client.sendto(message.encode("utf-8"), (addr, 7171))
                        sent_servers.append(server)
                        if server in self._send_failed_servers:
                            self.__log(f"[{ts}][update] Send recovered for {server} ({addr})")
                            self._send_failed_servers.remove(server)
                    except Exception as error:
                        if server not in self._send_failed_servers:
                            self.__log(f"[{ts}][update] Send failed for {server} ({addr}), suppressing repeats until recovery: {error}")
                            self._send_failed_servers.add(server)
                if sent_servers:
                    state = (ip_value, connectivity)
                    if state != self._last_sent_state:
                        self.__log(f"[{ts}][update] Sent valid IP update: ip={ip_value}, connectivity={connectivity}, targets={len(sent_servers)}")
                        self._last_sent_state = state
                else:
                    self._log_with_cooldown("update-no-success", f"[{ts}][update] No server accepted update packet.", 600)
            except Exception:
                self._log_with_cooldown("update-unexpected-error", f"[{ts}][update] Unexpected error:\n{traceback.format_exc()}", 300)
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
            if time.time() - start > 600:
                os.execv(sys.executable, ["python"] + sys.argv)
