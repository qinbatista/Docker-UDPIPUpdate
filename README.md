# UDP IP Update System

## Client Start Command
```powershell
docker rm -f udpclient 2>$null; docker run -d --name udpclient --restart=always -e CLIENT_DOMAIN_NAME_OVERRIDE=cn2.qinyupeng.com qinbatista/udpclient
```

## Server Start Command
```bash
docker rm -f udpserver && docker pull --platform linux/arm64 qinbatista/udpserver && docker run -d --platform linux/arm64 --name udpserver --restart=always -p 7171:7171/udp -e IP_MONITOR_INTERVAL_MINUTES=1 qinbatista/udpserver
```

The client now sends UDP IP updates every interval (default: 1 minute), and the server checks local DNS first: if the domain already points to that IP it skips updating, otherwise it keeps uploading until DNS matches.
