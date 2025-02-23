# -*- coding: utf-8 -*-
import subprocess
import uuid
import os
import json
import requests
import time
import threading
from socket import *
from datetime import datetime
import pytz
import platform


class LightSail:
    def __init__(self, _region, _server_name):
        self.__region = _region
        self.__server_name = _server_name
        self.__received_count = 0
        self.__CN_timezone = pytz.timezone("Asia/Shanghai")
        self.__current_ip_from_udp = ""
        self.__udpServer = socket(AF_INET, SOCK_DGRAM)
        self.__file_path = "/root/logs.txt"
        if platform.system() == "Darwin":
            self.__file_path = ("~/logs.txt")
        self.__is_connect = ""
        self.__the_ip = ""
        self.__inaccessible_count = 0
        self.__record_time = datetime.now(self.__CN_timezone)
        self.__ave_time = 0

    def __log(self, result):
        with open(self.__file_path, "a+") as f:
            f.write(f"{str(result)}\n")
        if os.path.getsize(self.__file_path) > 1024 * 512:
            with open(self.__file_path, "r") as f:
                content = f.readlines()
                os.remove(self.__file_path)

    def _exec_aws_command(self, command):
        _fn_stdout = f"/root/_get_static_ip_stdout{uuid.uuid4()}.json"
        _fn_tderr = f"/root/_get_static_ip_stderr{uuid.uuid4()}.json"
        _get_static_ip_stdout = open(_fn_stdout, "w+")
        _get_static_ip_stderr = open(_fn_tderr, "w+")
        process = subprocess.Popen(
            command,
            stdout=_get_static_ip_stdout,
            stderr=_get_static_ip_stderr,
            universal_newlines=True,
            shell=True,
        )
        process.wait()
        # reuslt
        aws_result = ""
        filesize = os.path.getsize(_fn_tderr)
        if filesize == 0:
            # print("The file is empty: " + str(filesize))
            with open(_fn_stdout) as json_file:
                result = json.load(json_file)
                aws_result = result
        else:
            with open(_fn_tderr) as json_file:
                aws_result = json_file.read()
        # clean cache files
        os.remove(_fn_stdout)
        os.remove(_fn_tderr)
        # print(aws_result)
        self.__log(aws_result)
        return aws_result

    def _allocateIP(self):
        cli_command = f"aws lightsail --no-paginate allocate-static-ip --static-ip-name {uuid.uuid4()} --region {self.__region} --no-cli-pager"
        result = self._exec_aws_command(cli_command)
        try:
            if result["operations"][0]["status"] == "Succeeded":
                # print("_allocateIP a ip")
                return result["operations"][0]["resourceName"]
        except Exception as e:
            self.__log(f"[_allocateIP] error:{str(e)}")
            return -1

    def _get_static_ip(self):
        # execute aws command
        cli_command = f"aws lightsail get-static-ip --static-ip-name StaticIp-1 --region {self.__region} --no-cli-pager"
        result = self._exec_aws_command(cli_command)

    def _release_static_ip(self, _ips):
        result = ""
        try:
            if _ips == -1:
                return -1
            for ip in _ips:
                cli_command = f"aws lightsail --no-paginate  release-static-ip --static-ip-name {ip} --region {self.__region} --no-cli-pager"
                result = self._exec_aws_command(cli_command)
        except Exception as e:
            self.__log(f"[_release_static_ip] error:{str(e)} result:{result}")
            return -1

    def _get_unattached_static_ips(self):
        try:
            cli_command = f"aws lightsail --no-paginate  get-static-ips --region {self.__region} --no-cli-pager"
            result = self._exec_aws_command(cli_command)
            unattached_ips = []
            for ip in result["staticIps"]:
                if ip["isAttached"] == False:
                    unattached_ips.append(ip["name"])
            return unattached_ips
        except Exception as e:
            self.__log(f"[_get_unattached_static_ips] error:{str(e)} result:{result}")
            return -1

    def _check_instance_ip_state(self):
        while True:
            try:
                self.__received_count = self.__received_count - 1
                # self.__log(f"self.__received_count={self.__received_count}")
                if self.__received_count <= -60*24 or self.__inaccessible_count >= 5:
                    first_time = datetime.now(self.__CN_timezone)
                    self._replace_instance_ip()
                    second_time = datetime.now(self.__CN_timezone)
                    difference = second_time - first_time
                    last_time = datetime.now(self.__CN_timezone) - self.__record_time
                    if self.__ave_time == 0:
                        self.__ave_time = last_time.seconds
                    else:
                        self.__ave_time = (self.__ave_time + last_time.seconds) / 2
                    # print(f"| Used:{ difference.seconds:2.2f} seconds | Duration:{last_time.seconds/3600:2.2f} hours | Ave:{self.__ave_time/3600:2.2f} hours | Count:{self.__received_count}")
                    self.__log(f"| Used:{ difference.seconds:2.2f} seconds | Duration:{last_time.seconds/3600:2.2f} hours | Ave:{self.__ave_time/3600:2.2f} hours | Count:{self.__received_count}")
                    self.__record_time = datetime.now(self.__CN_timezone)
                    self.__received_count = 0
                    self.__inaccessible_count = 0
                time.sleep(60)
            except Exception as e:
                self.__log(f"{str(e)}")

    def _attach_static_ip(self, ip_name, _instance_name):
        try:
            cli_command = f"aws lightsail --no-paginate  attach-static-ip --static-ip-name {ip_name} --instance-name {_instance_name} --region {self.__region} --no-cli-pager"
            result = self._exec_aws_command(cli_command)
            # print(result)
            if result["operations"][0]["status"] == "Succeeded":
                self.__log("_attach_static_ip success")
            else:
                self.__log(f"[error][_attach_static_ip]_attach_static_ip:{str(result)}")
        except Exception as e:
            self.__log(f"[error][_attach_static_ip]_attach_static_ip:{str(result)}")

    def _replace_instance_ip(self):
        try:
            result = self._allocateIP()
            time.sleep(1.5)
            if result != -1:
                self._attach_static_ip(result, self.__server_name)
                time.sleep(1.5)
                result = self._release_static_ip(self._get_unattached_static_ips())
                time.sleep(1.5)
        except Exception as e:
            self.__log(f"_replace_instance_ip:{str(e)}")

    def _get_host_ip(self):
        try:
            text = requests.get("https://checkip.amazonaws.com").text.strip()
            # self.__log("_get_host_ip", text)
            return text
        except Exception as e:
            self.__log(f"[_get_host_ip]using ip {self.__current_ip_from_udp}, error:" + str(e))
            return self.__current_ip_from_udp

    def _test_log(self):
        while True:
            self.__log(str(datetime.now(self.__CN_timezone)))

    def _get_message_from_remote(self):
        thread_refresh = threading.Thread(target=self._get_message_from_remote_refresh, name="t1", args=())
        thread_refresh.start()

    def _get_message_from_remote_refresh(self):
        try:
            self.__udpServer = socket(AF_INET, SOCK_DGRAM)
            self.__udpServer.bind(("", 7171))
            while True:
                data, addr = self.__udpServer.recvfrom(1024)
                ip, port = addr
                self.__received_count = 0
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
                # print(f"{str(datetime.now(self.__CN_timezone))} self.__inaccessible_count:{self.__inaccessible_count} self.__is_connect={self.__is_connect} self.__current_ip_from_udp={self.__current_ip_from_udp} from:{ip}:{port} the_ip:{self.__the_ip} count:{self.__received_count}")
                self.__log(f"{str(datetime.now(self.__CN_timezone))} self.__inaccessible_count:{self.__inaccessible_count} self.__is_connect={self.__is_connect} self.__current_ip_from_udp={self.__current_ip_from_udp} from:{ip}:{port} the_ip:{self.__the_ip} count:{self.__received_count}")
        except Exception as e:
            self.__log(f"{str(e)}")


if __name__ == "__main__":
    ls = LightSail("us-west-2", "Debian-1")
    ls._get_message_from_remote()
    ls._check_instance_ip_state()
