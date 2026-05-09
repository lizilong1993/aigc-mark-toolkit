# aigc-mark-toolkit

本地优先的 AIGC 图像标记检测与清除工具。支持 C2PA 内容凭证、生成器标记、EXIF/XMP 元数据、LSB 隐写、频域水印等多种标记的检测与移除。

**诚实声明**：不承诺"100% 移除"。项目输出标签严格区分：
- `confirmed removed` — 已知标记确认移除
- `not detected after processing` — 处理后未检出
- `residual suspicion remains` — 仍有可疑信号
- `cannot verify vendor-private watermark` — 供应商私有方案无法验证

---

## 快速使用
在claude code/codex中上传待检测/移除标记的图片，并`/aigc-mark-toolkit`调用该skill。


---

## 检测范围

| 类型 | 检测方法 | 覆盖内容 |
|------|---------|---------|
| **文件级嵌入标记** | PNG 文本块解析 + JPEG 段扫描 + 全文件特征字节匹配 | C2PA, JUMBF, OpenAI, Veo, Sora, Midjourney, Stable Diffusion, Adobe Firefly, Google Imagen 等 30+ 生成器标记；XMP 命名空间 |
| **可见水印叠加层** | Alpha 通道角部分析 | 半透明 logo、文字、角标 |
| **像素级隐写信号** | numpy 向量化 LSB 相关性检测（8 种空间模式） | 周期性 LSB 隐写、棋盘格/条纹/对角线模式 |
| **频域水印** | FFT/DCT 块分析（aggressive 模式下注入 DCT 域噪声破坏） | DCT/DWT 域嵌入的水印 |

---

## 移除能力

| 策略 | 操作 | 用途 |
|------|------|------|
| `preserve` | 剥离元数据 + 轻度重编码 | 只需清除文件标记，保留画质 |
| `balanced` | 元数据剥离 + 1bit LSB 清零 + 0.985x 重采样 | 常规清除，平衡效果与画质 |
| `aggressive` | 元数据剥离 + 2bit LSB 清零 + 0.94x 重采样 + 清晰度调整 + **DCT 域噪声注入** | 深度清除，对抗 LSB 隐写和频域水印 |

aggressive 模式下 PNG 自动转 JPEG（有损编码进一步破坏隐写标记）。

---

## 命令参考

```powershell
# 检测
aigc-mark-toolkit inspect input.png --output report.json

# 剥离元数据
aigc-mark-toolkit strip-metadata input.png --output stripped.png

# 标准化图像（核心移除步骤）
aigc-mark-toolkit normalize-image input.png --output out.jpg --strategy aggressive

# 区域覆盖物修复
aigc-mark-toolkit remove-overlay input.png --output repaired.png --box 20,20,120,80

# 前后对比验证
aigc-mark-toolkit recheck original.png processed.jpg --output recheck.json

# 完整流水线（含所有中间产物）
clean-aigc-marks input.png --output-dir ./out --strategy aggressive

# 一键清理（无中间文件）
aigc-mark-toolkit quick-clean input.png
```

---

## 安装

项目依赖 `Pillow` 和 `numpy`，Python 3.10+：

```powershell
# 从项目目录安装
py -3 -m pip install -e .

# 或直接用 thin wrapper（无需安装）
powershell -ExecutionPolicy Bypass -File skill/run-local-skill.ps1 quick-clean 图片.png
```

---

## 项目结构

```
cli/aigc_mark_toolkit/     # Python 包 + CLI 实现
skill/run-local-skill.ps1  # 本地 thin wrapper
references/                 # 方法论与输出边界说明
tests/                      # 自动化测试
SKILL.md                   # 技能入口
```


---

