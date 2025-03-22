---
title: Saveole's Tech Review, Issue 1
date: 2025-03-21 21:50:30 +0800
categories: [Randomly]
tags: [Java, ZGC, Virtual Thread, eBPF]
description: JDK24发布了，改动还挺多|Spring7预览版先来预览预览|Java + eBPF
---



### Post

- Java

  - [JDK 24 发布了！](https://openjdk.org/projects/jdk/24/)

    > JDK 24 最近(2025-03-18)发布了, 讲下几个让我感兴趣的地方吧。
    - [Compact Object Headers](https://openjdk.org/jeps/450)
        > 压缩对象头：将 64 位机器的 HotSpot JVM 对象头从 96 - 128 位压缩为 64 位，且保证由此造成的吞吐/延迟损失不超过 5%，相关的项目是 [Liliput](https://openjdk.org/projects/lilliput/)。Java 一直以较大的内存开销闻名，很大一块原因就是 Java 对象的冗余设计，在云原生时代这的确是一个劣势。好在社区在这块终于有所动作，最近会花时间看看压缩对象头在内存这块有多大提升。
    - [Stream Gatherers](https://openjdk.org/jeps/485)
        > 这个 JEP 是对 [Stream API](https://docs.oracle.com/en/java/javase/21/docs/api/java.base/java/util/stream/package-summary.html) 的增强，用户能够自定义构建流的中间(如 jdk 提供的 `filter/map/flatMap/distinct/limit` 等返回 `Stream<T> 的方法`)操作，简单用法：`source.gather(...).gather(...).gather(...).collect(...)`。
    - [Ahead-of-Time Class Loading & Linking](https://openjdk.org/jeps/483)
        > 加速 JVM 应用启动时间的技术，通过监控和存储系统在运行时的 class 等信息，在下次启动时直接链接/加载上次存储的文件到内存直接运行，大大减少应用的启动时间。
    - [Prepare to Restrict the Use of JNI](https://openjdk.org/jeps/472)
        > 开始限制 JNI 的使用，引导开发者使用 [Foreign Function & Memory API](https://openjdk.org/jeps/454)。
    - [Class-File API](https://openjdk.org/jeps/484)
        > 直接操作字节码文件的 API，因为 Java 六个月的发版节奏导致字节码文件格式变化加快，怕第三方字节码操作库如 `ASM` 等跟不上节奏，官方自己下场干活了，这对于 `APM` 类软件研发可能是更好的选择。
    - [Module Import Declarations (Second Preview)](https://openjdk.org/jeps/494)
        > 类似将 `import java.util.* ` 的引用变更为 `import module java.base`，如果引用某一个模块的类比较多的话，还是能大大简化 import 语句的。
    - [ZGC: Remove the Non-Generational Mode](https://openjdk.org/jeps/490)
        > 上个版本 ZGC 默认使用分代模式，这个版本中是移除 ZGC 的非分代模型。
    - [Permanently Disable the Security Manager](https://openjdk.org/jeps/486)
        > JDK 17 中开始准备移除 Security Manager，现在正式永久移除。
    - [Synchronize Virtual Threads without Pinning](https://openjdk.org/jeps/491)
        > 之前版本的 Virtual Thread + synchronized 在执行方法出现阻塞(例如 IO 场景)([pinning](https://docs.oracle.com/en/java/javase/21/core/virtual-threads.html#GUID-04C03FFC-066D-4857-85B9-E5A27A875AF9))的情况下，VT 不能 unmount 其依赖的底层 OS 线程，可能导致线程饥饿甚至死锁等问题(可以通过 `jdk.VirtualThreadPinned` JFR 事件监控)，[Netflix](https://netflixtechblog.com/java-21-virtual-threads-dude-wheres-my-lock-3052540e231d) 团队之前也遇到过，JEP491 解决了这个问题。下面是一个由此导致的[死锁代码](https://gist.github.com/DanielThomas/0b099c5f208d7deed8a83bf5fc03179e)案例：
        
        
        ```java
        import java.time.Duration;
        import java.util.List;
        import java.util.concurrent.locks.ReentrantLock;
        import java.util.stream.IntStream;
        import java.util.stream.Stream;

        /**
         * Demonstrate potential for deadlock on a {@link ReentrantLock} when there is both a synchronized and
         * non-synchronized path to that lock, which can allow a virtual thread to hold the lock, but
         * other pinned waiters to consume all the available workers. 
        */
        public class VirtualThreadReentrantLockDeadlock {

            public static void main(String[] args) {
                final boolean shouldPin = args.length == 0 ||Boolean.parseBoolean(args[0]);
                final ReentrantLock lock = new ReentrantLock(true); // With faireness to ensure that the unpinned thread is next in line

                lock.lock();
        
                Runnable takeLock = () -> {
                    try {
                        System.out.println(Thread.currentThread() + " waiting for lock");
                        lock.lock();
                        System.out.println(Thread.currentThread() + " took lock");
                    } finally {
                        lock.unlock();
                        System.out.println(Thread.currentThread() + " released lock");
                    }
                };

                Thread unpinnedThread = Thread.ofVirtual().name("unpinned").start(takeLock);

                List<Thread> pinnedThreads = IntStream.range(0, Runtime.getRuntime().availableProcessors())
            .mapToObj(i -> Thread.ofVirtual().name("pinning-" + i).start(() -> {
                        if (shouldPin) {
                            synchronized (new Object()) {
                                takeLock.run();
                            }
                        } else {
                            takeLock.run();
                        }
                    })).toList();
        
                lock.unlock();
        
                Stream.concat(Stream.of(unpinnedThread), pinnedThreads.stream()).forEach(thread -> {
                    try {
                        if (!thread.join(Duration.ofSeconds(3))) {
                            throw new RuntimeException("Deadlock detected");                    
                        }
                    } catch (InterruptedException e) {
                        throw new RuntimeException(e);
                    }
                });
            }

        }
        ```
        
        ```
        (base) saveole@saveoledeMacBook-Pro src % java VirtualThreadReentrantLockDeadlock.java
        VirtualThread[#25,unpinned]/runnable@ForkJoinPool-1-worker-1 waiting for lock
        VirtualThread[#28,pinning-0]/runnable@ForkJoinPool-1-worker-1 waiting for lock
        VirtualThread[#30,pinning-2]/runnable@ForkJoinPool-1-worker-3 waiting for lock
        VirtualThread[#29,pinning-1]/runnable@ForkJoinPool-1-worker-2 waiting for lock
        VirtualThread[#33,pinning-5]/runnable@ForkJoinPool-1-worker-6 waiting for lock
        VirtualThread[#31,pinning-3]/runnable@ForkJoinPool-1-worker-4 waiting for lock
        VirtualThread[#35,pinning-7]/runnable@ForkJoinPool-1-worker-9 waiting for lock
        VirtualThread[#32,pinning-4]/runnable@ForkJoinPool-1-worker-5 waiting for lock
        VirtualThread[#34,pinning-6]/runnable@ForkJoinPool-1-worker-7 waiting for lock
        VirtualThread[#36,pinning-8]/runnable@ForkJoinPool-1-worker-8 waiting for lock
        VirtualThread[#38,pinning-9]/runnable@ForkJoinPool-1-worker-10 waiting for lock
        Exception in thread "main" java.lang.RuntimeException: Deadlock detected
        at VirtualThreadReentrantLockDeadlock.lambda$main$3(VirtualThreadReentrantLockDeadlock.java:49)
        at java.base/java.util.stream.Streams$StreamBuilderImpl.forEachRemaining(Streams.java:411)
        at java.base/java.util.stream.Streams$ConcatSpliterator.forEachRemaining(Streams.java:734)
        at java.base/java.util.stream.ReferencePipeline$Head.forEach(ReferencePipeline.java:762)
        at VirtualThreadReentrantLockDeadlock.main(VirtualThreadReentrantLockDeadlock.java:46)

        ```
        

  - [Reproducing a Java 21 virtual threads deadlock scenario with TLA+](https://surfingcomplexity.blog/2024/08/01/reproducing-a-java-21-virtual-threads-deadlock-scenario-with-tla/)
    > ​对 Java 21 虚拟线程 + synchronized 造成死锁的解释文章，值得一看。

- [Spring Framework 7.0 - preview 版本](https://github.com/spring-projects/spring-framework/wiki/Spring-Framework-7.0-Release-Notes)

  - [Programmatic Bean Registration](https://docs.spring.io/spring-framework/reference/7.0-SNAPSHOT/core/beans/java/programmatic-bean-registration.html#page-title)
    > 编程化控制 Spring Bean 的注册逻辑，可以和 `Spring AOT` 以及 `GraalVM native images` 兼容使用。
  - [Null-safety](https://docs.spring.io/spring-framework/reference/7.0-SNAPSHOT/core/null-safety.html)
    > 使用 [Jspecify](https://jspecify.dev/docs/user-guide/) 进行 `Null` 值注解方式检查。
  - [API versioning support in web applications](https://github.com/spring-projects/spring-framework/issues/34565)
    > 通过在 `@RequestMapping` 中指定 API 版本路由到不同的 controller 方法中。
  - [Optional support with null-safe](https://docs.spring.io/spring-framework/reference/7.0-SNAPSHOT/core/expressions/language-ref/operator-safe-navigation.html#expressions-operator-safe-navigation-optional) and [Elvis operators in SpEL expressions](https://docs.spring.io/spring-framework/reference/7.0-SNAPSHOT/core/expressions/language-ref/operator-elvis.html)
    > 终于！！！ 
    > SpEL + Optional : `Optional<User>` -> `user?.name`
    > SpEL + 三目表达式 : `(name != null ? name : "Unknown")` -> `"name ?: 'Unknown'"`



### GitHub

- [eclipse-jifa/jifa](https://github.com/eclipse-jifa/jifa) - 在线 GC 日志/Heap Dump/JFR 文件可视化分析工具。
- [java24-demo](https://github.com/SimonVerhoeven/java24-demo) - JDK24 特性相关的代码示例和解释。
- [hello-ebpf](https://github.com/parttimenerd/hello-ebpf) - 用 Java 代码写 [eBPF](https://ebpf.io/what-is-ebpf/) 程序。



### Video

- [Project Lilliput - Beyond Compact Headers](https://www.youtube.com/watch?v=kHJ1moNLwao)
- [Build a lightning fast Firewall with Java & eBPF - Johannes Bechberger - CPH DevFest 2024](https://www.youtube.com/watch?v=WYwHiDyMK68)



### Book

- NaN

  