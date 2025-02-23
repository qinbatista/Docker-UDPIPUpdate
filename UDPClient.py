#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os, time, requests, threading, subprocess
from socket import socket, AF_INET, SOCK_DGRAM, AF_INET6
from datetime import datetime


class UDPClient:
    def __init__(self, client_domain_name, server_domain_name, log_file=None):
        self._my_domain = client_domain_name
        self._target_server = server_domain_name
        # Place log file in the current script folder if not provided.
        if log_file is None:
            script_dir = os.path.dirname(os.path.abspath(__file__))
            log_file = os.path.join(script_dir, "udp_client.log")
        self._log_file = log_file
        self._can_connect = 0

        # Lists of services to get public IPs
        self._ipv4_services = ["https://checkip.amazonaws.com", "https://api.ipify.org", "https://ifconfig.me/ip", "https://ipinfo.io/ip"]
        self._ipv6_services = ["https://api6.ipify.org", "https://ifconfig.co/ip", "https://ipv6.icanhazip.com", "https://ip6.seeip.org"]

        self.__log(f"client_domain_name={client_domain_name}, server_domain_name={server_domain_name}")
        self.__log(f"Initial IPv4={self.get_ipv4()}, Initial IPv6={self.get_ipv6()}")

    def __log(self, message):
        with open(self._log_file, "a+") as f:
            f.write(message + "\n")
        if os.path.getsize(self._log_file) > 1024 * 128:
            os.remove(self._log_file)

    def _request_ip(self, url):
        try:
            r = requests.get(url, timeout=5)
            r.raise_for_status()
            ip = r.text.strip()
            if ip:
                return ip
        except Exception as e:
            self.__log(f"[IP lookup] {url} failed: {e}")
        return None

    def get_public_ipv4(self):
        for url in self._ipv4_services:
            ip = self._request_ip(url)
            if ip:
                return ip
        return None

    def get_public_ipv6(self):
        for url in self._ipv6_services:
            ip = self._request_ip(url)
            if ip:
                return ip
        return None

    def get_local_ipv4(self):
        try:
            s = socket(AF_INET, SOCK_DGRAM)
            s.connect(("8.8.8.8", 80))
            ip = s.getsockname()[0]
            s.close()
            return ip
        except Exception as e:
            self.__log(f"[local_ipv4] Error: {e}")
        return "0.0.0.0"

    def get_local_ipv6(self):
        try:
            s = socket(AF_INET6, SOCK_DGRAM)
            s.connect(("2001:4860:4860::8888", 80))
            ip = s.getsockname()[0]
            s.close()
            return ip
        except Exception as e:
            self.__log(f"[local_ipv6] Error: {e}")
        return "::"

    def get_ipv4(self):
        ip = self.get_public_ipv4()
        return ip if ip else self.get_local_ipv4()

    def get_ipv6(self):
        ip = self.get_public_ipv6()
        return ip if ip else self.get_local_ipv6()

    def ping_server(self):
        while True:
            try:
                proc = subprocess.Popen(f"ping -c 1 {self._target_server}", stdout=subprocess.PIPE, universal_newlines=True, shell=True)
                proc.wait()
                self._can_connect = 1 if proc.returncode == 0 else 0
                self.__log(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}][ping] {self._target_server} reachable={self._can_connect}")
            except Exception as e:
                self.__log(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}][ping] Error: {e}")
            time.sleep(60)

    def update_server(self):
        udp_client = socket(AF_INET, SOCK_DGRAM)
        while True:
            try:
                ip4 = self.get_ipv4()
                ip6 = self.get_ipv6()
                message_v4 = f"{self._my_domain},v4,{ip4},{self._can_connect}"
                message_v6 = f"{self._my_domain},v6,{ip6},{self._can_connect}"
                udp_client.sendto(message_v4.encode("utf-8"), (self._target_server, 7171))
                udp_client.sendto(message_v6.encode("utf-8"), (self._target_server, 7171))
                self.__log(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}][update] Sent IPv4: {message_v4}")
                self.__log(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}][update] Sent IPv6: {message_v6}")
            except Exception as e:
                self.__log(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}][update] Error: {e}")
            time.sleep(10)


if __name__ == "__main__":
    client_domain_name = os.environ.get("CLIENT_DOMAIN_NAME", "")
    server_domain_name = os.environ.get("SERVER_DOMAIN_NAME", "")

    ddns_client = UDPClient(client_domain_name, server_domain_name)
    threading.Thread(target=ddns_client.ping_server, daemon=True).start()
    threading.Thread(target=ddns_client.update_server, daemon=True).start()
    while True:
        time.sleep(1)
