---
title: 博客方案：Jekyll + Chirpy
date: 2024-05-31 13:38:00 +0800
categories: [博客]
tags: [Jekyll]     # TAG names should always be lowercase
description: 将自己的建站方案从 Gmeek 迁移到 Jekyll + Chirpy 的过程和一些体验
---



- 安装 Jekyll
    - 先装 Ruby 和相关依赖项: `sudo apt-get install ruby-full build-essential zlib1g-dev`
    - 设置当前用户有 `gem` 的执行权限
      
        ```bash
        echo '# Install Ruby Gems to ~/gems' >> ~/.bashrc
        echo 'export GEM_HOME="$HOME/gems"' >> ~/.bashrc
        echo 'export PATH="$HOME/gems/bin:$PATH"' >> ~/.bashrc
        source ~/.bashrc
        ```
        
    - 安装 Jekyll: `gem install jekyll bundler`
    
- 使用 Chirpy 主题
    - Clone 或下载 https://github.com/cotes2020/chirpy-starter 仓库
    - 安装依赖： `bundle`
    - 启动项目： `bundle exec jekyll s`
    - 访问：http://localhost:4000
    
- 基本配置及写 post
    - https://chirpy.cotes.page/posts/getting-started/
    - https://chirpy.cotes.page/posts/write-a-new-post/
    
- 初次感受
    - 清新简洁，大方美观，响应迅速
    - 定制项挺多，支持视频/音频等媒体格式
    - 从自己平时写的 Markdown 文件转换过来要改造的内容也挺多的， 可以考虑写个程序做这个事情
    - 其他更细致的体验待自己深入使用再评价
    
- Changelog
  
    > 准备使用这个作为自己的博客框架，先把博客写起来再谈其他
    >
    > - [x]  头像/联系方式等设置
    > - [x]  [favicon 替换](https://chirpy.cotes.page/posts/customize-the-favicon/)
    > - [x]  接入 [giscus](https://giscus.app/zh-CN) 评论系统 - [martin‘s blog](https://blog.martinp7r.com/posts/adding-giscus-comments-to-my-blog/)
    > - [x]  [接入 Google Analytics](https://nokids.fun/posts/chirpy-add-google-analytics/)
    > - [ ]  国内网络环境加速 - 是否有必要？

- 和 [Gmeek](https://github.com/Meekdai/Gmeek) 的简单对比
  - 之前的博客框架主要根据 [GitHub Issue as a Blog](https://dylanninin.com/blog/2023/05/08/github-issue-as-a-blog.html) 和 [Gmeek 快速上手](https://blog.meekdai.com/post/Gmeek-kuai-su-shang-shou.html) 构建的。
  - Gmeek 是基于 GitHub Issues 的，最大的特点就是简洁, 然后是都基于 GitHub 平台，不用在本地安装各种环境，遇到的最大问题是之前 Gmeek 提供的 Github Action 脚本不兼容，导致后续的构建失败。
  - Chirpy 对于 Gmeek 的话，我个人感觉页面布局要好一点，可配置的地方也要丰富一点。