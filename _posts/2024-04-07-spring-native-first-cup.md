---
title: Spring Native 初体验
date: 2024-04-07 13:30:30 +0800
categories: [技术, Java]
tags: [Docker,JVM,Java,GraalVM]     # TAG names should always be lowercase
description: Spring Native 结合实际项目的体验
---



- 项目背景
    - mqtt 的消费端应用，应用逻辑较简单，主要是消费 mqtt 消息，然后做对应的持久化(写多读少)操作
    - 项目架构主要使用到了 Spring Boot 作为 IoC 容器，MongoDB 作为存储，然后开源的 [mqtt-spring-boot-starter](https://github.com/tocrhz/mqtt-spring-boot-starter) 作为 mqtt 客户端
    - 当前存在的问题：
        - 过度依赖：依赖了 Spring Web 等本不需要的依赖(这里的 Spring 主要作为 bean 容器)
        - 弹性不足：当消费能力不足需要添加实例的时候，应用启动速度不够快 + 镜像体积较大(451M)
        - 基于spring boot fat jar 的应用内存占用较高
- 环境
    - OS: Ubuntu 22.04
    - JDK: openjdk 21 GraalVM CE 21+35.1
    - IDE: IDEA Ultimate 2023.2.5
    - CPU: i5-12400
    - 内存: 32G 2666Hz
- 改造内容
    - JDK 17 → 21
    - Spring Boot 2.7.0 → 3.1.5
    - Spring AOT
    - Dockerfile
- 存在问题
    - build 阶段问题
        - `commons-logging 与 spring jcl 的冲突`  → 去除对应的 commons-logging 包
    - runtime 阶段问题
        - [profiles 问题](https://stackoverflow.com/questions/71660363/spring-native-set-active-profile)
        - `Java 21 ResourceBundle`  → `Caused by: java.util.MissingResourceException: Can't find bundle for base name oss, locale en_US`
            - 由 ali-sdk-oss 引入，发现项目中没用到，移除依赖
        - `运行时 hutool ReflectUtil 使用报错` → 改由改写依赖的开源三方库实现，避免使用reflection
        - `mqtt-client 周期性断连/重连`
            - 待分析解决
        - `whether JVM Runtime shutdown hook is executed when spring native app exited`
    - CI/CD
        - 目前阿里云默认流水线集群不支持
        - 将自己的 ecs 主机作为构建机器，发现 2g 的内存不足以进行应用构建
- 总结体验
    - 其他更详细的信息见：[chat](https://codeup.aliyun.com/608626eaa7600a4c353f87ce/chat)