---
name: aigc-mark-toolkit
description: Use when the user provides an image and wants to remove AIGC marks, watermarks, C2PA metadata, hidden logos, or any AI-generated content markers. Triggers include "去除AIGC标记", "移除水印", "去水印", "clean AIGC marks", "remove watermark", "strip C2PA".
---

# AIGC Mark Toolkit

## 行为规则

当用户提供一张图片要求去除 AIGC 标记或水印时：

1. **自动执行**，不给用户展示 CLI 命令或操作步骤
2. 直接运行清理，返回最终结果
3. 不要询问用户选择策略，默认用 `aggressive`
4. 不要生成中间文件，用 `quick-clean` 命令

## 执行步骤

```
用户提供图片路径 → 运行 quick-clean → 返回清理后的图片路径
```

### 命令

```powershell
cd <项目根目录>
powershell -ExecutionPolicy Bypass -File skill/run-local-skill.ps1 quick-clean "<用户图片路径>"
```

输出自动生成为 `{原图路径去除后缀}_remove.jpg`，与用户原图在同一目录。

### 策略

- 默认 `aggressive`（无需用户指定）
- 该策略执行：元数据剥离 → 2bit LSB 清零 → 重采样 → DCT 域噪声注入 → PNG 自动转 JPEG

## 汇报格式

清理完成后直接告知用户：

```
处理完成。
- 输入：{路径}
- 输出：{_remove.jpg 路径}
- 结果：confirmed removed / not detected after processing
```

不要展示 inspect 详细 JSON、不要展示命令执行过程、不要询问"是否满意"。

## 边界

- 如果 quick-clean 执行失败，检查项目根目录是否正确（`C:\Users\lizilong\Desktop\WHUAI\tools\skills\aigc-mark-toolkit`）
- 如果图片没有 detectable 标记，告知用户"未检出已知 AIGC 标记，已执行预防性清理"
- 供应商私有水印方案不在检测范围内，不要在结果中承诺"完全移除"
- 如需保留 PNG 格式或调整策略，在报错时回退到 `--strategy balanced` 重试
