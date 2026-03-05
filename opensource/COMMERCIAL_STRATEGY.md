# gcc-evo 商业开源策略

> 如何在开源框架的同时保护商业利益

---

## 核心策略：分层开源模型

```
┌─────────────────────────────────────────────────────────────┐
│                     用户应用层                              │
│              (用户的交易系统/诊断系统/etc)                  │
└────────────────────────┬────────────────────────────────────┘
                         │
┌────────────────────────▼────────────────────────────────────┐
│ 🔒 Layer 3: 企业版增强 (商业收费)                           │
│  ├─ 实时协作 (multi-user)                                 │
│  ├─ 分布式内存 (Redis/数据库)                              │
│  ├─ 企业集成 (Kafka/API网关)                               │
│  ├─ SLA服务承诺                                            │
│  └─ 技术支持 + 咨询                                        │
└────────────────────────┬────────────────────────────────────┘
                         │
┌────────────────────────▼────────────────────────────────────┐
│ 📦 Layer 2: 核心功能 (开源但BUSL 1.1)                      │
│  ├─ 五层框架核心逻辑                                       │
│  ├─ 基础内存存储 (JSON/SQLite)                             │
│  ├─ 基础检索 (不含高级算法)                                │
│  ├─ 基本蒸馏 (经验提炼)                                    │
│  └─ 开源，但商用需授权                                     │
└────────────────────────┬────────────────────────────────────┘
                         │
┌────────────────────────▼────────────────────────────────────┐
│ ✅ Layer 1: 框架基础 (MIT/Apache 2.0 开源)                 │
│  ├─ Pipeline DAG引擎                                       │
│  ├─ 内存接口定义 (抽象类)                                  │
│  ├─ 检索接口定义 (抽象类)                                  │
│  ├─ 蒸馏接口定义 (抽象类)                                  │
│  ├─ 决策接口定义 (抽象类)                                  │
│  ├─ 完全自由使用                                           │
│  └─ 可用于任何目的（含商业）                               │
└─────────────────────────────────────────────────────────────┘
```

---

## 开源范围设计

### ✅ 开源的 Layer 1: 框架基础

这部分完全开源（MIT 或 Apache 2.0），允许任何人：
- 自由使用
- 商业应用
- 修改和分发
- 私有使用

**具体内容**：

```python
# 框架接口定义 (纯抽象)
# gcc_evolution/core/__init__.py

from abc import ABC, abstractmethod

class MemoryTier(ABC):
    """记忆层抽象接口"""
    @abstractmethod
    def record(self, event): pass
    @abstractmethod
    def query(self, query_str): pass

class Retriever(ABC):
    """检索层抽象接口"""
    @abstractmethod
    def search(self, query, top_k=5): pass

class Distiller(ABC):
    """蒸馏层抽象接口"""
    @abstractmethod
    def extract_skill(self, experience): pass

class SkepticGate(ABC):
    """决策层抽象接口"""
    @abstractmethod
    def verify(self, decision): pass

class LoopEngine(ABC):
    """编排层抽象接口"""
    @abstractmethod
    def run_once(self): pass

# Pipeline 执行引擎 (具体实现，但不涉及业务逻辑)
class PipelineExecutor:
    """DAG 任务调度 - 开源实现"""
    def __init__(self, dag):
        self.dag = dag
        self.results = {}

    def execute(self):
        """执行 DAG 中的任务"""
        executed = set()
        while len(executed) < len(self.dag):
            for task_name, config in self.dag.items():
                if task_name in executed:
                    continue
                if not all(dep in executed for dep in config['deps']):
                    continue

                result = config['executor'](self.results)
                self.results[task_name] = result
                executed.add(task_name)

        return self.results
```

**优势**：
- ✅ 允许竞争对手或用户自己实现功能
- ✅ 你的框架成为标准
- ✅ 社区可贡献核心框架改进
- ✅ 法律风险最低

---

### 📦 开源的 Layer 2: 核心功能 (BUSL 1.1)

这部分开源但受 BUSL 1.1 限制，允许：
- ✅ 非商业使用（学术、个人）
- ✅ 年收入 < $1M 的公司使用
- ✅ 查看源代码
- ❌ 商用需付费授权

**具体内容**：

```
gcc_evolution/memory/
├─ tiers.py                  # 三层实现 (开源 BUSL)
├─ storage.py               # JSON/SQLite 存储 (开源 BUSL)
├─ lifecycle.py             # 自动过期管理 (开源 BUSL)

gcc_evolution/retrieval/
├─ semantic.py              # Embedding 检索 (开源 BUSL)
├─ temporal.py              # 时间加权 (开源 BUSL)
├─ keyword.py               # BM25 匹配 (开源 BUSL)
├─ hybrid.py                # 混合融合 (开源 BUSL)

gcc_evolution/distillation/
├─ extractor.py             # 经验卡提炼 (开源 BUSL)
├─ skillbank.py             # SkillBank 管理 (开源 BUSL)
├─ versioning.py            # 版本管理 (开源 BUSL)

gcc_evolution/decision/
├─ skeptic.py               # 防幻觉门控 (开源 BUSL)
├─ confidence.py            # 置信度计算 (开源 BUSL)

gcc_evolution/orchestration/
├─ loop_engine.py           # 6步闭环 (开源 BUSL)
├─ pipeline.py              # DAG 调度 (开源 BUSL)
```

**关键特性**：

```python
# 基础实现 (开源)
class BasicMemoryTier(MemoryTier):
    """基础三层内存 - 开源 BUSL 1.1"""
    def __init__(self, storage_type='json'):
        self.storage_type = storage_type  # 仅支持 JSON/SQLite
        self.sensory = []
        self.short_term = []
        self.long_term = {}

class BasicRetriever(Retriever):
    """基础混合检索 - 开源 BUSL 1.1"""
    def search(self, query, top_k=5):
        # 支持三种基础方法的加权融合
        results = {}
        results['semantic'] = self._semantic_search(query)
        results['temporal'] = self._temporal_search(query)
        results['keyword'] = self._keyword_search(query)
        return self._fuse_results(results, top_k)

class BasicDistiller(Distiller):
    """基础蒸馏 - 开源 BUSL 1.1"""
    def extract_skill(self, experience):
        # 基础规则提炼
        # 通过 LLM 调用（用户提供自己的 API key）
        pass
```

**BUSL 1.1 条款保护**：
- 2028-05-01 自动转为 Apache 2.0
- 商用需付费许可
- 代码审计权
- 不能 SaaS 提供

---

### 🔒 商业版 Layer 3: 企业增强 (完全收费)

这部分完全私有，仅提供给付费客户，包含：

```
gcc_evolution_enterprise/
├─ memory/
│  ├─ distributed_memory.py     # Redis/数据库存储
│  ├─ sharding.py               # 分片策略
│  ├─ replication.py            # 主从复制
│  └─ consistency.py            # 一致性保证
│
├─ retrieval/
│  ├─ advanced_semantic.py      # 自训练 embedding 模型
│  ├─ hierarchical_search.py    # 分层索引
│  ├─ cache_optimization.py     # 智能缓存
│  └─ quantization.py           # 向量量化加速
│
├─ collaboration/
│  ├─ multi_user_session.py     # 多用户会话
│  ├─ permission_control.py     # 权限管理
│  ├─ audit_logging.py          # 审计日志
│  └─ conflict_resolution.py    # 冲突解决
│
├─ integration/
│  ├─ kafka_connector.py        # Kafka 集成
│  ├─ grpc_service.py           # gRPC API
│  ├─ rest_api.py               # REST API
│  └─ webhook.py                # Webhook 支持
│
├─ observability/
│  ├─ prometheus_metrics.py     # Prometheus 指标
│  ├─ jaeger_tracing.py         # 分布式追踪
│  ├─ custom_dashboard.py       # 自定义仪表板
│  └─ alerting.py               # 告警规则
│
└─ security/
   ├─ encryption.py             # 端到端加密
   ├─ saml_auth.py              # SAML 认证
   ├─ rbac.py                   # 基于角色的访问控制
   └─ data_masking.py           # 数据脱敏
```

**仅限企业版客户**：
- 实时多用户协作
- 分布式部署
- 企业级集成
- SLA 保证
- 专业支持

---

## 代码结构设计

### 目录组织

```
gcc-evo/
├─ LICENSE.md                          # BUSL 1.1 (整个项目)
├─ ADDITIONAL_USE_GRANT.md             # 商用许可说明
│
├─ opensource/                         # 开源部分
│  ├─ setup.py                         # pip 包配置
│  ├─ README.md
│  ├─ CHANGELOG.md
│  └─ gcc_evolution/
│     ├─ core/                         # ✅ Layer 1: 框架 (MIT)
│     │  ├─ __init__.py               # 抽象接口
│     │  └─ pipeline.py               # DAG 执行器
│     │
│     ├─ memory/                       # 📦 Layer 2: 记忆 (BUSL)
│     │  ├─ tiers.py                  # 三层实现
│     │  └─ storage.py                # 基础存储
│     │
│     ├─ retrieval/                    # 📦 Layer 2: 检索 (BUSL)
│     │  ├─ hybrid.py                 # 混合检索
│     │  └─ implementations.py        # 基础实现
│     │
│     ├─ distillation/                 # 📦 Layer 2: 蒸馏 (BUSL)
│     │  └─ distiller.py              # 经验提炼
│     │
│     ├─ decision/                     # 📦 Layer 2: 决策 (BUSL)
│     │  └─ skeptic.py                # 防幻觉门控
│     │
│     └─ orchestration/                # 📦 Layer 2: 编排 (BUSL)
│        └─ loop_engine.py            # 6 步闭环
│
├─ enterprise/                         # 🔒 Layer 3: 企业版 (私有)
│  ├─ memory/
│  │  ├─ redis_memory.py              # Redis 实现
│  │  └─ distributed.py               # 分布式
│  │
│  ├─ retrieval/
│  │  ├─ advanced_retrieval.py        # 高级检索
│  │  └─ custom_embeddings.py         # 自训练模型
│  │
│  ├─ collaboration/
│  │  └─ multi_user.py                # 多用户协作
│  │
│  └─ integration/
│     └─ enterprise_connectors.py     # 企业集成
│
└─ docs/
   ├─ COMMERCIAL_STRATEGY.md          # 本文档
   ├─ BUSINESS_MODEL.md               # 商业模式说明
   └─ LICENSE_FAQ.md                  # 许可证常见问题
```

### 许可证标记

每个文件顶部添加许可证标记：

```python
# gcc_evolution/memory/tiers.py

"""
Three-tier memory implementation.

License: BUSL 1.1 (Business Source License)
For commercial use, see: https://gcc-evo.dev/licensing

This file is part of gcc-evo core functionality.
Dual licensing available under ADDITIONAL_USE_GRANT.md
"""
```

```python
# gcc_evolution/core/pipeline.py

"""
DAG Pipeline executor - base framework.

License: MIT / Apache 2.0
This file is part of gcc-evo framework layer.
Freely usable for any purpose including commercial.
"""
```

```
# enterprise/memory/redis_memory.py
# PRIVATE - Not part of open source release
# Enterprise customers only
```

---

## 许可证策略设计

### BUSL 1.1 条款（核心功能）

**开源条件**：
```
✅ 免费使用场景：
  - 学术研究
  - 非商业项目
  - 个人使用
  - 年收入 < $1M 的公司
  - 开源项目（引用 BUSL 项目）

❌ 付费场景：
  - 年收入 >= $1M 的公司
  - SaaS 产品化
  - 嵌入付费产品
  - 提供商业服务
```

**转换条款**：
```
2028-05-01：自动转为 Apache 2.0
这意味着：
  - 免费期：3 年（2025-2028）
  - 过期后：完全开源，无商用限制
  - 目的：成熟后自动开源，保留初期商业窗口
```

### Additional Use Grant（例外许可）

**免费例外**：
```
以下情况可免费商用（无需授权）：

1. 学术机构
   - 大学、研究所
   - 研究论文中使用
   - 开源课程

2. 开源项目
   - 如果你的项目也遵循同等或更宽松的许可证
   - 自动获得商用豁免

3. 个人开发者
   - 个人创业初期（< $100K 营收）
   - 可申请 1 年免费试用

4. 非营利组织
   - NGO、慈善机构
   - 完全免费
```

**灰色地带处理**：
```
如果用户不确定是否需要许可证：
1. 自动评估（技术手段）
   - 检测收入规模（可选自填）
   - 检测 SaaS 提供

2. 明确告知
   - "这个场景需要付费许可证"
   - "你可以申请免费豁免"
   - "选项 A: 付费 / 选项 B: 申请免费 / 选项 C: 使用开源框架"

3. 友好但清晰
   - 不强制（技术上无法强制）
   - 但明确法律后果
```

---

## 商业模式

### 定价策略

```
产品线：

1️⃣ 开源 (Free)
   - gcc-evo 开源版
   - Layer 1 (框架)
   - 基础 Layer 2 (BUSL)
   - 目标：社区、学生、开源爱好者

2️⃣ 专业版 ($49/月)
   - 核心功能 + 高级配置
   - 企业级存储选项 (SQLite)
   - 私有模型集成
   - 标准支持 (邮件)
   - 针对：个人开发者、小型团队

3️⃣ 企业版 ($499/月+)
   - Layer 3 完整功能
   - 分布式部署
   - 多用户协作
   - 企业集成 (Kafka/gRPC)
   - 优先支持 (电话/Slack)
   - 自定义开发
   - 针对：中大型公司

4️⃣ 咨询服务 (按时计费)
   - 架构设计咨询
   - 性能优化
   - 定制开发
   - 企业培训
```

### 许可证验证 (Honor System)

**技术不强制，但法律清晰**：

```python
# 可选的许可证检查（非强制）
class LicenseChecker:
    """
    Informational license checker
    Does not prevent usage but informs users
    """

    @staticmethod
    def check_commercial_usage():
        """提示用户是否需要许可证"""
        print("""
        ┌─────────────────────────────────────┐
        │ gcc-evo License Information        │
        ├─────────────────────────────────────┤
        │ This is a BUSL-licensed project     │
        │ Requires commercial license for:   │
        │ • Companies with $1M+ revenue      │
        │ • SaaS/embedded products          │
        │ • Commercial services             │
        │                                    │
        │ Free for:                          │
        │ • Personal use                     │
        │ • Startups < $1M                  │
        │ • Academics & open source         │
        │                                    │
        │ Check: gcc-evo.dev/licensing      │
        └─────────────────────────────────────┘
        """)
```

**不做的事**：
- ❌ 不在代码中嵌入 DRM 或关键代码检查
- ❌ 不要求激活码或注册
- ❌ 不限制核心功能（Honor System）
- ❌ 不跟踪用户使用

**为什么**：
- 开源项目应该信任用户
- 强制手段会导致 fork 或破解
- 法律框架足以保护权益
- 优秀的开发者会尊重许可证

---

## 竞争者防护

### 如何防止竞争者滥用

**问题**：竞争者可能会：
1. Fork 项目并商用
2. 剥离许可证声明
3. 声称自己原创

**防护措施**：

#### 1. 法律防护（首要）
```
✓ BUSL 1.1 明确规定了使用条件
✓ 源代码著作权归 baodexiang
✓ 违反许可证可追究法律责任
✓ 需要时可起诉侵权

法律基础：
- 中国 《著作权法》
- 国际 《TRIPS 协议》
- BUSL 许可证本身
```

#### 2. 社区防护
```
✓ 核心框架使用 MIT（开源标准）
✓ 社区可以自由改进框架
✓ 竞争者如果修改 fork，必须：
  - 标注修改
  - 保留原始许可证
  - 不能隐瞒来源

示例：
竞争产品不能宣称自己"发明了"五层架构
必须承认源自 gcc-evo
```

#### 3. 技术防护
```
✓ Layer 1 框架开源
  - 任何人都可以实现自己的 Layer 2-3
  - 但你的实现是"标准参考"
  - 用户会倾向于用你的成熟实现

✓ Layer 2 开源但 BUSL
  - 小公司/个人可用
  - 大公司需付费
  - 激励生态依赖你的官方版本

✓ Layer 3 完全私有
  - 企业级功能不公开
  - 只有付费客户获得
  - 提供差异化优势
```

#### 4. 品牌防护
```
✓ 保留 gcc-evo 官方身份
  - 官网：gcc-evo.dev
  - 官方文档最权威
  - 官方支持最好

✓ 认证程序
  - "gcc-evo Certified Partner"
  - "gcc-evo Enterprise License"
  - 用户知道谁是官方版

✓ 社区治理
  - 自己领导项目演进
  - 社区提交的改进由你审核和集成
  - 确保官方版本保持竞争力
```

---

## 风险评估与对策

### 风险 1：被大公司抄袭

**风险**：Google、OpenAI 等复制架构

**对策**：
- ✅ 及早获得用户（先发优势）
- ✅ 提供企业版差异化功能
- ✅ 建立 1-2 年领先期（通过专有 Layer 3）
- ✅ 获得论文发表（学术影响力）
- ✅ 到 2028 年转 Apache 2.0 后就无所谓

**说实话**：
- 这个行业，大公司通常不会 100% 抄
- 即使抄，你的一阶优势（品牌+社区+支持）很难被复制
- BUSL 的 3 年商业窗口已经足够成熟了

---

### 风险 2：用户通过 fork 逃避许可证

**风险**：
```
用户 fork gcc-evo，
修改版权声明，
声称自己的产品不受 BUSL 限制
```

**对策**：
1. **法律上**：
   - BUSL 许可证保护的是"衍生作品"
   - Fork 并修改 ≠ 新作品（如果改动不足 50%）
   - 可追究侵权责任

2. **技术上**：
   - 在关键地方添加 git commit 签名
   - 代码中添加版本信息和来源标记
   - 文档中明确说明衍生来源

3. **实际上**：
   - 诚实的开发者会尊重许可证
   - 不诚实的开发者也赚不了大钱（维护成本高）
   - 最终还是会回到官方版本

---

### 风险 3：BUSL 不被认可

**风险**：某些律师认为 BUSL 在中国不适用

**对策**：
- ✅ 同时使用 BUSL + 中文许可证说明
- ✅ 添加 "Additional Use Grant"（例外条款）
- ✅ 关键文件使用多重许可证（BUSL OR Apache-2.0 after 2028）
- ✅ 咨询国际律师（可选，但稳妥）

---

## 推荐方案总结

### 立即执行

```
✅ 目前现状（已完成）
└─ BUSL 1.1 许可证

✅ 需要完成
├─ ADDITIONAL_USE_GRANT.md （豁免条款）
├─ LICENSE_FAQ.md （常见问题）
├─ COMMERCIAL_STRATEGY.md （本文档）
└─ 代码中添加许可证标记

✅ 可选但建议
├─ 官方网站 (gcc-evo.dev/licensing)
├─ 许可证检查器（信息性，非强制）
└─ 律师咨询（国际化后）
```

### 分阶段策略

```
阶段 1 (现在-2025年底):
  目标：积累用户和社区
  策略：
    - 开源 BUSL 核心功能
    - 免费给 < $1M 公司使用
    - 建立社区和开源生态
    - 积累 github stars 和使用案例

阶段 2 (2026-2027年):
  目标：商业化验证
  策略：
    - 企业版（Layer 3）上线
    - 专业支持和咨询服务
    - 获得 5-10 个付费企业客户
    - 为 Layer 2 商业许可做准备

阶段 3 (2028年):
  目标：过渡到开源
  策略：
    - BUSL 自动转为 Apache 2.0
    - 所有代码完全开源
    - 商业收入从许可证转向：
      * 企业级 Layer 3
      * 咨询和定制开发
      * SaaS 托管服务
```

---

## 最终建议

### 不要做的

❌ **不要**尝试 100% 封闭源代码
  - 这是开源项目，用户期望看到代码
  - 会丧失信任和社区

❌ **不要**在代码中强制检查许可证
  - 会导致 fork 和破解
  - 开源精神是信任

❌ **不要**过度复杂化许可证
  - BUSL 已经够清晰
  - 太多豁免条款反而混乱

### 应该做的

✅ **应该**清晰表达商业意图
  - "这是开源的，但商用需授权"
  - "这是我的创意，我保护我的权益"
  - 用户会尊重你的立场

✅ **应该**通过产品差异化竞争
  - Layer 3 企业版功能
  - 企业级支持和服务
  - 托管 SaaS 版本
  - 这些才是真正的竞争力

✅ **应该**投资社区和生态
  - 好的开源项目最终都成功了
  - gcc-evo 价值在于"框架思想"而非代码行数
  - 让社区繁荣反而增加你的商业价值

---

**最终结论**：

你的策略既保护了商业利益，也尊重了开源精神。

- 📚 开源框架（Layer 1）让任何人都能学习和创新
- 💼 商业实现（Layer 2-3）给你 3 年的商业窗口
- 🚀 到 2028 年完全开源，实现可持续的商业模式

这是**最聪明的方式**。

---

**[English](COMMERCIAL_STRATEGY.en.md) | [中文](COMMERCIAL_STRATEGY.md)**
