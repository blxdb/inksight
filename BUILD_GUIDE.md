# InkSight 手写字符 → SVG 转换器 — 构建与部署指南

> 目标：将此项目打包为 Docker 镜像，推送到共绩算力 Harbor 仓库，在 GPU 平台上跑 Job 批处理，生成原子化 SVG 字符文件。

---

## 一、前置检查

### 需要的工具

| 工具 | 检查命令 | 说明 |
|------|---------|------|
| Docker Desktop | `docker --version` | 如果没启动，先重启 Docker Desktop |
| Git | `git --version` | 检查项目是否完整 |
| 网络 | — | 需要能访问 HuggingFace（下载模型）和 `harborpush.suanleme.cn` |

### 项目文件清单

确认 `D:\inksight\` 目录下有以下文件：

```
D:\inksight\
├── Dockerfile              ← 镜像构建文件
├── process.py              ← 核心处理脚本
├── entrypoint.sh           ← 容器入口（处理→打包→HTTP下载服务）
├── push.ps1                ← 一键构建+推送脚本
├── .dockerignore           ← 排除不必要文件
├── pyproject.toml          ← Python 依赖
├── uv.lock                 ← 依赖锁定文件
├── utils/                  ← InkSight 工具库
├── inksight.jpg            ← ⚠️ 你的手写字符输入图片
└── 共绩算力登陆.txt         ← Harbor 仓库登录信息
```

---

## 二、构建镜像

### 步骤 1：登录 Harbor 仓库

```powershell
# 打开 PowerShell，进入项目目录
cd D:\inksight

# 登录共绩算力的镜像仓库
docker login harborpush.suanleme.cn --username=wangduoduo2026
# 密码在 共绩算力登陆.txt 里
```

### 步骤 2：构建镜像

```powershell
# 在 D:\inksight 目录下执行
docker build -t inksight-processor .
```

> ⏱ 首次构建需要 15-30 分钟，因为：
> 1. 拉取 `nvidia/cuda:12.2.2-cudnn8-runtime-ubuntu22.04` 基础镜像 (~3GB)
> 2. 安装 Python 3.11 + 系统依赖
> 3. `uv sync` 安装 TensorFlow 2.17 + docTR 等 (~1GB)
> 4. 从 HuggingFace 下载 InkSight Small-p 模型权重 (~500MB)
>
> **以后修改代码重新构建时，因为缓存了基础层和依赖层，只需几秒钟。**

### 步骤 3：打标签并推送

```powershell
# 方式 A：使用一键脚本
.\push.ps1

# 方式 B：手动操作
docker tag inksight-processor harborpush.suanleme.cn/wangduoduo2026/inksight-processor:v1
docker tag inksight-processor harborpush.suanleme.cn/wangduoduo2026/inksight-processor:latest
docker push harborpush.suanleme.cn/wangduoduo2026/inksight-processor:v1
docker push harborpush.suanleme.cn/wangduoduo2026/inksight-processor:latest
```

---

## 三、在共绩算力创建 Job

### 控制台操作

1. 打开 https://console.suanli.cn → 登录（账号密码在 `共绩算力登陆.txt`）
2. 左侧菜单 → **Job批处理** → **新增Job批处理**
3. 填写以下参数：

| 字段 | 值 |
|------|-----|
| 镜像地址 | `harborpush.suanleme.cn/wangduoduo2026/inksight-processor:v1` |
| 启动命令 | **留空**（使用 Dockerfile 内置的 ENTRYPOINT） |
| 区域 | 四川三区 `scws-p1` |
| GPU 型号 | 4090-48G 1卡（或其他有库存的型号） |
| 实例类型 | ✅ 抢占式实例（大幅折扣） |
| 队列 | 创建或选择一个已有队列 |
| 组内任务总数 | 1 |
| 组内并发上限 | 1 |
| 单元运行时长 | 建议设为 30 分钟（实际处理通常 ≤ 5 分钟，但 HTTP 下载需要容器保持运行） |
| ⚙️ 环境变量 | 如果平台给了你外网访问地址，设置 `INK_PLATFORM_URL`（可选） |

4. 勾选服务协议 → 点击 **部署服务**

### 下载结果

Job 启动后，查看**实时日志**，会看到类似这样的输出：

```
==========================================
  处理完成！
==========================================
  SVG 文件: 62 个
  ZIP 包:   inksight_svgs.zip
  HTTP 下载服务已启动:
  容器地址: http://172.17.0.2:8080/
==========================================
```

**下载方式（在你的本地电脑打开新终端）：**

```bash
# 查看文件列表
curl http://<容器地址>:8080/

# 下载单个 SVG
curl -O http://<容器地址>:8080/A.svg

# 下载全部 SVG + ZIP
wget -r -np http://<容器地址>:8080/
curl -O http://<容器地址>:8080/inksight_svgs.zip
```

> ⚠️ 如果平台不暴露端口，上述地址可能无法直接访问。此时可以：
> - 检查共绩算力控制台是否有「文件管理」或「Web 终端」功能
> - 通过平台的 OpenAPI 拉取结果文件
> - 或者联系我加一个直接上传到对象存储的备选方案

**下载完成后，记得在控制台停止 Job，避免持续计费。**

---

## 四、输出说明

### SVG 文件

每个字符一个独立的 SVG 文件，命名规则：

| 文件名 | 说明 |
|--------|------|
| `A.svg` | InkSight 自动识别出是大写 A |
| `a.svg` | 识别出是小写 a |
| `0.svg` | 识别出是数字 0 |
| `√.svg` | 识别出是根号 |
| `char_001.svg` | 模型无法识别时 fallback 到序号命名 |

### 在 Blender 中使用

1. 打开 Blender → `File → Import → SVG`
2. 选择下载的 `.svg` 文件
3. 每个字符自动成为独立的 Grease Pencil 对象，位于原点
4. 可在 3D 视图中自由排列组合

### SVG 格式特性

| 特性 | 说明 |
|------|------|
| 每个笔画一个 `<path>` | 保持笔画独立性 |
| 坐标居中到原点 | Blender 导入后直接可用 |
| `stroke="#1a1a1a"` | 深灰色描边，适合 3D 视口 |
| `stroke-width="2.0"` | 适中粗细 |

---

## 五、常见问题

### Q: 构建时 HuggingFace 下载模型太慢？
参考共绩算力的网络加速文档：
- https://suanli.cn/docs/platform/resource-acceleration/b8t4wbnsdieruakadxsc2mnrn2f/
- https://suanli.cn/docs/platform/resource-acceleration/askjwkwl5i5i8fkzkuacbdnfnig/

### Q: 想换一张输入图片？
把新图片放到 `D:\inksight\` 目录下，重命名为 `inksight.jpg`，或者修改启动命令参数：
```
# 在 Job 的「启动命令」里写（覆盖 ENTRYPOINT）：
.venv/bin/python process.py --input 你的图片.jpg
```

### Q: 容器启动后看不到 HTTP 地址？
共绩算力的 Job 容器可能不暴露端口映射。检查控制台是否有「文件管理」功能，或联系我加备选方案（推送到阿里云OSS等）。

### Q: 构建成功后想修改代码重推？
修改 `process.py` 或 `entrypoint.sh` 后，重新运行：
```powershell
docker build -t inksight-processor .          # 利用缓存，几秒完成
docker push harborpush.suanleme.cn/wangduoduo2026/inksight-processor:v1
```
