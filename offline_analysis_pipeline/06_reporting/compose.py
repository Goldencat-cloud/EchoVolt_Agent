"""Assemble a report snapshot from computed counts and explicitly reviewed examples."""
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
A = HERE/'analysis'


def read(name):
    return json.loads((A/name).read_text(encoding='utf-8'))


def main():
    summary, profiles, scope = read('summary.json'), read('profiles.json'), read('scope.json')
    core = {r['key']:r for r in read('core-claims.json')}
    potential = {r['key']:r for r in read('potential-claims.json')}
    selected = core | potential
    cases = [
        ('后排支撑与长途舒适', '0e9d99b0abd6f19a:C5', '试驾体验，不是SU7持有证明',
         '作者明确提到开自己的A3并简单试驾SU7；保留后排支撑的试驾观察，不计作长期车主反馈。',
         '让不同身高的后排乘客在长时间乘坐中获得足够腿部支撑。', '分析推导；长途后果在这条原文中是预期，不是已发生的长期体验。'),
        ('后排身高适配', '4d2d1ce29103cdc6:C4', '自述主力用车；叙事真实性未核验',
         '表达了高个乘客的后排空间约束；全文同时有车评式宣传表达，不据此认证真实车主。',
         '看车与试驾环节提供可感知的身高—坐姿适配信息。', '分析推导；不能由单帖推成所有高个乘客结论。'),
        ('HUD可读性与信息提前量', '79aba2b132c3f554:C1', '主观体验；持有状态不单独确证',
         '原文同时提到模糊、视觉负担、路面观察及连续路口提示不足；并肯定空悬与座椅。',
         '让驾驶员在复杂道路和连续分叉路口看得清、看得早，减少遮挡感。', '分析推导；分辨率低是作者解释，不是测量结论。'),
        ('导航中语音响应', '4d2d1ce29103cdc6:C5', '自述使用体验',
         '导航时语音唤醒“慢半拍”是具体任务障碍；同帖也肯定语音控空调和播放音乐。',
         '保留自然语音交互优势，同时提高导航任务下响应的一致性。', '分析推导；未测量延迟，也未确认软件版本。'),
        ('遥控泊车中断', 'e024a801eee64c1f:C2', '自述一次尝试',
         '作者称蓝牙中断后车辆停在半道；这是异常中止及恢复体验，不证明车辆失控。',
         '连接中断时清楚说明车辆状态、停止原因及下一步恢复方式。', '分析推导；风险判断来自作者，不认定技术缺陷或事故原因。'),
        ('自动泊车与售后责任', '9f09473f23bafc55:C1', '单方事故归因陈述',
         '同帖称自动泊车后尾部撞损并被拒绝维修责任；图片说明却描述疑似前部局部，需单列图文不一致。',
         '为泊车争议提供可回查的过程记录、功能边界和清晰责任处理流程。', '分析推导；碰撞过程、责任、图中位置均未核验。'),
        ('充电功率信息解释', 'a3f7ae73d505588a:C1', '带数值的用户疑问',
         '作者比较桩侧7kW与车端6.6–6.7kW显示，询问差异；不把疑问直接认作少充电或质量故障。',
         '在桩端、车辆端及计费数据间提供清晰的口径与损耗解释。', '分析推导；没有测量或账单验证。'),
        ('冬季租车的补能预期', 'e3322fb90b3349d5:C7', '明确租车一天，不是长期持有',
         '北京冬季租车、暖风、165公里和公充费用构成具体场景；费用由作者自述，不能从一次经历外推车型电耗。',
         '按温度、暖风、路线和补能方式展示可理解的用车成本预期。', '分析推导；公充账单不等于同一行程的真实耗电。'),
        ('交付承诺一致性', 'de660a335338f489:C4', '自述提车争议',
         '作者将礼包承诺未兑现解释为被区别对待，并明确要求解释和补救；这是服务公平感，不只是赠品价值。',
         '把销售承诺、提前提车条件与交付清单提前说清，并保持执行一致。', '作者明确要求解释与补救；具体流程方案为分析推导。'),
        ('售后可达性影响购车顾虑', '013c71a6c3d9fc56:C2', '未购者的历史顾虑',
         '作者称最近交付店相距一千多公里，担心当地维修时效；这是帖时点的感知，不是当前网点事实。',
         '在购车前明确当地服务覆盖、故障送修路径及预计处理时效。', '分析推导；须按用户城市和当下服务覆盖再验证。'),
        ('权益形式与实用价值', '170a414efc11ae8f:C1', '未购者的权益偏好',
         '作者明确建议把冰箱权益折现，认为便携式产品对自己的场景更实用。',
         '提供与个人使用场景匹配、可理解的权益选择。', '作者明确提出折现；不是所有用户都偏好现金优惠。'),
    ]
    # The selected source ID for the benefit example is C1/C2-dependent: locate by content, never manufacture it.
    desired = [r for r in potential.values() if r['post_id']=='170a414efc11ae8f' and '冰箱' in r['content'] and '折' in r['content']]
    if desired:
        c=list(cases[-1]); c[1]=desired[0]['key']; cases[-1]=tuple(c)
    evidence=[]
    for title, key, interpretation, observation, need, boundary in cases:
        r=selected[key]
        evidence.append({'case': title, 'key':key, 'aspect':r['aspect'], 'date':r['date'],
                         'title':r['title'], 'url':r['url'], 'quote':'\n\n'.join(e['quote'] for e in r['evidence']),
                         'blocks': ', '.join(e['block_id'] for e in r['evidence']),
                         'sentiment':r['sentiment'], 'source_status':interpretation,
                         'observation':observation, 'need':need, 'boundary':boundary,
                         'review':'Codex定向原文复核；不是人类语义验收'})
    owner=profiles['当前拥有且亲历使用']
    experiences=profiles['产品体验或风险']
    pre=profiles['明确未拥有的购车前表达']
    totals={name: v for name,v in summary['cohorts'].items()}
    source_files=['AUTO-016 V2.3 repair1/contract-passed.jsonl', 'AUTO-018 V2/delivery-r3/mention-mapping.jsonl',
                  '004_A4_图片策展_主链路终版.csv','AUTO-016 frozen inputs/<post_id>.json']
    def query(rows, label, definition):
        return {'rows':rows, 'source':{'label':label, 'files':source_files,
                'filters':['现有修复数据；原数据只读；SU7明确主要对象；比较Claim不混入单车情感统计',
                           '引文须可在同一命名block及同类型来源中定位（忽略空白和大小写）'],
                'metricDefinitions':[{'label':'口径', 'definition':definition}],
                'evidenceFlow':[{'title':'读取与连接','detail':'按post_id与局部product_id连接既有映射，不按标题连接。'},
                                {'title':'计算与复现','detail':'运行同目录analyze.py；analysis/input-manifest.json保存源文件和冻结原文SHA256。'},
                                {'title':'证据边界','detail':'结构和引文定位不证明语义正确；作者身份、车型归属及技术归因未全量人工验收。'}]},
                'methods':[{'language':'text','code':'复现：python collaboration/result/auto018-product-entity-normalization/report-v1/analyze.py（analysis目录须不存在）；精确规则见随附脚本。'}]}
    queries={
        'scope':query([{'cohort':k,**v} for k,v in totals.items()], '逐层筛选结果','Claims是表达数，posts是该层去重帖子数；层之间嵌套，不可相加。'),
        'aspects':query(experiences, 'SU7体验与风险表达的属性分布','每方面按帖子去重；同帖可涉及多个方面。negativeShare=该方面负面Claim数/该方面全部Claim数，含中性和正负混合；不是车主不满意比例。'),
        'owner_aspects':query(owner, '当前拥有＋亲历使用候选分布','当前拥有是模型的帖子级标签，不等于持有SU7；297条/148帖仅是候选集合，未经语义修正。'),
        'pre_aspects':query(pre,'明确未拥有＋购车前表达','255帖/522条；只描述未购者表达，不代表总体购买意向。'),
        'comparators':query([r for r in scope['candidates'] if (r['brand'],r['series']) in [tuple(x) for x in scope['whitelist']]], 'SU7比较Claim共同提及的车系','既有comparison非空且Claim连接SU7与该车系，按帖子去重；是比较相关共提及，不保证该两车构成直接比较对，也不是市场竞品认定。'),
        'evidence':query(evidence,'定向原文复核的具体问题样例','有目的选择的11个案例，不是随机样本；不能用它估计总体比例或准确率。'),
        'quality':query([{'check':k,'claims':v} for k,v in summary['evidence_checks'].items()], '原文引文定位检查','逐条Claim要求所有引文在指定原文block和来源类型中可定位；未过者暂不进入本报告统计，不等于全部抽取错误。'),
    }
    snapshot={'surface':'report','title':'外观吸引关注，舒适性暴露改进线索',
              'generatedAt':'2026-10-18T12:12:00Z','status':'reviewed','buildStatus':'creating',
              'report':{'asOf':'2026-10-03'},'filters':[], 'queries':queries}
    (HERE/'reviewed.json').write_text(json.dumps(snapshot,ensure_ascii=False,indent=2),encoding='utf-8')
    (A/'reviewed-cases.json').write_text(json.dumps(evidence,ensure_ascii=False,indent=2),encoding='utf-8')
    print('snapshot prepared:',len(evidence),'cases;',len(queries),'datasets')


if __name__=='__main__':
    main()
