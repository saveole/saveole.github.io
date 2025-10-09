---
title: 阿里云百炼大模型配合自家云效 DevOps MCP token 消耗巨大
date: 2025-10-09 19:50:30 +0800
categories: [AI Coding]
tags: [阿里云, Java, Claude Code, MCP]
description: 一个小需求用了阿里云百炼大模型+yuxiao mcp 一下子干掉了 25 RMB,还是得用订阅模式。
---

## 摘要
​    试用阿里云效 devops 平台[推荐](https://help.aliyun.com/zh/lingma/use-cases/mcp-usage-practice-1)的 [mcp 工具](https://www.modelscope.cn/mcp/servers/@aliyun/alibabacloud-devops-mcp-server)进行 ai coding 的实践,刚弄一个不算太大的需求试水，结果阿里云百炼大模型 + yuxiao mcp 一下子花费了 25 RMB, 记录下这次坑爹的经历。如有条件，还是得远离国内云服务！

## 过程

- 探索如何在公司的项目(devops 试用的阿里云效)中落地 ai coding，看到 [通义灵码+云效 DevOps MCP：通过云效工作项自动生成代码并提交请求](https://help.aliyun.com/zh/lingma/use-cases/mcp-usage-practice-1) 的推荐再加上最近 cc + mcp 的实践，想着只要将我的变更需求写小写细，应该能够通过上述的流程实现日常需求的 ai coding，自己只需要做好 review 就好。

- **需求任务工单**

  ```
  接口：PUT scrm-api/form/component
    数据结构示例：
    {
      "components": [
        {
          "name": "输入框",
          "type": "input",
          "config": [
            {
              "label": "姓名",
              "checked": true,
              "disabled": true,
              "switchActive": true,
              "isCustomize": false
            },
            {
              "label": "手机号",
              "checked": true,
              "disabled": true,
              "switchActive": true,
              "isCustomize": false
            },
            {
              "label": "短信验证",
              "checked": true,
              "noShow": true
            }
          ]
        },
        {
          "name": "单选项",
          "type": "radioButton",
          "config": [
            {
              "label": "年龄段",
              "checked": true,
              "disabled": false,
              "switchActive": true,
              "isCustomize": false,
              "children": [
                {
                  "label": "22"
                },
                {
                  "label": "33"
                }
              ],
              "mappingFields": []
            }
          ]
        },
        {
          "name": "多选项",
          "type": "multipleChoices",
          "config": [
            {
              "label": "目前遇到的问题",
              "checked": true,
              "disabled": false,
              "switchActive": true,
              "isCustomize": false,
              "children": [
                {
                  "label": "啊啊"
                },
                {
                  "label": "搜索xx"
                }
              ],
              "mappingFields": []
            }
          ]
        }
      ],
      "name": "如测22",
      "hint": "",
      "hintChecked": false,
      "id": "6721931e1bcfd54f1f532457"
    }
    1. components.config.label 字段字数限制调整为不超过 50 字
    2. 将姓名和手机号(+短信验证)分离出来为两个单独 component
    3. 所有component 添加排序字段 sort
  ```

- 首先使用了智谱的 api key，发现任务执行会**中断**，然后换的阿里百炼的 api key(用的 cc switch 做的切换)

  ```
  > 调用 yunxiao mcp 中的工具，获取 兴智技术项目管理项目中8.3.0迭代中Id 为NFQX-10950的任务详情,读取任务详情中上下文相关的代码，生成详细的代码执行计划(不需要执行)，写入到 NFQX-10950.md 文件中供我review 
  
  ● 我需要获取云效项目中具体任务的详情。让我先找到您的组织和项目信息，然后获取指定任务的详情。
    ⎿  {                                                                                                                                                                                                                         
         "lastOrganization": "xxxxxxxxxxxxx",
         "userId": "xxxxxxxxxxxxxxx",
       … +2 lines (ctrl+o to expand)
    ⎿  {                                                                                                                                                                                                                         
         "id": "xxxxxxx",
         "name": "xxxx",
       … +4 lines (ctrl+o to expand)
  
    Todos
    ☒ 获取当前用户和组织信息
    ☐ 查找兴智技术项目
    ☐ 获取8.3.0迭代信息
    ☐ 获取任务NFQX-10950详情
    ☐ 分析任务上下文和相关代码
    ☐ 生成详细的代码执行计划
    ☐ 写入NFQX-10950.md文件
  ```

  - 可以看到调用一次 mcp 的 tool 就中断了，这块需要看看原因。

- **执行历史(倒序查看)**

  ```
  {
      "display": "对于姓名和手机号未分离的历史数据，在修改的时候自动进行分离",
  	"pastedContents": {}
  },
  {
      "display": "FormComponentByWebDTOTest#testValidateLabelLengthFailure 测试失败",
  	"pastedContents": {}
  },
  {
  	"display": "调用 yunxiao mcp 中的工具，获取 兴智技术项目管理项目中8.3.0迭代中Id 为NFQX-10950的任务详情,读取任务详情中相关的代码，生成详细的代码执行计划，写入到 NFQX-10950.md 文件中",
  	"pastedContents": {}
  },
  {
  	"display": "/exit ",
  	"pastedContents": {}
  },
  {
  	"display": "调用 yunxiao mcp 中的工具，获取 兴智技术项目管理项目中8.3.0迭代中Id 为NFQX-10950的任务详情",
  	"pastedContents": {}
  },
  {
  	"display": "/exit ",
  	"pastedContents": {}
  },
  {
  	"display": "将上述代码编写计划写入到 NFQX-10950.md 文件中",
  	"pastedContents": {}
  },
  {
  	"display": "执行上述修改",
  	"pastedContents": {}
  },
  {
  	"display": "根据上述任务需求描述生成详细的代码编写计划并写入文档，供我review",
  	"pastedContents": {}
  },
  {
  	"display": "调用 yunxiao mcp 中的工具，获取 兴智技术项目管理项目中8.3.0迭代中Id 为NFQX-10950的任务详情",
  	"pastedContents": {}
  },
  {
  	"display": "调用 yunxiao mcp 中的工具，获取 兴智技术项目管理项目中8.3.0迭代中我的任务列表",
  	"pastedContents": {}
  }
  ```

- **效果(通过测试的 Git 提交总结)**

  ```
  提交信息: feat:#NFQX-10950 作者: saveole 提交时间:
  2025年10月9日 11:16:33
  
  📊 统计信息
  - 修改文件数: 4个
  - 代码行数变更: +395行, -1行
  
  📁 修改的文件
    1.scrm/src/main/java/com/ds/scrm/model/promo/dto/FormComponentByWebDTO.java
    2. scrm/src/main/java/com/ds/scrm/model/promo/entity/BaseComponent.java
    3. scrm/src/test/java/com/ds/scrm/model/promo/BaseComponentTest.java
    4. scrm/src/test/java/com/ds/scrm/model/promo/FormComponentByWebDTOTest.java
  
  🔧 主要功能改动
  1. FormComponentByWebDTO.java 核心功能增强
  - 自动分离姓名和手机号: 实现了 autoSeparateNameAndPhone() 方法，当检测到组
    件中同时包含姓名和手机号字段时，会自动将它们分离成独立的组件
  - 标签长度验证: 添加了字段标签长度限制，最多50个字符
  - 类型转换优化: 修复了 Hutool JSON 和 FastJSON 之间的类型转换问题
  
  2. BaseComponent.java 实体扩展
  - 新增排序字段: 添加了 sort 字段用于组件排序功能
  
  3. 测试用例完善
  - BaseComponentTest.java: 新增47行测试代码，测试排序字段和基础功能
  - FormComponentByWebDTOTest.java: 新增211行测试代码，覆盖以下场景：
    - 姓名和手机号分离成功案例
    - 自动分离功能测试
    - 标签长度验证测试
    - 排序字段测试
  ```

- Token 和费用消耗

  
