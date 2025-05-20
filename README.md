# UDP IP Update System


## Client Start Command
```bash
docker rm -f udpclient && docker pull --platform linux/arm64 qinbatista/udpclient && docker run -d --platform linux/arm64 --name udpclient --restart=always qinbatista/udpclient
```

Note: Replace `