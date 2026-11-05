# -*- coding: utf-8 -*-
"""离线深度清洗：六大类框架 + 风险分级（R0 静默 / R3 关闭）。

输入: data/processed/汽车之家_小米SU7_清洗语料.csv (9970 x 23)
输出: 汽车之家_小米SU7_深度清洗语料.csv   (全量, 追加标注列)
      汽车之家_小米SU7_深度清洗_clean.csv  (高置信子集)

实现约定:
  - ① 结构校验 (R0): 静默执行, 不输出
  - ② 降冗余 (R1): norm_key 分组, 首条保留
  - ③ 去垃圾 (R2): system_junk / gibberish 标 excluded
  - ④ 统形式 (R1): 剥离 @/#/URL, emoji 抽除, 全半角数字归一; 全角标点不动
  - ⑤ 护隐私 (R2): 手机号/长数字串打码 (仅 clean_text, 保留原始 text_content 可追溯)
  - ⑥ 增标注 (R0/R1): dedup_group_id/non_chinese/is_long/quality_score/high_confidence
  - R3 (语义近重复 / 车牌打码): 默认关闭, 不实现

清洗后文本两列(与原始列对齐, 不破坏多模态结构):
  - clean_text        : text_content 去 @/#/URL、emoji、打码、折叠空白
  - clean_multimodal  : multimodal_content 解析 JSON, 仅清 type=text 块(@/#/emoji/空白),
                        type=img 图片 URL 原样保留 —— 绝不去 URL, 否则图片链接全毁
  - emoji 不单列, 已并入清洗过程直接剔除
"""
import sys, re, json, unicodedata
sys.stdout.reconfigure(encoding='utf-8')
import pandas as pd

SRC = 'data/processed/汽车之家_小米SU7_清洗语料.csv'
OUT = 'data/processed/汽车之家_小米SU7_深度清洗语料.csv'
OUT_CLEAN = 'data/processed/汽车之家_小米SU7_深度清洗_clean.csv'

EMOJI = re.compile(r'[\u2600-\u27BF\u2B00-\u2BFF\U0001F000-\U0001FAFF\U0001F1E6-\U0001F1FF\uFE00-\uFE0F\u2190-\u21FF]', re.UNICODE)
JUNK = re.compile(r'查看详情|我要申诉|加载中|点击展开|展开更多')
# 仅最退化的装饰性符号才算"纯符号垃圾"; ？！… 等表达性标点保留
JUNK_SYMBOLS = set('*\u2022·.。，、#')
URL = re.compile(r'https?://\S+|www\.\S+')
AT = re.compile(r'@[A-Za-z0-9_一-鿿]+')
HASH = re.compile(r'#[^\s#]+#')
PHONE = re.compile(r'1[3-9]\d{9}')
LONGDIGIT = re.compile(r'\d{7,}')
QQ = re.compile(r'QQ\s*[号码]{0,2}\s*[:：]?\s*\d{5,11}', re.IGNORECASE)  # ⑤.4 显式QQ号(≥5位, 避开奇瑞QQ3等车型误伤)
HTML_ENT = re.compile(r'&(amp|lt|gt|quot|apos|nbsp|#\d+);', re.IGNORECASE)  # ④.7 HTML实体
CJK = re.compile(r'[一-鿿]')
# ④.5 全半角归一: 仅数字 ０-９ → 0-9 (2行)。
# ⚠️ 禁止用 NFKC 处理输出文本: 会把全角标点 ，！？：； 转成半角, 违反 ④.6 (全角标点=正常中文)
FW_DIGITS = str.maketrans('０１２３４５６７８９', '0123456789')

def _decode_entity(m):
    e = m.group(1).lower()
    if e.startswith('#'):
        try:
            return chr(int(e[1:]))
        except Exception:
            return m.group(0)
    return {'amp': '&', 'lt': '<', 'gt': '>', 'quot': '"', 'apos': "'", 'nbsp': ' '}.get(e, m.group(0))

# ---------- ① 结构校验 (R0, 静默) ----------
df = pd.read_csv(SRC, dtype=str).fillna('')
N = len(df)
assert df['post_id'].is_unique, 'post_id 非唯一'
for col in ['multimodal_content', 'images']:
    for v in df[col]:
        if v.strip():
            try:
                json.loads(v)
            except Exception:
                pass  # 已知 0 非法, 静默跳过

text = df['text_content'].fillna('')
stripped = text.str.strip()

# ---------- ② 降冗余 (R1): norm_key ----------
def norm_key(s):
    s = unicodedata.normalize('NFKC', s).lower()   # 全→半角 + 兼容
    s = re.sub(r'\s+', ' ', s).strip()
    return s

key = stripped.map(norm_key)
nonempty = key != ''
groups = {}
gid = 0
dedup_group_id = [0] * N
is_dup = [False] * N
for i, k in enumerate(key):
    if not nonempty.iloc[i]:
        continue
    if k not in groups:
        groups[k] = gid
        gid += 1
        dedup_group_id[i] = groups[k]
    else:
        dedup_group_id[i] = groups[k]
        is_dup[i] = True
df['dedup_group_id'] = dedup_group_id
df['is_duplicate'] = is_dup

# ---------- ④ 统形式 (R1) + ⑤ 护隐私 (R2) ----------
def clean_text(s):
    """clean_text: 去 @/#/URL、emoji、HTML实体解码、全半角归一、手机号/QQ/长数字打码、折叠空白。"""
    s = HTML_ENT.sub(_decode_entity, s)         # ④.7 HTML实体解码
    s = s.translate(FW_DIGITS)                  # ④.5 仅全角数字归一 (NFKC 会误伤全角标点, 禁用)
    s = URL.sub('', s)                          # ④.3 URL
    s = AT.sub('', s)                           # ④.1 @
    s = HASH.sub('', s)                         # ④.2 #
    s = PHONE.sub(lambda m: m.group(0)[:3] + '****' + m.group(0)[-4:], s)  # ⑤.1
    s = QQ.sub('QQ****', s)                     # ⑤.4 显式QQ号打码
    s = LONGDIGIT.sub('****', s)                # ⑤.2 微信号/QQ 等长数字串
    s = EMOJI.sub('', s)                        # ④.4 emoji 抽除(不单列)
    s = re.sub(r'\s+', ' ', s).strip()
    return s

df['clean_text'] = stripped.map(clean_text)
df['norm_key'] = key
df['text_changed'] = df['clean_text'] != stripped   # ⑥.7 清洗是否改动正文

# ---------- clean_multimodal: 平行列, 仅清文本块, 保留图片 URL ----------
def clean_multimodal(s):
    s = s.strip()
    if not s:
        return ''
    try:
        obj = json.loads(s)
    except Exception:
        return s  # 已知 0 非法, 保底原样
    if not isinstance(obj, list):
        return s
    out = []
    for item in obj:
        if isinstance(item, dict) and item.get('type') == 'text':
            # type=text 块: 与 clean_text 同款清洗(去@/#/emoji/空白), 但不去 URL
            # (文本块不含图片链接, 安全); type=img 原样保留
            v = item.get('v', '')
            v = HTML_ENT.sub(_decode_entity, v)
            v = v.translate(FW_DIGITS)
            v = AT.sub('', v)
            v = HASH.sub('', v)
            v = PHONE.sub(lambda m: m.group(0)[:3] + '****' + m.group(0)[-4:], v)
            v = QQ.sub('QQ****', v)
            v = LONGDIGIT.sub('****', v)
            v = EMOJI.sub('', v)
            v = re.sub(r'\s+', ' ', v).strip()
            out.append({'type': 'text', 'v': v})
        else:
            out.append(item)  # img 及其他类型原样保留
    return json.dumps(out, ensure_ascii=False)

df['clean_multimodal'] = df['multimodal_content'].fillna('').map(clean_multimodal)

# ---------- ③ 去垃圾 (R2): excluded ----------
excluded = []
for s in stripped:
    if s == '':
        excluded.append('')          # 空文本=图片帖, 不剔除
        continue
    if JUNK.search(s):
        excluded.append('system_junk')
        continue
    em = EMOJI.findall(s)
    t = EMOJI.sub('', s)
    t = re.sub(r'\s', '', t)
    if t == '' and not em:
        excluded.append('gibberish')   # 纯 emoji (无字)
        continue
    if t != '' and not re.search(r'[A-Za-z0-9一-鿿]', t):
        remnant = re.sub(r'[A-Za-z0-9一-鿿]', '', t)
        if remnant and all(c in JUNK_SYMBOLS for c in remnant):
            excluded.append('gibberish')
            continue
    excluded.append('')
df['excluded'] = excluded

# ---------- ⑥ 增标注 (R0/R1) ----------
df['non_chinese'] = [bool(s) and not bool(CJK.search(s)) for s in stripped]
df['is_long'] = [len(s) > 2000 for s in stripped]

slen = stripped.str.len()
q = pd.Series(1.0, index=df.index)
q[df['excluded'] != ''] = 0.0
q[df['is_duplicate']] = 0.3
lowq = (slen <= 10) & (df['excluded'] == '') & (~df['is_duplicate'])
q[lowq] = 0.6
nc = df['non_chinese'] & (df['excluded'] == '') & (~df['is_duplicate'])
q[nc] = 0.5
df['quality_score'] = q

df['high_confidence'] = (df['excluded'] == '') & (~df['is_duplicate']) & (df['clean_text'].str.len() > 0)

# ---------- 写出 ----------
def safe_write(frame, path):
    try:
        frame.to_csv(path, index=False, encoding='utf-8-sig')
        return path
    except PermissionError:
        alt = path[:-4] + '_NEW.csv' if path.endswith('.csv') else path + '.new'
        frame.to_csv(alt, index=False, encoding='utf-8-sig')
        print('WARN 权限拒绝, 已写入备用名: ' + alt)
        return alt

safe_write(df, OUT)

# 高置信子集: 仅保留原始列 + 清洗后文本(clean_text) + 清洗后多模态(clean_multimodal),
# 丢弃内部标注/簿记列, emoji 不单列已并入清洗
ANNOT_DROP = ['norm_key', 'dedup_group_id', 'is_duplicate', 'excluded',
              'non_chinese', 'is_long', 'quality_score', 'high_confidence', 'text_changed']
clean = df[df['high_confidence']][[c for c in df.columns if c not in ANNOT_DROP]]
safe_write(clean, OUT_CLEAN)

# 统计 (自检用)
print('N=%d  cols=%d' % (N, len(df.columns)))
print('dup_rows=%d  dup_groups=%d' % (sum(is_dup), gid))
print('system_junk=%d  gibberish=%d' % ((df['excluded'] == 'system_junk').sum(), (df['excluded'] == 'gibberish').sum()))
print('non_chinese=%d  is_long=%d  text_changed=%d' % (df['non_chinese'].sum(), df['is_long'].sum(), df['text_changed'].sum()))
print('clean_multimodal 非空=%d' % (df['clean_multimodal'].str.len() > 0).sum())
print('high_confidence=%d  clean_file_rows=%d' % (df['high_confidence'].sum(), len(clean)))

# ⑤.4 QQ 打码复核 (10 行, 全量打印供人工确认)
qq_masked = [i for i, s in enumerate(stripped) if QQ.search(s)]
print('--- QQ 打码命中 %d 行 ---' % len(qq_masked))
for i in qq_masked:
    raw = re.sub(r'\s+', ' ', stripped.iloc[i])
    cln = df['clean_text'].iloc[i]
    print('[%s] 原: %s' % (df['post_id'].iloc[i], raw[:100]))
    print('       清: %s' % cln[:100])
