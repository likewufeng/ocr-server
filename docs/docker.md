## python创建虚拟环境

```
python -m venv .venv
# Windows 激活命令：
.venv\Scripts\activate
```

## 项目启动
docker compose up --build

docker compose build --no-cache

## 镜像加速配置

```
{
  "builder": {
    "gc": {
      "defaultKeepStorage": "20GB",
      "enabled": true
    }
  },
  "experimental": false,
  "registry-mirrors": [
    "https://docker.1ms.run/",
    "https://dockerproxy.com/",
    "https://hub-mirror.c.163.com/"
  ]
}
```
