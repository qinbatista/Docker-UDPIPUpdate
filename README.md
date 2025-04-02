docker rm -f udpserver && docker pull qinbatista/udpserver && docker run -d --name udpserver --restart=always -p 7171:7171/udp qinbatista/udpserver

s