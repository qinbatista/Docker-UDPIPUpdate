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
        self._connected_server = "-"
        self._connected_server_ip = "-"
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
        self._last_ip_rejection_summary = ""
        self._last_ip_source = "none"
        self._last_observed_public_ip = None
        self._last_upload_success_ip = None
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

    def _normalize_global_ipv4(self, ip_text):
        normalized_ip = self._normalize_ipv4(ip_text) if ip_text else None
        if normalized_ip and ipaddress.IPv4Address(normalized_ip).is_global:
            return normalized_ip
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
                self._last_ip_rejection_summary = ""
                self._last_ip_source = "fresh"
                return ip_value
            rejections.append(reason)
        self._last_ip_rejection_summary = ",".join(sorted(set(rejections))) if rejections else "lookup_failed"
        if self._last_good_public_ip:
            self._last_ip_source = "fallback"
            return self._last_good_public_ip
        self._last_ip_source = "none"
        return "0.0.0.0"

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
            if reachable != self._can_connect:
                self.__log(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}][ping] Connectivity status changed: {self._can_connect} -> {reachable}, target={connected_server}@{connected_server_ip}")
            self._can_connect = reachable
            self._connected_server = connected_server
            self._connected_server_ip = connected_server_ip
            time.sleep(self._ping_interval_seconds)

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

    def update_server(self):
        udp_client = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        udp_client.settimeout(5)
        while True:
            ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            try:
                raw_ip_value = self.get_public_ip()
                vpn_domain = self._vpn_domain_for_ip(raw_ip_value)
                connectivity_payload = str(self._can_connect)
                connectivity_text = f"{self._can_connect}({self._connected_server}@{self._connected_server_ip})" if self._can_connect == 1 else "0(none)"
                if vpn_domain and connectivity_payload == "0":
                    connectivity_payload = "or failed"
                    connectivity_text = f"{connectivity_text}->send:{connectivity_payload}"
                dns_ip, dns_status = self._resolve_domain_ipv4(self._my_domain)
                dns_global_ip = self._normalize_global_ipv4(dns_ip) if dns_status == "ok" else None
                ip_value = dns_global_ip if raw_ip_value == "0.0.0.0" and dns_global_ip else raw_ip_value
                ip_source = "dns_fallback" if ip_value != raw_ip_value else self._last_ip_source
                previous_ip = self._last_observed_public_ip if self._last_observed_public_ip else "-"
                ip_changed = ip_value != self._last_observed_public_ip
                self._last_observed_public_ip = ip_value
                dns_match = dns_global_ip is not None and ip_value == dns_global_ip
                should_send = True
                action = "send_update_periodic"
                if ip_value == "0.0.0.0":
                    should_send = False
                    action = "skip_invalid_ip"
                sent_servers = []
                dns_failed_servers = []
                send_failed_servers = []
                if should_send:
                    message = f"{self._my_domain},v4,{ip_value},{connectivity_payload}"
                    for server in self._target_servers:
                        try:
                            addr = socket.gethostbyname(server)
                        except socket.gaierror as error:
                            dns_failed_servers.append(f"{server}:{error}")
                            continue
                        try:
                            udp_client.sendto(message.encode("utf-8"), (addr, self._udp_port))
                            sent_servers.append(server)
                        except Exception as error:
                            send_failed_servers.append(f"{server}:{error}")
                    if sent_servers:
                        self._last_upload_success_ip = ip_value
                info_items = []
                if ip_value == "0.0.0.0":
                    info_items.append(f"reason={self._last_ip_rejection_summary}")
                if ip_source == "dns_fallback":
                    info_items.append(f"raw_ip={raw_ip_value}")
                if vpn_domain:
                    info_items.append(f"vpn={vpn_domain}")
                if dns_status != "ok":
                    info_items.append(f"dns_status={dns_status}")
                if dns_failed_servers:
                    info_items.append(f"dns_fail={';'.join(dns_failed_servers)}")
                if send_failed_servers:
                    info_items.append(f"send_fail={';'.join(send_failed_servers)}")
                info_text = " | ".join(info_items) if info_items else "ok"
                self.__log(f"[{ts}][update] ip={ip_value} changed={1 if ip_changed else 0} prev={previous_ip} source={ip_source} dns={dns_global_ip if dns_global_ip else '-'} dns_ok={1 if dns_match else 0} action={action} udp_port={self._udp_port} connectivity={connectivity_text} sent={len(sent_servers)}/{len(self._target_servers)} info={info_text}")
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
