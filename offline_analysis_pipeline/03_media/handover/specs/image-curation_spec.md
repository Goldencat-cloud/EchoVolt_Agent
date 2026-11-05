# Spec Delta

## Purpose

基于本地 Chinese-CLIP 特征缓存的图片语料治理能力：对已下载的帖子图片做帖内视觉去冗余、图-帖相关性、图片侧广告嫌疑三类判定，产出可追溯的标记建议表。全部判定只读原图，不删除、不修改任何数据文件，供下游清洗决策与多模态索引复用。

## ADDED Requirements

### Requirement: 图片特征缓存构建与持久化
系统 SHALL 依据 `image_manifest.csv` 中 `status` 为可用的图片记录，将本地图片批量编码为 CLIP 图像特征并以 `image_id` 为键持久化缓存；缓存 SHALL 支持增量复用（已编码的 `image_id` 重跑时不重复编码）。图片文件缺失或解码失败时 SHALL 记录错误清单并继续，不得中断整体流程。

#### Scenario: 全量编码
- **WHEN** 首次运行且 manifest 中有 22079 张可用图片
- **THEN** 缓存覆盖全部可用图片，每张图为 512 维特征向量，且 `image_id` 可回溯到 `local_path`

#### Scenario: 增量复用
- **WHEN** 缓存已存在时重新运行编码步骤
- **THEN** 仅编码缓存中不存在的 `image_id`，已编码图片不被重新计算

#### Scenario: 坏图容错
- **WHEN** 某图片文件缺失或无法解码
- **THEN** 该 `image_id` 被写入错误清单并跳过，其余图片编码正常完成

### Requirement: 帖内视觉去冗余标记
系统 SHALL 对每个帖子内的图片两两计算特征余弦相似度，对相似度达到冗余阈值的图片对做传递闭值聚类（连通分量），并将组内除建议保留图（`seq` 最小者）外的图片标记为 `visual_dup`；单图帖 SHALL 不产生去冗余标记。

#### Scenario: 连拍冗余
- **WHEN** 某帖内图 A 与图 B 余弦相似度达到冗余阈值且 A 的 `seq` 小于 B
- **THEN** A、B 归入同一冗余组，A 标记为建议保留，B 标记为 `visual_dup`

#### Scenario: 相似传递链
- **WHEN** 帖内图 A~B 相似、B~C 相似但 A~C 低于阈值
- **THEN** A、B、C 归入同一冗余组（传递闭包），仅保留 `seq` 最小者

#### Scenario: 单图帖豁免
- **WHEN** 某帖仅含 1 张图片
- **THEN** 该帖不产生任何去冗余标记

### Requirement: 图-帖低相似标记
系统 SHALL 将帖子文本（标题 + `clean_text`）切分为不超过 CLIP 文本塔长度限制的句子并逐句编码，以图特征与各句特征余弦相似度的最大值作为该图的图-帖相关分数；分数低于阈值的图片 SHALL 标记为 `low_text_sim`。

#### Scenario: 正文句命中
- **WHEN** 某图与帖内任一句子的相似度达到阈值
- **THEN** 该图相关分数取该最大值，不产生 `low_text_sim` 标记

#### Scenario: 全句低相似
- **WHEN** 某图与帖子全部句子的相似度均低于阈值
- **THEN** 该图标记为 `low_text_sim`，并记录其最大分数

#### Scenario: 纯图帖退化为比标题
- **WHEN** 某帖 `clean_text` 为空但 `title` 非空
- **THEN** 以标题切句后的最大相似度作为相关分数

#### Scenario: 完全无文本跳过
- **WHEN** 某帖 `clean_text` 与 `title` 均为空
- **THEN** 该帖所有图片的相关分数记为空且 `sim_status="no_text"`，不产生 `low_text_sim` 标记

### Requirement: 图片内容类型分类与分类感知判定
系统 SHALL 以 CLIP zero-shot 方式对每张图片输出内容类型标记：`text_graphic`（表格/数据/大量文字类）或 `photo`（照片类），并记录分类概率。去冗余与图-帖低相似判定 SHALL 感知内容类型：`text_graphic` 图片 SHALL NOT 因低于照片类阈值被标记（表格文字不可读导致的天然低分须被保护），仅当其配对相似度达到近重复阈值时才标记冗余。

#### Scenario: 表格图受保护
- **WHEN** 某图被分类为 `text_graphic` 且其图-帖相似分数低于照片类阈值
- **THEN** 该图 `sim_status="text_graphic"`，不产生 `low_text_sim` 标记

#### Scenario: 表格图近重复才归组
- **WHEN** 两个 `text_graphic` 图片相似度达到近重复阈值（高于照片类冗余阈值）
- **THEN** 它们归入同一冗余组；未达到时 SHALL NOT 归组

#### Scenario: 照片类判定不受影响
- **WHEN** 某图被分类为 `photo`
- **THEN** 该图按照片类冗余阈值与低相似阈值正常参与判定

### Requirement: 图片侧广告嫌疑标记
系统 SHALL 以 CLIP zero-shot 方式，将每张图片特征与广告类及正常类中文提示词集编码后计算归一化概率，广告类概率超过阈值的图片 SHALL 标记为 `ad_suspect` 并记录概率值；提示词集与阈值 SHALL 为可配置参数。

#### Scenario: 广告海报识别
- **WHEN** 某图为促销海报类图片且广告类概率超过阈值
- **THEN** 该图标记为 `ad_suspect` 并记录广告概率

#### Scenario: 正常分享不受影响
- **WHEN** 某图为正常车辆分享照片且广告类概率低于阈值
- **THEN** 该图不产生 `ad_suspect` 标记

### Requirement: 标记建议表输出契约
系统 SHALL 在 `outputs/` 下输出：特征缓存文件、图-帖相关分数表、帖内冗余标记表、广告嫌疑标记表；所有表 SHALL 以 `image_id`/`post_id` 为主键且可回溯到原图路径。系统 SHALL NOT 修改或删除 `data/images/` 下任何文件及 `image_manifest.csv` 的任何行。

#### Scenario: 产物齐全可追溯
- **WHEN** 管线运行完成
- **THEN** 四类产物均存在于 `outputs/`，任意标记可通过 `image_id` 关联到 `image_manifest.csv` 的 `local_path`

#### Scenario: 原数据只读
- **WHEN** 对比管线运行前后的 `data/images/` 与 `image_manifest.csv`
- **THEN** 二者内容与文件均无任何变化

### Requirement: 阈值调优无需重编码
三类判定的阈值 SHALL 均为运行参数；修改阈值后重跑 SHALL 仅基于已持久化的特征缓存与分数重新计算标记，SHALL NOT 触发图片重新编码。

#### Scenario: 仅调阈值重跑
- **WHEN** 修改任一阈值后重新运行判定步骤
- **THEN** 标记结果更新且图片编码步骤被完全跳过
