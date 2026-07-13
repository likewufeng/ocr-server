# Docker 开发启动

```bash
# 第一次（需要构建镜像和下载模型）
cd /home/user/ocr-server
docker compose down && docker compose up --build

# 后续开发（代码修改后自动重载）
docker compose up

# 只重启容器（不重新构建）
docker compose restart
```

**热重载验证：**

1. 修改本地代码
2. Docker 容器自动检测到变化并重启
3. 日志显示：`Reloading...`