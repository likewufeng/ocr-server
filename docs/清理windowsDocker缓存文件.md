## 这是 Docker Desktop 的 WSL2 虚拟磁盘。镜像和容器删除后，`docker_data.vhdx` 通常不会自动缩小，需要先清理 Docker 数据，再压缩 VHDX。

先查看占用：

```bash
docker system df -v
```

清理未使用的容器、网络、镜像和构建缓存：

```bash
docker system prune -a
docker builder prune -a
```

如果确认不再需要任何“未被容器使用”的数据卷，再执行下面这条。数据库数据可能存在 volume 中，务必谨慎：

```bash
docker volume prune
```

然后彻底退出 Docker Desktop，以管理员身份打开 PowerShell：

```bash
wsl --shutdown
Optimize-VHD -Path "D:\DockerData\DockerDesktopWSL\disk\docker_data.vhdx" -Mode Full
```

如果系统提示找不到 `Optimize-VHD`，可使用管理员终端中的 `diskpart`：

```bash
diskpart
select vdisk file="D:\DockerData\DockerDesktopWSL\disk\docker_data.vhdx"
attach vdisk readonly
compact vdisk
detach vdisk
exit
```

完成后重新启动 Docker Desktop。

注意：

- 不要直接删除 `docker_data.vhdx`，否则本地镜像、容器和 volumes 都会丢失。
- `docker system prune -a` 不删除正在运行的容器，也默认不删除 volumes。
- 压缩前应保证 Docker Desktop完全退出，并执行过 `wsl --shutdown`。
- 若主要空间来自数据库 volume，普通清理不会释放它，需要先备份并处理对应数据库数据。









## 如果 Docker 内所有容器、镜像、缓存和 volume 都可以删除，在 PowerShell 执行：

```bash
docker ps -aq | ForEach-Object { docker rm -f $_ }
docker volume ls -q | ForEach-Object { docker volume rm -f $_ }
docker system prune -a --volumes -f
```

然后压缩虚拟磁盘。彻底退出 Docker Desktop，以管理员身份运行：

```bash
wsl --shutdown
Optimize-VHD -Path "D:\DockerData\DockerDesktopWSL\disk\docker_data.vhdx" -Mode Full
```

如果没有 `Optimize-VHD`，使用管理员终端：

```bash
diskpart
select vdisk file="D:\DockerData\DockerDesktopWSL\disk\docker_data.vhdx"
attach vdisk readonly
compact vdisk
detach vdisk
exit
```

这会永久删除所有 Docker 容器、镜像和 volume 数据，但不会影响宿主机上的项目源代码。不要直接删除 `docker_data.vhdx`。