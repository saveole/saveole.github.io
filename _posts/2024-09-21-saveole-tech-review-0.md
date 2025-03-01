---
title: Saveole's Weekly Tech Review, Issue 0
date: 2024-09-21 16:50:30 +0800
categories: [Weekly]
tags: [Java, SSE, ZGC, Go， Raft]
description: JDK23|SpringBoot CDS|ZGC|Go SSE|Raft
---



### Post

- Java

  - [JDK 23 发布了！](https://jdk.java.net/23/release-notes)

    > ​        前不久，go 发布了 1.23 版本，Java 最近也如期发布了 JDK 23(none tls)，主要更新大部分还是 preview 阶段的提案，个人印象深刻点的 一[(JEP474)](https://openjdk.org/jeps/474)是 ZGC 默认使用分代模式(Generational Mode), 二[(JEP471)](https://openjdk.org/jeps/471)是 `sun.misc.Unsafe` 的大部分 memory-access 相关的方法被标记 `@Deprecated` 了，以后会移除，类库的开发者需要额外注意下，可以用 [JEP 193](https://openjdk.org/jeps/193) 和 [JEP 454](https://openjdk.org/jeps/454) 中提及的 API 替代。ps: 从 471 看，Java 的更新还是很克制的，充分考虑到老用户的兼容问题，但另一方面也可以看到 Java 的大体量对于新事物的推广还是很慢的，现在 Java 使用最多的版本还是 Java 8，我在面试候选人的时候一说起 Java 的新特性是 Lambda/Stream 流的时候就皱起了眉头 😂
    >
    > ​        也可看看 foojay 上[这篇](https://foojay.io/today/java-23-has-arrived-and-it-brings-a-truckload-of-changes/)对于 JDK 23 的解读文章。

  - [Spring Boot CDS support and Project Leyden anticipation](https://spring.io/blog/2024/08/29/spring-boot-cds-support-and-project-leyden-anticipation)

    > ​        介绍了如何使用 Spring Boot 3.3 + CDS + Leydon + Spring Native 构建应用程序以显著减少 Spring Boot 应用的启动时间和运行时内存消耗，非常推荐看一看试一试。

  - [Bending pause times to your will with Generational ZGC](https://netflixtechblog.com/bending-pause-times-to-your-will-with-generational-zgc-256629c9386b)

    > ​        Netflix 使用 JDK21 + 分代 ZGC 的实践，非常好，俺也想在生产环境试试 🐶

- Go

  - [How to implement Server-Sent Events in Go](https://packagemain.tech/p/implementing-server-sent-events-in-go)

    > ​        SSE(Server-Sent Events) 是服务器向客户端不断发送 event 的单向通信协议(不同于 WebSocket 的双向通信 )，底层也是基于 HTTP，可以用于需要服务端实时生成内容的场景，如 ChatGPT 的流式相应等。
    >
    > ​        这篇文章使用 go 的 net/http 实现了一个简单的 SSE 案例，可以看到 go 的基础类库还是很强大的，比 Java 要简洁很多。
    >
    > 前不久使用 gin 框架也实现了 SSE：
    >
    > ```go
    > func ScriptRecognize(c *gin.Context) {
    > 	id := c.Param("id")
    > 	var record models.ScriptUploadRecord
    > 	err := models.FindOne(common.TB_SCRIPT, bson.M{"_id": bson.ObjectIdHex(id)}, nil, &record)
    > 	if err != nil {
    > 		c.JSON(http.StatusOK, helpers.Fail(err))
    > 		return
    > 	}
    > 	if len(record.Texts) > 0 {
    > 		txt := strings.Join(record.Texts, "")
    > 		c.Stream(func(w io.Writer) bool {
    > 			c.String(200, "data: %s\n\n", txt)
    > 			return false
    > 		})
    > 		return
    > 	}
    > 	chanStream := make(chan string, 100)
    > 	go recognizer.RecognizeFromUrl(record.FileUrl, chanStream)
    > 
    > 	content := make([]string, 0)
    > 	c.Header("Content-Type", "text/event-stream")
    > 	c.Header("X-Accel-Buffering", "no")
    > 	c.Stream(func(w io.Writer) bool {
    > 		if msg, ok := <-chanStream; ok {
    > 			fmt.Printf("转文本：%s", msg)
    > 			c.String(200, "data: %s\n\n", msg)
    > 			content = append(content, msg)
    > 			return true
    > 		}
    > 		go updateScript(id, "texts", content)
    > 		return false
    > 	})
    > }
    > ```
    >
    > ​        主要注意的就是：1. header 的控制参数 2. event 发送的格式

  - [Don't defer Close() on writable files](https://www.joeshaw.org/dont-defer-close-on-writable-files/)

    > ​        不要因为使用了 `defer io.Closer.Close()` 而忽略了后续操作系统因为 close syscall 不成功产生的 error ,建议用 `return f.Close()` --> os 还是不一定马上刷盘，或者 `return f.Sync()` --> 马上刷盘，严重影响性能。

  - [Implementing Raft: Part 2 - Commands and Log Replication](https://eli.thegreenplace.net/2020/implementing-raft-part-2-commands-and-log-replication/)

    > ​        一个实现简单 raft 协议的国外教程的 Log Replication 部分，翔实的 test case 以及 log 可视化(html 表格对比形式)做的很好，要是做成动态可视化就更好了。



### GitHub

- [petclinic-efficient-container](https://github.com/sdeleuze/petclinic-efficient-container) - 经典 Spring Boot 演示项目 **[spring-petclinic](https://github.com/spring-projects/spring-petclinic)** 的优化版
- [eraft](https://github.com/eraft-io) - 一步步实现 [raft](https://raft.github.io/) 协议并打造一个分布式 KV 存储
- [starflare](https://github.com/nieheyong/starflare) - 给自己 star 的项目分类/打标签
- [omakub](https://github.com/basecamp/omakub) - 配置全新安装的 Ubuntu 的工具



### Video

- [Implementing Domain Driven Design with Spring by Maciej Walkowiak @ Spring I/O 2024](https://www.youtube.com/watch?v=VGhg6Tfxb60)



### Book

- [Build Your Own Database From Scratch in Go](https://build-your-own.org/database/)

  > 看了一点，感觉很不错，最近在实现 raft 的时候发现 go 基础很不好，先补基础，后面再来学习。

  