# Synjuku Pitch Deck 解析

> 基于 `docs/synjuku/synjuku_*.png` 4 张拼图 + Page 6 高清原图整理。
> 原始材料：Synjuku 2026 年 4 月 SAFE 轮融资 pitch deck（共 18 页）。

---

## 1. 公司定位

**Synjuku** — 专注机器人训练数据 **质量瓶颈** 的公司。

核心论点（封面 + Page 2）：
> *Data's the bottleneck in robotics. We solve the quality bottleneck nobody measures.*
>
> *Not all data is the same. Only 5–10% of what vendors ship is actually trainable. The bottleneck isn't supply — it's the quality no one measures.*

行业现状：vendor 按"小时/帧数"卖数据，但实际可训练率只有 **5–10%**。Synjuku 把"质量"做成可衡量、可运营的工程问题。

---

## 2. 行业痛点（Page 4 — Insight Gap）

| 角色 | 痛点 |
|------|------|
| Field labs | 不知道自己采的东西哪里效率低 |
| Tech leads | 看不到数据里的问题 |
| Vendors | 不知道模型真正需要什么 |
| 整体 | Low-signal data 又贵又慢 |

并附数据点：**500 hrs** —— 某实验室因坏数据浪费的工时。

---

## 3. 质量衡量框架（Page 6 — What the work actually looks like）

### 3.1 底层数据模型：三层分类法

> **Task → Subtask → Primitive**
>
> *Every captured frame lands in a node. Every node is training-ready.*

- 每一帧必须落到某个 Primitive 节点上（不能"散着"）
- 每个 Primitive 节点本身就是 **training-ready** 的最小单元
- 未分类的帧 = 不可训练 = 不算数据

### 3.2 四个面板 = 四个质量维度

| 面板 | 标题 | 质量维度 | 作用 |
|------|------|---------|------|
| 左上 | **Task Mapping · Sankey + Grading** | 每个 primitive 的 **coverage grade**（如 "3 supporting" / "10 supporting"） | Sankey 流程图驱动 capture priority |
| 右上 | **Primitive Coverage Tracker** | **Gap detection** — 哪些 primitive 已经够、哪些还缺 | 跨整个 commercial environment library 的活跃覆盖率热力表 |
| 左下 | **Diversity Matrix · Commercial** | **Cross-environment diversity** — 同一 primitive 出现在几种环境 | Tasks per Environment + Environments per Task 双柱状 + chord 图，对应模型 generalization |
| 右下 | **Primitive Co-occurrence Chord** | **Co-occurrence pattern** — primitive 跨 room 的真实共现分布 | 训练数据共现分布必须匹配真实世界，避免 long-tail 偏移 |

### 3.3 完整质量标准清单

| 维度 | 指标 |
|------|------|
| 结构化 | 每帧必须分类到 Task→Subtask→Primitive 节点 |
| 节点就绪度 | 每个 Primitive 节点是否 training-ready |
| 覆盖深度 | 单个 primitive 的 sample 数 / grading |
| 覆盖广度（gap） | 已覆盖 vs 待补 primitive |
| 环境多样性 | 同一 primitive 出现在几种环境 |
| 共现真实性 | primitive 跨房间共现是否匹配真实世界分布 |

### 3.4 其他暗示的质量维度（来自 customer voice / 痛点表述）

- **Task-level usefulness**：vendor 不思考 task 设计，Synjuku 思考
- **At-a-glance distinguishability**：交付物有可视化的 quality signature，"一眼可辨"
- **Signal density**：单位数据中的有效训练信号
- **Customer-validated**：客户实际拿去训了模型并认可

---

## 4. 运营方式（Page 7）

> *Production runs on a platform — not a spreadsheet.*

- 平台化 dashboard + 实操图 + 数据列表
- 不用 Excel 手工管理
- （Page 7 dashboard 的具体运营指标字段拼图分辨率读不清，待补）

---

## 5. 客户与规模（Page 8 + Page 10）

### Page 8 指标
- 客户正在主动要求扩容（"Customers are pulling us to scale"）
- 关键数字：**750 / $300M / 50+**（客户/合同规模/客户数级别）

### Page 10 客户证言（Confidential robotics lab advisor，2026 年 4 月）
1. *"When data comes to us, we can see the difference at a glance. To others it looks similar — but when your data lands, it looks completely different from everyone else's."*
2. *"Most vendors don't even think about tasks. They ask us what tasks we want them to collect — none of them have thought through what's actually useful for training. You have."*
3. *"You can say 'validated by our customer.' When the time comes, let us be a reference."*

---

## 6. 团队（Page 5）

- 名字可辨：**Frank Song**、**Gary Zhang** 等
- 学术 + 实战经验组合，"a team built to solve yield rate"

---

## 7. 信念（Page 11 — What We Believe）

> *When we scale beyond LLM, we will be ...*

当行业从 LLM 扩展到具身智能时，**质量层** 将成为基石。

---

## 8. 融资（Page 15–17）

### 资金规划（Page 15）
- $300M aggregate 预算拆分（Tier 1/2/3）
- 高亮 key segment：**$122M**

### 融资形式（Page 16）
> *Raising via SAFE. Lead is open.*

4-month horizon，资金用途：
- **Capture ops scale-up** — 支持 200K push + ByteDance OEM conversation
- **Priority library expansion** — Researcher-led task catalog growth（commercial/outdoor/domestic）
- **Customer integration** — 深度技术整合（active labs、delivery format、QC dashboard、reference workflow）
- **Research bench** — VLA intra advisors + research advisors + broader scientific reference network

### Recent wins（Page 17）
- POD design：100–200 people across PODs
- Hardware R&D：自研 100+ capture kits
- Factory partners：formalize partnership，扩 supply
- SOC 2 scoped：customer-required
- Legal partners：solidify entities + filings
- SEA partners：look sites，train POD leaders
- Pipeline built：100K+ task hours

### Beyond Capital
欢迎 angels/investors who understand：
- SEA Operating Hubs
- Vietnam Mfg Network
- Hardware Vendors
- Robotics Customer Access
- Institutional Fund Vehicle

---

## 9. 时机（Page 18 — Why Now / The Window）

> *Over fifty vendors launched last year.*

市场窗口期已开，行业开始 commoditize "data supply" — Synjuku 切的是上面一层的 **quality / yield**。

---

## 10. 一句话总结

> Synjuku 在做的事 = **把"机器人训练数据质量"从一个谁都说不清的玄学，变成一个由 Task→Subtask→Primitive 分类法 + 覆盖率/多样性/共现性四维指标支撑的工程系统**。
> 护城河叙事 = "我们能测、别人测不了"。融资目的 = 加速已经被客户拉着跑的执行，而非探索方向。
