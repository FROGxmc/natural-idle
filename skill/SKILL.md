---
name: natural-idle
description: 数字人/虚拟人动作"去AI味"自然微扰后处理。当用户需要给 AI 数字人口播、虚拟主播、A2F/Wav2Lip/SadTalker/MetaHuman 等生成的说话动作去僵硬、去AI味，要求头部轻微随机位移/各方向小点头、面部肌群轻微微动、嘴部同一字每次开合大小有区别、情绪克制不夸张、身体轻微跟动时使用。输入任意 blendshape/骨骼权重动作 CSV（列名含通道关键词），输出叠加低频平滑随机扰动的同结构 CSV，并可选输出扰动诊断 JSON。仅做动作后处理，不生成画面、不替换唇形同步模型。适用：口播视频、虚拟主播、数字人短视频、视频生成后续修。
---

# Natural-Idle 自然微扰去AI味

对任意数字人动作序列做**分层低频随机扰动后处理**，解决 AI 数字人僵硬、口型固定、表情用力过猛的"AI味"。

## 核心能力

- **头部**：各方向轻微随机位移 / 小点头 / 歪头 / 漂移（非循环动画）
- **面部肌群**：眉、脸颊、眼周微弱随机微动
- **嘴部**：口型权重叠加小幅度随机偏移 → **同一个字，每次嘴开合大小略有区别**（自带口型保护，不脱轨）
- **情绪**：上限锁死 + 随机波动，拒绝 100% 饱满夸张表情
- **躯干/双肩**：极慢极弱漂移，双肩左右独立随机不同步；躯干→头部弱耦合联动
- 所有通道独立开关、独立强度、独立随机种子；固定种子可复现，随机种子每次效果不同

## 快速使用

```bash
# 演示模式（生成模拟口播 + 扰动前后 CSV + 诊断 JSON）
python scripts/natural_idle.py --demo --outdir ./demo_out --plot ./demo_out/plot.json

# 处理真实动作 CSV
python scripts/natural_idle.py -i input.csv -o output.csv --config config.json

# 仅查看统计（不写文件）
python scripts/natural_idle.py -i input.csv --stats
```

## 输入要求

- CSV：第一行为列名，后续每行一帧；值通常为 0~1（非 0~1 亦可用，扰动幅度按相对峰值计）。
- 列名自动按关键词分层（不区分大小写）：
  - `body`：body/spine/chest/torso/hip/pelvis/躯干/身体/脊柱
  - `shoulder`：shoulder/clavicle/肩（左右按列名含 l/left/左 区分）
  - `head`：head/neck/pitch/yaw/roll/头/颈
  - `face`：brow/cheek/eye/blink/squint/smile/nose/眉/脸/颊/眼
  - `mouth`：mouth/lip/jaw/tongue/嘴/唇/颌
  - `emotion`：emotion/情绪/express/happy/angry/surprise
- 无法识别的列原样保留不动。
- 可选：名为 `energy`（或通过 config 的 `energy_column` 指定）的语音能量列，存在时静音段自动把上身/头部扰动压低（Idle 模式）。

## 参数（config JSON，缺省见 DEFAULT_CONFIG）

| 参数 | 默认 | 说明 |
|---|---|---|
| body_str / shoulder_str / head_str / face_str / mouth_str | 0.06/0.05/0.12/0.08/0.15 | 各通道峰值扰动强度 |
| body_scale / shoulder_scale / head_scale / face_scale / mouth_scale | 0.12/0.10/0.06/0.08/0.10 | 噪声尺度，越大越慢越平缓 |
| emotion_max | 0.6 | 情绪上限锁死（防夸张） |
| emotion_wave | 0.2 | 情绪随机波动幅度 |
| body_head_couple | 0.2 | 躯干带动头部弱耦合系数（0.15~0.25 最佳） |
| global_strength | 1.0 | 全局缩放 |
| enable_* | true | 各通道独立开关 |
| seed | 42 | 固定种子可复现；null 每次不同 |
| energy_column / idle_reduce | "" / 0.4 | 语音能量调制与静音降幅 |
| mouth_guard | 0.25 | 口型保护：单帧口部偏移上限 |

经验值：头 0.10~0.15、脸 0.06~0.10、嘴 0.12~0.18、躯干 ≤0.08（>0.1 易违和）、肩 ≤0.06、emotion_max 0.5~0.7。口型扰动超过 0.2 易轻微跑音，谨慎。

## 输出

- 输出 CSV：与输入同列名、同帧数、值域钳制 0~1。
- `--plot` 诊断 JSON：`input`/`output` 双序列 + `stats`（各通道扰动峰值与 RMS 差值），可用于可视化对比验证。

## 约束与红线

- 只做动作后处理，**不封装、不包含、不调用任何底层唇形同步模型**（A2F/Wav2Lip/SadTalker 等由用户自备），避免版权与分发风险。
- 扰动是叠加增量，不是替换主信号；默认强度下口型依然对齐音频。
- 全身数字人：不要对髋/大腿加本扰动；下肢如需动，单独做重心漂移通道。
- 噪声必须低频平滑（本实现已内建），高强度+高频=恐怖谷。
