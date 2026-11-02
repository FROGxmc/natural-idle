#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
natural_idle.py — 数字人动作"去AI味"自然微扰后处理层 v1.0
========================================================================
作用：不生成画面、不替换底层唇形同步模型，只对任意数字人输出的
      blendshape / 骨骼权重序列做"分层低频随机扰动后处理"：

      * 躯干/上身：极慢、极弱漂移（脊柱俯仰/侧倾/微转），跟随语音能量弱联动
      * 双肩：左右独立随机微错落（不同步，拒绝"焊死肩膀"）
      * 头部：各方向轻微随机位移/点头/歪头/漂移（非循环动画）
      * 面部肌群：眉、脸颊、眼周微弱随机微动
      * 嘴部：口型权重叠加小幅度随机偏移 —— 同一个字每次嘴开合大小略有区别
      * 情绪：上限锁死 + 随机波动，拒绝100%饱满夸张表情
      * 躯干→头部弱耦合联动，模拟颈椎连带

设计原则：
  1. 扰动是"叠加增量"，不是替换主信号 —— 口型依然对齐音频，只是有自然浮动
  2. 所有噪声为低频平滑噪声（高斯平滑白噪声），杜绝高频抽搐抖动
  3. 所有通道独立控幅、独立开关、独立随机种子
  4. 纯 numpy 实现，零第三方依赖，Python 3.9+

输入/输出：
  输入 CSV：任意数字人动作序列，列名含通道类别关键词（自动分层），
            例如 headPitch/headYaw、jawOpen/lipPress、browUp、shoulderL 等；
            或通过 --map 指定"列名 -> 类别"。
  输出 CSV：与输入同结构、同帧数、同列名的扰动后序列（值域钳制 0~1）。
  附加输出：--plot 可输出扰动诊断 JSON（各通道峰值幅度/帧数，供可视化）。

命令行示例：
  python natural_idle.py -i in.csv -o out.csv --config config.json
  python natural_idle.py --demo --outdir ./demo_out          # 生成演示数据
  python natural_idle.py -i in.csv -o out.csv --stats         # 仅打印统计
========================================================================
"""

import argparse
import json
import math
import os
import sys
import csv
import re

import numpy as np

__version__ = "1.0.0"

# ---------------------------------------------------------------------------
# 类别 -> 列名关键词（不区分大小写，命中即归类）
# ---------------------------------------------------------------------------
CHANNEL_KEYWORDS = {
    "body":     ["body", "spine", "chest", "torso", "hip", "pelvis", "躯干", "身体", "脊柱", "胸腔"],
    "shoulder": ["shoulder", "clavicle", "肩"],
    "head":     ["head", "neck", "pitch", "yaw", "roll", "头", "颈"],
    "face":     ["brow", "cheek", "eye", "blink", "squint", "smile", "nose", "眉", "脸", "颊", "眼"],
    "mouth":    ["mouth", "lip", "jaw", "tongue", "嘴", "唇", "颌"],
    "emotion":  ["emotion", "情绪", "express", "happy", "angry", "surprise"],
}

CATEGORY_ORDER = ["body", "shoulder", "head", "face", "mouth", "emotion"]

DEFAULT_CONFIG = {
    # 每通道峰值扰动强度（0~1，相对该通道权重量程）
    "body_str":        0.06,
    "shoulder_str":    0.05,
    "head_str":        0.12,
    "face_str":        0.08,
    "mouth_str":       0.15,
    # 噪声尺度：越大越慢越平缓（0~1，约等于平滑核占全序列比例）
    "body_scale":      0.12,
    "shoulder_scale":  0.10,
    "head_scale":      0.06,
    "face_scale":      0.08,
    "mouth_scale":     0.10,
    # 情绪：上限锁死（防夸张）+ 随机波动幅度
    "emotion_max":     0.6,
    "emotion_wave":    0.2,
    "emotion_scale":   0.12,
    # 躯干带动头部弱耦合系数（0.15~0.25 最自然）
    "body_head_couple": 0.2,
    # 全局缩放与开关
    "global_strength": 1.0,
    "enable_body":     True,
    "enable_shoulder": True,
    "enable_head":     True,
    "enable_face":     True,
    "enable_mouth":    True,
    "enable_emotion":  True,
    # 随机种子：固定种子=可复现；null=每次不同
    "seed":            42,
    # 静音Idle模式：若存在 voice 能量列，静音段把上身/头部扰动压到更低
    "energy_column":   "",          # 例如 "energy"/"volume"，留空=不启用
    "idle_reduce":     0.4,         # 静音时上身噪声乘数
    "mouth_guard":     0.25,        # 口型保护：单帧口部扰动偏移不得超过此值
}


# ---------------------------------------------------------------------------
# 低频平滑噪声（高斯平滑白噪声，替代生硬高斯抖动）
# ---------------------------------------------------------------------------
def _gaussian_kernel(sigma):
    radius = max(1, int(math.ceil(3 * sigma)))
    x = np.arange(-radius, radius + 1, dtype=float)
    k = np.exp(-(x ** 2) / (2 * sigma * sigma))
    return k / k.sum()


def smooth_noise(n, scale=0.08, seed=None, amp=1.0):
    """返回长度 n、峰值约 amp 的低频平滑噪声（均值~0）。"""
    rng = np.random.default_rng(seed)
    raw = rng.normal(0.0, 1.0, n)
    sigma = max(0.75, scale * n)
    k = _gaussian_kernel(sigma)
    pad = len(k) // 2
    if pad > 0:
        padded = np.pad(raw, pad, mode="reflect")
        sm = np.convolve(padded, k, mode="same")[pad:-pad]
    else:
        sm = raw
    peak = float(np.max(np.abs(sm))) or 1.0
    return (sm / peak * amp).astype(float)


# ---------------------------------------------------------------------------
# 列名分层
# ---------------------------------------------------------------------------
def classify_columns(columns):
    """返回 {类别: [列索引...]}，未识别列归入 'other'（原样保留不动）。"""
    mapping = {c: [] for c in CATEGORY_ORDER}
    mapping["other"] = []
    for i, col in enumerate(columns):
        cl = col.lower()
        hit = None
        for cat in CATEGORY_ORDER:
            if any(kw.lower() in cl for kw in CHANNEL_KEYWORDS[cat]):
                hit = cat
                break
        mapping[hit if hit else "other"].append(i)
    return mapping


# ---------------------------------------------------------------------------
# 主扰动函数
# ---------------------------------------------------------------------------
def apply_natural_disturb(seq, columns, cfg=None, seed=None):
    """
    seq: numpy 2D (n_frames, n_channels)，值域通常 0~1
    columns: 列名列表，与 seq 的通道一一对应
    返回: (out_seq, stats)
    """
    cfg_full = dict(DEFAULT_CONFIG)
    if cfg:
        cfg_full.update(cfg)
    cfg = cfg_full
    seed = seed if seed is not None else cfg["seed"]

    n_frames, n_ch = seq.shape
    out = np.array(seq, dtype=float).copy()
    mapping = classify_columns(columns)

    # 语音能量调制（可选）：上身/头部扰动跟随声音强弱
    energy = None
    if cfg.get("energy_column"):
        ec = cfg["energy_column"].lower()
        for i, c in enumerate(columns):
            if c.lower() == ec:
                energy = np.clip(seq[:, i], 0, 1)
                break
    if energy is None and "energy" in [c.lower() for c in columns]:
        for i, c in enumerate(columns):
            if c.lower() == "energy":
                energy = np.clip(seq[:, i], 0, 1)
                break

    gs = float(cfg["global_strength"])
    seed_base = seed if seed is not None else 0

    def chan_scale(enable, strength):
        return (gs * float(strength)) if enable else 0.0

    # 各通道噪声（独立种子，互不相关）
    n_body    = smooth_noise(n_frames, scale=cfg["body_scale"],     seed=seed_base,   amp=1.0)
    n_shouldL = smooth_noise(n_frames, scale=cfg["shoulder_scale"], seed=seed_base+1, amp=1.0)
    n_shouldR = smooth_noise(n_frames, scale=cfg["shoulder_scale"], seed=seed_base+2, amp=1.0)
    n_head    = smooth_noise(n_frames, scale=cfg["head_scale"],     seed=seed_base+3, amp=1.0)
    n_face    = smooth_noise(n_frames, scale=cfg["face_scale"],     seed=seed_base+4, amp=1.0)
    n_mouth   = smooth_noise(n_frames, scale=cfg["mouth_scale"],    seed=seed_base+5, amp=1.0)
    n_emot    = smooth_noise(n_frames, scale=cfg["emotion_scale"],  seed=seed_base+6, amp=1.0)

    # 能量调制：静音/低音量时上身与头部扰动减弱
    if energy is not None:
        mod = cfg["idle_reduce"] + (1.0 - cfg["idle_reduce"]) * energy
        n_body  = n_body * mod
        n_shouldL = n_shouldL * mod
        n_shouldR = n_shouldR * mod
        n_head  = n_head * mod

    stats = {"frames": n_frames, "channels": n_ch,
             "peaks": {}, "per_channel_rms": {}}

    # 1) 躯干/上身（最慢最弱）
    s = chan_scale(cfg["enable_body"], cfg["body_str"])
    for idx in mapping["body"]:
        out[:, idx] = np.clip(out[:, idx] + n_body * s, 0, 1)
        stats["peaks"]["body"] = max(stats["peaks"].get("body", 0), s)

    # 2) 双肩：左右独立、不同种子，天然不同步
    s = chan_scale(cfg["enable_shoulder"], cfg["shoulder_str"])
    sL, sR = s, s
    for idx in mapping["shoulder"]:
        # 按列名猜测左右（肩字眼带 l/left/r/right）
        cl = columns[idx].lower()
        noise = n_shouldL if ("l" in cl or "left" in cl or "左" in columns[idx]) else n_shouldR
        out[:, idx] = np.clip(out[:, idx] + noise * (sL if noise is n_shouldL else sR), 0, 1)
        stats["peaks"]["shoulder"] = max(stats["peaks"].get("shoulder", 0), s)

    # 3) 头部：独立噪声 + 躯干弱耦合
    s_head = chan_scale(cfg["enable_head"], cfg["head_str"])
    couple = float(cfg["body_head_couple"])
    head_noise = n_head * s_head + n_body * s_head * couple
    for idx in mapping["head"]:
        out[:, idx] = np.clip(out[:, idx] + head_noise, 0, 1)
        stats["peaks"]["head"] = max(stats["peaks"].get("head", 0), s_head * (1 + couple))

    # 4) 面部肌群
    s = chan_scale(cfg["enable_face"], cfg["face_str"])
    for idx in mapping["face"]:
        out[:, idx] = np.clip(out[:, idx] + n_face * s, 0, 1)
        stats["peaks"]["face"] = max(stats["peaks"].get("face", 0), s)

    # 5) 嘴部微扰动（核心卖点：同字不同嘴型）+ 口型保护
    s = chan_scale(cfg["enable_mouth"], cfg["mouth_str"])
    guard = float(cfg["mouth_guard"])
    for idx in mapping["mouth"]:
        delta = n_mouth * s
        # 口型保护：单帧偏移超过 guard 时压缩回 guard，避免脱轨
        delta = np.clip(delta, -guard, guard)
        out[:, idx] = np.clip(out[:, idx] + delta, 0, 1)
        stats["peaks"]["mouth"] = max(stats["peaks"].get("mouth", 0), min(s, guard))

    # 6) 情绪：上限锁死 + 随机波动（拒绝 100% 饱满）
    if cfg["enable_emotion"] and mapping["emotion"]:
        emax = float(cfg["emotion_max"])
        ewave = float(cfg["emotion_wave"])
        wave = 1.0 + ewave * n_emot
        for idx in mapping["emotion"]:
            out[:, idx] = np.clip(out[:, idx] * wave, 0, emax)
        stats["peaks"]["emotion"] = emax

    # 统计：每类别扰动前后 RMS 差值（验证确实发生了微动）
    for cat in CATEGORY_ORDER:
        idxs = mapping[cat]
        if idxs:
            d = out[:, idxs] - seq[:, idxs]
            stats["per_channel_rms"][cat] = float(np.sqrt(np.mean(d ** 2)))
    return out, stats


# ---------------------------------------------------------------------------
# CSV 读写
# ---------------------------------------------------------------------------
def read_csv(path):
    with open(path, "r", encoding="utf-8-sig", newline="") as f:
        reader = csv.reader(f)
        rows = list(reader)
    if not rows:
        raise ValueError("空 CSV")
    header = rows[0]
    data = []
    for r in rows[1:]:
        if len(r) < len(header):
            r = r + [""] * (len(header) - len(r))
        row = []
        for v in r[:len(header)]:
            try:
                row.append(float(v))
            except ValueError:
                row.append(0.0)
        data.append(row)
    return header, np.asarray(data, dtype=float)


def write_csv(path, header, data):
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(header)
        for r in data:
            w.writerow([f"{v:.6f}" for v in r])


def make_demo(frames=600, fps=30, seed=7):
    """生成一段模拟口播：带语音能量包络 + 原始确定性口型/面部/头部动作。"""
    rng = np.random.default_rng(seed)
    t = np.arange(frames) / fps
    # 语音能量包络：近似说话节奏
    speech = np.clip(np.sin(2 * np.pi * 1.7 * t) * 0.6 +
                     np.sin(2 * np.pi * 0.53 * t) * 0.4, 0, 1)
    speech = np.clip(speech + rng.normal(0, 0.05, frames), 0, 1)
    cols = ["energy",
            "bodySpineZ", "bodySpineX", "bodyChestY",
            "shoulderL_Y", "shoulderR_Y",
            "headPitch", "headYaw", "headRoll",
            "browUp_L", "browUp_R", "cheek_L", "eyeBlink_L",
            "jawOpen", "mouthClose", "lipPress", "lipStretch", "tongueOut",
            "emotion_joy"]
    n = len(cols)
    seq = np.zeros((frames, n))
    seq[:, 0] = speech
    # 原始动作：确定性、机械（这正是"AI味"的来源）
    seq[:, 1]  = 0.5 + 0.06 * np.sin(2 * np.pi * 0.2 * t)         # bodySpineZ 呆板缓慢
    seq[:, 2]  = 0.5 + 0.05 * np.sin(2 * np.pi * 0.18 * t)        # bodySpineX
    seq[:, 3]  = 0.5 + 0.04 * np.sin(2 * np.pi * 0.15 * t)        # bodyChestY
    seq[:, 4]  = 0.5 + 0.03 * np.sin(2 * np.pi * 0.9 * t)         # shoulderL_Y 固定节拍（焊死肩）
    seq[:, 5]  = 0.5 + 0.03 * np.sin(2 * np.pi * 0.9 * t)         # shoulderR_Y 与左同步（机械对称）
    seq[:, 6]  = 0.5 + 0.5 * np.sin(2 * np.pi * 2.1 * t)          # headPitch 说话节奏（机械点头）
    seq[:, 7]  = 0.5 + 0.3 * np.sin(2 * np.pi * 0.4 * t)          # headYaw 固定摆头
    seq[:, 8]  = 0.5 + 0.2 * np.sin(2 * np.pi * 0.27 * t)         # headRoll
    seq[:, 9]  = 0.4 + 0.4 * np.sin(2 * np.pi * 0.8 * t)          # browUp_L 机械摆动
    seq[:, 10] = 0.4 + 0.4 * np.sin(2 * np.pi * 0.8 * t)          # browUp_R 与左同步
    seq[:, 11] = 0.5 + 0.1 * np.sin(2 * np.pi * 0.6 * t)          # cheek_L
    blink = (np.mod(t, 3.0) < 0.1) * 1.0                          # eyeBlink_L 固定周期眨眼
    seq[:, 12] = np.clip(blink, 0, 1)
    seq[:, 13] = np.clip(speech * 1.2, 0, 1)                      # jawOpen 与语音强相关（刻板）
    seq[:, 14] = np.clip(1 - speech * 1.1, 0, 1)                  # mouthClose
    seq[:, 15] = np.clip(speech * 0.9, 0, 1)                      # lipPress
    seq[:, 16] = 0.3 + 0.3 * np.sin(2 * np.pi * 1.9 * t)          # lipStretch
    seq[:, 17] = np.clip(speech * 0.6, 0, 1)                      # tongueOut
    seq[:, 18] = np.clip(speech * 1.0, 0, 1)                      # emotion 随语音拉满（AI 通病）
    return cols, seq


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def main(argv=None):
    p = argparse.ArgumentParser(description="natural_idle 数字人动作自然微扰 v" + __version__)
    p.add_argument("-i", "--input", help="输入动作 CSV（列名按通道类别命名）")
    p.add_argument("-o", "--output", help="输出扰动后 CSV")
    p.add_argument("-c", "--config", help="参数 JSON 文件（缺省用 DEFAULT_CONFIG）")
    p.add_argument("--plot", help="输出扰动诊断 JSON（供可视化）")
    p.add_argument("--seed", type=int, default=None, help="随机种子（覆盖 config）")
    p.add_argument("--stats", action="store_true", help="仅打印统计，不写文件")
    p.add_argument("--demo", action="store_true", help="生成演示数据并跑通全流程")
    p.add_argument("--frames", type=int, default=600, help="演示帧数（默认600=20秒@30fps）")
    p.add_argument("--outdir", default=".", help="演示输出目录")
    args = p.parse_args(argv)

    cfg = dict(DEFAULT_CONFIG)
    if args.config:
        with open(args.config, "r", encoding="utf-8") as f:
            cfg.update(json.load(f))

    if args.demo:
        cols, seq = make_demo(frames=args.frames)
        outdir = args.outdir
        os.makedirs(outdir, exist_ok=True)
        in_path = os.path.join(outdir, "demo_input.csv")
        out_path = os.path.join(outdir, "demo_output.csv")
        write_csv(in_path, cols, seq)
        out, stats = apply_natural_disturb(seq, cols, cfg, seed=args.seed)
        write_csv(out_path, cols, out)
        print(f"[demo] 输入: {in_path}")
        print(f"[demo] 输出: {out_path}")
        if args.plot:
            plot_path = args.plot if not os.path.isdir(args.plot) else os.path.join(args.plot, "plot.json")
            with open(plot_path, "w", encoding="utf-8") as f:
                json.dump({"columns": cols,
                           "input": seq.tolist(),
                           "output": out.tolist(),
                           "config": cfg,
                           "stats": stats}, f, ensure_ascii=False)
            print(f"[demo] plot: {plot_path}")
        print(f"[stats] {json.dumps(stats, ensure_ascii=False)}")
        return 0

    if not args.input:
        p.error("需要 -i/--input 或 --demo")
    if not args.output and not args.stats:
        p.error("需要 -o/--output 或 --stats")

    header, seq = read_csv(args.input)
    out, stats = apply_natural_disturb(seq, header, cfg, seed=args.seed)
    print(f"[stats] {json.dumps(stats, ensure_ascii=False)}")
    if args.output:
        write_csv(args.output, header, out)
        print(f"[ok] 已写入 {args.output}（{stats['frames']} 帧 x {stats['channels']} 通道）")
    if args.plot:
        with open(args.plot, "w", encoding="utf-8") as f:
            json.dump({"columns": header, "input": seq.tolist(),
                       "output": out.tolist(), "config": cfg, "stats": stats},
                      f, ensure_ascii=False)
        print(f"[ok] plot: {args.plot}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
