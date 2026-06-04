# Daniels 跑步法训练建议 —— 完整实现解析

> 基于 pbRun 项目的源码分析，提取可复用的 Daniels 训练法实现方案。

---

## 一、整体架构

整个 Daniels 训练法建议系统由三个核心模块组成：

```
                    ┌─────────────────────────┐
                    │  VDOT 跑力计算（同步时）   │
                    │  vdot-calculator.js      │
                    │  输入: 距离 + 时长 + 心率  │
                    │  输出: VDOT 值            │
                    └───────────┬─────────────┘
                                │
                    ┌───────────▼─────────────┐
                    │  当前跑力（展示时）        │
                    │  近一周活动的 VDOT 平均值   │
                    └───────────┬─────────────┘
                                │
               ┌────────────────┼────────────────┐
               │                │                │
    ┌──────────▼──────┐  ┌─────▼──────┐  ┌──────▼─────────┐
    │  配速区间换算     │  │ 心率区间    │  │  训练建议预警   │
    │  vdot-pace.ts    │  │ Z1-Z5 划分  │  │  AnalysisClient │
    │  VDOT→各区间配速  │  │ 按心率统计  │  │  偏差检测+提示   │
    └─────────────────┘  └────────────┘  └────────────────┘
```

---

## 二、VDOT 跑力计算

### 2.1 核心公式

来源：Jack Daniels《Daniels' Running Formula》

**步骤 1：由配速计算 VO2（摄氧量当量）**

```
VO2 = -4.60 + 0.182258 × v + 0.000104 × v²
```

其中 `v` = 速度（米/分钟）= 距离(米) / 时长(分钟)

**步骤 2：由运动时长计算 %VO2max（运动效率衰减）**

```
%VO2max = 0.8 + 0.1894393 × e^(-0.012778 × t) + 0.2989558 × e^(-0.1932605 × t)
```

其中 `t` = 运动时长（分钟）

- 时间越短（如 5K），能维持的 %VO2max 越高（接近 100%）
- 时间越长（如全马），能维持的 %VO2max 越低（约 80%）

**步骤 3：计算 VDOT**

```
VDOT = VO2 / %VO2max
```

### 2.2 代码实现

```javascript
/**
 * VDOT 跑力计算器
 * @param {number} distanceMeters  - 距离（米）
 * @param {number} durationSeconds - 时长（秒）
 * @param {number} avgHr          - 平均心率（可选，用于区间修正）
 * @param {number} maxHr          - 最大心率（需配置）
 * @param {number} restingHr      - 静息心率（需配置）
 * @returns {number|null} VDOT 值
 */
function calculateVdot(distanceMeters, durationSeconds, avgHr = null, maxHr, restingHr) {
  if (durationSeconds <= 0 || distanceMeters <= 0) return null;

  const durationMinutes = durationSeconds / 60;
  const velocityMPerMin = distanceMeters / durationMinutes;

  // 步骤 1: VO2
  const vo2 = -4.60 + 0.182258 * velocityMPerMin + 0.000104 * (velocityMPerMin ** 2);

  // 步骤 2: %VO2max
  const t = durationMinutes;
  const percentVo2max = 0.8
    + 0.1894393 * Math.exp(-0.012778 * t)
    + 0.2989558 * Math.exp(-0.1932605 * t);

  // 步骤 3: VDOT
  let vdot = vo2 / percentVo2max;

  // 可选: 心率区间修正
  if (avgHr && avgHr > 0 && maxHr) {
    const hrPercent = (avgHr / maxHr) * 100;
    let zone;
    if (hrPercent < 70) zone = 1;
    else if (hrPercent < 80) zone = 2;
    else if (hrPercent < 87) zone = 3;
    else if (hrPercent < 93) zone = 4;
    else zone = 5;

    const zoneMultipliers = {
      1: 0.97,  // 轻松跑 — 心率低，实际 VO2max 可能被低估
      2: 0.99,  // 有氧基础
      3: 1.00,  // 节奏跑 — 基准
      4: 1.00,  // 乳酸阈
      5: 1.00   // VO2max
    };
    vdot *= zoneMultipliers[zone] || 1.0;
  }

  // 合理范围检查: 业余跑者约 30-55，进阶 55+
  if (vdot < 20 || vdot > 100) return null;

  return Math.round(vdot * 10) / 10;
}
```

### 2.3 "当前跑力"的计算

取近一周所有活动的 VDOT 平均值，作为当前训练水平的代表：

```javascript
const currentVdot = weekStats.averageVDOT; // 近一周活动的 VDOT 均值
```

---

## 三、配速区间换算（VDOT → 建议配速）

### 3.1 反向求解：给定 VDOT 和强度百分比，求配速

已知 `VDOT × %VO2max = VO2`，代入 VO2 公式得到关于速度 v 的一元二次方程：

```
VDOT × percent = -4.60 + 0.182258 × v + 0.000104 × v²
```

整理得：

```
0.000104 × v² + 0.182258 × v + (-4.60 - VDOT × percent) = 0
```

用求根公式解出 v（取正根），然后配速 = 60000 / v（秒/公里）。

### 3.2 代码实现

```javascript
/**
 * 给定 VDOT 和 %VO2max，返回该强度下的配速（秒/公里）
 */
function vdotToPaceSecPerKm(vdot, percentVo2max) {
  if (vdot <= 0 || percentVo2max <= 0 || percentVo2max > 1) return 9999;

  // 一元二次: 0.000104*v² + 0.182258*v - (4.60 + vdot*percent) = 0
  const c = 4.60 + vdot * percentVo2max;
  const disc = 0.182258 ** 2 + 4 * 0.000104 * c; // 判别式
  if (disc < 0) return 9999;

  const v = (-0.182258 + Math.sqrt(disc)) / (2 * 0.000104); // 米/分钟
  if (v <= 0) return 9999;

  return 60000 / v; // 秒/公里
}
```

### 3.3 Z1-Z5 各区间的 %VO2max 取值

对应 Daniels 的 E（轻松）、M（马拉松配速）、T（乳酸阈）、I（间歇）强度：

| 区间 | 名称     | %VO2max | 对应 Daniels 强度 |
|------|----------|---------|-------------------|
| Z1   | 轻松     | 65%     | E 低端            |
| Z2   | 有氧     | 72%     | E 高端            |
| Z3   | 节奏     | 80%     | M（马拉松配速）    |
| Z4   | 乳酸阈   | 88%     | T（乳酸阈训练）    |
| Z5   | VO2max  | 98%     | I（间歇训练）      |

```javascript
const ZONE_PERCENT = {
  1: 0.65,  // Z1 轻松 ≈ E 低端
  2: 0.72,  // Z2 有氧 ≈ E 高端
  3: 0.80,  // Z3 节奏 ≈ M
  4: 0.88,  // Z4 乳酸阈 ≈ T
  5: 0.98,  // Z5 VO2max ≈ I
};
```

### 3.4 区间边界计算

相邻区间的中心配速取中点作为分界线：

```javascript
function getPaceZoneBounds(vdot) {
  // 先算出 5 个区间的中心配速
  const paces = [];
  for (let z = 1; z <= 5; z++) {
    paces.push(vdotToPaceSecPerKm(vdot, ZONE_PERCENT[z]));
  }
  // paces[0]=Z1(最慢), paces[4]=Z5(最快)

  const bounds = {};
  bounds[1] = { paceMin: (paces[0] + paces[1]) / 2, paceMax: 9999 };   // Z1: 从 Z1-Z2 中点到无穷慢
  bounds[2] = { paceMin: (paces[1] + paces[2]) / 2, paceMax: (paces[0] + paces[1]) / 2 };
  bounds[3] = { paceMin: (paces[2] + paces[3]) / 2, paceMax: (paces[1] + paces[2]) / 2 };
  bounds[4] = { paceMin: (paces[3] + paces[4]) / 2, paceMax: (paces[2] + paces[3]) / 2 };
  bounds[5] = { paceMin: 0,                       paceMax: (paces[3] + paces[4]) / 2 };  // Z5: 从无穷快到 Z4-Z5 中点
  return bounds;
}
```

**注意**：paceMax 是"更慢"的方向（秒/公里更大），paceMin 是"更快"的方向。一个 lap 的 average_pace 落在 `[paceMin, paceMax]` 范围内则归入该区间。

---

## 四、心率区间划分

按最大心率（MAX_HR）百分比划分，需在 .env 中配置：

| 区间 | 心率范围        | 含义          |
|------|----------------|---------------|
| Z1   | < 70% × MAX_HR | 恢复/轻松跑    |
| Z2   | 70%–80%        | 有氧基础       |
| Z3   | 80%–87%        | 节奏跑/马拉松  |
| Z4   | 87%–93%        | 乳酸阈训练     |
| Z5   | ≥ 93%          | VO2max 间歇    |

```javascript
function getHrZone(avgHr, maxHr) {
  const hrPercent = (avgHr / maxHr) * 100;
  if (hrPercent < 70) return 1;
  if (hrPercent < 80) return 2;
  if (hrPercent < 87) return 3;
  if (hrPercent < 93) return 4;
  return 5;
}
```

---

## 五、训练建议与偏差预警

### 5.1 心率区间时间占比 vs Daniels 建议比例

统计各心率区间的总跑步时间占比，与理想分布对比：

| 区间组合              | Daniels 建议 | 检测条件      | 预警类型 |
|----------------------|-------------|--------------|---------|
| Z1+Z2（轻松/有氧）    | ≥ 70%       | 实际 < 70%   | 不足警告 |
| Z3（节奏/马拉松配速） | ≤ 15%       | 实际 > 15%   | 超标警告 |
| Z4（乳酸阈）          | ≤ 10%       | 实际 > 10%   | 超标警告 |
| Z5（间歇/强度）       | ≤ 8%        | 实际 > 8%    | 超标警告 |

### 5.2 代码实现

```javascript
function checkHrZoneOverflow(hrZoneDurationByZone) {
  const totalSec = hrZoneDurationByZone.reduce((s, z) => s + z.total_duration, 0);
  if (totalSec <= 0) return [];

  const byZone = {};
  hrZoneDurationByZone.forEach(z => {
    byZone[z.zone] = (z.total_duration / totalSec) * 100;
  });

  const warnings = [];

  // Z1+Z2 合计不足 70%
  const z12 = (byZone[1] ?? 0) + (byZone[2] ?? 0);
  if (z12 < 70) {
    warnings.push({
      label: 'Z1-Z2（轻松/有氧）',
      actual: Math.round(z12 * 10) / 10,
      limit: '建议 ≥ 70%',
      type: 'under'
    });
  }

  // Z3 超标
  if ((byZone[3] ?? 0) > 15) {
    warnings.push({
      label: 'Z3（节奏/马拉松配速）',
      actual: Math.round((byZone[3] ?? 0) * 10) / 10,
      limit: '建议 ≤ 15%',
      type: 'over'
    });
  }

  // Z4 超标
  if ((byZone[4] ?? 0) > 10) {
    warnings.push({
      label: 'Z4（乳酸阈）',
      actual: Math.round((byZone[4] ?? 0) * 10) / 10,
      limit: '建议 ≤ 10%',
      type: 'over'
    });
  }

  // Z5 超标
  if ((byZone[5] ?? 0) > 8) {
    warnings.push({
      label: 'Z5（间歇/强度）',
      actual: Math.round((byZone[5] ?? 0) * 10) / 10,
      limit: '建议 ≤ 8%',
      type: 'over'
    });
  }

  return warnings;
}
```

### 5.3 配速区间统计

用当前 VDOT 算出 Z1-Z5 配速边界后，将数据库中每个 lap 的 `average_pace` 归入对应区间，统计各区间的：

- 活动次数（lap 数）
- 总时长、总距离
- 平均心率、平均步频、平均步幅

```javascript
function getPaceZoneStats(vdot, startDate, endDate) {
  const bounds = getPaceZoneBounds(vdot);

  // 从 DB 查出日期范围内的所有 laps
  const laps = db.prepare(`
    SELECT al.average_pace, al.average_heart_rate,
           al.average_cadence, al.average_stride_length,
           al.distance, al.duration
    FROM activity_laps al
    INNER JOIN activities a ON a.activity_id = al.activity_id
    WHERE a.start_time >= ? AND a.start_time <= ?
      AND al.average_pace IS NOT NULL AND al.distance > 0
  `).all(startDate, endDate);

  const zoneStats = {};
  for (let z = 1; z <= 5; z++) {
    zoneStats[z] = { count: 0, duration: 0, distance: 0, paces: [], hrs: [], cadences: [], strides: [] };
  }

  for (const lap of laps) {
    const pace = lap.average_pace;
    let zone = 0;
    for (let z = 1; z <= 5; z++) {
      const b = bounds[z];
      if (pace >= b.paceMin && pace <= b.paceMax) {
        zone = z;
        break;
      }
    }
    if (zone === 0) continue;

    const s = zoneStats[zone];
    s.count++;
    s.duration += lap.duration;
    s.distance += lap.distance;
    s.paces.push(pace);
    if (lap.average_heart_rate != null) s.hrs.push(lap.average_heart_rate);
    if (lap.average_cadence != null) s.cadences.push(lap.average_cadence);
    if (lap.average_stride_length != null) s.strides.push(lap.average_stride_length);
  }

  // 汇总输出
  return [1, 2, 3, 4, 5].map(zone => {
    const s = zoneStats[zone];
    const b = bounds[zone];
    return {
      zone,
      target_pace: vdotToPaceSecPerKm(vdot, ZONE_PERCENT[zone]), // 建议配速
      pace_range: `${formatPace(b.paceMax)} - ${formatPace(b.paceMin)}`, // 区间范围
      activity_count: s.count,
      total_duration: s.duration,
      total_distance: s.distance,
      avg_pace: average(s.paces),
      avg_heart_rate: average(s.hrs),
      avg_cadence: average(s.cadences),
      avg_stride_length: average(s.strides),
    };
  });
}
```

---

## 六、训练负荷计算

除了 VDOT 和区间建议，项目还实现了训练负荷（Training Load）的计算：

```javascript
function calculateTrainingLoad(durationSeconds, avgHr, maxHr) {
  const durationHours = durationSeconds / 3600;
  let baseLoad = durationHours * 100; // 基础负荷 = 小时 × 100

  if (avgHr && avgHr > 0 && maxHr) {
    const zone = getHrZone(avgHr, maxHr);
    const zoneFactors = {
      1: 0.6,   // 轻松恢复
      2: 0.8,   // 有氧基础
      3: 1.0,   // 节奏
      4: 1.3,   // 乳酸阈
      5: 1.5    // VO2max
    };
    baseLoad *= zoneFactors[zone] || 1.0;
  }

  return Math.round(baseLoad);
}
```

---

## 七、数据要求与前置条件

要让整个系统正常工作，需要以下数据：

### 必需

| 数据项        | 来源                  | 说明                          |
|--------------|----------------------|-------------------------------|
| 距离（米）     | Garmin FIT / Strava   | 每次活动的总距离               |
| 时长（秒）     | Garmin FIT / Strava   | 每次活动的总时长               |
| 平均心率（bpm）| Garmin FIT / Strava   | 用于 VDOT 计算、区间划分       |
| MAX_HR        | 用户手动配置           | 最大心率，用于心率区间划分      |
| RESTING_HR    | 用户手动配置           | 静息心率（可选，VDOT 计算用）   |

### 可选（增强精度）

| 数据项              | 来源         | 说明                          |
|--------------------|-------------|-------------------------------|
| 分段（laps）配速     | Garmin FIT  | 用于配速区间统计               |
| 逐秒心率/步频/步幅   | Garmin FIT  | 用于趋势图                    |
| 总爬升/海拔         | Garmin FIT  | 区分路跑/跑步机                |

---

## 八、完整数据流总结

```
┌──────────────────────────────────────────────────────────────────┐
│  数据同步阶段（脚本，每日自动）                                      │
│                                                                    │
│  Garmin FIT 文件                                                  │
│    ├── session（活动汇总）→ distance, duration, avg_hr             │
│    ├── laps（分段数据）  → 每段的 pace, hr, cadence, stride        │
│    └── records（逐秒采样）→ hr/cadence/stride 随时间变化            │
│                                                                    │
│  VDOT 计算:                                                        │
│    distance + duration + avg_hr → Daniels 公式 → vdot_value        │
│    duration + avg_hr → zone factor → training_load                │
│                                                                    │
│  写入 SQLite: activities / activity_laps / activity_records        │
└──────────────────────┬───────────────────────────────────────────┘
                       │
┌──────────────────────▼───────────────────────────────────────────┐
│  展示阶段（Next.js，用户访问时）                                     │
│                                                                    │
│  1. 读 DB → 近一周 VDOT 取平均 → "当前跑力"                         │
│                                                                    │
│  2. 当前跑力 × 5个%VO2max → Z1-Z5 建议配速                         │
│     （每区间: vdotToPaceSecPerKm(vdot, percent)）                   │
│                                                                    │
│  3. 各 lap 的 average_pace → 归入 Z1-Z5 → 统计各区间的             │
│     平均心率/步频/步幅 → 配速区间详细指标表                          │
│                                                                    │
│  4. 各活动心率 → 归入 Z1-Z5 → 统计总时间占比                       │
│     → 与 Daniels 建议比例对比 → 偏差预警                            │
│     （如 Z1+Z2 < 70% → "有氧基础不足"）                             │
└──────────────────────────────────────────────────────────────────┘
```

---

## 九、复用指南

### 最小实现（仅需 VDOT + 配速区间）

只需要以下公式即可在任意项目中实现 Daniels 训练建议：

1. **VDOT 计算**：距离 + 时长 → VO2 → %VO2max → VDOT
2. **配速反解**：VDOT + %VO2max → 一元二次求根 → 配速
3. **区间边界**：5 个中心配速取中点
4. **偏差检测**：实际占比 vs 建议比例

### 推荐技术栈

- **后端/脚本**：Node.js 或 Python（公式纯数学运算，语言无关）
- **数据库**：SQLite（轻量，随代码部署）
- **前端可视化**：ECharts 或 Chart.js（区间柱状图、趋势折线图）
- **自动化**：GitHub Actions 定时同步 + Vercel 部署

### 关键文件参考

| 功能             | pbRun 文件                         | 可复用度 |
|-----------------|------------------------------------|---------|
| VDOT 计算        | `scripts/common/vdot-calculator.js` | ★★★★★  |
| 配速区间换算      | `app/lib/vdot-pace.ts`             | ★★★★★  |
| 心率区间划分      | `scripts/common/vdot-calculator.js` | ★★★★☆  |
| 配速区间统计      | `app/lib/db.ts` (getPaceZoneStats)  | ★★★★☆  |
| 偏差预警逻辑      | `app/analysis/AnalysisClient.tsx`   | ★★★★☆  |
| 知识说明页        | `app/daniels/page.tsx`              | ★★★☆☆  |
