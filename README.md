# UDP IP Update System

## Client Start Command
```bash
docker rm -f udpclient && docker pull --platform linux/arm64 qinbatista/udpclient && docker run -d --platform linux/arm64 --name udpclient --restart=always --dns=8.8.8.8 --dns=1.1.1.1 -e UPDATE_INTERVAL_MINUTES=1 qinbatista/udpclient
```

## Server Start Command
```bash
docker rm -f udpserver && docker pull --platform linux/arm64 qinbatista/udpserver && docker run -d --platform linux/arm64 --name udpserver --restart=always -p 7171:7171/udp -e IP_MONITOR_INTERVAL_MINUTES=1 qinbatista/udpserver
```

The client now sends UDP IP updates every interval (default: 1 minute), and the server checks local DNS first: if the domain already points to that IP it skips updating, otherwise it keeps uploading until DNS matches.
