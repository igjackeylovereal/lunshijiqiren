# lunshijiqiren · bobac2 轮式智能机器人综合实训

基于 **bobac2 轮式服务机器人**（Ubuntu 16.04 + ROS Kinetic）的课程实训系统：把**人脸身份识别**、**中文语音交互**、**SLAM 建图与自主导航**整合到同一个网页端，笔记本即可完成全部操作。

---

## 功能

| 模块 | 说明 |
|---|---|
| 人脸识别 | OpenFace 128 维特征 + 多帧表决，网页刷脸登录；一次验证后整个会话有效 |
| 中文语音 | 按《bobac2 使用文档》5.1「语音综合应用」：唤醒「元宝」→ 切换 闲聊/控制/导航 模式 |
| 语音控制 | 前进 / 后退 / 左转 / 右转 / 停止（限速限时，导航中拒绝执行） |
| 语音导航 | “我要去教室” → 查地点表 → move_base 规划并前往 |
| SLAM 建图 | 网页键盘遥控（W/A/S/D），实时栅格地图，一键保存 `.pgm/.yaml` |
| 自主导航 | map_server + AMCL + move_base（TEB），网页地图选点、设朝向、确认导航 |
| 模式切换 | 网页内一键切换 导航 / 建图 模式，无需登录机器人终端 |
| 安全 | 服务端会话校验、地图 ID/栅格校验、速度看门狗、失联停车、物理急停独立 |

## 目录结构

```text
bobac_practicum/        机器人端 ROS 包（Python 2.7）
├── scripts/            app.py（HTTP 服务）、core.py（交互状态机）、ros_adapter.py、
│                       face_recognition.py、mapping_control.py、access_gate.py …
├── web/                登录页、配置页、建图页（原生 JS）
├── launch/             static / navigation / mapping / voice_services
├── config/             默认配置
├── assets/             人脸模型（OpenFace nn4、SSD 检测器、Haar 级联）
└── tests/              单元与集成测试

tools/laptop/           笔记本工具：启动台、补丁脚本
tools/robot/            机器人端脚本：practicum_ctl.sh、安装/上传脚本
docs/                   操作手册、实践手册、页面认证说明
```

## 快速开始

### 1. 机器人端

```bash
# 依赖厂家 bobac2_ws（消息、驱动、SLAM、导航、语音服务）
cd ~/bobac_practicum_ws
catkin_make
bash ~/bobac_practicum_ctl.sh up nav
```

### 2. 笔记本端

```powershell
# 依赖 Python 3 + paramiko
.\tools\laptop\启动台.bat
```

填写机器人 IP、账号 `bobac2`、密码，点「一键启动并打开」：自动上传控制脚本 → 检查/启动运行栈 → 建立 8765 隧道 → 打开网页。

### 3. 网页操作

```text
/            人脸验证（一次）
/console     地图选点导航、语音、人脸录入、模式切换
/mapping     键盘建图（W/A/S/D，松开停车）
```

## 语音指令（文档 5.1）

```text
“元宝元宝”      → 我在，请说指令
“切换模式”      → 请选择：闲聊、控制或导航
“控制模式”      → 已切换到控制模式
“前进/后退/左转/右转/停止”
“导航模式”      → 已切换到导航模式
“我要去教室”    → 规划并前往（需先标定地点坐标）
```

## 环境

- 机器人：Ubuntu 16.04.7、ROS Kinetic、Python 2.7、OpenCV 3.3
- 厂家工作空间：`/home/bobac2/bobac2_ws`（保持原样，不改动）
- 本工程工作空间：`/home/bobac2/bobac_practicum_ws`
- 运行数据：`/home/bobac2/bobac_practicum_run`（配置、地图、人脸样本、日志）

> 运行数据（人脸样本、地图、日志、会话缓存）不入库，见 `.gitignore`。

## 已知限制

- 人脸识别阈值与准确率需按现场光照标定；仓库内不含人脸样本。
- 地点表需现场标定（`教室` 初始无坐标），未标定时语音导航会被拒绝。
- 障碍物语义类别识别未实现，仅保留激光占用检测与导航避障。
- 语音识别依赖讯飞在线服务，需机器人联网。

## 许可

课程实训项目，仅供学习使用。第三方模型见 `bobac_practicum/assets/` 内的许可说明。
