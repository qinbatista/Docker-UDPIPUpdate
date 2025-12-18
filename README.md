# UDP IP Update System

## Client Start Command
```bash
docker rm -f udpclient && docker pull --platform linux/arm64 qinbatista/udpclient && docker run -d --platform linux/arm64 --name udpclient --restart=always --dns=8.8.8.8 --dns=1.1.1.1 qinbatista/udpclient
```

## Server Start Command
```bash
docker rm -f udpserver && docker pull --platform linux/arm64 qinbatista/udpserver && docker run -d --platform linux/arm64 --name udpserver --restart=always -p 7171:7171/udp qinbatista/udpserver
```
