# 纯视觉、纯人为动作操作、多模态模型决策、case虚拟回放
## 过程
### 自然语言描述的case-->多模态模型分析每步的意图返回执行坐标-->执行器执行-->（验证器验证）-->case 虚拟回放完整过程

### 注意:没有执行脚本、模型不要生成什么执行脚本，纯人为行为的动作，实时执行，case 回放确保case 是完整执行的

**stage1**
**自然语言描述的case**【单步描述：action+position+color?+text/shape&icon】
**多模态模型分析** 接收每步文本，结合实际屏幕图片，判断文本在图片上的意图，返回执行坐标/操作行为；操作行为【点击坐标，滑动（坐标1，坐标2）】
**执行器** 接收坐标-计算实际设备屏幕和模型处理图片大小比例-转化实际执行坐标
**验证器** 一个独立的agent,负责验证执行是否成功
**case虚拟回放** case每步有保留执行前图片&执行后图片，执行成功后对执行前图片进行位置标注，以此形成个串联的图片列表，执行前标注的图片就是该步骤对应的操作，执行后的图片既是该步的预期，回放就是把图片串联起来形成的个图片快照；

**stage2**
**足够多的数据后：1.微调模型；2.制作RAG 提供模型可参考内容；**
**skills:验证器添针对不同应用添加不同应用skills,提供对特殊场景、特殊行为的支持** 
**虚拟应用：整个过程迁移到虚拟应用上执行，再在真实环境执行**
**逐步降低人工干预：早期每个过程应该都是要人工大量干预，要逐步实现零人工干预，实现模型分析-执行-验证-回溯全链路的agent闭环；人工只对报警内容做二次确定，检查是否触发bug工单等后续工作**

#### process
**2026-06-09**：开始构建自然语言描述的case ,基础功能基本完成，优化打磨后续全链路构建完成再考虑；
**2026-06-09**：开始构建agent意图分析，执行操作，自动验证的功能

---

## 项目结构

```
AutoTestVision/
├── backend/          # FastAPI + PostgreSQL + ADB 设备控制
├── frontend/         # React 三栏 UI
├── docker-compose.yml
└── README.md
```

## 快速启动

### Docker 一键编排（推荐）

```bash
# 1. 宿主机先把 adb server 暴露到 0.0.0.0:5037（容器内 adb 客户端会远程指挥它）
adb kill-server
adb -a -P 5037 nodaemon server start &

# 2. （可选）在仓库根目录建一个 .env，写入大模型 Key（compose 会自动读取）
#    AGENT_LLM_API_KEY=sk-xxx
#    AGENT_LLM_BASE_URL=https://api.openai.com/v1
#    AGENT_LLM_MODEL=gpt-4o-mini

# 3. 编排启动 postgres + backend + frontend
docker compose up -d --build

# 4. 查看状态 / 日志
docker compose ps
docker compose logs -f backend
```

访问：
- 前端：http://localhost:5179
- 后端：http://localhost:8099/api/health
- 数据库：localhost:5432（autotest / autotest）

停止：

```bash
docker compose down        # 停掉容器，保留数据
docker compose down -v     # 连数据卷一起删
```

> ADB 说明：容器里装的是 Debian 自带 adb，会通过 `ADB_SERVER_SOCKET=tcp:host.docker.internal:5037` 连宿主上的 adb server。所以 USB 设备插在 **宿主**、`adb devices` 在 **宿主** 能看到，容器才认得到。Linux 用户务必让宿主 adb 绑定到 `host-gateway` 能访问的地址（compose 已配 `extra_hosts`）。

### 本地一键启动（Windows）

确保 PostgreSQL 已运行、首次依赖已安装后，双击根目录：

```
start.bat
```

会自动打开两个窗口分别运行后端和前端，并打开浏览器访问 http://localhost:5179 。

PowerShell 环境也可执行：

```powershell
.\start.ps1
```

> 首次使用需先完成下方「准备 PostgreSQL」和依赖安装；`start.bat` 会自动检测并安装前端 `node_modules`。

### 1. 准备 PostgreSQL

本地已有 PostgreSQL 时，创建项目库：

```bash
psql -h localhost -p 5432 -U postgres -c "CREATE DATABASE autotestvision;"
```

后端默认连接：`postgres@localhost:5432/autotestvision`，账号密码在 `backend/.env` 中配置。

### 2. 手动启动后端（可选）

```bash
cd backend
python -m venv .venv
.venv\Scripts\activate        # Windows
pip install -r requirements.txt
python run.py
```

后端默认运行在 http://localhost:8099

### 3. 手动启动前端（可选）

```bash
cd frontend
npm install
npm run dev
```

前端默认运行在 http://localhost:5179

### 4. 连接 Android 设备

- 手机开启 USB 调试
- 安装 [ADB](https://developer.android.com/tools/adb) 并确保 `adb devices` 能看到设备
- 右侧设备面板会自动列出已连接设备，支持实时屏幕流、点击、长按与滑动

## Stage 1 当前能力

| 区域 | 功能 |
|------|------|
| 左侧 | 富文本编辑器，粘贴/编辑原始脚本 |
| 中间 | 自然语言 Case 步骤构建，点击 + 添加步骤，保存到 PostgreSQL |
| 右侧 | ADB 实时屏幕镜像，支持点击/长按/滑动；应用权限查看与一键重置 |

## API 概览

- `GET/POST/PUT/DELETE /api/cases` — Case CRUD
- `GET /api/device/list` — 列出 ADB 设备
- `WS /api/device/stream` — 实时屏幕流
- `POST /api/device/tap` — 点击
- `POST /api/device/long-press` — 长按
- `POST /api/device/swipe` — 滑动
- `GET /api/device/apps` — 列出设备安装应用（系统/常用应用优先排序）
- `GET /api/device/apps/{package}/permissions` — 获取应用权限及授予状态
- `POST /api/device/apps/{package}/permissions/apply` — 按勾选结果授予/撤销权限

> 权限变更通过 `pm grant` / `pm revoke` 实现，仅对**可运行时变更**的权限生效；部分系统签名权限、安装时固定权限可能显示为「不可变更」。

### Agent Test Service（LangGraph Harness）

独立存储表：`agent_runs`、`agent_run_steps`、`agent_logs`（与自然语言 Case 表分离）

- `GET /api/agent-test/cases?limit=10` — Agent 页 Case 列表
- `POST /api/agent-test/analyze` — 单步意图分析（多模态）
- `POST /api/agent-test/runs` — 创建 Agent 运行实例
- `GET /api/agent-test/runs/{run_id}` — 查询执行状态与截图
- `GET /api/agent-test/runs/{run_id}/logs` — 查询 Agent 日志
- `GET /api/agent-test/runs/{run_id}/stream` — SSE 实时推送执行过程
- `POST /api/agent-test/runs/{run_id}/step` — 手动执行一步
- `DELETE /api/agent-test/runs/{run_id}` — 取消执行

配置 `AGENT_LLM_API_KEY` 后启用多模态 LLM；未配置时使用启发式分析/像素差异验证。