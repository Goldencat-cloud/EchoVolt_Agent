import React, { useState } from 'react';
import { EvidenceChart, DataComponent, DataTable, ReportSection, RichNarrative, useDataApp } from '../../data-app-public.jsx';
import './su7.css';

export const copy = {
intro:'小米 SU7 · 汽车之家论坛需求分析 · 离线初版',
summary:`## 核心发现

- **外观是关注入口，舒适性是更集中的改进线索。** 筛选出的 3.36k 条体验／风险表达中，外观与内饰有 635 帖、717 条表达，其中 575 条正面；空间与舒适性有 239 帖、302 条表达，其中 131 条负面，占该方面表达的 43.4%。这描述的是论坛表达，不是用户满意度。
- **现有方面与情感已经够用，原文决定问题能说多具体。** 后排支撑、HUD 可读性、遥控泊车中断、充电信息解释、交付承诺，都能形成可回查的改进假设，无需先跑主题模型。
- **“已购亲历”不能只靠帖子级标签。** 标签筛出的 148 帖／297 条候选中，定向复核发现其他品牌车主试驾 SU7、明确租车一天等情况。本版不输出“SU7 真实车主满意度”或故障率。`,
volume:`## 关注量不等于改进优先级

外观与内饰有 575 条正面、63 条负面表达；空间与舒适性则为 118 条正面、131 条负面。**舒适性不是最热的话题，却值得先拆开看具体障碍。**

同帖可以涉及多个方面，方面帖数不可直接相加。负面占比的分母是该方面全部表达，包含中性与正负混合；不是负面人数比例。`,
polarity:`### 舒适性、交付与故障类内容，要分开解读

服务与交付为 132 条表达，其中负面 62 条；可靠性与故障为 98 条，其中负面 54 条。故障类别本身更容易收录负面内容，不能据此认定车辆故障最多。空间与舒适性的 131 条负面表达涉及 113 帖，值得进一步分成后排、坐姿、噪声、温度等具体问题。

下图比较各方面的表达构成，不代表市场随机样本。内容来自不同历史时点、年款与软件版本，不能直接用于判断现售产品。`,
pre:`## 未购者关注价格与价值，不应与用车抱怨混算

明确未拥有且处于购车前的候选共有 **255 帖、522 条表达**。外观与内饰涉及 100 帖，价格与成本 77 帖；配置与功能、智能座舱与车机分别涉及 38 帖，空间与舒适性涉及 35 帖。

有用信息不止是“嫌贵”：有人明确希望把冰箱权益折现，有人担心当地没有便捷售后路径，分别指向**权益选择与价值解释**、**购前服务信息透明度**。这些是作者表达，不是已验证的技术事实，也不能预测购买转化。`,
cases:`## 从负面标签走到具体改进问题

以下 11 个案例来自有目的的证据选择，Codex 已回读所涉 10 个帖子的冻结文本；不是随机样本，也不是人类语义验收。每个案例分开呈现作者表达、改进假设与证据边界。

“后排不舒服”可以拆成身高适配和腿部支撑；“功能不好用”可以拆成 HUD 看得清／看得早、泊车中断后知道怎么办。推导出的需求仍待验证，不写成作者已明确提出的要求。`,
actions:`## 先细查舒适性，再评估交互与服务闭环

这是调查顺序，不是已经计算出的研发优先级或 ROI。

1. **后排与长途舒适：** 将身高、坐姿、腿部支撑、道路和乘坐时长分开验证，区分试驾与长期用车。先判断问题在哪些条件下重复出现，不直接要求修改整车尺寸。
2. **HUD 与辅助功能：** 复现可读性、连续路口提示、遥控泊车断连后的状态与恢复提示；保留同帖对车身稳定、座椅及成功泊车的正面评价，避免只挑负面。
3. **补能与服务信息：** 对齐桩端与车端显示口径，解释场景化成本；明确销售承诺、交付条件和本地服务路径。旧帖的网点、权益及软件描述须另外核对当前状态。

**这版不需要新增主题模型。** 只有现有方面过粗、同义表达重复或长尾遗漏妨碍分析时，再检验模型是否带来可核验的增益。`,
cohort:`## 为什么不直接把标签人群叫“SU7 车主”

候选条件为：SU7 唯一可确认主对象、非比较 Claim、全部引文可定位、类型为体验／风险、明确亲历、帖子级“当前拥有”，且旅程为使用／售后／交付。这样得到的仍只是候选，因为“当前拥有”可能指作者自己的其他车。

- “年轻人的第一台小米 SU7”原文写“我的 A3”和“简单试驾”，不支持长期持有 SU7。
- “在北京租一天 SU7”可以研究冬季体验，但不能当长期持有者。
- “雷总，对不住了”写“可以买，但不急”，图片说明为展厅；不能仅因有操控评价就确认已购。

本版保留原标签用于定位误差，不静默改写源数据。正面内容也可能含推广或车评叙事；190 条正面候选／297 条候选不是满意率。`,
scope:`## 只保留重点产品，长尾保留原文

临时报告白名单为 SU7，加上与 SU7 比较相关共提及去重帖数最多的 8 个非小米车系，且至少 10 帖：Model 3、极氪 001、极氪 007、比亚迪汉、Taycan、尚界 Z7、Model S、阿维塔 12。

它们是**语料比较相关对象**，不是已经认定的市场直接竞品，也不保证每条比较 Claim 都以两者组成直接比较对。范围内提及 10,392 条，范围外 3,686 条，未解决 734 条，排除 190 条。长尾保留原词及旧映射，不新建报告分析节点；品牌级内容不分摊给 SU7，年款和配置不补齐。

本次是独立分析视图，未覆盖 V2 taxonomy。下表只展示共提及帖数，不比较车型优劣。`,
methods:`## 数据与方法

数据来自 V2.3 修复抽取、AUTO-018 V2 delivery-r3 映射、冻结帖子原文与元数据。共有 9,529 帖、26,936 条 Claim、15,002 次产品提及，覆盖 2022-10-28 至 2026-10-03；这是一份历史快照，不是实时监测。

实际 Claim 有 **aspect（方面）、content、sentiment** 等字段，没有独立的已规范化细粒度 attribute 字段。量化部分直接使用已有方面，案例从原文解释具体属性，没有冒充已完成全量细粒度归一。

引文检查要求每条 Claim 的全部证据在指定 block 和来源类型中可定位（忽略空白和大小写）。22,971 条通过、3,965 条待复核；未过可能包含省略或改写，不等于全是抽取错误。此检查不是语义准确率。图片说明与文字分开，未重新验证图片本身。

统计限定 SU7 为唯一可确认主要讨论对象、comparison 为空且引文通过，再取体验／风险类型，得到 1,810 帖／3,356 条表达。该集合含非亲历与身份未知内容，不称作真实用车样本。无目标引用、仅品牌级或对象不明的内容未强行赋给 SU7。

按 post_id、(post_id, product.id)、(post_id, claim.id) 连接和去重，不按标题连接，Claim 不当人数；比较 Claim 不用整体情感给每个车型打分。筛选集合有嵌套，帖数／表达数不能相加。

没有重爬、全量重抽、主题模型、embedding、新 Qwen 调用、因果分析或市场推断。源文件只读，脚本和源哈希随报告保留。本版不能推出车型故障率、总体满意度、购买转化率或现行技术规格。`
};

function Text({id, value, queryId, rows, sources}) {
return queryId ? <ReportSection id={id} title={value.split('\n')[0].replace(/^#+ /,'')} queryId={queryId} sourceRows={rows}
  queryIds={sources?Object.keys(sources):undefined} sourceRowsByQuery={sources} showHeading={false}>
  <RichNarrative id={id+':body'} value={value}/></ReportSection> : <RichNarrative id={id} value={value}/>;
}

export function ReportContent() {
const {reviewedRows,visible,appTitle,canEdit,mode,setAppTitle}=useDataApp();
const rows=id=>reviewedRows(id);
const [aspect,setAspect]=useState('全部');
const evidence=rows('evidence'), selected=evidence.filter(r=>aspect==='全部'||r.aspect===aspect);
const polar=rows('aspects').map(r=>({...r,'正面':r.positive,'负面':r.negative,'中性':r.neutral,'正负混合等':r.other}));
const cols=[{key:'aspect',label:'方面'},{key:'posts',label:'去重帖数',type:'number'},{key:'claims',label:'表达数',type:'number'},
  {key:'positive',label:'正面',type:'number'},{key:'negative',label:'负面',type:'number'},{key:'negativeShare',label:'负面占比',renderCell:value=>(value*100).toFixed(1)+'%'}];
return <article className="report-content su7-report" aria-label="SU7论坛需求分析报告">
<header className="report-hero"><RichNarrative id="su7:eyebrow" value={copy.intro}/>
<h1 data-data-app-title contentEditable={canEdit&&mode==='edit'} suppressContentEditableWarning
onBlur={e=>{if(canEdit&&mode==='edit')setAppTitle(e.currentTarget.textContent.trim()||appTitle)}}>{appTitle}</h1></header>
<Text id="su7-summary" value={copy.summary} queryId="aspects" rows={rows('aspects')}
  sources={{aspects:rows('aspects'),scope:rows('scope'),evidence:rows('evidence')}}/>
<section><Text id="su7-volume-story" value={copy.volume} queryId="aspects" rows={rows('aspects')}/>
{visible('su7-volume')&&<EvidenceChart id="su7-volume" queryId="aspects" title="各方面涉及的去重帖子数" rows={rows('aspects')} sourceRows={rows('aspects')} height={560}
spec={{type:'horizontalBar',x:'aspect',y:'posts',stackable:false,valueDecimals:0,colors:['#255f85']}}/>}
<Text id="su7-polarity-story" value={copy.polarity} queryId="aspects" rows={rows('aspects')}/>
{visible('su7-polarity')&&<EvidenceChart id="su7-polarity" queryId="aspects" title="各方面的情感表达数（不是人数）" rows={polar} sourceRows={rows('aspects')} height={560}
spec={{type:'horizontalStackedBar',x:'aspect',y:'正面',fields:['正面','负面','中性','正负混合等'],valueDecimals:0,colors:['#255f85','#c27c35','#a7adb1','#967ea1']}}/>}
<DataComponent id="su7-exact-counts" title="精确计数与分母" kind="table" queryId="aspects" sourceRows={rows('aspects')}>
<DataTable rows={rows('aspects')} columns={cols} caption="各方面精确计数" searchable={false}/></DataComponent></section>
<section><Text id="su7-pre-story" value={copy.pre} queryId="pre_aspects" rows={rows('pre_aspects')}/>
<EvidenceChart id="su7-pre-volume" title="未购者购前表达涉及的方面" queryId="pre_aspects" rows={rows('pre_aspects')} sourceRows={rows('pre_aspects')} height={560}
spec={{type:'horizontalBar',x:'aspect',y:'posts',stackable:false,valueDecimals:0,colors:['#255f85']}}/></section>
<section><Text id="su7-cases-story" value={copy.cases} queryId="evidence" rows={evidence}/>
<label className="case-filter">仅筛选下方案例的方面： <select value={aspect} onChange={e=>setAspect(e.target.value)}>
{['全部',...new Set(evidence.map(r=>r.aspect))].map(a=><option key={a}>{a}</option>)}</select></label>
{selected.map(r=><ReportSection key={r.key} id={'case-'+r.key.replace(':','-')} title={r.case} queryId="evidence" sourceRows={[r]} showHeading={false}>
<RichNarrative id={'case:'+r.key+':body'} value={`### ${r.case}\n\n${r.observation}\n\n**改进假设：** ${r.need}\n\n**表达性质：** ${r.source_status}`}/>
<details className="case-details"><summary>展开原文与判断边界</summary><div data-reviewed-rows><blockquote>{r.quote}</blockquote>
<p>{r.date} · {r.blocks} · {r.sentiment}</p><p><a href={r.url} target="_blank" rel="noreferrer">原帖：{r.title}</a></p></div>
<RichNarrative id={'case:'+r.key+':boundary'} value={`**证据边界：** ${r.boundary}`}/></details></ReportSection>)}</section>
<Text id="su7-actions" value={copy.actions} queryId="evidence" rows={evidence}/>
<section><Text id="su7-cohort-story" value={copy.cohort} queryId="owner_aspects" rows={rows('owner_aspects')}/>
<DataComponent id="su7-scope" title="从全部数据到分析候选的筛选结果" queryId="scope" kind="table" sourceRows={rows('scope')}>
<DataTable rows={rows('scope')} columns={[{key:'cohort',label:'筛选集合'},{key:'posts',label:'帖数',type:'number'},{key:'claims',label:'表达数',type:'number'}]} searchable={false}/></DataComponent></section>
<section><Text id="su7-product-scope" value={copy.scope} queryId="comparators" rows={rows('comparators')}/>
<DataComponent id="su7-comparators" title="重点比较相关对象（不是优劣排名）" queryId="comparators" kind="table" sourceRows={rows('comparators')}>
<DataTable rows={rows('comparators')} columns={[{key:'brand',label:'品牌'},{key:'series',label:'车系'},{key:'posts',label:'共提及去重帖数',type:'number'}]} searchable={false}/></DataComponent></section>
<Text id="su7-methods" value={copy.methods} queryId="quality" rows={rows('quality')}/>
</article>;
}
