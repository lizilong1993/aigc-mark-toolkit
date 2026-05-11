---
name: aigc-mark-toolkit
description: Use when the user provides an image or images and wants to remove AIGC marks, watermarks, C2PA metadata, hidden logos, or any AI-generated content markers. Supports single image and batch directory processing. Triggers include "去除AIGC标记", "移除水印", "去水印", "批量去水印", "clean AIGC marks", "remove watermark", "strip C2PA", "batch remove".
---

# AIGC Mark Toolkit

## 行为规则

当用户要求去除 AIGC 标记或水印时：

1. **自动执行**，不给用户展示 CLI 命令或操作步骤
2. 直接运行清理，返回最终结果
3. 默认用 `aggressive` 策略，不要询问用户
4. 不要生成中间文件

## 输出路径规则（重要）

输出图片的存放位置自动判断：

| 输入来源 | 输出位置 | 文件名 |
|---------|---------|--------|
| 用户桌面或项目目录下的图片 | 与原图同一目录 | `{原图名}_remove.jpg` |
| 拖拽上传的图片（`.claude/uploads/` 下） | **自动存到桌面** | `{原图名}_remove.jpg` |
| 批量处理目录 | 每张图各自的原图目录 | `{原图名}_remove.jpg` |

拖拽上传的图片不会存到 `.claude/uploads/`，而是放在桌面上，方便用户找到。

## 使用场景

### 场景一：用户提供单张图片路径

直接运行 quick-clean：

```powershell
cd <项目根目录>
powershell -ExecutionPolicy Bypass -File skill/run-local-skill.ps1 quick-clean "<图片路径>"
```

输出自动生成为 `{原图路径去除后缀}_remove.jpg`，与原图同目录。

### 场景二：用户上传单张图片

图片通常在 `C:\Users\lizilong\.claude\uploads\` 下。直接对该路径运行 quick-clean。

### 场景三：用户提供一个目录路径（批量处理）

1. 判断是文件还是目录：`ls "<路径>"` 或检查后缀
2. 如果是目录，运行 batch-clean：

```powershell
cd <项目根目录>
# 只处理该目录下的图片（不含子目录）
powershell -ExecutionPolicy Bypass -File skill/run-local-skill.ps1 batch-clean "<目录路径>"

# 递归处理子目录
powershell -ExecutionPolicy Bypass -File skill/run-local-skill.ps1 batch-clean "<目录路径>" --recursive

# 强制重新处理（即使已有 _remove.jpg）
powershell -ExecutionPolicy Bypass -File skill/run-local-skill.ps1 batch-clean "<目录路径>" --force
```

3. 批处理逻辑：
   - 扫描目录下所有图片（.png/.jpg/.jpeg/.webp/.bmp/.tiff）
   - 跳过已清理的（已有 `{原名}_remove.jpg` 的视为已处理）
   - 只处理未清理过的图片
   - 每张输出为 `{原图名}_remove.jpg`

### 场景四：用户提供多个文件路径

如用户给出多张图片路径（空格分隔或列举），对每张依次运行 quick-clean。

## 汇报格式

### 单张处理

```
处理完成。
- 输入：{路径}
- 输出：{_remove.jpg 路径}
- 结果：confirmed removed / not detected after processing
```

### 批量处理

```
批量处理完成。
- 目录：{路径}
- 总计：{N} 张
- 已处理：{N} 张
- 已跳过（此前已清理）：{N} 张
- 失败：{N} 张
- 输出：每张原图所在目录下的 {原名}_remove.jpg
```

失败详情仅在存在失败时展示。

## 边界

- 如果图片没有 detectable 标记，告知"未检出已知 AIGC 标记，已执行预防性清理"
- 供应商私有水印方案不在检测范围内，不承诺"完全移除"
- batch-clean 失败时检查目录是否存在、是否有图片文件
- 如需保留 PNG 格式或调整策略，在报错时回退到 `--strategy balanced` 重试
