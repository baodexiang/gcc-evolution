"""P0 外挂参数分析 — 基于历史日志推导建议值"""
import re, json
from collections import defaultdict, Counter

print('='*60)
print('P0 外挂参数分析报告')
print('='*60)

# ─── 1. N字结构 ───────────────────────────────────────────
lines = open('state/audit/signal_log.jsonl').readlines()
records = [json.loads(l) for l in lines]
total = len(records)

print()
print('【1】N字结构 — 信号分布分析')
pat_cnt = Counter(r.get('n_pattern') for r in records)
for pat, cnt in pat_cnt.most_common():
    print(f'  {pat:20s} {cnt:4d}条  {cnt/total:.0%}')

valid = [r for r in records if r.get('n_pattern') != 'SIDE' and r.get('n_quality', 0) > 0]
if valid:
    qs = [r['n_quality'] for r in valid]
    print(f'  非SIDE共 {len(valid)} 条, quality 均={sum(qs)/len(qs):.2f} min={min(qs):.2f} max={max(qs):.2f}')
    for bucket, lo, hi in [('q<0.5',0,0.5),('0.5~0.7',0.5,0.7),('0.7~0.85',0.7,0.85),('0.85+',0.85,1.01)]:
        cnt = sum(1 for q in qs if lo <= q < hi)
        print(f'    {bucket}: {cnt}条 ({cnt/len(qs):.0%})')

allowed = sum(1 for r in records if r.get('allowed'))
print(f'  allowed={allowed} blocked={total-allowed} 放行率={allowed/total:.0%}')
div_cnt = sum(1 for r in records if r.get('n_wave5_divergence'))
print(f'  wave5_divergence 触发: {div_cnt}条 ({div_cnt/total:.0%})')

# retrace_ratio 分布（非零）
rr = [r['n_retrace_ratio'] for r in records if r.get('n_retrace_ratio', 0) > 0]
if rr:
    print(f'  retrace_ratio: min={min(rr):.2f} max={max(rr):.2f} 均={sum(rr)/len(rr):.2f}')

# 用 price_after_4h 算各 pattern 准确率
filled = [r for r in records if r.get('price_after_4h') and r.get('signal_price', 0) > 0]
if filled:
    print(f'  已有4h结果: {len(filled)} 条')
    pat_wr = defaultdict(lambda: [0, 0])
    for r in filled:
        move = (r['price_after_4h'] - r['signal_price']) / r['signal_price']
        win = (move > 0.002 and r['direction'] == 'BUY') or (move < -0.002 and r['direction'] == 'SELL')
        pat_wr[r['n_pattern']][0 if win else 1] += 1
    print('  Pattern 4h准确率:')
    for pat, (w, l) in pat_wr.items():
        t = w + l
        print(f'    {pat:20s} {w}/{t} = {w/t:.0%}' if t else '')

# ─── 2. Rob Hoffman ───────────────────────────────────────
print()
print('【2】Rob Hoffman — ER阈值与方向偏差分析')
log = open('logs/rob_hoffman_plugin.log').read()
signals = re.findall(
    r'\[(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})\] \[(\w+)\] SIGNAL: (\w+), alignment=(\w+), entry=([\d.]+)',
    log
)
filtered_count = log.count('FILTERED: EMA tangled')
total_rh = len(signals) + filtered_count
buy1  = sum(1 for s in signals if s[2] == 'BUY1')
sell1 = sum(1 for s in signals if s[2] == 'SELL1')
print(f'  总触发: {total_rh}  信号: {len(signals)}  过滤(EMA tangled): {filtered_count}')
print(f'  过滤率: {filtered_count/total_rh:.0%}')
print(f'  BUY1={buy1} ({buy1/len(signals):.0%})  SELL1={sell1} ({sell1/len(signals):.0%})')

sym_cnt = Counter(s[1] for s in signals)
print('  品种信号 BUY/SELL:')
for sym, cnt in sym_cnt.most_common():
    b  = sum(1 for s in signals if s[1] == sym and s[2] == 'BUY1')
    sl = sum(1 for s in signals if s[1] == sym and s[2] == 'SELL1')
    tag = 'SELL-ONLY' if b == 0 else ('BUY-ONLY' if sl == 0 else 'MIXED')
    print(f'    {sym:8s} 共{cnt:3d}  BUY={b:3d} SELL={sl:3d}  [{tag}]')

# 日期分布：从哪天开始有 BUY 信号
buy_signals = [(s[0], s[1]) for s in signals if s[2] == 'BUY1']
if buy_signals:
    print(f'  BUY1信号时间范围: {buy_signals[0][0][:10]} ~ {buy_signals[-1][0][:10]}')

# ─── 3. Feiyun / Double Pattern ───────────────────────────
print()
print('【3】Feiyun / Double Pattern — 过滤分析')
log_fy = open('logs/feiyun_plugin.log').read()
lines_fy = log_fy.split('\n')
filt_fy  = [l for l in lines_fy if 'FILTERED' in l]
exec_fy  = [l for l in lines_fy if 'EXECUTED' in l]
print(f'  EXECUTED={len(exec_fy)}  FILTERED={len(filt_fy)}')
if filt_fy:
    trend_mis = sum(1 for l in filt_fy if 'Trend mismatch' in l)
    print(f'  Trend mismatch: {trend_mis}条 ({trend_mis/len(filt_fy):.0%})')
    confs = [float(c) for c in re.findall(r'conf=([\d.]+)', log_fy)]
    if confs:
        print(f'  conf分布: min={min(confs):.2f} max={max(confs):.2f} 均={sum(confs)/len(confs):.2f}')
        hi_conf = sum(1 for c in confs if c >= 0.75)
        print(f'  conf>=0.75 被过滤: {hi_conf}条 ({hi_conf/len(confs):.0%})')

# double_pattern 单独看
log_dp = open('logs/double_pattern_plugin.log').read()
dp_lines = log_dp.split('\n')
dp_exec  = [l for l in dp_lines if 'EXECUTED' in l]
dp_filt  = [l for l in dp_lines if 'FILTERED' in l]
dp_sigs  = re.findall(r'\[(\w+)\] (\w+)\|', log_dp)
print(f'  double_pattern EXECUTED={len(dp_exec)} FILTERED={len(dp_filt)} 事件={len(dp_sigs)}')
if dp_sigs:
    types = Counter(s[1] for s in dp_sigs)
    print(f'  形态分布: {dict(types.most_common(5))}')

print()
print('='*60)
print('建议值汇总 (基于以上分析)')
print('='*60)
