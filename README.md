# UDP IP Update System

## Server Start Command
```bash
docker rm -f udpserver && docker pull --platform linux/arm64 qinbatista/udpserver && docker run -d --platform linux/arm64 --name udpserver --restart=always -p 7171:7171/udp qinbatista/udpserver
```

## Client Start Command
```bash
docker rm -f udpclient && docker pull --platform linux/arm64 qinbatista/udpclient && docker run -d --platform linux/arm64 --name udpclient --restart=always qinbatista/udpclient
```

Note: Replace `