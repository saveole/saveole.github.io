---
title: GraalVM Native + Base64 编解码命令行小工具开发
date: 2024-04-29 13:38:00 +0800
categories: [技术, Java]
tags: [GraalVM,Java,JShell]     # TAG names should always be lowercase
---


- 初衷：
    - 浏览  [V 站](https://www.v2ex.com/) 帖子有很多 Base64 加密的信息，希望能够快速解密。
- 实现：
    - v1：直接使用 [JShell](https://docs.oracle.com/en/java/javase/21/jshell/introduction-jshell.html) 命令行运行 Java 代码解密
      
        ```bash
        ant@ant:~$ jshell 
        |  Welcome to JShell -- Version 17.0.9
        |  For an introduction type: /help intro
        
        jshell> var enc = "c2F2ZW9sZQ=="
        enc ==> "c2F2ZW9sZQ=="
        
        jshell> var decodedBytes = Base64.getDecoder().decode(enc.getBytes())
        decodedBytes ==> byte[8] { 115, 97, 118, 101, 95, 111, 108, 101 }
        
        jshell> new String(decodedBytes)
        $3 ==> "saveole"
        ```
        
    - v2：[GraalVM Native](https://www.graalvm.org/latest/docs/getting-started/) 的方式将 Java 程序编译打包成可执行文件小工具
        - 原 Java 程序：
          
            ```java
            import java.util.Base64;
            
            public class Base64Tool {
                static String helpMsg = """
            		-e Encode input string
            		-d Decode input string 
                        """;;
                
                public static void main(String[] args) {
                    if (args == null || args.length == 0) {
                        System.err.println(helpMsg);
                        System.exit(1);
                    }
                    var arg = args[0];
                    switch(arg) {
                      case "-help":
                          System.out.println(helpMsg);
                          break;
                      case "-e":
                          var toEncode = getAndCheckArg(args);
                          System.out.println(new String(Base64.getEncoder().encode(toEncode.getBytes())));
                          break;
                      case "-d":
                          var toDecode = getAndCheckArg(args);
                          System.out.println(new String(Base64.getDecoder().decode(toDecode.getBytes())));
                          break;
                      default:
                          System.err.println("Unknown command, use -help to see how to use this tool.");
                          break;
                    }
                    System.exit(1);
                }
            
                static String getAndCheckArg(String[] args) {
                    if (args == null || args.length < 2) {
                        System.err.println("Please input valid string");
                        System.exit(0);
                    }
                    return args[1];
                }
            }
            ```

        - 使用 native-image 编译构建可执行程序
          
            ```bash
            ant@ant:~/native$ javac Base64Tool.java 
            ant@ant:~/native$ native-image Base64Tool
            ========================================================================================================================
            GraalVM Native Image: Generating 'base64tool' (executable)...
            ========================================================================================================================
            [1/8] Initializing...                                                                                    (1.7s @ 0.14GB)
             Java version: 17.0.9+9, vendor version: GraalVM CE 17.0.9+9.1
             Graal compiler: optimization level: 2, target machine: x86-64-v3
             C compiler: gcc (linux, x86_64, 11.4.0)
             Garbage collector: Serial GC (max heap size: 80% of RAM)
            [2/8] Performing analysis...  [****]                                                                     (4.4s @ 0.27GB)
               2,912 (71.67%) of  4,063 types reachable
               3,536 (50.94%) of  6,942 fields reachable
              13,209 (43.86%) of 30,116 methods reachable
                 907 types,     0 fields, and   348 methods registered for reflection
                  58 types,    58 fields, and    52 methods registered for JNI access
                   4 native libraries: dl, pthread, rt, z
            [3/8] Building universe...                                                                               (0.9s @ 0.30GB)
            [4/8] Parsing methods...      [*]                                                                        (0.6s @ 0.32GB)
            [5/8] Inlining methods...     [***]                                                                      (0.5s @ 0.22GB)
            [6/8] Compiling methods...    [**]                                                                       (4.5s @ 0.35GB)
            [7/8] Layouting methods...    [*]                                                                        (0.7s @ 0.37GB)
            [8/8] Creating image...       [*]                                                                        (1.1s @ 0.38GB)
               4.42MB (36.75%) for code area:     7,506 compilation units
               7.04MB (58.46%) for image heap:   89,275 objects and 5 resources
             590.55kB ( 4.79%) for other data
              12.03MB in total
            ------------------------------------------------------------------------------------------------------------------------
            Top 10 origins of code area:                                Top 10 object types in image heap:
               3.37MB java.base                                         1009.70kB byte[] for code metadata
             795.13kB svm.jar (Native Image)                             889.53kB java.lang.String
             112.32kB java.logging                                       836.32kB byte[] for general heap data
              62.07kB org.graalvm.nativeimage.base                       671.94kB java.lang.Class
              24.15kB jdk.internal.vm.ci                                 665.65kB byte[] for java.lang.String
              23.14kB org.graalvm.sdk                                    347.48kB java.util.HashMap$Node
               6.11kB jdk.internal.vm.compiler                           250.25kB com.oracle.svm.core.hub.DynamicHubCompanion
               1.68kB Base64Tool                                         169.02kB java.lang.String[]
               1.35kB jdk.proxy1                                         165.57kB java.lang.Object[]
               1.27kB jdk.proxy3                                         148.84kB byte[] for embedded resources
               1.56kB for 2 more packages                                  1.20MB for 829 more object types
            ------------------------------------------------------------------------------------------------------------------------
            Recommendations:
             HEAP: Set max heap for improved and more predictable memory usage.
             CPU:  Enable more CPU features with '-march=native' for improved performance.
            ------------------------------------------------------------------------------------------------------------------------
                                    0.7s (4.3% of total time) in 164 GCs | Peak RSS: 0.84GB | CPU load: 8.21
            ------------------------------------------------------------------------------------------------------------------------
            Produced artifacts:
             /home/ant/native/base64tool (executable)
            ========================================================================================================================
            Finished generating 'base64tool' in 14.8s.
            ```
            
        - 使用
          
            ```bash
            ant@ant:~/native$ ./base64tool -help
            -e Encode input string
            -d Decode input string
            
            ant@ant:~/native$ ./base64tool -e saveole
            c2F2ZW9sZQ==
            ant@ant:~/native$ ./base64tool -d c2F2ZW9sZQ==
            saveole
            ant@ant:~/native$ 
            ```
    
- 注意事项
    - 使用 native-image 构建可执行程序时，需要注意当前的执行目录。它默认会扫描当前目录及子目录下的所有文件(不能区分 Java 程序相关的文件)，导致构建失败。建议在单独的文件夹中进行编译构建。