---
name: lanhu
description: >-
  蓝湖设计稿高保真还原、画板标注提取、组件聚拢、Design Tokens 与切图资产工程化专家技能。
  当用户分享蓝湖链接 (lanhuapp.com)、要求根据设计稿还原页面、查看画板标注与图层属性、
  提取 Axure 原型需求说明、导出色板与字体规范、或下载切图资源时必须使用。
---

# 蓝湖设计高保真还原与前端工程化专家技能 (Lanhu Skill)

本技能帮助 AI 助手无缝打通蓝湖设计资产与前端/移动端高保真代码实现。
通过深度解析蓝湖 Sketch / Figma DDS 数据，自动纠正尺寸基准、智能聚拢分离图层（如 Button Background Shape + Text）、提取带 Alpha 的精准色彩与圆角规范，并生成流式响应式布局骨架（支持 Jetpack Compose、Flutter、React/Tailwind）。

---

## 🚀 核心工作流与极速统一入口

### 1. 单图与项目统一入口（最优先推荐）
当用户分享任意蓝湖链接时，**直接调用 `lanhu_inspect_url`**：
```python
result = lanhu_inspect_url(url="https://lanhuapp.com/web/#/item/project/detailDetach?pid=xxx&image_id=yyy")
```
返回结果包含完整的高保真设计资产包：
- **`visual_summary`（视觉结构与组件蓝图）**：
  - `canvas`: 自动校正后的画板基准尺寸（如 `375x812`，非缩放尺寸）与背景底色（`background_color`）；
  - `atmosphere_background`: 识别顶部氛围大图/背景切图，附带尺寸与居中填充代码；
  - `navigation`: 顶部导航栏、返回按钮位置与尺寸；
  - `buttons`: **已聚拢的复合按钮清单**（文本、背景色十六进制及Alpha、圆角、高度、字重、是否通栏、推荐代码）；
  - `texts`: 按自然视觉流排序的独立文本（包含文字、字号、字重、颜色 Hex+Alpha、设计规范色板名称）；
  - `agreement_rows`: 协议勾选行、复选框位置与高亮链接文本；
  - `declarative_guidelines`: 针对当前页面的流式布局自适应指引。
- **`assets`（切图清单）**：所有可导出的矢量 SVG 与位图 WebP，包含下载直链与推荐资源命名（如 `ic_xxx`）。

---

## 📐 蓝湖设计稿高保真还原三步法（不可违背准则）

不管是移动端（Jetpack Compose / Flutter）还是 Web 端（React / Vue / Tailwind），**严格遵循以下三层架构还原**：

### 1. 第一层：画板基准与背景层 (Canvas & Backdrop)
- **基准分辨率对齐**：获取 `visual_summary.canvas.width` 与 `height`（常见移动端标准为 `375.dp` 或 `390.dp` 宽）。
- **根容器覆盖**：使用根容器（如 Compose `Box(Modifier.fillMaxSize().background(page_bg))`）填充全屏底色。
- **背景氛围图**：若有顶部大图（如 `bg_login`），使用居顶填充（`Modifier.fillMaxWidth().height(...dp).align(Alignment.TopCenter)`），**切勿**将背景图塞进 Column 主内容流而导致滚动下移。

### 2. 第二层：流式主轴与安全区弹性骨架 (Fluid Axis & Safe Area)
- **严格禁止写死绝对坐标**：
  ❌ **严禁**：`Modifier.offset(x = 20.dp, y = 465.dp)` 或 `Modifier.padding(top = 465.dp)`（在不同机型屏幕下会彻底错位）。
  ✅ **正确**：使用垂直流式布局 `Column(modifier = Modifier.fillMaxSize().statusBarsPadding().navigationBarsPadding())`。
- **弹性自适应推进**：
  - 主要操作区（如 Logo、主表单）置于上中部；
  - 主要操作按钮（如“注册/登录”）置于中间偏下；
  - 协议勾选行紧随主按钮下方（间距通常为 `16.dp ~ 20.dp`）；
  - 底部操作按钮（如“游客模式”）使用 **`Spacer(modifier = Modifier.weight(1f))`** 弹性推到屏幕底边上方，适配从 16:9 到 21:9 的所有屏幕！

### 3. 第三层：组件像素级微调与 Token 精确映射 (Pixel-Perfect Components)
- **复合按钮合并**：
  在 Sketch/Figma 中，按钮通常由容器 Group + 背景矩形 (Shape) + 居中文本 (Text) 分离组成。
  务必参考 `visual_summary.buttons` 中的聚合数据：
  - 高度：通常为 `44.dp`、`48.dp` 或 `52.dp`；
  - 圆角：精准还原（如 `RoundedCornerShape(12.dp)`）；
  - 背景色：注意透明度（例如 `#00C18C` 为纯色，`#1AE6E8F2` 为 10% 透明度）；
  - 文字样式：字号（如 16sp）、字重（`FontWeight.SemiBold` / `FontWeight.Normal`）、白色或主题色。
- **协议勾选行**：
  - 单选框/复选框：16.dp ~ 18.dp，必须支持勾选状态切换（`agreed = !agreed`）；
  - 协议链接：高亮颜色（如天蓝 `Color(0xFF7BD5F5)`），必须绑定真实协议跳转或弹窗逻辑。
- **切图与图标匹配**：
  - 先在项目 `res/drawable` 或 `assets` 中搜索同名或相似图标；
  - 若缺失，调用 `lanhu_download_asset` 下载为标准 SVG 或 WebP。

---

## 🛠️ 常用工具链与调用场景

| 工具名称 | 适用场景 | 核心参数与返回值 |
|:---|:---|:---|
| `lanhu_inspect_url` | **统一总入口**。直接解析任意蓝湖 URL，一步到位返回单图视觉摘要、组件蓝图、画板列表或 Axure 原型 | `url` |
| `lanhu_get_annotations` | 获取指定单图的原始图层树、CSS 属性及 `visual_summary` | `project_id`, `image_id` 或 `url` |
| `lanhu_get_layout_skeleton` | 智能推断响应式 Flexbox 骨架与 Tailwind 语义化类名 | `project_id`, `image_id` 或 `url` |
| `lanhu_get_design_tokens` | 提取全局色板、字号阶梯、字重、圆角规范（支持 css/tailwind/w3c） | `project_id`, `format` |
| `lanhu_batch_export_assets` | 批量下载画板中所有切图资源并自动生成清单 | `project_id`, `image_id`, `save_dir` |
| `lanhu_download_asset` | 单个切图下载（位图 WebP，矢量 SVG） | `download_url`, `asset_name`, `save_dir` |

---

## 💡 跨端高保真映射字典 (Jetpack Compose 范式)

当还原 Android Jetpack Compose 界面时，严格对照下表映射：

| 蓝湖标注属性 | Compose 对应实现 | 示例 |
|:---|:---|:---|
| 背景色带透明度 `#RRGGBBAA` | `Color(0xAARRGGBB)` | `#E6E8F21A` → `Color(0x1AE6E8F2)` |
| 纯色 `#RRGGBB` | `Color(0xFFRRGGBB)` | `#00C18C` → `Color(0xFF00C18C)` |
| 圆角 `border_radius: 12` | `RoundedCornerShape(12.dp)` | `.background(color, RoundedCornerShape(12.dp))` |
| 字重 `weight: 600` / `bold` | `FontWeight.SemiBold` / `FontWeight.Bold` | `fontWeight = FontWeight.SemiBold` |
| 字重 `weight: 400` / `regular` | `FontWeight.Normal` | `fontWeight = FontWeight.Normal` |
| 行高 `line_height` | `lineHeight = ...sp` | `lineHeight = 22.sp` |
| 边框 `border: 1px solid #...` | `BorderStroke(1.dp, Color(...))` | `border(BorderStroke(1.dp, color), shape)` |
| 状态栏/底部栏遮挡 | `statusBarsPadding()`, `navigationBarsPadding()` | 添加于顶层主布局 Column 上 |
