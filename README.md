# NaturalIdle · 数字人「去AI味」自然微扰后处理层

NaturalIdle 是一个**纯后处理工具**：它不生成画面、不训练模型、也不替换任何唇形同步模型。它的工作对象是「你已经得到的数字人动作序列」——把任意数字人（A2F / Wav2Lip / SadTalker / MetaHuman 等）输出的 blendshape 或骨骼权重 CSV，叠加一层**分层低频随机扰动**，让僵硬的 AI 数字人多一点真人式的自然微动。

可以把它理解成挂在任意数字人身上的一层「后期修饰」：输入动作数据，输出同结构、同帧数、仅叠加了自然微动的动作数据。

## 它解决什么问题

| AI 数字人常见的「AI 味」 | 成因 | NaturalIdle 怎么处理 |
|---|---|---|
| 同一个字，嘴型开合永远一样大 | 确定性 viseme 映射 | 口型权重叠加小幅随机偏移 → 同字不同嘴型 |
| 头部像焊死，只有预制循环摆动 | 固定 idle 动画 | 各方向低频随机位移 / 点头 / 歪头 / 漂移（非循环） |
| 表情用力过猛、情绪 100% 饱满 | 情绪权重被拉满 | 情绪上限锁死 + 随机波动（默认 ≤ 0.6） |
| 肩膀同步抬起、上身钉死 | 无上身联动 | 双肩独立随机错落 + 躯干极弱跟动 + 语音能量联动 |
| 动作抽搐、抖动、落入恐怖谷 | 高频噪声 | 高斯平滑低频噪声，杜绝高频抽搐 |

## 核心特性

- **分层六通道低频随机扰动**，强度按真人发力逻辑逐级递减：
  躯干 0.06 → 双肩 0.05 → 头部 0.12 → 面部 0.08 → 嘴部 0.15 → 情绪上限 0.6（均为默认值，可独立调整）。
- **同字不同嘴型**：嘴部通道叠加小幅随机偏移，默认强度下同一个字每次开合大小略有区别。
- **口型保护不脱轨**：单帧口部偏移受 `mouth_guard`（默认 0.25）钳制，扰动是叠加增量、不替换主信号，口型依然对齐音频。
- **情绪上限锁死**：情绪通道输出被钳制在 `emotion_max`（默认 0.6）以内，再叠加随机波动，避免表情夸张。
- **语音能量联动**：检测到 `energy` 列时，静音段自动把上身 / 头部扰动压低（Idle 模式）。
- **纯 numpy、零第三方依赖**，Python 3.9+ 即可运行；每个通道独立开关、独立强度、独立随机种子，固定种子可复现。
- **任意动作 CSV 通用**：只要你手里有数字人输出的 blendshape / 骨骼权重 CSV（A2F、Wav2Lip、SadTalker、GLDiTalker、MetaHuman 等均可），按列名关键词自动分层，即可接入。

## 快速开始

环境要求：Python 3.9+，仅依赖 `numpy`。

```bash
pip install numpy

# 1. 运行演示：生成模拟口播数据 + 扰动前后 CSV + 诊断 JSON
python natural_idle.py --demo --outdir ./demo_out --plot ./demo_out/plot.json

# 2. 处理你自己的动作 CSV
python natural_idle.py -i input.csv -o output.csv --config config.json

# 3. 只查看扰动统计（不写文件）
python natural_idle.py -i input.csv --stats
```

仓库内 `demo_out/` 已包含一组演示数据：`demo_input.csv`（机械的「AI 味」原始动作）与 `demo_output.csv`（叠加扰动后的结果），可以直接对比。浏览器打开 `demo.html` 可交互查看扰动前后曲线对比。

### 演示视频

约 27 秒的真实录屏，演示在浏览器中打开 `demo.html`、查看扰动前后双图表对比的实际效果：

[media/NaturalIdle_demo_30s.mp4](./media/NaturalIdle_demo_30s.mp4)（1280×720，H.264）

### 输入 CSV 格式

- 第一行为列名，后续每行一帧，值通常为 0~1（非 0~1 亦可用，扰动幅度按相对峰值计）。
- 列名自动按关键词分层（不区分大小写，命中即归类）：

| 通道 | 列名关键词 |
|---|---|
| body 躯干 | body / spine / chest / torso / hip / pelvis / 躯干 / 脊柱 |
| shoulder 肩 | shoulder / clavicle / 肩（列名含 l / left / 左 归左肩，否则右肩） |
| head 头 | head / neck / pitch / yaw / roll / 头 / 颈 |
| face 面 | brow / cheek / eye / blink / squint / smile / nose / 眉 / 眼 |
| mouth 嘴 | mouth / lip / jaw / tongue / 嘴 / 唇 / 颌 |
| emotion 情绪 | emotion / 情绪 / express / happy / angry / surprise |

- 无法识别的列原样保留不动。
- 可选：名为 `energy` 的语音能量列（或通过 `energy_column` 指定），存在时静音段自动压低上身 / 头部扰动。

### 参数速查

完整配置见 `config.example.json` 与 `skill/SKILL.md`。

| 参数 | 默认值 | 建议范围 |
|---|---|---|
| body_str | 0.06 | ≤ 0.08（>0.1 违和） |
| shoulder_str | 0.05 | ≤ 0.06 |
| head_str | 0.12 | 0.10 ~ 0.15 |
| face_str | 0.08 | 0.06 ~ 0.10 |
| mouth_str | 0.15 | 0.12 ~ 0.18（>0.2 易跑音） |
| emotion_max | 0.6 | 0.5 ~ 0.7 |
| body_head_couple | 0.2 | 0.15 ~ 0.25 |
| seed | 42 | 固定种子可复现，null = 每次不同 |

## 输出说明

- 输出 CSV 与输入同列名、同帧数，值域钳制 0~1。
- `--plot` 输出诊断 JSON：`input` / `output` 双序列 + `stats`（各通道扰动峰值与 RMS 差值），用于可视化对比与验证。

## 使用边界（请先读）

- **你需要自备动作数据**：本工具不生成任何动作，它只处理「你已经有的数字人动作序列」。请先用你的数字人模型 / 管线产出 CSV，再用本工具做后处理。
- **闭源 SaaS 不可接入**：HeyGen、D-ID 等闭源数字人平台不开放底层动作数据，无法接入；这是使用边界，不是缺陷。
- **不捆绑、不分发任何第三方唇形模型**：A2F / Wav2Lip / SadTalker 等均由用户自行获取与安装，本仓库不包含、不调用它们。
- 强度是经验值而非保证：默认参数面向口播类数字人；全身形象请只对上半身使用，下肢如需动作请单独做重心漂移通道。

## 目录结构

```
natural-idle/
├── natural_idle.py            # 核心算法 + CLI（可独立运行）
├── demo.html                  # 可交互演示页（浏览器打开，查看扰动前后对比）
├── config.example.json        # 参数配置示例
├── demo_out/                  # 演示数据（输入 / 输出 CSV + 诊断 JSON）
│   ├── demo_input.csv
│   ├── demo_output.csv
│   └── plot.json
├── tools/build_demo_html.py    # 由 plot.json 重新生成 demo.html
├── media/
│   └── NaturalIdle_demo_30s.mp4  # demo.html 录屏演示（约27秒，1280×720）
└── skill/SKILL.md             # 工具说明文档（含完整参数表与经验值）
```

## Pro 版本规划

> 以下为规划中（planned）内容，当前开源版本不包含，不代表已提供的服务或可购买渠道。

- 可视化调参桌面端（实时预览扰动效果）
- 视频帧序列直通管线（直接对接渲染输出）
- 更多预置形象模板与行业（口播 / 虚拟主播 / 短视频）参数包

Pro 版本如有进展会在本仓库更新，暂无购买链接。

## License

[MIT](./LICENSE) © FROGxmc
