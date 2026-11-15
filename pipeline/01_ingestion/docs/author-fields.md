# 作者资料五字段：已实现链路与验证范围

## 统一语义

| 中文含义 | users当前资料 | posts.author_context_json采集时资料 | 类型/含义 |
|---|---|---|---|
| 平台帖子数 | platform_post_count | platform_post_count | 非负整数；不是本数据集发帖数 |
| 热门帖数 | popular_post_count | popular_post_count | 非负整数；0有效 |
| 平台回复数 | platform_reply_count | platform_reply_count | 非负整数；不与某一帖的reply_count混淆 |
| 自述车辆 | declared_vehicle | declared_vehicle | 文本；多项完整保留，以“ \| ”分隔；不是车主认证 |
| 热门帖入口 | popular_post_urls_json | popular_post_urls_raw | 用户表为入口URL数组，帖子上下文为源入口文本；不是具体热门帖子清单 |

旧CSV字段名只在输入兼容层出现；三个计数与自述车辆经过normalize/author.py的同一转换函数。标准表字段映射由standard.py执行。原始CSV/HTML字节保留于source_snapshots指向的文件，不以当前资料回填历史发帖时资料。

## 在线来源与处理

1. 帖子列表/详情确认作者ID；身份缺失不猜测作者。
2. 请求`https://club.autohome.com.cn/frontnc/user/getdetailusertpl/{uid}-{flag}`，普通帖flag=0，问答flag=1；同一运行按uid+flag复用。
3. 使用name链接核验作者ID；只在count-item/strong中读取计数，在profile-cars-item中读取车辆，不能缺结构就填0。
4. 原始响应先落盘；解析后的资料卡经同一Repository.ingest/project写入users，再关联posts的采集上下文。卡片快照ID和取得时间随上下文保存。
5. 用户主页用于补充粉丝、关注、性别、IP等；失败不能清空已经取得的五字段。卡片单独成功不等于主页完整成功。
6. 离线回放按保存关联读取资料卡和互动统计，不联网；不会用重放当天作为采集锚点。

未展示、结构缺失、身份冲突、请求失败分别处理。源卡片经身份/计数结构验证后没有展示车辆，可记not_displayed；旧脚本未采集造成的空字段不能套用此理由。逐批质检保留来源未展示计数，不把它当有值。

## 实际验证（2026-10-21）

- `tests/run_suite.py --report evidence/unit-tests-author-fields.json`：79条离线测试通过，外部网络禁用。包含五字段解析、真实0、缺计数、错作者、多项车辆、旧CSV/在线类型一致、两帖一卡、HTTP任务到SQL、主页失败保留、冻结回放。
- `tools/smoke_live.py --allow-network --author-card-only ...`：通过本机HTTP任务接口进行1次真实外部请求，HTTP200；三个计数和热门入口均已入SQL。该用户原卡片没有爱车标签或车辆节点，declared_vehicle为空且明确not_displayed。该任务预算只有1次，额外主页因预算限制未执行，任务partial且不可发布；不宣称完整用户采集成功。
- `tools/verify_frozen_http.py --input-data evidence/local-data/live-author-card-20261021/data --output evidence/local-data/author-card-replay-20261021`：复制恢复后禁网回放，重复输出一致、hash/FK检查通过。
- 有车辆的5字段全量链路来自合成端到端测试，不宣称本轮实测用户展示了车辆。单用户验证不证明全站模板覆盖。

本轮真实小样本使用独立证据库，没有添加帖子或把已排除的127帖重新入库。业务库仍是9994篇存量帖子。
