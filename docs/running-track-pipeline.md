# 跑步轨迹数据获取与生成流程

本文档描述从 Garmin Connect 获取跑步活动数据、解析 GPS 轨迹、编码存储、前端 SVG 可视化，以及轨迹相似度计算的完整流程。

---

## 整体架构概览

```mermaid
graph TB
    subgraph 数据源
        GC[Garmin Connect<br/>garmin.cn]
    end

    subgraph 定时同步
        GHA["GitHub Actions<br/>每日 02:00 UTC"]
        SYNC["scripts/sync_garmin.py"]
    end

    subgraph 数据存储
        ACT["running-data/activities.json<br/>活动汇总数据"]
        FIT["running-data/fit/*.fit<br/>原始 FIT 文件"]
        BODY["running-data/body.json<br/>身体指标数据"]
    end

    subgraph 构建生成
        BUILD["build.js<br/>Node.js 构建脚本"]
        EJS["theme/running.ejs<br/>跑步页模板"]
        DIST["dist/running.html<br/>最终页面"]
    end

    subgraph 前端计算
        SIM["Grid Jaccard<br/>轨迹相似度计算"]
        OVERLAY["相似路线<br/>弹窗展示"]
    end

    GC -->|"OAuth2 API"| SYNC
    GHA -->|"cron 触发"| SYNC
    SYNC -->|"写入"| ACT
    SYNC -->|"写入"| FIT
    BUILD -->|"读取 activities.json"| ACT
    BUILD -->|"读取 body.json"| BODY
    BUILD -->|"渲染模板"| EJS
    EJS --> DIST
    DIST -->|"客户端计算"| SIM
    SIM -->|"点击交互"| OVERLAY
```

---

## 阶段一：定时同步（GitHub Actions）

同步由 GitHub Actions 工作流 `.github/workflows/sync-garmin.yml` 触发。

```mermaid
flowchart TD
    A["🕐 每日 UTC 02:00<br/>（北京时间 10:00）<br/>或手动 workflow_dispatch"] --> B["Checkout 仓库"]
    B --> C["安装 Python 3.12"]
    C --> D["pip install garth"]
    D --> E["运行 sync_garmin.py"]
    E --> F{"activities.json<br/>有变更？"}
    F -- 是 --> G["git commit & push"]
    F -- 否 --> H["结束（无变更）"]
    G --> H
```

**关键配置：**
- 认证凭据 `GARMIN_SECRET` 存储在 GitHub Secrets 中
- 使用 `garth` 库管理 OAuth2 令牌（自动刷新）
- 仅提交 `running-data/activities.json` 的变更

---

## 阶段二：数据获取与处理（sync_garmin.py）

这是核心的 Python 脚本，负责从 Garmin Connect API 获取跑步数据并提取 GPS 轨迹。

```mermaid
flowchart TD
    START["sync_garmin.py 启动"] --> AUTH["OAuth2 认证<br/>garth.configure(domain=garmin.cn)<br/>garth.client.loads(secret)"]
    AUTH --> |"令牌过期"| REFRESH["刷新 OAuth2 Token"]
    AUTH --> |"令牌有效"| LOAD["加载已有 activities.json<br/>用于增量同步"]
    REFRESH --> LOAD

    LOAD --> MODE{"运行模式？"}

    MODE -- "默认模式" --> INCR["增量同步<br/>startDate = 昨天日期"]
    MODE -- "--full-fit" --> FULL["全量拉取<br/>startDate = null"]
    MODE -- "--fit-only" --> FITONLY["仅补充 FIT 文件"]

    INCR --> FETCH["调用 Garmin API<br/>分页获取跑步活动列表"]
    FULL --> FETCH
    FITONLY --> FETCH_ALL["调用 Garmin API<br/>获取全部活动 ID"]
    FETCH --> AGG
    FETCH_ALL --> BACKFILL

    subgraph 聚合处理
        AGG["按日期聚合活动<br/>同一天多次跑步合并"] --> CALC["计算加权指标<br/>• 距离、时长直接累加<br/>• 心率按距离加权平均<br/>• 步频按距离加权平均<br/>• 最大心率、VO2Max 取最大值"]
    end

    CALC --> POLY{"哪些活动<br/>缺少轨迹？"}
    POLY --> NEEDS["对比已有数据<br/>筛选无 polyline 的活动"]

    NEEDS --> DOWNLOAD["下载 FIT 文件"]
    DOWNLOAD --> PARSE["解析 GPS 坐标"]
    PARSE --> ENCODE["编码为 Google Polyline"]
    ENCODE --> MERGE["合并到 day_map"]
    MERGE --> FINAL

    BACKFILL --> DOWNLOAD
    FINAL["格式化输出<br/>• 距离保留 1 位小数<br/>• 计算平均配速<br/>• 清除临时字段"] --> SAVE["保存 activities.json<br/>按日期排序"]
```

### Garmin API 调用细节

```mermaid
sequenceDiagram
    participant Script as sync_garmin.py
    participant Garth as garth (OAuth2)
    participant Garmin as Garmin Connect API

    Script->>Garth: loads(GARMIN_SECRET)
    Garth->>Garth: 检查 Token 是否过期
    alt Token 已过期
        Garth->>Garmin: refresh_oauth2()
        Garmin-->>Garth: 新 Token
    end

    loop 分页获取（每页 100 条）
        Script->>Garmin: GET /activitylist-service/activities/search/activities
        Note right of Garmin: 参数: start, limit, activityType=running, startDate
        Garmin-->>Script: 活动列表 JSON
    end

    loop 对每个缺少轨迹的活动
        Script->>Garmin: GET /download-service/files/activity/{id}
        Garmin-->>Script: ZIP 包（含 .fit 文件）
        Script->>Script: 解压 ZIP → 提取 .fit
        Script->>Script: 解析 FIT → GPS 坐标
        Script->>Script: 编码为 Google Polyline
    end
```

---

## 阶段三：GPS 坐标解析与 Polyline 编码

### FIT 文件解析

```mermaid
flowchart LR
    subgraph "FIT 文件结构"
        FIT["FIT 二进制文件"] --> REC["record 消息<br/>（每秒一条）"]
        REC --> LAT["position_lat<br/>semicircle 单位"]
        REC --> LON["position_long<br/>semicircle 单位"]
    end

    subgraph "坐标转换"
        LAT --> |"× (180 / 2³¹)"| DEGLAT["十进制纬度"]
        LON --> |"× (180 / 2³¹)"| DEGLON["十进制经度"]
    end

    subgraph "数据精简"
        DEGLAT --> CHECK{"坐标点 > 400？"}
        DEGLON --> CHECK
        CHECK -- 是 --> THIN["每 5 个点取 1 个<br/>体积减少 ~80%"]
        CHECK -- 否 --> KEEP["保留全部"]
    end

    THIN --> ENCODE["Google Polyline 编码"]
    KEEP --> ENCODE
```

### Google Encoded Polyline 算法

```mermaid
flowchart TD
    INPUT["输入: [(lat₁, lng₁), (lat₂, lng₂), ...]"] --> INIT["初始化: last_lat = 0, last_lng = 0"]

    INIT --> LOOP["遍历每个 (lat, lng)"]
    LOOP --> DELTA["计算差值<br/>δlat = round(lat × 10⁵) - last_lat<br/>δlng = round(lng × 10⁵) - last_lng"]

    DELTA --> SIGNED["有符号编码<br/>若 value < 0: value = ~(value << 1)<br/>若 value ≥ 0: value = value << 1"]

    SIGNED --> CHUNKS["分块编码<br/>每 5 bit 一组, 低有效位在前<br/>每组 OR 0x20 表示后续有更多<br/>每组 + 63 转为 ASCII"]

    CHUNKS --> APPEND["追加到结果字符串"]
    APPEND --> UPDATE["更新 last_lat, last_lng"]
    UPDATE --> MORE{"还有更多点？"}
    MORE -- 是 --> LOOP
    MORE -- 否 --> OUTPUT["输出: 编码字符串<br/>例: _gv~H~ps@..."]
```

**编码示例：**

| 步骤 | 值 | 说明 |
|------|------|------|
| 原始纬度 | `39.9042` | 北京天安门附近 |
| × 10⁵ 取整 | `3990420` | 转为整数 |
| 首点 δ | `3990420` | 第一个点无差值 |
| 左移 1 位 | `7980840` | `value << 1` |
| 分块 | `0x14 0x6E 0x79 0x00` | 每 5 bit 一组 |
| +63 转 ASCII | `"..."` | 最终编码字符 |

---

## 阶段四：数据存储格式

### activities.json 结构

```json
[
  {
    "date": "2026-05-25",
    "start_time": "07:15:32",
    "type": "running",
    "distance_km": 8.5,
    "duration_s": 2550,
    "avg_pace_s_per_km": 300,
    "avg_hr": 155,
    "max_hr": 172,
    "cadence_spm": 178.5,
    "vo2max": 48.2,
    "summary_polyline": "_gv~H~ps@..."
  }
]
```

| 字段 | 类型 | 说明 |
|------|------|------|
| `date` | string | 活动日期 YYYY-MM-DD |
| `start_time` | string | 开始时间 HH:MM:SS |
| `type` | string | `running`（户外）或 `treadmill_running`（跑步机） |
| `distance_km` | float | 距离（公里），同日多次跑步累加 |
| `duration_s` | int | 时长（秒），同日累加 |
| `avg_pace_s_per_km` | int | 平均配速（秒/公里） |
| `avg_hr` | int | 平均心率，按距离加权 |
| `max_hr` | int | 最大心率，取当日最大 |
| `cadence_spm` | float | 平均步频（步/分钟），按距离加权 |
| `vo2max` | float | 最大摄氧量，取当日最大 |
| `summary_polyline` | string | GPS 轨迹的 Google Polyline 编码 |

---

## 阶段五：构建处理（build.js）

构建脚本读取 JSON 数据，格式化后注入 EJS 模板。

```mermaid
flowchart TD
    START["build.js 启动"] --> READ["读取 running-data/activities.json 和 body.json"]

    READ --> FORMAT_ACT["格式化活动列表<br/>配速: 秒转为分秒格式<br/>时长: 秒转为分钟<br/>按日期降序排列"]

    READ --> FILTER["筛选轨迹数据<br/>polyline 非空且距离大于等于5km<br/>按日期降序排列"]

    READ --> TIMELINE["构建统一时间线<br/>合并活动日期与身体指标日期"]

    FORMAT_ACT --> INJECT["组装 runningPageData<br/>activitiesJSON: 活动列表<br/>tracksJSON: 轨迹列表<br/>bodyJSON: 身体数据<br/>timelineJSON: 时间线"]
    FILTER --> INJECT
    TIMELINE --> INJECT

    INJECT --> RENDER["ejs.render 渲染 running.ejs"]
    RENDER --> OUTPUT["输出 dist/running.html"]
```

**轨迹筛选条件：**
1. `summary_polyline` 不为空（有 GPS 数据的户外跑）
2. `distance_km >= 5`（至少 5 公里）
3. 前端最多显示 **9 条**最近轨迹

---

## 阶段六：前端可视化与相似度（running.ejs）

```mermaid
flowchart TD
    LOAD["页面加载<br/>注入 JSON 数据到 JS 变量"] --> READCSS["读取 CSS 变量<br/>获取主题颜色"]
    READCSS --> TABS["初始化 Tab 切换<br/>轨迹 / 图表"]

    TABS --> RENDER["renderTracks()"]
    RENDER --> CHECK{"已有 DOM 节点？"}
    CHECK -- 是 --> SKIP["跳过（已渲染）"]
    CHECK -- 否 --> LOOP["遍历最近 9 条轨迹"]

    LOOP --> DECODE["decodePolyline<br/>解码 Google Polyline"]
    DECODE --> SVG["buildTrackSVG<br/>生成 SVG polyline"]

    SVG --> CARD["包装为 track-card<br/>显示日期、距离、配速"]
    CARD --> GRID["追加到 tracksGrid"]

    GRID --> SIM{"轨迹数 >= 2？"}
    SIM -- 是 --> COMPUTE["computeSimilarityMatrix<br/>计算 Grid Jaccard 相似度"]
    SIM -- 否 --> DONE["完成"]

    COMPUTE --> BADGE{"有相似匹配？"}
    BADGE -- 是 --> MARK["添加 has-similar 类<br/>显示相似数量徽章<br/>绑定点击事件"]
    BADGE -- 否 --> DONE
    MARK --> DONE
```

### Polyline 解码过程

```mermaid
flowchart LR
    subgraph "编码字符串"
        STR["'_gv~H~ps@...'"]
    end

    subgraph "逐字符解码"
        CHR["读取字符"] --> |"- 63"| FIVE["提取 5-bit 块"]
        FIVE --> |"继续标志 ≥ 0x20"| CHR
        FIVE --> |"结束"| COMBINE["组合为整数"]
    end

    subgraph "还原坐标"
        COMBINE --> CHECK2{"最低位 = 1？"}
        CHECK2 -- 是 --> NEG["右移 1 位 → 取反<br/>负数差值"]
        CHECK2 -- 否 --> POS["右移 1 位<br/>正数差值"]
        NEG --> ACC["累加到 lat/lng"]
        POS --> ACC
        ACC --> |"÷ 10⁵"| RESULT["[lat, lng] 十进制坐标"]
    end

    STR --> CHR
```

### SVG 轨迹渲染原理

```
┌─────────────────────────────┐
│  SVG viewBox="0 0 200 200"  │
│                             │
│   pad=5                     │
│   ┌───────────────────┐     │
│   │    ╭───╮          │     │
│   │   ╱    ╲    ╭─╮   │     │
│   │  ╱      ╲──╯  ╲  │     │
│   │ ╱              ╲ │     │
│   │╱                 ╰╯     │
│   └───────────────────┘     │
│                             │
│  2026-05-25                 │
│  8.5 km · 5'00"            │
└─────────────────────────────┘
```

- 所有坐标归一化到 `[5, 195]` 范围（留 5px 内边距）
- Y 轴翻转（纬度越大越靠上）
- 使用 SVG `<polyline>` 绘制连续路径
- 无需外部地图库，纯 SVG 渲染

---

## 阶段七：轨迹相似度计算（Grid Jaccard）

### 为什么需要相似度

跑者经常重复跑同一条路线。相似度计算帮助识别「哪些日子跑了相同的路线」，发现训练规律。

### 方案选型

| 方案 | 复杂度 | 准确性 | 抗速度差异 | 选择 |
|------|--------|--------|-----------|------|
| Fréchet Distance | 高（DP 矩阵） | 优秀 | 好 | 过重 |
| DTW | 高（DP 矩阵） | 好 | 优秀 | 不必要 |
| Hausdorff Distance | 中 | 差 | — | 小分支误判 |
| **Grid Jaccard** | **低（~30 行）** | **好** | **天然支持** | **✅ 采用** |
| Bounding Box | 极低 | 差 | — | 过于粗糙 |
| Route Hashing | 中 | 仅精确匹配 | 差 | 过于严格 |

### 算法原理

将 GPS 坐标离散化为网格单元，比较两条轨迹覆盖的网格重叠度（Jaccard 系数 = 交集 / 并集）。

```mermaid
flowchart TD
    subgraph "1. 预处理"
        RAW["原始 Polyline"] --> DECODE["decodePolyline<br/>解码为坐标数组"]
        DECODE --> SAMPLE["downsampleTrack<br/>均匀采样至 80 个点"]
    end

    subgraph "2. 网格化"
        SAMPLE --> QUANT["量化为网格单元<br/>cellSize = 0.0004 度（约 44 米）<br/>key = round(lat/cellSize), round(lng/cellSize)"]
        QUANT --> SET["构建 Set<br/>每条轨迹的唯一网格集合"]
    end

    subgraph "3. Jaccard 计算"
        SETA["轨迹 A 的网格集合"] --> INTER["计算交集大小"]
        SETB["轨迹 B 的网格集合"] --> INTER
        SETA --> UNION["计算并集大小"]
        SETB --> UNION
        INTER --> JACCARD["Jaccard = 交集 / 并集"]
        UNION --> JACCARD
    end

    JACCARD --> THRESH{"Jaccard >= 0.20？"}
    THRESH -- 是 --> MATCH["标记为相似路线"]
    THRESH -- 否 --> DIFF["不同路线"]
```

### 参数说明

| 参数 | 值 | 说明 |
|------|------|------|
| `cellSize` | `0.0004` 度 | 约 44 米，覆盖半个街区，允许小偏差 |
| `sampleCount` | `80` 个点 | 统一采样密度，消除速度差异影响 |
| `threshold` | `0.20` | Jaccard >= 20% 视为相似路线 |

### 算法优势

- **天然抗速度差异**：比较空间覆盖，不比较点顺序，快跑慢跑同一路线结果一致
- **容错性好**：44 米网格单元意味着偏离一两个路口仍能匹配
- **部分匹配**：5km 短路线与 10km 长路线共享路段时，Jaccard 反映重叠比例
- **纯前端计算**：无需后端，9 条轨迹 36 对比较 < 5ms

### 相似路线交互流程

```mermaid
flowchart TD
    PAGE["页面加载<br/>9 条轨迹卡片"] --> RENDER["渲染 track-card 网格"]
    RENDER --> COMPUTE["computeSimilarityMatrix<br/>计算所有轨迹对相似度"]
    COMPUTE --> BADGE["有匹配的卡片显示<br/>右上角蓝色徽章（相似数量）"]

    BADGE --> CLICK["用户点击带徽章的卡片"]
    CLICK --> OVERLAY["弹出相似路线面板"]
    OVERLAY --> MAIN["显示选中轨迹<br/>大号 SVG（400x180）"]
    MAIN --> LIST["显示相似轨迹列表<br/>缩略图 + 相似百分比"]

    LIST --> NAV["点击缩略图可切换主轨迹"]
    NAV --> CLOSE["点击遮罩 / Escape 关闭面板"]
```

### UI 元素

| 元素 | 样式 | 作用 |
|------|------|------|
| `.track-similar-badge` | 右上角蓝色圆角标签 | 显示相似路线数量 |
| `.track-card.has-similar` | 鼠标指针变手型，悬停蓝色边框 | 提示可点击查看相似路线 |
| `.similar-overlay` | 全屏半透明遮罩 | 弹窗背景 |
| `.similar-panel` | 居中白色面板 | 包含主轨迹 + 相似列表 |
| `.similar-track-thumb` | 水平滚动缩略图 | 每个显示日期 + 相似百分比 |

---

## 完整数据流总结

```mermaid
flowchart LR
    subgraph "1️⃣ Garmin Connect"
        A["跑步活动<br/>GPS + 传感器数据"]
    end

    subgraph "2️⃣ Python 同步"
        B["OAuth2 认证"]
        C["API 获取活动列表"]
        D["下载 FIT 原始文件"]
        E["解析 GPS → Polyline"]
        F["聚合 + 保存 JSON"]
    end

    subgraph "3️⃣ Node.js 构建"
        G["读取 JSON"]
        H["格式化 + 筛选"]
        I["注入 EJS 模板"]
    end

    subgraph "4️⃣ 前端渲染"
        J["解码 Polyline"]
        K["坐标归一化"]
        L["SVG 渲染轨迹"]
    end

    subgraph "5️⃣ 相似度计算"
        M["Grid Jaccard 算法"]
        N["标记相似路线"]
        O["弹窗交互展示"]
    end

    A --> B --> C --> D --> E --> F --> G --> H --> I --> J --> K --> L --> M --> N --> O
```

---

## 关键技术决策

| 决策 | 选择 | 原因 |
|------|------|------|
| GPS 编码格式 | Google Encoded Polyline | 紧凑（比 JSON 坐标数组小 ~80%），前端解码简单 |
| 轨迹渲染方式 | SVG polyline | 无需地图 SDK，轻量级，适合展示路线轮廓 |
| 坐标精简策略 | >400 点时每 5 取 1 | Garmin 每秒记录，1 小时 3600 点；精简后视觉无损 |
| 同步策略 | 增量（默认）+ 全量（`--full-fit`） | 日常增量快速；全量用于补充缺失轨迹 |
| 同日多次跑步 | 距离/时长累加，心率加权 | 避免同日多条记录，保持日期维度唯一 |
| 户外 vs 跑步机 | 有 polyline 为户外，无则为跑步机 | 跑步机无 GPS，polyline 为空自然区分 |
| 相似度算法 | Grid Jaccard | 实现简单（~30 行），天然抗速度差异，前端计算 < 5ms |
| 网格单元大小 | 0.0004 度（约 44 米） | 覆盖半个街区，允许路线小幅偏差仍能匹配 |
| 相似度阈值 | 0.20（20%） | 区分同小区不同路线与真正重复路线 |
| 相似度计算时机 | 前端页面加载后 | 静态站点无后端，纯客户端计算 |
