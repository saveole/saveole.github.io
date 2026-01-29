---
title: Win10 Docker 环境安装及设置
date: 2023-05-19 13:30:30 +0800
categories: [技术, Docker]
tags: [Docker]     # TAG names should always be lowercase
---



- 前置步骤

    - 安装 WSL2 - [安装 WSL | Microsoft Learn](https://learn.microsoft.com/zh-cn/windows/wsl/install)
    - 在 **设置 > 应用 > 程序和功能 > 启用或关闭 Windows 功能** 中勾选 **Hyper-V** 和 **适用于 Linux 的 Windows 子系统**
    - 重启电脑
    - 安装 Linux 发行版
      
        ```powershell
        # 列出可用 linux 发行版本
        wsl --list --online
        # 安装选定发行版
        wsl --install -d <Distribution Name>
        # 查看 wsl 安装信息
        wsl -l -v
        ```

- 下载 Docker Desktop for Windows 并安装
- Docker Desktop 默认安装到 C 盘，可以将它的数据存储到其他盘

    ```powershell
    # 先备份 docker-desktop 和 docker-desktop-data 数据
    wsl --export docker-desktop docker-desktop.tar
    wsl --export docker-desktop-data docker-desktop-data.tar
    
    # 卸载 wsl 中的 docker-desktop 和 docker-desktop-data
    wsl --unregister docker-desktop
    wsl --unregister docker-desktop-data
    
    # 在其他盘创建存储目录并导入之前的数据
    wsl --import docker-desktop D:\data\docker-desktop docker-desktop.tar
    wsl --import docker-desktop-data D:\data\docker-desktop-data docker-desktop-data.tar
    ```

- 重启电脑
- 遇到的问题
    - docker desktop 卸载重装后不能启动
      
        ```
        原因：没有在 启用或关闭 Windows 功能 中勾选 Hyper-V
        ```
        
    - `wsl —list —online` 一直没有响应
      
        ```
        启用或关闭 Windows 功能 设置变更后需要重启电脑生效
        ```
      <!-- ##{"timestamp":1684319502}## -->