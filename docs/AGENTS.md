# bobac2 教室服务机器人实训 · 工作区 Agent 指南

> 本文件是本工作区的入口说明，供接手的人或 Agent 使用。
> 位置：`D:\课设\AGENTS.md`（根目录）。子目录另有更细的规则文件，靠近代码时以子目录规则优先。
> 最后更新：2026-11-23

---

## 1. 项目是什么

一台 **bobac2 轮式服务机器人**（Ubuntu 16.04 + ROS Kinetic + Python 2.7）的课程实训系统：
用笔记本（Windows/PowerShell）通过 **SSH 隧道** 打开机器人本机的网页，完成
**人脸登录 → 地图选点/语音导航 → SLAM 建图 → 建图/导航模式互切**。

机器人主机名 `reinovo`，账号 `bobac2`（不是 root）。密码按现场交代，**不要写进源码、日志或交付文档**。

角色定位：务实的开发协作者。先讲结论，说明原因，并且**严格区分**四种状态——
「代码已实现」「本机测试通过」「已部署到机器人」「实机已验证」。

---

## 2. 开始前先读（按顺序）

| 顺序 | 文件 | 作用 |
|---|---|---|
| 1 | 本文件 `AGENTS.md` | 工作区地图、硬性规则、当前状态 |
| 2 | [机器人操控手册.md](机器人操控手册.md) | 启停、隧道、目录、话题、故障对照表 |
| 3 | [当前进度与核心逻辑.md](当前进度与核心逻辑.md) | 架构、状态机、数据流、完成度、当前定位问题 |
| 4 | [实践操作手册.md](实践操作手册.md) | 按《实践计划书》逐条要做的现场操作 |
| 5 | [操作手册.md](操作手册.md) | 笔记本启动台（双击即用）的用法 |
| 6 | [页面认证补丁说明.md](页面认证补丁说明.md) | 页面级鉴权补丁的记录 |
| 7 | `gh_repo2\lunshijiqiren\bobac_practicum\TASK_PLAN.md` | 分阶段任务与验收条件 |

根目录这 5 个 `.md` 是**可编辑的正本**，`gh_repo2\lunshijiqiren\docs\` 下是同步副本（目前逐字节一致）。
改文档时两边一起改，否则下次同步会打架。

---

## 3. 工作区地图

```text
D:\课设\
├── AGENTS.md                       ← 本文件
├── 机器人操控手册.md / 当前进度与核心逻辑.md / 实践操作手册.md
│   操作手册.md / 页面认证补丁说明.md      ← 文档正本
│
├── gh_repo2\lunshijiqiren\          ← 唯一的 git 仓库（提交停在 11-16，见 3.1）
│   ├── bobac_practicum\scripts\     机器人端 Python 2.7（app/core/ros_adapter/…）
│   ├── bobac_practicum\web\         前端（login/index/mapping + js）
│   ├── bobac_practicum\launch\ config\ assets\ tests\
│   ├── tools\laptop\                笔记本工具：启动台、隧道、apply_* 补丁
│   ├── tools\robot\                 机器人端：bobac_practicum_ctl.sh 等
│   └── docs\                        根目录文档的同步副本
│
├── gh_repo\ github_repo\           ← 历史遗留空壳克隆，无有效内容，不要当基线
│
├── console\                        笔记本控制台（Python 3 + paramiko，含 .venv）
│   ├── bobac_launcher.py 启动台.bat  一键启动 / 隧道 / 浏览器
│   ├── bobac_console.py 启动控制台.bat
│   ├── tunnel_now.py               只建 8765 隧道
│   └── apply_*.py                  按功能逐项打补丁到机器人（人脸/模式/鉴权/地点/语音/地图）
│
├── deploy\                         上传到机器人 ~/ 的运维脚本（ctl、安装、检查、VNC）
├── patched_*\                      各功能打过补丁的文件片段（app.py / index.html / modules.js）
├── _tmp\                           SSH 探针、一次性补丁、从机器人拉回的源码快照
│   ├── cur\ cur2\ robot_src\        不同日期的机器人源码快照（只读参考）
│   └── 2026-11-19 / 11-23 的脚本    定位链排查、地点写入、应用重启、隧道日志
├── _handoff\bobac2_handoff_20261104\  11-04 打包的交接包（自带 AGENTS.md，内容较旧）
├── bobac2_face\ practicum_manager\    更早/备用的 ROS 包，不在当前主线
└── *.zip  *.pdf  *.docx              原始素材（实践计划书、实验指导书、历史打包）
```

### 3.1 版本关系（重要，别搞反方向）

三份代码不是同一个版本，**仓库比机器人旧**：

| 位置 | 版本 | 说明 |
|---|---|---|
| 机器人 `/home/bobac2/bobac_practicum_ws` | **最新（运行基线）** | 含 11-17 地点保存接口、11-19 AMCL 参数与 TF 回退 |
| `gh_repo2\lunshijiqiren\bobac_practicum` | 11-16 提交 | 缺 `place/save_from_map`，且 `scripts\wheel_odometry.py:82` **仍有已废弃的 `+0.3` TF 超前补偿** |
| `patched_place\`（11-17） | 介于两者之间 | `app.py`（52,671 B）带 `save_from_map`，`modules.js` 带 `placeMode` |

**所以：不要把仓库文件直接 `scp` 覆盖到机器人。**
那样会把 `+0.3` TF 超前补偿重新装回去（AMCL 会再次 `Dropped 100%`），并删掉地点保存接口。
正确方向是**先从机器人拉回源码**（`_tmp\fetch_src.py` / `pull_src.py` / `pull_cur2.py` 这类脚本，
或直接 `scp bobac2@<IP>:... /tmp/`）再改。

`_tmp\cur\`、`_tmp\cur2\`、`_tmp\robot_src\`、`_handoff\` 都是某一天的只读切片；
判断机器人上真实跑的是哪版，用 `_tmp\check_fixes.sh` 这类 grep 脚本核对，别凭文件名猜。

---

## 4. 环境与访问

| 项 | 值 |
|---|---|
| 笔记本 | Windows / PowerShell；`console\.venv\Scripts\python.exe`（Python 3） |
| 机器人 | Ubuntu 16.04.7、ROS Kinetic、Python **2.7**、OpenCV 3.3 |
| 机器人工作空间 | `/home/bobac2/bobac_practicum_ws`（本工程） |
| 运行目录 | `/home/bobac2/bobac_practicum_run`（配置、地图、人脸样本、日志） |
| 厂家工作空间 | `/home/bobac2/bobac2_ws` —— **只读，不要改** |
| 机器人 IP | DHCP 会变。最近用过 `10.166.34.14`；历史 `10.224.117.14`、`10.109.40.14`。先 `ping reinovo.local` |
| 网页 | 只绑 `127.0.0.1:8765` 且校验 `Host: 127.0.0.1:8765`，**必须**建隧道且本地端口固定 8765 |

```powershell
# 一键（推荐）：启动台
D:\课设\console\启动台.bat

# 只建隧道
D:\课设\console\.venv\Scripts\python.exe D:\课设\console\tunnel_now.py

# 手工隧道
ssh -N -L 127.0.0.1:8765:127.0.0.1:8765 bobac2@<机器人IP>
```

机器人端启停**只用 ctl**，不要 `setsid python app.py`：

```bash
bash ~/bobac_practicum_ctl.sh status
bash ~/bobac_practicum_ctl.sh up nav      # 或 up mapping / up static
bash ~/bobac_practicum_ctl.sh stop        # 保留 roscore
bash ~/bobac_practicum_ctl.sh save-map classroom_$(date +%m%d_%H%M)
bash ~/bobac_practicum_ctl.sh maps | log app 100
```

当前固定初始位姿（AMCL 从已知位姿起步，摆不回这里就设初始位姿）：

```text
x = -1.76728869346   y = -2.81884047614   yaw = -1.53206144219
```

---

## 5. 硬性规则（违反会导致现场事故或返工）

### 5.1 代码
1. 机器人端 ROS 共用代码必须是 **Python 2.7 语法**：不要 f-string、`subprocess.run`、`exist_ok=`、类型注解。
   只有 `console\`、`deploy\` 下的笔记本工具才可用 Python 3，且要明确标注。
2. 不要替换机器人系统 Python / OpenCV，不要动 `bobac2_ws`，不要把电脑端 py3 环境整体搬过去。
3. 改机器人的文件先备份：`cp x x.bak_$(date +%Y%m%d_%H%M%S)`。
4. 写 JSON 配置用「临时文件 + `os.rename`」原子替换；中文用 `ensure_ascii=True` 或显式 UTF-8。
   历史上出现过 `open(...,'w')` 中途抛异常把配置截断成几十字节的情况。
5. 默认做局部修改，不做大重构、不引入大依赖、不改现有阈值来让测试通过。
6. 不执行 `git commit` / `push` / `reset` / 清理未跟踪文件，除非用户明确要求。
   仓库当前停在 `ecdccb7`（11-16），本地有未跟踪的文档与工具文件，属于正常待提交状态。

### 5.2 运动与安全
1. **离线开发不等于授权连机器人、部署或发运动指令。** 实机动作以用户当次指令和现场条件为准。
2. 导航模式下「确认目标就会动车」：现场必须有人、有物理急停。软件停车**不替代**物理急停。
3. 发目标前先确认 `health.localized=true` 且地图上机器人位置与实物一致。
4. 雷达未覆盖方向（约 240°）不能推断为空闲；建图默认 0.15 m/s、0.6 rad/s，首次使用先降速。
5. 不要为了「好开」关掉权限校验、地图 ID 校验、速度看门狗、数据新鲜度、失联停车。

### 5.3 记录与结论
1. 不虚构地图、坐标、识别率、实机成功。没有现场证据就写「未验证」。
2. 「已实现 / 本机测试通过 / 已部署 / 实机已验证」必须分开表述。
3. 障碍物**语义类别识别**不在当前范围（用户 11-03 缩减），不把激光占用检测冒充「识别率 90%」。
   人脸 90% 必须来自独立标注试验，不能用录入样本或录像帧当成绩。

---

## 6. 当前状态（2026-11-23）

**链路**：机器人在线，本机 `8765` 隧道正在工作（`curl http://127.0.0.1:8765/` → 200）。
这些是易变状态，**每次操作前重新核实**，不要直接引用本行。

已完成并验证过的功能见 [当前进度与核心逻辑.md](当前进度与核心逻辑.md) §7。要点：

```text
✅ 网页刷脸登录（会话持久化，切模式不重刷）
✅ 语音综合应用（唤醒元宝 / 闲聊 / 控制 / 导航）
✅ 地图点选导航、设初始位姿、命名保存地点
✅ 建图（gmapping + 键盘长按）、建图/导航模式互切
⚠️ 定位链：AMCL 参数已固化，11-19 之后未做端到端复验
❌ 选择地图真正切换运行中地图（/api/maps/select 只记录待加载项）
❌ 新建空白 yaml/pgm 地图（曾实现后回退）
```

**11-19 定位问题（可能仍存在）**：车静止时 AMCL 不更新 → `/amcl_pose` 与 `map→odom` 过期 →
`health.localized=false` → 一律报「雷达、里程计或定位尚未就绪」或「导航 Action 不可用」。
已做：`navigation.launch` 固化 `update_min_d=0`、`update_min_a=0`、`transform_tolerance=1.0`；
`wheel_odometry.py` 的 **TF +0.3 s 超前补偿已回退**（它会让 TF 缓冲「最早数据在未来」，
任何按激光时刻的查询都报 extrapolation into the past）。

**11-23 现场进展**：用 `_tmp\add_points.py` 把 5 个地点（中段 / 深处 / 尽头 / 远端 / 空区）
连同当前 `map_id` 写进运行配置，`restart_app.sh` 重启应用，隧道与页面正常。
这批点是否都能真正导航到位，仍属**未验证**。

**待办优先级**（同 [当前进度与核心逻辑.md](当前进度与核心逻辑.md) §11）：
复验定位链 → 选择地图真正生效 → 语音失败给出具体原因 → 新建空白地图 → 提交一次 Git。

---

## 7. 常见改动落在哪

| 要改的东西 | 文件 |
|---|---|
| 网页接口 / 路由 / 鉴权 | `bobac_practicum\scripts\app.py` |
| 指令词与业务状态机 | `scripts\core.py`（`parse_command`、`RobotController`） |
| 健康检查 / 导航发送 | `scripts\ros_adapter.py`（`health()`、`LiveNavigation.send`） |
| 建图遥控与心跳 | `scripts\mapping_control.py`（`MappingLease`、`KeyboardLease`） |
| 人脸 / 会话 | `scripts\face_recognition.py`、`scripts\access_gate.py` |
| 像素→米制、地图清单 | `scripts\map_tools.py` |
| 前端页面与交互 | `bobac_practicum\web\*.js`、`*.html` |
| ROS 启动栈 | `launch\navigation.launch`、`mapping.launch`、`static.launch` |
| 机器人启停 | `deploy\bobac_practicum_ctl.sh` → 部署为 `~/bobac_practicum_ctl.sh` |
| 笔记本一键入口 | `console\bobac_launcher.py` |

上线流程：改 → `scp`（或 `console\apply_*.py` / `patched_*` 覆盖）→ `ctl stop && ctl up nav` → 验证。
Python 脚本改完**不需要** `catkin_make`；launch 下次启动生效。

---

## 8. 验证命令

在 `D:\课设\gh_repo2\lunshijiqiren` 下：

```powershell
python -m unittest discover -s bobac_practicum/tests -v
node --check bobac_practicum/web/app.js
node --check bobac_practicum/web/login.js
node --check bobac_practicum/web/modules.js
node --check bobac_practicum/web/mapping.js
```

离线看界面（不连 ROS、不采人脸，模拟身份必须明确标注）：
`python bobac_practicum/scripts/offline_preview.py --port 8766`，先确认端口没被占用。

机器人上的一条式体检：

```bash
source /opt/ros/kinetic/setup.bash
source /home/bobac2/bobac_practicum_ws/devel/setup.bash
rostopic hz /scan                     # ~7.6 Hz
rostopic hz /odom                     # ~50 Hz
rostopic hz /amcl_pose                # ≥2 Hz（静止也要有）
rosrun tf tf_echo /map /base_footprint
rostopic list | grep move_base
curl -s -H 'Host: 127.0.0.1:8765' http://127.0.0.1:8765/api/status
```

- 缺依赖导致的跳过项**不算通过**；HTTP 测试被沙箱挡住就走审批，不要删测试或假装通过。
- 改了页面交互就要在浏览器里实际走一遍关键路径与错误态；语法检查不能替代视觉验收。

---

## 9. 已知坑（都是本机真实踩过的）

| 现象 | 根因 / 处理 |
|---|---|
| 页面 403「仅允许本机或 SSH 隧道访问」 | 本机端口不是 8765，或 Host 头不对；杀掉旧 `ssh -L` 重建 |
| 页面打不开但日志写 `HTTP ready` | 隧道断了，应用本身正常；`curl -v` 看是否 `Connection reset` |
| 一直报「雷达、里程计或定位尚未就绪」 | 看 `health` 三项，多数是 `localized`；先查 `/amcl_pose` 与 `tf map→base` |
| `rosnode list` 里没有 `/bobac_practicum` | 手工启动顺序错，app 与 master 断连；`ctl stop && ctl up nav` |
| `Address already in use` | 旧 app 占着 8765；结束旧进程再用 ctl |
| AMCL `Dropped 100.00%` | TF 在扫描时刻查不到，常见于给 TF 时间戳做了超前补偿 |
| 车静止 2 秒后定位失效 | `update_min_d/a` 不为 0；已固化为 0，别再改回去 |
| `pixel_goal()` 取值报错 | 它返回 **dict** 不是 tuple，别写 `pose[0]` |
| 地点导航被拒 | `pose=null`（未标定）或 `map_id` 与当前 `/map` 不一致；重建地图后必须重新标定 |
| 配置 JSON 变几十字节 | 非原子写入被截断；从 `*.bak_*` 恢复并改成临时文件+rename |
| 建图页按键没反应 | 后端没带 `--mapping-teleop --mapping-keyboard`，或初始处于暂停 |

---

## 10. 协作方式

1. 每轮收到具体任务，先说明理解和预计耗时范围；不确定就说不确定在哪，不编时间。
   - 上限 ≤3 分钟：说明后直接做。
   - 上限 >3 分钟：先问是否开始。
   - 同一任务内的继续、工具调用不算新任务，不重复询问。
2. 先看现状（文件、日志、机器人状态）再动手；一次性做连贯的小任务，不同时开多摊。
3. 不自动起并行 Agent、定时任务或新增 MCP；需要时按用户具体要求来。
4. 每轮结束按这个格式汇报：
   - 改了什么（文件清单）；
   - 实际跑了什么验证、结果如何、环境是什么；
   - 没做什么、为什么；
   - 是否部署、是否发生真实运动；
   - 剩余限制与下一步。
5. 历史记录里的测试结果**不算本轮的通过证据**。
