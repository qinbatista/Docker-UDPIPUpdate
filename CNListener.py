# -*- coding: utf-8 -*-
import os
import subprocess
import time
import threading
from socket import *
from datetime import datetime
import pytz
from ECSManager import ECSManager


class CNListener:
    def __init__(self):
        self.__received_count = 0
        self.__CN_timezone = pytz.timezone("Asia/Shanghai")
        self.__current_ip_from_udp = ""
        self.__udpServer = socket(AF_INET, SOCK_DGRAM)
        self.__file_path = "/cnlistener.txt"
        self.__is_connect = ""
        self.__the_ip = ""
        self.__inaccessible_count = 0

    def __log(self, result):
        with open(self.__file_path, "a+") as f:
            f.write(f"{str(result)}\n")
        if os.path.getsize(self.__file_path) > 1024 * 512:
            with open(self.__file_path, "r") as f:
                content = f.readlines()
                # print("content:"+str(len(content)))
                os.remove(self.__file_path)

    def __post_client_to_google_DNS(self, client_ip, client_verify_key, client_domain_name):
        try:
            ipv4_url = f"https://{client_verify_key}@domains.google.com/nic/update?hostname={client_domain_name}&myip={client_ip}"
            ipv4_curl_command = f"curl '{ipv4_url}'"
            ipv4_result = subprocess.run(ipv4_curl_command, shell=True, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            self.__log(f"IPv4 POST CURL: {ipv4_url}")
            self.__log(f"IPv4 POST Output: {ipv4_result.stdout}")
        except Exception as e:
            self.__log(f"_post_ip_address:{str(e)} self.__current_ip_from_udp={str(self.__current_ip_from_udp)}")

    def _thread_listening_CN(self):
        thread_refresh = threading.Thread(target=self.__listening_CN, name="t1", args=())
        thread_refresh.start()

    def __listening_CN(self):
        try:
            self.__udpServer = socket(AF_INET, SOCK_DGRAM)
            self.__udpServer.bind(("", 7171))
            while True:
                data, addr = self.__udpServer.recvfrom(1024)
                ip, port = addr
                message = data.decode(encoding="utf-8").split(",")
                if len(message) == 2:
                    self.__current_ip_from_udp = message[0]
                    self.__is_connect = message[1]
                    if self.__is_connect == "1":
                        self.__inaccessible_count = 0
                    else:
                        self.__inaccessible_count += 1
                else:
                    self.__current_ip_from_udp = message
                self.__log(f"{str(datetime.now(self.__CN_timezone))} Server IP:{self.__the_ip} self.__inaccessible_count:{self.__inaccessible_count} 60*24 mins restart :{self.__received_count} client message IP={self.__current_ip_from_udp} from:{ip}:{port}")
                self.__post_client_to_google_DNS(ip, message[2], message[3])
        except Exception as e:
            self.__log(f"{str(e)}")

    def _thread_ip_holding(self):
        thread_refresh = threading.Thread(target=self.__ip_holding, name="t1", args=())
        thread_refresh.start()

    def __ip_holding(self):
        while True:
            try:
                self.__received_count = self.__received_count - 1
                if self.__inaccessible_count >= 5 or self.__received_count <= -60*24:
                    em = ECSManager()
                    em._replace_fargate()
                    self.__received_count = 0
                    self.__inaccessible_count = 0
                time.sleep(60)
            except Exception as e:
                self.__log(f"{str(e)}")\

    def _running(self):
        while True:
            time.sleep(10)

if __name__ == "__main__":
    sf = CNListener()
    sf._thread_listening_CN()
    sf._thread_ip_holding()
    sf._running()