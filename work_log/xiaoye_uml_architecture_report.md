# Xiaoye Agent - 架构 UML 建模报告

基于 `HANDOVER_PROMPT.md` 与核心代码（`swarm_coordinator.py`, `task_board.py`, `graph.py`, `skill_loader.py`, `ultraplan.py`），以下是提炼自项目当前实现的架构 UML 建模报告。平台整体参考了 Anthropic Claude Code 的设计哲学，从传统的 Monolithic (全局状态循环) 升级为真正的多智能体异步 Swarm 体系。

## 1. 核心架构拓扑 (Component Diagram)
该图表展示了系统各个组件之间的功能划分与流向，重点突出了基于“黑板模式 (Blackboard)”的解耦通信设计和启发式技能挂载机制。

```mermaid
graph TD
    User([冶金工程师]) -->|Request| Entry[入口: handle_complex_query]
    
    subgraph Planning Phase [大脑: 规划与编排]
        Entry --> Planner[UltraPlanner]
        Planner -->|Interactive Review| User
        Planner -->|Human-in-the-loop| Plan[UltraPlan]
    end

    subgraph Coordination Phase [大脑: 异步调度中心]
        Entry -.-> Plan
        Plan --> Coordinator[SwarmCoordinator]
        Coordinator -->|写入任务/监听状态| Board[TaskBoard]
    end
    
    subgraph State Hub [黑板: 分布式状态锁]
        Board <-->|Read / Write / Claim| Redis[(Redis / JSON Tasks)]
    end
    
    subgraph Execution Phase [手脚: 脱水流水线兵团]
        Worker1[Worker 1] <-->|竞争提取| Board
        Worker2[Worker N] <-->|竞争提取| Board
    end

    subgraph Worker Lifecycle [单节点执行图 graph.py]
        direction TB
        Worker1 --> Researcher(Researcher Node)
        Researcher --> SkillLoader[眼睛: SkillLoader]
        SkillLoader -->|环境物理探针| Tools[动态计算/查询沙盒]
        Researcher --> ToolsNode(Tools Mode)
        ToolsNode --> Compactor(Compactor Node: 上下文溢出拦截)
        Compactor --> Evaluator(Evaluator Node: 反思验收)
        Evaluator -->|Unsatisfied| Researcher
        Evaluator -->|Satisfied| TaskDone([写回黑板])
    end
```

## 2. 核心工作流与运行生命周期 (Sequence Diagram)
展现了一次复杂查询从解析到规划，再到黑板拆解发包、各路 Worker 抢占式执行、验证汇总的完整时序逻辑。

```mermaid
sequenceDiagram
    actor User as 冶金工程师
    participant Main as 外壳调度层
    participant UP as UltraPlanner
    participant SC as SwarmCoordinator
    participant TB as TaskBoard
    participant W as Worker 协程
    participant SL as SkillLoader

    User->>Main: 发起复杂冶金计算或查询
    Main->>UP: interactive_review_and_edit(query)
    UP-->>User: 输出拟定拓扑图 (Task List/Dependencies)
    
    rect rgb(200, 220, 240)
    Note over User,UP: Human-In-The-Loop 审批回路
    User->>UP: 批准 (Approve) 或 打回重新起草
    end
    
    UP-->>Main: 返回正式的 UltraPlan
    
    Main->>SC: 引导上线 (SwarmCoordinator)
    Main->>SC: 映射为真实的 Redis 任务块
    SC->>TB: create_task(depends_on)
    
    loop 异步中心节点空转 (Idle)
        SC->>TB: get_unassigned_tasks() (检查解除阻塞的节点)
        alt 存在就绪任务
            SC->>W: spawn_worker(task_id) 发起分发
        end
        SC->>SC: asyncio.sleep(2.0)
    end
    
    par Worker 并发竞标执行
        W->>TB: claim_task(task_id)
        Note over W,TB: 采用 Redis WATCH 乐观锁，杜绝 Race Condition
        TB-->>W: 竞标成功 / 失败
        
        alt 竞标成功
            W->>SL: probe_environment(task_desc)
            Note over W,SL: 环境检测 (CSV, PyScript, MCP)
            SL-->>W: 返回限定版沙盒工具列表
            W->>W: 运行局部图(Researcher -> Tools -> Compactor -> Evaluator)
            W->>TB: mark_completed(task_id, result)
        end
    end
    
    SC->>TB: 轮询 _is_all_completed()
    TB-->>SC: 全部完成 (Yes)
    SC-->>Main: 聚合整理所有 Node 返回数据
    Main-->>User: 答复最终研究结果
```

## 3. 任务状态机定义 (State Diagram)
体现基于依赖图的 `SwarmTask` 生命周期流转机制。借助依赖图，复杂流程可以像 DAG 一样逐步解冻执行。

```mermaid
stateDiagram-v2
    [*] --> BLOCKED: 若生成任务包含 depends_on
    [*] --> TODO: 若生成任务无前置依赖
    
    BLOCKED --> TODO: 依赖检测全部完成 (refresh_blocked_tasks)
    
    TODO --> IN_PROGRESS: 发生并发竞标 (claim_task 乐观锁加锁)
    IN_PROGRESS --> COMPLETED: 任务管道处理验收完毕 (mark_completed)
    
    COMPLETED --> [*]
```

## 4. 核心类图逻辑关系 (Class Diagram)
展示代码内部各定义类的关联方式和核心职责方法：

```mermaid
classDiagram
    class SwarmCoordinator {
        +TaskBoard board
        +bool running
        +run() async
        +spawn_worker(task_id) async
        -_is_all_completed() bool
        -_aggregate_results() string
    }

    class TaskBoard {
        +String team_name
        +Redis r
        +create_task(desc, deps) SwarmTask
        +claim_task(task_id, agent_name) bool
        +mark_completed(task_id, result)
        +get_unassigned_tasks() List~SwarmTask~
        +refresh_blocked_tasks()
    }

    class UltraPlanner {
        +ChatOpenAI llm
        +generate_plan(user_query, seed_feedback) UltraPlan
        +interactive_review_and_edit(query) UltraPlan
    }

    class UltraPlan {
        +List~TaskDefinition~ tasks
    }
    
    class TaskDefinition {
        +String task_id
        +String description
        +List~String~ depends_on
    }

    class SkillLoader {
        +String workspace_path
        +probe_environment(task_desc) List~Callable~
    }

    class WorkerGraph {
        <<LangGraph>>
        +researcher_node()
        +tools_node()
        +compactor_node()
        +evaluator_node()
    }

    SwarmCoordinator --> TaskBoard : 读/写/监控依赖
    UltraPlanner --> UltraPlan : 渲染生成
    UltraPlan o-- TaskDefinition : 聚合解析
    SwarmCoordinator ..> WorkerGraph : 异步派生(Spawn) Worker
    WorkerGraph --> SkillLoader : 寻求可用工具
```

## 5. 架构分析与建议 (Architectural Insight)

从目前的架构来看，它精准且优雅地匹配了 Handover Prompt 中提到的改造目标：

1. **分布式安全 (Fault Tolerance)**: 打破 LangGraph 原生 `AgentState` 大内存循环。单个 Worker 死循环、报错或上下文 Token 爆满，**不会拖垮整体流程**，可以通过 Coordinator 回收任务重新下发。
2. **算力精准集约 (Resource/Microcompact)**: **Skill Loader** 摒弃了大模型传统的巨大 Prompt API 头，按需扫描文件夹探针。**Compactor** 实现了粗暴但高容错的内容“墓碑 (Tombstone)”截断。
3. **人类控制权 (Human-in-the-Loop)**: `UltraPlanner` 在 Swarm 激活之前插入了一个拦截点，方便高级工程师调整与拒绝错误拓扑。

### 接下来可落地的工程推进点：
- **Redis 方案实装**: 当前的代码混杂着部分注释 mock `Redis Pipeline` 事务原型，确保证明 `claim_task()` 是完全防并发竞争（TOCTOU）的，可稳定承接下一代微服务 Celery / K8s Job 分发。
- **Agent-to-SQL DB 沙盒支持**: 下行规划中的结构化查询工具亟需将 `create_db.py` 链接到 `SkillLoader._mock_sql_agent_tool` 真正跑通实体代码。
