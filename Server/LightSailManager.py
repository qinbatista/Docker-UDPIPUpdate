#!/usr/bin/env python3
import subprocess, uuid, os, json, time
from datetime import datetime
import pytz


class LightSail:
    def __init__(self):
        self.timezone = pytz.timezone("Asia/Shanghai")
        # Log file stored in the same directory as the script.
        self.log_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "lightsail.log")

    def log(self, msg):
        timestamp = datetime.now(self.timezone)
        log_msg = f"{timestamp}: {msg}"
        with open(self.log_path, "a+") as f:
            f.write(log_msg + "\n")
        print(log_msg)  # Print log to stdout for immediate feedback
        # If the log file exceeds 512 KB, remove it.
        if os.path.exists(self.log_path) and os.path.getsize(self.log_path) > 512 * 1024:
            os.remove(self.log_path)

    def exec_aws(self, cmd):
        self.log(f"Executing AWS command: {cmd}")
        p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, shell=True)
        stdout, stderr = p.communicate()

        if stderr:
            result = stderr.decode().strip()
            self.log(f"Error output: {result}")
        else:
            try:
                result = json.loads(stdout.decode())
            except Exception as e:
                result = f"Error parsing JSON output: {e}"
                self.log(result)

        self.log(f"AWS Command Result: {result}")
        return result

    def allocate_ip(self, region):
        cmd = f"aws lightsail allocate-static-ip --static-ip-name {uuid.uuid4().hex} --region {region} --no-cli-pager"
        result = self.exec_aws(cmd)
        if isinstance(result, dict):
            try:
                if result["operations"][0]["status"] == "Succeeded":
                    ip_name = result["operations"][0]["resourceName"]
                    self.log(f"Allocated IP: {ip_name}")
                    return ip_name
            except Exception as e:
                self.log(f"allocate_ip error: {e}")
        else:
            self.log("allocate_ip received a non-dictionary result")
        return None

    def detach_ip(self, ip_name, region):
        cmd = f"aws lightsail detach-static-ip --static-ip-name {ip_name} --region {region} --no-cli-pager"
        result = self.exec_aws(cmd)
        if isinstance(result, dict):
            if result.get("operations", [{}])[0].get("status") == "Succeeded":
                self.log(f"Detached IP: {ip_name}")
                time.sleep(2)
                return True
        else:
            self.log("detach_ip received a non-dictionary result")
        self.log(f"Failed to detach IP: {ip_name}")
        return False

    def release_ip(self, ip_name, region):
        cmd = f"aws lightsail release-static-ip --static-ip-name {ip_name} --region {region} --no-cli-pager"
        result = self.exec_aws(cmd)
        if isinstance(result, dict):
            if result.get("operations", [{}])[0].get("status") == "Succeeded":
                self.log(f"Released IP: {ip_name}")
                return True
        else:
            self.log("release_ip received a non-dictionary result")
        self.log(f"Failed to release IP: {ip_name}")
        return False

    def get_unattached_ips(self, region):
        cmd = f"aws lightsail get-static-ips --region {region} --no-cli-pager"
        result = self.exec_aws(cmd)
        unattached = []
        if isinstance(result, dict):
            for ip in result.get("staticIps", []):
                if not ip.get("isAttached", False):
                    unattached.append(ip["name"])
            self.log(f"Unattached IPs: {unattached}")
        else:
            self.log("get_unattached_ips received a non-dictionary result")
        return unattached

    def attach_ip(self, ip_name, region, server_name):
        cmd = f"aws lightsail attach-static-ip --static-ip-name {ip_name} --instance-name {server_name} --region {region} --no-cli-pager"
        result = self.exec_aws(cmd)
        if isinstance(result, dict):
            if result.get("operations", [{}])[0].get("status") == "Succeeded":
                self.log(f"Attached IP {ip_name} to {server_name}")
                return
        self.log(f"Failed to attach IP {ip_name}: {result}")

    def replace_ip(self, region, server_name):
        """Replace the instance IP by detaching and releasing any attached IP,
        then allocating and attaching a new IP."""
        self.log("Starting IP replacement")
        cmd = f"aws lightsail get-static-ips --region {region} --no-cli-pager"
        result = self.exec_aws(cmd)
        attached_ips = []
        if isinstance(result, dict):
            for ip in result.get("staticIps", []):
                # Check if the ip is attached and matches the given server name.
                if ip.get("isAttached") and ip.get("attachedTo") == server_name:
                    attached_ips.append(ip["name"])
            self.log(f"Found attached IPs for {server_name}: {attached_ips}")
        else:
            self.log("replace_ip received a non-dictionary result when fetching static IPs")
            return

        for ip in attached_ips:
            if self.detach_ip(ip, region):
                # Double-check that the IP is now unattached.
                if ip in self.get_unattached_ips(region):
                    self.release_ip(ip, region)
                else:
                    self.log(f"IP {ip} is not in the list of unattached IPs after detachment.")
            else:
                self.log(f"Skipping release of IP {ip} because detachment failed.")

        new_ip = self.allocate_ip(region)
        if new_ip:
            time.sleep(1.5)
            self.attach_ip(new_ip, region, server_name)
        else:
            self.log("Failed to allocate a new IP.")


if __name__ == "__main__":
    ls = LightSail()
    ls.replace_ip("ap-northeast-1", "Debian-1")
