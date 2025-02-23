import os
import time
import requests
import threading
import subprocess
from socket import *
from datetime import datetime


class DDNSClient:
    def __init__(self, client_domain_name, server_domain_name):
        self._my_domain = client_domain_name
        self.__target_server_v4 = server_domain_name
        self.__target_server_v6 = server_domain_name
        self.__file_path = "/ipreporter.txt"

        # Websites to fetch the current IP addresses
        self._get_ipv4_website = "https://checkip.amazonaws.com"
        self._get_ipv6_website = "https://api6.ipify.org"

        # 0 means not reachable, 1 means reachable.
        self._can_connect = 0

        self.__log(f"client_domain_name={client_domain_name}, server_domain_name={server_domain_name}")
        self.__log(f"this_docker_ipv4={self.__get_current_ipv4()}, this_docker_ipv6={self.__get_current_ipv6()}")

    def _ping_server_thread(self):
        thread_refresh = threading.Thread(target=self.__ping_server, name="t1")
        thread_refresh.start()

    def __ping_server(self):
        while True:
            try:
                # Ping the target server
                process = subprocess.Popen(f"ping -c 1 {self.__target_server_v4}", stdout=subprocess.PIPE, universal_newlines=True, shell=True)
                process.wait()

                # Update connectivity status based on the ping result
                self._can_connect = 1 if process.returncode == 0 else 0

                self.__log(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}][ping_server] ping -c 1 {self.__target_server_v4} reachable={self._can_connect}")

                # Wait for 1 minute before the next ping
                time.sleep(60)
            except Exception as e:
                self.__log(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}][ping_server] Error: {str(e)}")
                time.sleep(60)

    def _update_this_server_thread(self):
        thread_refresh = threading.Thread(target=self.__update_this_server, name="t1")
        thread_refresh.start()

    def __update_this_server(self):
        udpClient = socket(AF_INET, SOCK_DGRAM)
        while True:
            try:
                # Get the current IPv4 of the client
                this_docker_ipv4 = self.__get_current_ipv4()
                # Prepare the UDP message with client domain name, current IP, and ping result.
                message = f"{self._my_domain},{this_docker_ipv4},{self._can_connect}"
                udpClient.sendto(message.encode("utf-8"), (self.__target_server_v4, 7171))
                self.__log(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}][update_this_server] Sent message to {self.__target_server_v4}: {message}")
                time.sleep(60)
            except Exception as e:
                self.__log(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}][update_this_server] Error: {str(e)}")
                time.sleep(60)

    def __log(self, result):
        with open(self.__file_path, "a+") as f:
            f.write(result + "\n")
        # If the log file exceeds 128 KB, clear it.
        if os.path.getsize(self.__file_path) > 1024 * 128:
            os.remove(self.__file_path)

    def __get_current_ipv6(self):
        try:
            response = requests.get(self._get_ipv6_website, timeout=5)
            response.raise_for_status()
            return response.text.strip()
        except requests.exceptions.RequestException as err:
            self.__log(f"[get_current_ipv6] Request Exception: {err}")
        return None

    def __get_current_ipv4(self):
        try:
            response = requests.get(self._get_ipv4_website, timeout=5)
            response.raise_for_status()
            return response.text.strip()
        except requests.exceptions.RequestException as err:
            self.__log(f"[get_current_ipv4] Request Exception: {err}")
        return ""


if __name__ == "__main__":
    client_domain_name = os.environ["CLIENT_DOMAIN_NAME"]
    server_domain_name = os.environ["SERVER_DOMAIN_NAME"]

    ddns_client = DDNSClient(client_domain_name, server_domain_name)
    ddns_client._ping_server_thread()
    ddns_client._update_this_server_thread()
