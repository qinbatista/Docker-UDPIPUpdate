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
        self.__log(f"client_domain_name={client_domain_name}, server_domain_names={server_domain_names}, Initial IP={self.get_public_ip()}")

    def __log(self, message):
        with open(self._log_file, "a+") as file_handle:
            file_handle.write(message + "\n")
        if os.path.getsize(self._log_file) > self._max_log_size_bytes:
            os.remove(self._log_file)

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
                else:
                    self.__log(f"[IP lookup] {url} returned invalid IPv4: {response.text.strip()}")
            except Exception as error:
                self.__log(f"[IP lookup] {url} failed: {error}")
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
            except Exception as error:
                self.__log(f"[geoip] {url} failed: {error}")
        self._geoip_country_cache[ip_value] = {"country": "", "timestamp": now}
        return ""

    def _is_allowed_public_ip(self, ip_value):
        normalized_ip = self._normalize_ipv4(ip_value)
        if not normalized_ip:
            self.__log(f"[IP filter] Reject invalid IPv4: {ip_value}")
            return False
        if not ipaddress.IPv4Address(normalized_ip).is_global:
            self.__log(f"[IP filter] Reject non-global IPv4: {normalized_ip}")
            return False
        vpn_domain = self._vpn_domain_for_ip(normalized_ip)
        if vpn_domain:
            self.__log(f"[IP filter] Reject VPN IPv4: {normalized_ip} ({vpn_domain})")
            return False
        country_code = self._country_code_for_ip(normalized_ip)
        if country_code != self._accepted_country_code:
            if country_code:
                self.__log(f"[IP filter] Reject non-{self._accepted_country_code} IPv4: {normalized_ip} ({country_code})")
            else:
                self.__log(f"[IP filter] Reject IPv4 with unknown country: {normalized_ip}")
            return False
        return True

    def get_public_ip(self):
        candidates = self._lookup_public_ip_candidates()
        for ip_value, _ in Counter(candidates).most_common():
            if self._is_allowed_public_ip(ip_value):
                self._last_good_public_ip = ip_value
                return ip_value
        if self._last_good_public_ip:
            self.__log(f"[IP lookup] No valid fresh IP, fallback to last good IP: {self._last_good_public_ip}")
            return self._last_good_public_ip
        if not candidates:
            self.__log("[IP lookup] All services failed, returning 0.0.0.0")
        else:
            self.__log(f"[IP lookup] All candidates rejected: {sorted(set(candidates))}")
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
                    self.__log(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}][ping] Error pinging {server}: {error}")
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
                self.__log(f"[vpn-resolve] Failed to resolve {domain}: {error}")
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
                if ip_value == "0.0.0.0":
                    self.__log(f"[{ts}][update] Skip sending update: no valid public CN IPv4 available.")
                    time.sleep(60)
                    continue
                vpn_domain = self._vpn_domain_for_ip(ip_value)
                connectivity = str(self._can_connect)
                if vpn_domain and connectivity == "0":
                    connectivity = "or failed"
                    self.__log(f"[{ts}][update] Local traffic routed via {vpn_domain} ({ip_value}); reporting connectivity as '{connectivity}' to avoid VPN false-alarm.")
                message = f"{self._my_domain},v4,{ip_value},{connectivity}"
                for server in self._target_servers:
                    try:
                        addr = socket.gethostbyname(server)
                    except socket.gaierror as error:
                        self.__log(f"[{ts}][dns] Failed to resolve {server}: {error}")
                        continue
                    try:
                        udp_client.sendto(message.encode("utf-8"), (addr, 7171))
                        self.__log(f"[{ts}][update] Sent: {message} to {server} ({addr})")
                    except Exception as error:
                        self.__log(f"[{ts}][update] sendto error to {server} ({addr}): {error}")
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
            if time.time() - start > 600:
                os.execv(sys.executable, ["python"] + sys.argv)
