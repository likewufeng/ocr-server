<!--
 * @Author: WuFeng <763467339@qq.com>
 * @Date: 2026-07-09 10:25:14
 * @LastEditTime: 2026-07-09 10:29:28
 * @LastEditors: WuFeng <763467339@qq.com>
 * @Description: 
 * @FilePath: \ocr-server\docs\docker.md
 * Copyright 版权声明
-->
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
