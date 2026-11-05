# Spec Delta

## Purpose

提供批量 VLM 图片描述生成能力：对治理后的本地图片清单离线批量生成中文描述，作为后续文本分析链路的图片语义来源；在 8GB 显存约束下通过分辨率档位保证推理稳定，并支持断点续跑与失败补跑。

## ADDED Requirements

### Requirement: 输入图片清单
图片描述管线 SHALL 以 `image_manifest.csv`（`status=ok` 且无 `dup_of`）与 image-curation 保留标记的交集作为待描述图片集合，集合内每个 `image_id` 恰好对应一张本地存在的图片文件。

#### Scenario: 清单过滤
- **WHEN** manifest 中存在 `status != ok`、`dup_of` 非空、或被 curation 标记为剔除的图片
- **THEN** 这些图片 MUST NOT 出现在待描述集合中

#### Scenario: 本地文件缺失
- **WHEN** 待描述集合中某 `image_id` 的本地文件不存在
- **THEN** 该图片 MUST 记入失败表（原因 `file_missing`），MUST NOT 中断整体任务

### Requirement: 批量中文描述生成
管线 SHALL 对待描述集合中的每张图片调用本地 Qwen2.5-VL 模型生成一条中文描述，描述 MUST 为对画面客观内容的陈述（车辆外观/内饰/部件/场景等），MUST NOT 包含对用户意图或情绪的臆测。

#### Scenario: 单图描述
- **WHEN** 一张有效图片进入推理批次
- **THEN** 产出恰好一条非空中文描述，且与该 `image_id` 关联

#### Scenario: 全量覆盖
- **WHEN** 待描述集合全部处理完成
- **THEN** 集合中每张图片在产物表中 MUST 有且仅有一条描述或一条失败记录

### Requirement: 分辨率档位控制
管线 SHALL 通过模型的动态分辨率参数（visual token 预算下限 `min_pixels` 与上限 `max_pixels`）限制单图显存占用，且 SHALL 提供至少两档预设（省显存/高清），档位 MUST 可通过参数选择。

#### Scenario: 大图被压缩
- **WHEN** 输入图片像素面积超过当前档位的 `max_pixels`
- **THEN** 管线 MUST 将其缩放到预算内再送入模型，且推理过程不因该图片 OOM

#### Scenario: 档位切换生效
- **WHEN** 以不同档位参数分别运行同一小样本集
- **THEN** 两次运行的 visual token 预算参数 MUST 按所选档位生效（可通过产物元数据核对）

### Requirement: 显存压测校准
管线 SHALL 提供小样本压测脚本：对抽样图片按候选档位运行，报告峰值显存与吞吐，作为全量运行前选择档位的依据。

#### Scenario: 压测产出
- **WHEN** 压测脚本以某档位对样本集运行完成
- **THEN** 输出 MUST 包含该档位的峰值显存（GB）与平均单图耗时（秒）

#### Scenario: 压测 OOM
- **WHEN** 某档位压测中发生显存不足
- **THEN** 压测报告 MUST 明确标记该档位不可用，而非静默通过

### Requirement: 断点续跑
产物表 SHALL 按批增量写盘；重跑时管线 SHALL 跳过产物表中已有成功描述的 `image_id`，仅处理缺失与失败项。

#### Scenario: 中断后续跑
- **WHEN** 上次运行在中途被终止后重新启动
- **THEN** 已有描述的图片 MUST NOT 被重复推理，任务从缺失处继续

#### Scenario: 补跑失败项
- **WHEN** 以重试参数重新运行
- **THEN** 失败表中的图片 MUST 被重新尝试，成功后从失败表移入产物表

### Requirement: 产物表契约
管线 SHALL 产出 `image_captions.csv`（列：`image_id, post_id, caption, pixels_used, model, resolution_preset, created_at`）与 `image_captions_errors.csv`（列：`image_id, post_id, error_type, detail, attempts`），两表 MUST 以 `image_id` 唯一键可回挂到 `image_manifest.csv`。

#### Scenario: 可回挂
- **WHEN** 下游以任一 `image_id` 查询产物表
- **THEN** MUST 能通过该键在 manifest 中定位到对应图片文件与所属帖子

#### Scenario: 运行元数据
- **WHEN** 查看产物表任意一行
- **THEN** MUST 能得知该描述使用的模型标识与分辨率档位
