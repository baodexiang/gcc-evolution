
// Tab switching
document.querySelectorAll('.tab').forEach(tab => {
    tab.addEventListener('click', () => {
        document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
        document.querySelectorAll('.tab-content').forEach(c => c.classList.remove('active'));
        tab.classList.add('active');
        document.getElementById('tab-' + tab.dataset.tab).classList.add('active');
    });
});

let DATA = null;
let MULTI_DATA = null;

function ruleTransition(idx, newStatus) {
    const rules = DATA.extracted_rules || [];
    if (idx < 0 || idx >= rules.length) return;
    const r = rules[idx];
    const oldStatus = r.status;
    r.status = newStatus;
    // 写回本地state/key009_rules.json (通过fetch POST或直接更新)
    // 服务器模式: POST到/key009/rule-transition
    const payload = {rule_id: r.rule_id, old_status: oldStatus, new_status: newStatus};
    fetch('/key009/rule-transition', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(payload)})
        .then(resp => resp.ok ? resp.json() : Promise.reject(resp.statusText))
        .then(d => { $('subtitle').textContent = `规则 ${r.rule_id}: ${oldStatus}→${newStatus} ✓`; })
        .catch(e => { $('subtitle').textContent = `规则更新失败(${e}), 手动: python key009_audit.py --rule-status ${r.rule_id} ${newStatus}`; });
    render();
}

function switchRange(range, btn) {
    if (!MULTI_DATA && window.MULTI_DATA) MULTI_DATA = window.MULTI_DATA;
    if (!MULTI_DATA || !MULTI_DATA[range]) {
        $('subtitle').textContent = 'No data for range: ' + range + ' (MULTI_DATA=' + (MULTI_DATA ? Object.keys(MULTI_DATA).join(',') : 'null') + ')';
        return;
    }
    DATA = MULTI_DATA[range];
    document.querySelectorAll('.range-btn').forEach(b => {
        b.style.background = '#fff'; b.style.color = '#656d76';
    });
    btn.style.background = '#0969da'; btn.style.color = '#fff';
    render();
}

async function loadData() {
    // 优先用服务器注入的多范围数据
    if (window.MULTI_DATA) { MULTI_DATA = window.MULTI_DATA; DATA = MULTI_DATA['24h']; render(); return; }
    if (window.EMBEDDED_DATA) { DATA = window.EMBEDDED_DATA; render(); return; }
    try {
        const resp = await fetch('state/key009_audit.json?t=' + Date.now());
        if (resp.ok) {
            const json = await resp.json();
            // 多范围JSON: {24h:{...}, 1w:{...}, 1m:{...}}
            if (json['24h'] && json['1w'] && json['1m']) {
                MULTI_DATA = json; DATA = MULTI_DATA['24h'];
            } else {
                DATA = json;
            }
            render(); return;
        }
    } catch(e) {}
    $('subtitle').textContent = 'Cannot load data. Run: python key009_audit.py --export';
}

function barHTML(val, max, color, width) {
    const pct = max > 0 ? (val / max * width) : 0;
    return `<span class="bar ${color}" style="width:${Math.max(pct, 2)}px"></span>`;
}

function topSymbols(obj, n) {
    return Object.entries(obj || {}).sort((a,b)=>b[1]-a[1]).slice(0,n).map(([s,c])=>`${s}(${c})`).join(' ');
}

function $(id) { return document.getElementById(id) || {innerHTML:'',textContent:'',style:{},closest:()=>({insertAdjacentHTML:()=>{}}),classList:{add:()=>{},remove:()=>{}}}; }

function render() {
    if (!DATA) return;
    try { _doRender(); } catch(e) { console.error('render error:', e); $('subtitle').textContent = 'Render error: ' + e.message; }
}
function _doRender() {
    $('subtitle').textContent = `Window: ${DATA.hours}h | Generated: ${DATA.generated_at}`;
    $('footer-time').textContent = DATA.generated_at;

    // ── Review Status Bar ──
    const rs = DATA.review_status || {};
    const bar = $('review-bar');
    const phaseEl = $('review-phase');
    const detailEl = $('review-detail');
    const rejectBtn = $('reject-btn');
    const phaseMap = {
        'IDLE': ['IDLE', '等待下一个4h slot'],
        'COLLECTING': ['SYNCING', `正在等待日志同步 (第${Math.ceil((rs.collect_retries||0)/2)}次检查, 每10min)`],
        'READY': ['READY', '数据就绪, 即将启动审计'],
        'WAITING': ['WAITING', '已发送邮件, 30min内可拒绝 → 超时将写autofix.json'],
    };
    const [pLabel, pDetail] = phaseMap[rs.phase] || ['UNKNOWN', ''];
    phaseEl.textContent = `Claude Review: ${pLabel}`;
    detailEl.textContent = `${pDetail} | Slot: ${rs.slot || '-'}`;
    bar.style.display = 'block';
    bar.style.background = rs.phase === 'WAITING' ? '#fff8c5' : rs.phase === 'FIXING' ? '#ffebe9' : '#ddf4ff';
    bar.style.borderColor = rs.phase === 'WAITING' ? '#d4a72c' : rs.phase === 'FIXING' ? '#cf222e' : '#54aeff';
    rejectBtn.style.display = rs.phase === 'WAITING' ? 'inline' : 'none';

    const p = DATA.plugins || {};
    const md = DATA.macd || {};
    const bv = DATA.brooks_vision || {};
    const gt = DATA.gates || {};
    const vfl = DATA.vision_filter || {};
    const arb = DATA.arbiter || {};
    const mdiv = DATA.macd_divergence || {};
    const rh = DATA.rob_hoffman || {};
    const l1d = DATA.l1_diagnosis || {};
    const va = DATA.value_analysis || {};

    // ── Summary cards ──
    const hasErrors = DATA.total_errors > 0;
    const issueCount = (DATA.issues || []).length;
    const riskCount = (DATA.issues || []).filter(i => i.type === 'RISK').length;
    $('summary').innerHTML = `
        <div class="card"><div class="label">GCC Events</div><div class="value blue">${DATA.total_events}</div></div>
        <div class="card"><div class="label">Errors</div><div class="value ${hasErrors?'red':'green'}">${DATA.total_errors}</div></div>
        <div class="card"><div class="label">VF过滤</div><div class="value blue">${(p.vf_total||0)+(vfl.total||0)}</div><div class="sub">外挂VF ${p.vf_total||0} / Vision ${vfl.total||0}</div></div>
        <div class="card"><div class="label">MACD</div><div class="value blue">${md.trigger||0}</div><div class="sub">执行 ${md.execute||0} 拦截 ${md.gate_block||0}</div></div>
        <div class="card"><div class="label">BV信号</div><div class="value blue">${bv.signals||0}</div><div class="sub">执行 ${bv.executed||0}</div></div>
        <div class="card"><div class="label">Risks</div><div class="value ${riskCount?'yellow':'green'}">${riskCount}</div><div class="sub">${issueCount} total issues</div></div>
        <div class="card"><div class="label">仲裁HOLD率</div><div class="value ${arb.hold_rate>0.9?'yellow':'green'}">${(arb.hold_rate*100||0).toFixed(0)}%</div><div class="sub">${arb.total||0}次决策</div></div>
        <div class="card"><div class="label">L1 HOLD率</div><div class="value ${l1d.total>0&&(l1d.by_signal||{}).HOLD/l1d.total>0.95?'yellow':'green'}">${l1d.total>0?(((l1d.by_signal||{}).HOLD||0)/l1d.total*100).toFixed(0):0}%</div><div class="sub">${l1d.total||0}次诊断</div></div>
        <div class="card"><div class="label">估值Fallback</div><div class="value ${va.fallback>10?'red':'green'}">${va.fallback||0}</div><div class="sub">${va.batch_total||0}批 失败${va.batch_failed||0}</div></div>
    `;

    // ── 外挂运行 Tab ──
    // 从scan_plugins聚合真实数据(plugin_exec只匹配旧格式日志,数据不全)
    const sp_all = p.scan_plugins || {};
    let sp_scan=0, sp_trigger=0, sp_dispatch=0, sp_executed=0, sp_blocked=0;
    for (const pd of Object.values(sp_all)) {
        sp_scan += pd.scan||0; sp_trigger += pd.trigger||0;
        sp_dispatch += pd.dispatch||0; sp_executed += pd.executed||0; sp_blocked += pd.blocked||0;
    }
    $('plugin-summary').innerHTML = `
        <div class="card"><div class="label">VF过滤总计</div><div class="value blue">${p.vf_total||0}</div></div>
        <div class="card"><div class="label">KNN抑制</div><div class="value yellow">${p.knn_suppress_total||0}</div></div>
        <div class="card"><div class="label">外挂已执行</div><div class="value green">${sp_executed}</div><div class="sub">dispatch ${sp_dispatch} / trigger ${sp_trigger}</div></div>
        <div class="card"><div class="label">外挂扫描</div><div class="value blue">${sp_scan}</div></div>
        <div class="card"><div class="label">外挂拦截</div><div class="value red">${sp_blocked}</div></div>
    `;

    // VF by plugin
    const vfp = p.vf_by_plugin || {};
    const maxVF = Math.max(...Object.values(vfp).map(v => Object.values(v).reduce((a,b)=>a+b,0)), 1);
    let vfpHTML = '';
    for (const [plugin, syms] of Object.entries(vfp).sort((a,b) => {
        const sa = Object.values(a[1]).reduce((x,y)=>x+y,0);
        const sb = Object.values(b[1]).reduce((x,y)=>x+y,0);
        return sb - sa;
    })) {
        const total = Object.values(syms).reduce((a,b)=>a+b,0);
        vfpHTML += `<tr><td><strong>${plugin}</strong></td><td>${barHTML(total,maxVF,'blue',80)} ${total}</td><td style="font-size:0.78em;color:#656d76">${topSymbols(syms,4)}</td></tr>`;
    }
    $('vf-plugin-body').innerHTML = vfpHTML || '<tr><td colspan="3" style="color:#656d76">无数据</td></tr>';

    // KNN suppress
    const knn = p.knn_suppress || {};
    let knnHTML = '';
    for (const [plugin, syms] of Object.entries(knn).sort((a,b) => {
        const sa = Object.values(a[1]).reduce((x,y)=>x+y,0);
        const sb = Object.values(b[1]).reduce((x,y)=>x+y,0);
        return sb - sa;
    })) {
        const total = Object.values(syms).reduce((a,b)=>a+b,0);
        knnHTML += `<tr><td><strong>${plugin}</strong></td><td>${barHTML(total,p.knn_suppress_total||1,'yellow',80)} ${total}</td><td style="font-size:0.78em;color:#656d76">${topSymbols(syms,4)}</td></tr>`;
    }
    $('knn-body').innerHTML = knnHTML || '<tr><td colspan="3" style="color:#656d76">无数据</td></tr>';

    // VF by symbol
    const vfs = p.vf_by_symbol || {};
    const maxVFS = Math.max(...Object.values(vfs), 1);
    let vfsHTML = '';
    for (const [sym, cnt] of Object.entries(vfs).sort((a,b)=>b[1]-a[1])) {
        const pct = (p.vf_total > 0) ? (cnt / p.vf_total * 100).toFixed(1) + '%' : '-';
        vfsHTML += `<tr><td><strong>${sym}</strong></td><td>${barHTML(cnt,maxVFS,'blue',100)} ${cnt}</td><td>${pct}</td></tr>`;
    }
    $('vf-symbol-body').innerHTML = vfsHTML || '<tr><td colspan="3" style="color:#656d76">无数据</td></tr>';

    // RobHoffman ER stats
    if (rh.scans > 0) {
        $('plugin-summary').innerHTML += `
            <div class="card"><div class="label">RH震荡率</div><div class="value ${rh.er_below_pct>0.8?'yellow':'green'}">${(rh.er_below_pct*100).toFixed(0)}%</div><div class="sub">扫描${rh.scans} 信号${rh.signals||0} 过滤${rh.filtered}</div></div>
        `;
    }

    // Scan plugins table
    const sp = p.scan_plugins || {};
    let spHTML = '';
    for (const [pname, pd] of Object.entries(sp).sort((a,b) => {
        const sa = (a[1].scan||0) + (a[1].trigger||0) + (a[1].dispatch||0);
        const sb = (b[1].scan||0) + (b[1].trigger||0) + (b[1].dispatch||0);
        return sb - sa;
    })) {
        const isP0 = pd.scan === 0 || !pd.scan;
        const trigRate = isP0 ? (pd.trigger > 0 ? 'P0路径' : '-') : (pd.scan > 0 ? (pd.trigger / pd.scan * 100).toFixed(1) + '%' : '-');
        const execColor = pd.dispatch > 0 && pd.executed === 0 ? 'color:#cf222e' : '';
        // 拦截原因
        const br = pd.block_reasons || {};
        const brStr = Object.entries(br).sort((a,b)=>b[1]-a[1]).map(([r,c])=>`${r}:${c}`).join(' ') || '-';
        spHTML += `<tr>
            <td><strong>${pname}</strong>${isP0 && pd.trigger > 0 ? ' <span style="font-size:0.7em;color:#656d76">(P0)</span>' : ''}</td>
            <td>${pd.scan||0}</td>
            <td>${pd.trigger||0}</td>
            <td>${trigRate}</td>
            <td>${pd.dispatch||0}</td>
            <td style="color:#1a7f37">${pd.executed||0}</td>
            <td style="${execColor}">${pd.blocked||0}</td>
            <td style="font-size:0.78em;color:#656d76">${brStr}</td>
        </tr>`;
    }
    $('scan-plugin-body').innerHTML = spHTML || '<tr><td colspan="8" style="color:#656d76">无数据</td></tr>';

    // 拦截原因汇总
    const allReasons = {};
    for (const pd of Object.values(sp)) {
        for (const [r,c] of Object.entries(pd.block_reasons || {})) {
            allReasons[r] = (allReasons[r]||0) + c;
        }
    }
    const reasonEntries = Object.entries(allReasons).sort((a,b)=>b[1]-a[1]);
    if (reasonEntries.length > 0) {
        const totalBlocked = reasonEntries.reduce((s,e)=>s+e[1],0);
        let brHTML = '<h3 style="margin-top:16px">拦截原因分布</h3><table><thead><tr><th>原因</th><th>次数</th><th>占比</th><th>建议</th></tr></thead><tbody>';
        const suggestions = {
            '门控拦截': '检查KEY-001/002门控参数，或放宽Vision/N-Gate阈值',
            '执行失败': '检查SignalStack/3Commas连接状态（Schwab 7天重连）',
            'FilterChain': '检查Vision准确率和volume_score阈值',
            '限次/冷却': 'P0每日限次3次/品种，属正常防护',
            '仓位限制': '满仓或EMA条件不满足，属正常风控',
            '方向限制': 'daily_bias方向限制，检查set_bias.py配置是否合理',
        };
        for (const [r,c] of reasonEntries) {
            const pct = (c/totalBlocked*100).toFixed(0)+'%';
            const sug = suggestions[r] || '查看具体日志分析';
            brHTML += `<tr><td><strong>${r}</strong></td><td>${c}</td><td>${pct}</td><td style="font-size:0.82em;color:#656d76">${sug}</td></tr>`;
        }
        brHTML += '</tbody></table>';
        $('scan-plugin-body').closest('table').insertAdjacentHTML('afterend', brHTML);
    }

    // ── L2 MACD Tab ──
    $('macd-summary').innerHTML = `
        <div class="card"><div class="label">触发</div><div class="value blue">${md.trigger||0}</div></div>
        <div class="card"><div class="label">过滤</div><div class="value yellow">${md.reject||0}</div></div>
        <div class="card"><div class="label">执行</div><div class="value green">${md.execute||0}</div></div>
        <div class="card"><div class="label">门控拦截</div><div class="value red">${md.gate_block||0}</div></div>
    `;

    // MACD funnel
    const funnelTotal = Math.max(md.trigger || 1, 1);
    const stages = [
        {label:'触发', val:md.trigger||0, color:'blue'},
        {label:'未过滤', val:(md.trigger||0)-(md.reject||0), color:'blue'},
        {label:'执行', val:md.execute||0, color:'green'},
        {label:'门控拦截', val:md.gate_block||0, color:'red'},
    ];
    $('macd-funnel').innerHTML = stages.map(s =>
        `<div style="margin:4px 0;font-size:0.85em">${s.label}: ${barHTML(s.val,funnelTotal,s.color,200)} <strong>${s.val}</strong> (${(s.val/funnelTotal*100).toFixed(0)}%)</div>`
    ).join('');

    // MACD by symbol
    const mbs = md.by_symbol || {};
    let mbsHTML = '';
    for (const [sym, st] of Object.entries(mbs).sort((a,b)=>b[1].trigger-a[1].trigger)) {
        const rate = st.trigger > 0 ? (st.execute / st.trigger * 100).toFixed(0) + '%' : '-';
        mbsHTML += `<tr><td><strong>${sym}</strong></td><td>${st.trigger}</td><td>${st.execute}</td><td>${rate}</td></tr>`;
    }
    $('macd-symbol-body').innerHTML = mbsHTML || '<tr><td colspan="4" style="color:#656d76">无数据</td></tr>';

    // MACD divergence (from macd_divergence.log)
    if (mdiv.found > 0 || mdiv.filtered > 0) {
        $('macd-summary').innerHTML += `
            <div class="card"><div class="label">背离发现</div><div class="value blue">${mdiv.found}</div></div>
            <div class="card"><div class="label">背离过滤</div><div class="value yellow">${mdiv.filtered}</div></div>
            <div class="card"><div class="label">平均强度</div><div class="value blue">${mdiv.avg_strength||0}%</div></div>
        `;
        const fr = mdiv.filter_reasons || {};
        const frEntries = Object.entries(fr).sort((a,b)=>b[1]-a[1]);
        if (frEntries.length) {
            const frTotal = frEntries.reduce((s,e)=>s+e[1],0);
            const maxFR = Math.max(...frEntries.map(e=>e[1]),1);
            let frHTML = '<h3 style="margin-top:16px">背离过滤原因</h3><table><thead><tr><th>原因</th><th>次数</th><th>占比</th></tr></thead><tbody>';
            for (const [reason, cnt] of frEntries) {
                frHTML += `<tr><td>${reason}</td><td>${barHTML(cnt,maxFR,'yellow',100)} ${cnt}</td><td>${(cnt/frTotal*100).toFixed(0)}%</td></tr>`;
            }
            frHTML += '</tbody></table>';
            $('macd-symbol-body').closest('table').insertAdjacentHTML('afterend', frHTML);
        }
    }

    // ── Vision过滤 Tab ──
    const m = DATA.metrics || {};
    const vflTotal = vfl.total || 0;
    const vfPluginTotal = p.vf_total || 0;
    const vAllTotal = vflTotal + vfPluginTotal;
    const vflSymCount = Object.keys(vfl.by_symbol || {}).length;
    const vfAccAvg = m.vf_acc_avg;
    $('vision-summary').innerHTML = `
        <div class="card"><div class="label">总过滤</div><div class="value ${vAllTotal>0?'yellow':'green'}">${vAllTotal}</div><div class="sub">Vision ${vflTotal} + 外挂VF ${vfPluginTotal}</div></div>
        <div class="card"><div class="label">Vision方向拦截</div><div class="value red">${vflTotal}</div><div class="sub">${vflSymCount}个品种</div></div>
        <div class="card"><div class="label">外挂VF过滤</div><div class="value yellow">${vfPluginTotal}</div><div class="sub">${Object.keys(p.vf_by_plugin||{}).length}个外挂</div></div>
        ${vfAccAvg !== undefined ? `<div class="card"><div class="label">VF准确率</div><div class="value ${vfAccAvg>=0.5?'green':'red'}">${(vfAccAvg*100).toFixed(1)}%</div></div>` : ''}
    `;

    // Vision funnel
    const vFunnelMax = Math.max(vAllTotal, 1);
    const vFunnelStages = [
        {label:'Vision方向拦截', val:vflTotal, color:'red'},
        {label:'外挂VF过滤', val:vfPluginTotal, color:'yellow'},
    ];
    $('vision-funnel').innerHTML = vFunnelStages.map(s =>
        `<div style="margin:4px 0;font-size:0.85em">${s.label}: ${barHTML(s.val,vFunnelMax,s.color,250)} <strong>${s.val}</strong> (${(s.val/vFunnelMax*100).toFixed(0)}%)</div>`
    ).join('');

    // Vision方向拦截 (VISION_FILTER) 按品种
    const vflSym = vfl.by_symbol || {};
    const vflReason = vfl.by_reason || {};
    const vflEntries = Object.entries(vflSym).sort((a,b)=>b[1]-a[1]);
    if (vflEntries.length) {
        const maxVfl = Math.max(...vflEntries.map(e=>e[1]), 1);
        let vflHTML = '<table><thead><tr><th>品种</th><th>拦截次数</th><th>占比</th></tr></thead><tbody>';
        for (const [sym, cnt] of vflEntries) {
            const pct = vflTotal > 0 ? (cnt/vflTotal*100).toFixed(1)+'%' : '-';
            vflHTML += `<tr><td><strong>${sym}</strong></td><td>${barHTML(cnt,maxVfl,'red',120)} ${cnt}</td><td>${pct}</td></tr>`;
        }
        vflHTML += '</tbody></table>';
        $('vision-filter-detail').innerHTML = vflHTML;
    } else {
        $('vision-filter-detail').innerHTML = '<div style="color:#656d76;padding:10px">无Vision方向拦截</div>';
    }

    // Vision reason analysis
    const vflReasonEntries = Object.entries(vflReason).sort((a,b)=>b[1]-a[1]);
    if (vflReasonEntries.length) {
        const maxR = Math.max(...vflReasonEntries.map(e=>e[1]), 1);
        const totalR = vflReasonEntries.reduce((s,e)=>s+e[1],0);
        let vrHTML = '<table><thead><tr><th>原因</th><th>次数</th><th>占比</th></tr></thead><tbody>';
        for (const [reason, cnt] of vflReasonEntries) {
            vrHTML += `<tr><td><strong>${reason}</strong></td><td>${barHTML(cnt,maxR,'yellow',150)} ${cnt}</td><td>${(cnt/totalR*100).toFixed(0)}%</td></tr>`;
        }
        vrHTML += '</tbody></table>';
        $('vision-reason-chart').innerHTML = vrHTML;
    } else {
        $('vision-reason-chart').innerHTML = '<div style="color:#656d76;padding:10px">无拦截原因数据</div>';
    }

    // Vision detail: plugin×symbol matrix
    const plugins = Object.keys(vfp).sort();
    const symbols = [...new Set(Object.values(vfp).flatMap(v => Object.keys(v)))].sort();
    if (plugins.length && symbols.length) {
        let tbl = '<table><thead><tr><th>品种</th>';
        plugins.forEach(pl => tbl += `<th>${pl}</th>`);
        tbl += '<th>合计</th></tr></thead><tbody>';
        for (const sym of symbols) {
            tbl += `<tr><td><strong>${sym}</strong></td>`;
            let rowTotal = 0;
            plugins.forEach(pl => {
                const v = (vfp[pl] || {})[sym] || 0;
                rowTotal += v;
                tbl += `<td style="color:${v>0?'#58a6ff':'#484f58'}">${v||'-'}</td>`;
            });
            tbl += `<td><strong>${rowTotal}</strong></td></tr>`;
        }
        tbl += '</tbody></table>';
        $('vision-detail').innerHTML = tbl;
    } else {
        $('vision-detail').innerHTML = '<div style="color:#656d76;padding:20px">无VF过滤数据</div>';
    }

    // ── BrooksVision Tab ──
    const ev = bv.eval || {};
    const evDecisive = (ev.CORRECT||0) + (ev.INCORRECT||0);
    const evTotal = evDecisive + (ev.NEUTRAL||0);
    const bvAcc = evDecisive > 0 ? ((ev.CORRECT||0) / evDecisive * 100).toFixed(1) : '-';
    const bvDir = bv.by_direction || {};
    const bvExecRate = (bv.signals||0) > 0 ? ((bv.executed||0)/(bv.signals||1)*100).toFixed(1) : '-';
    $('bv-summary').innerHTML = `
        <div class="card"><div class="label">P0信号</div><div class="value blue">${bv.signals||0}</div><div class="sub">BUY ${bvDir.BUY||0} / SELL ${bvDir.SELL||0}</div></div>
        <div class="card"><div class="label">已执行</div><div class="value green">${bv.executed||0}</div><div class="sub">执行率 ${bvExecRate}%</div></div>
        <div class="card"><div class="label">门控观察</div><div class="value yellow">${bv.gate_obs||0}</div></div>
        <div class="card"><div class="label">评估总数</div><div class="value blue">${evTotal}</div><div class="sub">decisive ${evDecisive}</div></div>
        <div class="card"><div class="label">准确率</div><div class="value ${bvAcc!=='-'&&parseFloat(bvAcc)>=50?'green':'red'}">${bvAcc}%</div><div class="sub">${evDecisive} decisive</div></div>
    `;

    // BV funnel
    const bvFunnelMax = Math.max(bv.signals||0, 1);
    const bvBlocked = (bv.signals||0) - (bv.executed||0);
    const bvFunnelStages = [
        {label:'P0信号', val:bv.signals||0, color:'blue'},
        {label:'已执行', val:bv.executed||0, color:'green'},
        {label:'被拦截/过滤', val:bvBlocked > 0 ? bvBlocked : 0, color:'red'},
        {label:'门控观察', val:bv.gate_obs||0, color:'yellow'},
    ];
    $('bv-funnel').innerHTML = bvFunnelStages.map(s =>
        `<div style="margin:4px 0;font-size:0.85em">${s.label}: ${barHTML(s.val,bvFunnelMax,s.color,250)} <strong>${s.val}</strong> (${(s.val/bvFunnelMax*100).toFixed(0)}%)</div>`
    ).join('');

    // BV accuracy from state file (GCC-0172)
    const bvAccData = DATA.bv_accuracy || {};
    const bvAccOverall = bvAccData.overall || {};
    const bvAccPatterns = bvAccData.patterns || {};
    const bvAccEl = $('bv-acc-summary');
    const bvAccBodyEl = $('bv-acc-body');
    if (bvAccOverall.decisive > 0) {
        const oa = bvAccOverall;
        const accPctO = (oa.accuracy * 100).toFixed(1);
        bvAccEl.innerHTML = `
            <div class="card"><div class="label">总判定</div><div class="value blue">${oa.decisive}</div><div class="sub">${oa.correct} correct / ${oa.incorrect} incorrect</div></div>
            <div class="card"><div class="label">4H准确率</div><div class="value ${parseFloat(accPctO)>=50?'green':'red'}">${accPctO}%</div><div class="sub">neutral ${oa.neutral||0} excluded</div></div>
        `;
        const totalDec = oa.decisive;
        let accRows = '';
        for (const [pat, pv] of Object.entries(bvAccPatterns).sort((a,b)=>(b[1].decisive||0)-(a[1].decisive||0))) {
            if (!pv.decisive) continue;
            const pa = ((pv.accuracy||0)*100).toFixed(1);
            const cls = parseFloat(pa) >= 55 ? 'green' : parseFloat(pa) < 40 ? 'red' : 'yellow';
            const share = totalDec > 0 ? ((pv.decisive/totalDec)*100).toFixed(0)+'%' : '-';
            accRows += `<tr><td><strong>${pat}</strong></td><td>${pv.decisive}</td><td style="color:#1a7f37">${pv.correct||0}</td><td style="color:#cf222e">${(pv.decisive||0)-(pv.correct||0)}</td><td style="color:${cls==='green'?'#1a7f37':cls==='red'?'#cf222e':'#9a6700'};font-weight:600">${pa}%</td><td>${share}</td></tr>`;
        }
        bvAccBodyEl.innerHTML = accRows || '<tr><td colspan="6" style="color:#656d76">无数据</td></tr>';
    } else {
        bvAccEl.innerHTML = '<div class="card"><div class="label">BV信号准确率</div><div class="value">-</div><div class="sub">等待数据积累</div></div>';
        bvAccBodyEl.innerHTML = '<tr><td colspan="6" style="color:#656d76">无数据</td></tr>';
    }

    // BV eval chart
    if (evTotal > 0) {
        const pctC = (ev.CORRECT||0)/evTotal*100, pctI = (ev.INCORRECT||0)/evTotal*100, pctN = (ev.NEUTRAL||0)/evTotal*100;
        const accPct = evDecisive > 0 ? ((ev.CORRECT||0)/evDecisive*100).toFixed(1) : '-';
        $('bv-eval-chart').innerHTML = `
            <div style="display:flex;height:24px;border-radius:6px;overflow:hidden;margin-bottom:8px">
                <div style="width:${pctC}%;background:#1a7f37" title="CORRECT ${ev.CORRECT||0}"></div>
                <div style="width:${pctI}%;background:#cf222e" title="INCORRECT ${ev.INCORRECT||0}"></div>
                <div style="width:${pctN}%;background:#484f58" title="NEUTRAL ${ev.NEUTRAL||0}"></div>
            </div>
            <div style="font-size:0.82em;display:flex;gap:16px;flex-wrap:wrap">
                <span style="color:#1a7f37">CORRECT: ${ev.CORRECT||0} (${pctC.toFixed(0)}%)</span>
                <span style="color:#cf222e">INCORRECT: ${ev.INCORRECT||0} (${pctI.toFixed(0)}%)</span>
                <span style="color:#656d76">NEUTRAL: ${ev.NEUTRAL||0} (${pctN.toFixed(0)}%)</span>
                <span style="font-weight:600">准确率: ${accPct}% (decisive)</span>
            </div>`;
    } else {
        $('bv-eval-chart').innerHTML = '<div style="color:#656d76;padding:10px">无评估数据</div>';
    }

    // BV by symbol accuracy (from bv_accuracy patterns → aggregate by symbol)
    const bvSymAcc = {};
    for (const [pat, pv] of Object.entries(bvAccPatterns)) {
        for (const [sym, sv] of Object.entries(pv.symbols || {})) {
            if (!bvSymAcc[sym]) bvSymAcc[sym] = {correct:0, incorrect:0, neutral:0, decisive:0};
            bvSymAcc[sym].correct += sv.correct||0;
            bvSymAcc[sym].incorrect += sv.incorrect||0;
            bvSymAcc[sym].neutral += sv.neutral||0;
            bvSymAcc[sym].decisive += sv.decisive||0;
        }
    }
    const bvSymEntries = Object.entries(bvSymAcc).sort((a,b)=>b[1].decisive-a[1].decisive);
    const bvSymEl = $('bv-symbol-body');
    if (bvSymEntries.length) {
        const maxSymDec = Math.max(...bvSymEntries.map(e=>e[1].decisive), 1);
        bvSymEl.innerHTML = bvSymEntries.map(([sym, sv]) => {
            const acc = sv.decisive > 0 ? (sv.correct/sv.decisive*100).toFixed(1) : '-';
            const accColor = sv.decisive >= 5 ? (sv.correct/sv.decisive >= 0.55 ? '#1a7f37' : sv.correct/sv.decisive < 0.4 ? '#cf222e' : '#9a6700') : '#656d76';
            return `<tr><td><strong>${sym}</strong></td><td>${barHTML(sv.decisive,maxSymDec,'blue',100)} ${sv.decisive}</td><td style="color:#1a7f37">${sv.correct}</td><td style="color:${accColor};font-weight:600">${acc}%</td></tr>`;
        }).join('');
    } else {
        bvSymEl.innerHTML = '<tr><td colspan="4" style="color:#656d76">无数据</td></tr>';
    }

    // BV patterns
    const bvp = bv.patterns || {};
    const bvpTotal = Object.values(bvp).reduce((a,b)=>a+b,0);
    const maxBvp = Math.max(...Object.values(bvp), 1);
    let bvpHTML = '';
    for (const [pat, cnt] of Object.entries(bvp).sort((a,b)=>b[1]-a[1])) {
        const share = bvpTotal > 0 ? (cnt/bvpTotal*100).toFixed(1)+'%' : '-';
        bvpHTML += `<tr><td><strong>${pat}</strong></td><td>${barHTML(cnt,maxBvp,'blue',100)} ${cnt}</td><td>${share}</td></tr>`;
    }
    $('bv-pattern-body').innerHTML = bvpHTML || '<tr><td colspan="3" style="color:#656d76">无数据</td></tr>';

    // ── 门控拦截 Tab ──
    const gTotals = gt.totals || {};
    const gDetail = gt.detail || {};
    const totalGates = Object.values(gTotals).reduce((a,b)=>a+b, 0);
    const gateNames = Object.entries(gTotals).sort((a,b)=>b[1]-a[1]);
    // Summary cards
    let gateSummaryHTML = `<div class="card"><div class="label">总拦截</div><div class="value ${totalGates>0?'yellow':'green'}">${totalGates}</div></div>`;
    for (const [gn, gc] of gateNames) {
        if (gc > 0) {
            const symCount = Object.keys(gDetail[gn] || {}).length;
            gateSummaryHTML += `<div class="card"><div class="label">${gn}</div><div class="value yellow">${gc}</div><div class="sub">${symCount}个品种</div></div>`;
        }
    }
    if (totalGates === 0) gateSummaryHTML += `<div class="card"><div class="label">状态</div><div class="value green">无拦截</div></div>`;
    $('gate-summary').innerHTML = gateSummaryHTML;

    // Gate funnel (distribution)
    const maxGate = Math.max(...Object.values(gTotals), 1);
    $('gate-funnel').innerHTML = gateNames.filter(e=>e[1]>0).map(([gn, gc]) =>
        `<div style="margin:4px 0;font-size:0.85em">${gn}: ${barHTML(gc,maxGate,'yellow',250)} <strong>${gc}</strong> (${(gc/totalGates*100).toFixed(0)}%)</div>`
    ).join('') || '<div style="color:#1a7f37;padding:10px">无拦截</div>';

    // Gate detail table
    let gHTML = '';
    for (const [gname, cnt] of gateNames) {
        if (cnt === 0) continue;
        const detail = gDetail[gname] || {};
        const pct = totalGates > 0 ? (cnt/totalGates*100).toFixed(0)+'%' : '-';
        gHTML += `<tr><td><strong>${gname}</strong></td><td>${barHTML(cnt,maxGate,'yellow',120)} ${cnt}</td><td>${pct}</td><td style="font-size:0.78em;color:#656d76">${topSymbols(detail,5)}</td></tr>`;
    }
    $('gate-body').innerHTML = gHTML || '<tr><td colspan="4" style="color:#1a7f37">无拦截</td></tr>';

    // Gate heatmap: gate × symbol
    const allGateSyms = new Set();
    for (const detail of Object.values(gDetail)) {
        for (const sym of Object.keys(detail || {})) allGateSyms.add(sym);
    }
    const gateSymList = [...allGateSyms].sort();
    const activeGates = gateNames.filter(e=>e[1]>0).map(e=>e[0]);
    if (activeGates.length && gateSymList.length) {
        let hmHTML = '<table><thead><tr><th>品种</th>';
        activeGates.forEach(g => hmHTML += `<th>${g}</th>`);
        hmHTML += '<th>合计</th></tr></thead><tbody>';
        // find max for color intensity
        const maxCell = Math.max(...gateSymList.map(sym => activeGates.reduce((s,g)=>s+(gDetail[g]||{})[sym]||0, 0)), 1);
        for (const sym of gateSymList) {
            let rowTotal = 0;
            hmHTML += `<tr><td><strong>${sym}</strong></td>`;
            for (const g of activeGates) {
                const v = (gDetail[g] || {})[sym] || 0;
                rowTotal += v;
                const bg = v > 0 ? `rgba(212,167,44,${v/maxCell*0.5+0.1})` : 'transparent';
                hmHTML += `<td style="text-align:center;background:${bg};font-weight:${v>0?'600':'400'}">${v||'-'}</td>`;
            }
            hmHTML += `<td style="font-weight:700">${rowTotal}</td></tr>`;
        }
        hmHTML += '</tbody></table>';
        $('gate-heatmap').innerHTML = hmHTML;
    } else {
        $('gate-heatmap').innerHTML = '<div style="color:#656d76;padding:10px">无拦截数据</div>';
    }

    // ── GCC任务 Tab ──
    let mhtml = '';
    if (m.vf_acc_avg !== undefined) mhtml += `<div class="metric"><div class="k">VF Accuracy</div><div class="v">${(m.vf_acc_avg*100).toFixed(1)}%</div></div>`;
    if (m.nc_scored !== undefined) mhtml += `<div class="metric"><div class="k">NC Scored</div><div class="v">${m.nc_scored}</div></div>`;
    if (m.nc_hit_rate !== undefined) mhtml += `<div class="metric"><div class="k">NC Hit Rate</div><div class="v">${m.nc_hit_rate}</div></div>`;
    if (m.macd_backfilled !== undefined) mhtml += `<div class="metric"><div class="k">MACD Backfilled</div><div class="v">${m.macd_backfilled}</div></div>`;
    if (m.knn_backfilled !== undefined) mhtml += `<div class="metric"><div class="k">KNN Backfilled</div><div class="v">${m.knn_backfilled}</div></div>`;
    if (m.card_total !== undefined) mhtml += `<div class="metric"><div class="k">Cards Distilled</div><div class="v">${m.card_validated}/${m.card_total}</div></div>`;
    $('metrics').innerHTML = mhtml;

    const tbody = $('task-body');
    tbody.innerHTML = '';
    for (const [tid, t] of Object.entries(DATA.tasks)) {
        const cls = {OK:'badge-ok',ERROR:'badge-error',SILENT:'badge-silent',LOW:'badge-low'}[t.status]||'badge-ok';
        tbody.innerHTML += `<tr>
            <td><strong>${tid}</strong></td>
            <td>${t.name}</td>
            <td>${t.count}</td>
            <td style="color:${t.errors>0?'#cf222e':'inherit'}">${t.errors}</td>
            <td style="color:#656d76">${t.expect}/4h</td>
            <td><span class="badge ${cls}">${t.status}</span></td>
        </tr>`;
    }

    // ── 问题&风险 Tab ──
    const issTimerange = $('issues-timerange');
    if (DATA.generated_at && DATA.hours) {
        issTimerange.textContent = `检测窗口: 过去 ${DATA.hours}h | 截至 ${DATA.generated_at}`;
    }
    // 系统亮点 (POSITIVE)
    const strengthsList = $('strengths-list');
    const positives = (DATA.issues || []).filter(i => i.type === 'POSITIVE');
    if (positives.length > 0) {
        let sHtml = '<div style="margin-bottom:12px"><div style="font-weight:600;color:#1a7f37;font-size:1.05em;margin-bottom:6px">✅ 系统亮点</div>';
        sHtml += positives.map(i =>
            `<div class="strength-item"><strong>${i.task}</strong>: ${i.msg}</div>`
        ).join('');
        sHtml += '</div>';
        strengthsList.innerHTML = sHtml;
    } else {
        strengthsList.innerHTML = '';
    }
    const issList = $('issues-list');
    const allNonPositive = (DATA.issues || []).filter(i => i.type !== 'POSITIVE');
    if (allNonPositive.length > 0) {
        const active = allNonPositive.filter(i => !i.acked && !i.fixed);
        const fixed = allNonPositive.filter(i => i.fixed);
        const acked = allNonPositive.filter(i => i.acked && !i.fixed);
        // 按category分组显示
        const catLabels = {
            execution: {name: '信号执行', icon: '⚡', desc: 'SignalStack/3Commas/P0发送'},
            data:      {name: '数据层',   icon: '📊', desc: '数据源/估值/过期'},
            market:    {name: '市场环境', icon: '📈', desc: '趋势/震荡/HOLD率'},
            signal:    {name: '信号质量', icon: '🎯', desc: '准确率/胜率/门控'},
            system:    {name: '系统',     icon: '⚙️', desc: 'GCC任务/覆盖率'},
        };
        const catOrder = ['execution', 'data', 'signal', 'market', 'system'];
        const grouped = {};
        active.forEach(i => {
            const cat = i.category || 'system';
            if (!grouped[cat]) grouped[cat] = [];
            grouped[cat].push(i);
        });
        let html = '';
        for (const cat of catOrder) {
            const items = grouped[cat];
            if (!items || !items.length) continue;
            const info = catLabels[cat] || {name: cat, icon: '?', desc: ''};
            html += `<div style="margin-top:12px;margin-bottom:4px;font-weight:600;color:#24292f;font-size:0.95em">${info.icon} ${info.name} <span style="font-weight:400;color:#656d76;font-size:0.85em">${info.desc}</span></div>`;
            html += items.map(i =>
                `<div class="issue-item"><span class="issue-tag ${i.type}">[${i.type}]</span><strong>${i.task}</strong>: ${i.msg}</div>`
            ).join('');
        }
        if (fixed.length > 0) {
            html += `<div class="ack-toggle" onclick="$('fixed-issues').style.display=$('fixed-issues').style.display==='none'?'block':'none'">` +
                `已修复 (${fixed.length}) ▸</div>`;
            html += `<div id="fixed-issues" style="display:none">` + fixed.map(i =>
                `<div class="issue-item issue-fixed"><span class="issue-tag" style="color:#1a7f37">[FIXED]</span><strong>${i.task}</strong>: ${i.msg}` +
                (i.fix_note ? ` <span class="fix-note">— ${i.fix_note}</span>` : '') + `</div>`
            ).join('') + `</div>`;
        }
        if (acked.length > 0) {
            html += `<div class="ack-toggle" onclick="$('acked-issues').style.display=$('acked-issues').style.display==='none'?'block':'none'">` +
                `已确认 (${acked.length}) ▸</div>`;
            html += `<div id="acked-issues" style="display:none">` + acked.map(i =>
                `<div class="issue-item issue-acked"><span class="issue-tag ${i.type}">[${i.type}]</span><strong>${i.task}</strong>: ${i.msg}` +
                (i.ack_reason ? ` <span class="ack-reason">— ${i.ack_reason}</span>` : '') + `</div>`
            ).join('') + `</div>`;
        }
        issList.innerHTML = html;
    } else {
        issList.innerHTML = '<div class="issue-item" style="color:#1a7f37">All systems OK - no issues detected</div>';
    }

    // ── 交易分析 Tab (统一用FIFO配对数据) ──
    const ta = DATA.fifo_trades || DATA.trade_analysis || {};
    const taOld = DATA.trade_analysis || {};
    const trCards = $('trade-cards');
    const _taTotal = ta.total || 0;
    const _taWR = ta.win_rate || 0;
    const _taLosers = _taTotal - (ta.winners||0);
    const wrColor = _taWR >= 0.5 ? 'green' : _taWR >= 0.35 ? 'yellow' : 'red';
    const pnlColor = (ta.total_pnl_pct||ta.total_pnl||0) >= 0 ? 'green' : 'red';
    trCards.innerHTML = `
        <div class="card"><div class="label">FIFO配对数</div><div class="value blue">${_taTotal}</div><div class="sub">${DATA.hours}h window</div></div>
        <div class="card"><div class="label">Win Rate</div><div class="value ${wrColor}">${(_taWR*100).toFixed(1)}%</div><div class="sub">${ta.winners||0}W / ${_taLosers}L</div></div>
        <div class="card"><div class="label">Avg PnL%</div><div class="value ${(ta.avg_pnl_pct||0)>=0?'green':'red'}">${(ta.avg_pnl_pct||0).toFixed(2)}%</div></div>
        <div class="card"><div class="label">总PnL%</div><div class="value ${pnlColor}">${(ta.total_pnl_pct||ta.total_pnl||0)>=0?'+':''}${(ta.total_pnl_pct||ta.total_pnl||0).toFixed(1)}%</div></div>
        ${taOld.avg_hold_min > 0 ? `<div class="card"><div class="label">平均持仓</div><div class="value blue">${taOld.avg_hold_min.toFixed(0)}</div><div class="sub">分钟</div></div>` : ''}`;

    // ── 全链路信号→盈亏分析 ──
    const pa = DATA.pipeline_analysis || [];
    const paEl = $('pipeline-analysis');
    if (pa.length > 0) {
        let paHTML = '<table><thead><tr><th>外挂</th><th>扫描</th><th>触发</th><th>发送</th><th>执行</th><th>拦截</th><th>执行率</th><th>成交</th><th>胜率</th><th>质量分</th><th>优化建议</th></tr></thead><tbody>';
        for (const p of pa) {
            const f = p.funnel || {};
            const r = p.rates || {};
            const t = p.trades || {};
            const recs = p.recommendations || [];
            const qs = p.quality_score;
            // 质量分颜色
            const qsColor = qs === null ? '#656d76' : qs >= 60 ? '#1a7f37' : qs >= 30 ? '#9a6700' : '#cf222e';
            const qsText = qs === null ? '-' : qs.toFixed(0);
            // 执行率
            const execRate = r.exec_rate !== null && r.exec_rate !== undefined ? (r.exec_rate*100).toFixed(0)+'%' : '-';
            const execColor = r.exec_rate !== null && r.exec_rate < 0.3 ? '#cf222e' : '';
            // 胜率
            const wrText = t.total > 0 ? (t.win_rate*100).toFixed(0)+'%' : '-';
            const wrColor = t.total >= 3 ? (t.win_rate >= 0.5 ? '#1a7f37' : t.win_rate >= 0.35 ? '#9a6700' : '#cf222e') : '#656d76';
            // 建议: 只取HIGH和MEDIUM
            const recStr = recs.filter(r=>r.priority!=='LOW').map(r => {
                const icon = r.priority==='HIGH'?'🔴':r.priority==='POSITIVE'?'🟢':'🟡';
                const color = r.priority==='POSITIVE'?'color:#1a7f37':'';
                return `<span style="${color}">${icon}<strong>${r.target}</strong>: ${r.action}</span>`;
            }).join('<br>') || '<span style="color:#656d76">数据不足</span>';
            // 拦截原因mini
            const br = p.block_reasons || {};
            const brStr = Object.entries(br).sort((a,b)=>b[1]-a[1]).slice(0,2).map(([k,v])=>`${k}:${v}`).join(' ');
            paHTML += `<tr>
                <td><strong>${p.plugin}</strong></td>
                <td>${f.scan||0}</td>
                <td>${f.trigger||0}</td>
                <td>${f.dispatch||0}</td>
                <td style="color:#1a7f37;font-weight:600">${f.executed||0}</td>
                <td style="color:#cf222e">${f.blocked||0}${brStr ? '<br><span style="font-size:0.7em;color:#656d76">'+brStr+'</span>' : ''}</td>
                <td style="color:${execColor};font-weight:600">${execRate}</td>
                <td>${t.total||0}</td>
                <td style="color:${wrColor};font-weight:600">${wrText}</td>
                <td style="color:${qsColor};font-weight:700;font-size:1.1em">${qsText}</td>
                <td style="font-size:0.78em;max-width:350px">${recStr}</td>
            </tr>`;
        }
        paHTML += '</tbody></table>';
        paEl.innerHTML = paHTML;
    } else {
        paEl.innerHTML = '<div style="color:#656d76;padding:10px">无外挂信号数据（需要scan engine日志）</div>';
    }

    // ── 已修复问题 (交易分析Tab内也展示) ──
    const fixedInTrade = (DATA.issues || []).filter(i => i.fixed);
    const fixedTradeEl = $('trade-fixed');
    if (fixedTradeEl) {
        if (fixedInTrade.length > 0) {
            fixedTradeEl.innerHTML = fixedInTrade.map(i =>
                `<div class="issue-item issue-fixed"><span class="issue-tag" style="color:#1a7f37">[FIXED]</span><strong>${i.task}</strong>: ${i.msg}` +
                (i.fix_note ? ` <span class="fix-note">— ${i.fix_note}</span>` : '') + `</div>`
            ).join('');
        } else {
            fixedTradeEl.innerHTML = '';
        }
    }

    const tbs = $('trade-by-symbol');
    const _taSym = ta.by_symbol || {};
    const syms = Object.entries(_taSym).sort((a,b)=>(b[1].trades||b[1].total||0)-(a[1].trades||a[1].total||0));
    tbs.innerHTML = syms.length ? syms.map(([s,d]) => {
        const cnt = d.trades || d.total || 0;
        const wins = d.wins || d.winners || 0;
        const wr = cnt > 0 ? (wins/cnt*100).toFixed(1) : '0.0';
        const wrv = cnt > 0 ? wins/cnt : 0;
        const wrc = wrv>=0.5?'#1a7f37':wrv>=0.35?'#9a6700':'#cf222e';
        const pnl = d.total_pnl || 0;
        return `<tr><td><strong>${s}</strong></td><td>${cnt}</td><td>${wins}</td><td style="color:${wrc};font-weight:600">${wr}%</td><td style="color:${pnl>=0?'#1a7f37':'#cf222e'}">${pnl>=0?'+':''}${pnl.toFixed(1)}%</td></tr>`;
    }).join('') : '<tr><td colspan="5" style="color:#656d76">No completed trades in window</td></tr>';

    const tbp = $('trade-by-plugin');
    const _taSrc = ta.by_source || ta.by_plugin || {};
    const plugs = Object.entries(_taSrc).sort((a,b)=>(b[1].trades||b[1].total||0)-(a[1].trades||a[1].total||0));
    tbp.innerHTML = plugs.length ? plugs.map(([p,d]) => {
        const cnt = d.trades || d.total || 0;
        const wins = d.wins || d.winners || 0;
        const wr = cnt > 0 ? (wins/cnt*100).toFixed(1) : '0.0';
        const wrv = cnt > 0 ? wins/cnt : 0;
        const wrc = wrv>=0.5?'#1a7f37':wrv>=0.35?'#9a6700':'#cf222e';
        return `<tr><td><strong>${p}</strong></td><td>${cnt}</td><td>${wins}</td><td style="color:${wrc};font-weight:600">${wr}%</td></tr>`;
    }).join('') : '<tr><td colspan="4" style="color:#656d76">No plugin attribution data</td></tr>';

    // ── GCC-0197 S6: 信号准确率 Tab ──
    const paAcc = DATA.plugin_accuracy || {};
    const pp = DATA.plugin_phases || {};
    const sigaccBody = $('sigacc-body');
    const sigaccSummary = $('sigacc-summary');
    if (sigaccBody) {
        const srcs = Object.keys(paAcc).sort();
        let totalDecisive = 0, totalCorrect = 0, downgraded = 0;
        const rows = srcs.map(src => {
            const syms = paAcc[src] || {};
            const ov = syms._overall || {};
            const phase = (pp[src] || {}).phase || 'NORMAL';
            const symItems = Object.keys(syms).filter(s => s !== '_overall').map(sym => syms[sym] || {});
            const agg = symItems.reduce((a, d) => {
                a.total += d.total || 0;
                a.correct += d.correct || 0;
                a.incorrect += d.incorrect || 0;
                a.neutral += d.neutral || 0;
                a.pending += d.pending || 0;
                return a;
            }, { total: 0, correct: 0, incorrect: 0, neutral: 0, pending: 0 });
            const srcTotal = ov.total ?? agg.total;
            const srcCorrect = ov.correct ?? agg.correct;
            const srcIncorrect = ov.incorrect ?? agg.incorrect;
            const srcNeutral = ov.neutral ?? agg.neutral;
            const srcPending = ov.pending ?? agg.pending;
            const srcAccRaw = ov.acc != null ? ov.acc : (srcTotal > 0 ? (srcCorrect / srcTotal) : null);
            const acc = srcAccRaw != null ? (srcAccRaw * 100).toFixed(0) + '%' : 'N/A';
            const accColor = srcAccRaw == null ? '#656d76' : (srcAccRaw >= 0.55 ? '#1a7f37' : srcAccRaw < 0.5 ? '#cf222e' : '#9a6700');
            const phaseColor = phase === 'DOWNGRADED' ? '#cf222e' : '#1a7f37';
            totalDecisive += (srcTotal || 0);
            totalCorrect += (srcCorrect || 0);
            if (phase === 'DOWNGRADED') downgraded++;
            // 按品种明细
            const symRows = Object.keys(syms).filter(s => s !== '_overall').map(sym => {
                const d = syms[sym] || {};
                return `<tr style="font-size:0.85em;color:#656d76"><td style="padding-left:24px">${sym}</td><td>${d.total||0}</td><td>${d.correct||0}</td><td>${d.incorrect||0}</td><td>${d.neutral||0}</td><td>${d.pending||0}</td><td>${d.acc!=null?(d.acc*100).toFixed(0)+'%':'—'}</td><td></td></tr>`;
            }).join('');
            return `<tr><td><strong>${src}</strong></td><td>${srcTotal||0}</td><td>${srcCorrect||0}</td><td>${srcIncorrect||0}</td><td>${srcNeutral||0}</td><td>${srcPending||0}</td><td style="color:${accColor};font-weight:600">${acc}</td><td style="color:${phaseColor}">${phase}</td></tr>${symRows}`;
        }).join('');
        sigaccBody.innerHTML = rows || '<tr><td colspan="8" style="color:#656d76">暂无信号数据 (需scan engine重启后积累)</td></tr>';
        const overallAcc = totalDecisive > 0 ? (totalCorrect / totalDecisive * 100).toFixed(0) : 'N/A';
        if (sigaccSummary) {
            sigaccSummary.innerHTML = `
                <div class="card"><div class="label">总样本</div><div class="value">${totalDecisive}</div></div>
                <div class="card"><div class="label">整体准确率</div><div class="value">${overallAcc}%</div></div>
                <div class="card"><div class="label">外挂数</div><div class="value">${srcs.length}</div></div>
                <div class="card"><div class="label" style="color:${downgraded>0?'#cf222e':'#1a7f37'}">降级中</div><div class="value">${downgraded}</div></div>`;
        }
    }

    // ── 券商对账 Tab ──
    const bm = DATA.broker_match || {};
    const bmCards = $('broker-cards');
    if (bm.enabled) {
        const execColor = bm.sys_exec_rate >= 0.9 ? 'green' : bm.sys_exec_rate >= 0.7 ? 'yellow' : 'red';
        const covColor = bm.signal_coverage >= 0.8 ? 'green' : bm.signal_coverage >= 0.6 ? 'yellow' : 'red';
        bmCards.innerHTML = `
            <div class="card"><div class="label">系统信号</div><div class="value blue">${bm.sys_signals||0}</div><div class="sub">股票信号数</div></div>
            <div class="card"><div class="label">实际交易</div><div class="value blue">${bm.actual_trades||0}</div><div class="sub">券商CSV</div></div>
            <div class="card"><div class="label">系统执行率</div><div class="value ${execColor}">${((bm.sys_exec_rate||0)*100).toFixed(0)}%</div><div class="sub">${bm.sys_executed||0}/${bm.sys_signals||0} 已执行</div></div>
            <div class="card"><div class="label">信号覆盖率</div><div class="value ${covColor}">${((bm.signal_coverage||0)*100).toFixed(0)}%</div><div class="sub">${(bm.actual_trades||0)-(bm.no_signal_count||0)}/${bm.actual_trades||0} 有信号</div></div>
            <div class="card"><div class="label">无信号交易</div><div class="value ${bm.no_signal_count>0?'red':'green'}">${bm.no_signal_count||0}</div><div class="sub">手动/参考模式</div></div>
        `;

        // 匹配明细表
        const bmMatches = $('broker-matches');
        const mList = bm.matches || [];
        bmMatches.innerHTML = mList.length ? mList.map(m => {
            const tag = !m.matched ? '<span style="color:#cf222e;font-weight:600">✗未执行</span>'
                : Math.abs(m.price_diff_pct) < 2 ? '<span style="color:#1a7f37;font-weight:600">✓匹配</span>'
                : '<span style="color:#9a6700;font-weight:600">≈近似</span>';
            const actColor = m.action === 'BUY' ? '#cf222e' : '#1a7f37';
            return `<tr>
                <td style="font-size:0.82em">${m.ts||''}</td>
                <td style="color:${actColor};font-weight:600">${m.action}</td>
                <td><strong>${m.symbol}</strong></td>
                <td>$${(m.sys_price||0).toFixed(2)}</td>
                <td>${m.source||''}</td>
                <td>${m.actual_price !== null ? '$'+m.actual_price.toFixed(2) : '-'}</td>
                <td>${m.price_diff_pct !== null ? (m.price_diff_pct>=0?'+':'')+m.price_diff_pct.toFixed(2)+'%' : '-'}</td>
                <td>${m.amount !== null ? '$'+(m.amount).toLocaleString() : '-'}</td>
                <td>${tag}</td>
            </tr>`;
        }).join('') : '<tr><td colspan="9" style="color:#656d76">无系统信号数据</td></tr>';

        // 无信号交易
        const bmNS = $('broker-nosignal');
        const nsList = bm.no_signal || [];
        bmNS.innerHTML = nsList.length ? nsList.map(n => {
            const actColor = n.action === 'BUY' ? '#cf222e' : '#1a7f37';
            return `<tr>
                <td>${n.date||''}</td>
                <td style="color:${actColor};font-weight:600">${n.action}</td>
                <td><strong>${n.symbol}</strong></td>
                <td>$${(n.price||0).toFixed(2)}</td>
                <td>${n.qty||0}</td>
                <td>$${(n.amount||0).toLocaleString()}</td>
            </tr>`;
        }).join('') : '<tr><td colspan="6" style="color:#1a7f37">所有交易均有系统信号支撑</td></tr>';

        // 信号来源分布
        const bmSrc = $('broker-sources');
        const srcEntries = Object.entries(bm.by_source || {}).sort((a,b) => b[1]-a[1]);
        const srcTotal = srcEntries.reduce((s,e) => s+e[1], 0);
        bmSrc.innerHTML = srcEntries.length ? srcEntries.map(([src, cnt]) =>
            `<tr><td><strong>${src}</strong></td><td>${cnt}</td><td>${(cnt/srcTotal*100).toFixed(0)}%</td></tr>`
        ).join('') : '<tr><td colspan="3" style="color:#656d76">-</td></tr>';
    } else {
        bmCards.innerHTML = '<div class="card" style="grid-column:1/-1"><div class="label">券商对账</div><div class="sub">未找到 .GCC/doc/XXXX-X306.CSV</div></div>';
        $('broker-matches').innerHTML = '';
        $('broker-nosignal').innerHTML = '';
        $('broker-sources').innerHTML = '';
    }

    // ── 策略排行 Tab ──
    const ft = DATA.fifo_trades || {};
    const sr = DATA.strategy_ranking || [];
    const ftWR = ft.total > 0 ? ((ft.win_rate||0)*100).toFixed(1) : '-';
    const ftColor = (ft.win_rate||0) >= 0.5 ? 'green' : (ft.win_rate||0) >= 0.35 ? 'yellow' : 'red';
    const ftPnlColor = (ft.total_pnl_pct||0) >= 0 ? 'green' : 'red';
    $('ranking-summary').innerHTML = `
        <div class="card"><div class="label">FIFO配对数</div><div class="value blue">${ft.total||0}</div><div class="sub">${DATA.hours}h window</div></div>
        <div class="card"><div class="label">胜率</div><div class="value ${ftColor}">${ftWR}%</div><div class="sub">${ft.winners||0}W / ${(ft.total||0)-(ft.winners||0)}L</div></div>
        <div class="card"><div class="label">平均PnL%</div><div class="value ${(ft.avg_pnl_pct||0)>=0?'green':'red'}">${(ft.avg_pnl_pct||0).toFixed(2)}%</div></div>
        <div class="card"><div class="label">总PnL%</div><div class="value ${ftPnlColor}">${(ft.total_pnl_pct||0).toFixed(1)}%</div></div>
    `;
    // Ranking table
    const rankBody = $('ranking-body');
    if (sr.length > 0) {
        rankBody.innerHTML = sr.map(r => {
            const wrPct = (r.win_rate*100).toFixed(1);
            const wrC = r.win_rate>=0.5?'#1a7f37':r.win_rate>=0.35?'#9a6700':'#cf222e';
            const scoreC = r.score>70?'#1a7f37':r.score>=50?'#9a6700':'#cf222e';
            const actionBg = r.action==='加强'?'#dafbe1':r.action==='维持'?'#fff8c5':r.action==='降低频次'?'#ffebe9':'#ddf4ff';
            const actionColor = r.action==='加强'?'#1a7f37':r.action==='维持'?'#9a6700':r.action==='降低频次'?'#cf222e':'#0969da';
            return `<tr>
                <td style="font-weight:700;text-align:center">${r.rank}</td>
                <td><strong>${r.source}</strong></td>
                <td>${r.trades}</td>
                <td style="color:${wrC};font-weight:600">${wrPct}%</td>
                <td style="color:${r.avg_pnl>=0?'#1a7f37':'#cf222e'}">${r.avg_pnl>=0?'+':''}${r.avg_pnl.toFixed(2)}%</td>
                <td style="color:${r.total_pnl>=0?'#1a7f37':'#cf222e'}">${r.total_pnl>=0?'+':''}${r.total_pnl.toFixed(1)}%</td>
                <td style="color:${scoreC};font-weight:700;font-size:1.1em">${r.score}</td>
                <td><span class="badge" style="background:${actionBg};color:${actionColor}">${r.action}</span></td>
            </tr>`;
        }).join('');
    } else {
        rankBody.innerHTML = '<tr><td colspan="8" style="color:#656d76">无FIFO配对数据(需trade_history有source字段)</td></tr>';
    }
    // 优点/缺点发现 (从ranking + cross data)
    if (sr.length > 0) {
        const crossD = ft.by_source_symbol || {};
        const bvBlock = (DATA.block_validation || {}).by_source || {};
        let insightHTML = '<h2>优点 & 问题发现</h2><div style="display:flex;gap:8px;flex-wrap:wrap;margin-bottom:16px">';
        for (const r of sr) {
            const srcCross = crossD[r.source] || {};
            // 找best品种(pnl最高)
            const bestSym = Object.entries(srcCross).sort((a,b)=>(b[1].pnl||0)-(a[1].pnl||0))[0];
            const worstSym = Object.entries(srcCross).sort((a,b)=>(a[1].pnl||0)-(b[1].pnl||0))[0];
            const blockInfo = bvBlock[r.source];
            let tips = [];
            if (bestSym && bestSym[1].pnl > 0) tips.push(`<span style="color:#1a7f37">✓ ${bestSym[0]}盈利${bestSym[1].pnl.toFixed(1)}%(${bestSym[1].trades}笔)</span>`);
            if (worstSym && worstSym[1].pnl < -5) tips.push(`<span style="color:#cf222e">✗ ${worstSym[0]}亏损${worstSym[1].pnl.toFixed(1)}%(${worstSym[1].trades}笔)</span>`);
            if (blockInfo && blockInfo.total >= 3) tips.push(`<span style="color:${blockInfo.accuracy>=0.6?'#1a7f37':'#cf222e'}">拦截正确率${(blockInfo.accuracy*100).toFixed(0)}%(${blockInfo.total}次)</span>`);
            if (r.trades < 5) tips.push(`<span style="color:#656d76">样本不足(${r.trades}笔)</span>`);
            if (tips.length) {
                insightHTML += `<div style="background:#fff;border:1px solid #d0d7de;border-radius:8px;padding:10px 14px;min-width:220px;flex:1">
                    <div style="font-weight:700;margin-bottom:4px">${r.source} <span class="badge" style="background:${r.action==='加强'?'#dafbe1':r.action==='维持'?'#fff8c5':r.action==='降低频次'?'#ffebe9':'#ddf4ff'};color:${r.action==='加强'?'#1a7f37':r.action==='维持'?'#9a6700':r.action==='降低频次'?'#cf222e':'#0969da'}">${r.action}</span></div>
                    <div style="font-size:0.82em;line-height:1.6">${tips.join('<br>')}</div>
                </div>`;
            }
        }
        insightHTML += '</div>';
        $('ranking-heatmap').insertAdjacentHTML('beforebegin', insightHTML);
    }
    // Heatmap: source × symbol
    const crossData = ft.by_source_symbol || {};
    const hmSources = Object.keys(crossData).sort();
    const hmSymbols = [...new Set(hmSources.flatMap(s => Object.keys(crossData[s] || {})))].sort();
    if (hmSources.length && hmSymbols.length) {
        let hmHTML = '<table><thead><tr><th>品种\\策略</th>';
        hmSources.forEach(s => hmHTML += `<th>${s}</th>`);
        hmHTML += '</tr></thead><tbody>';
        const allPnl = hmSources.flatMap(s => Object.values(crossData[s]||{}).map(d=>Math.abs(d.pnl||0)));
        const maxPnl = Math.max(...allPnl, 1);
        for (const sym of hmSymbols) {
            hmHTML += `<tr><td><strong>${sym}</strong></td>`;
            for (const src of hmSources) {
                const cell = (crossData[src]||{})[sym];
                if (!cell || !cell.trades) {
                    hmHTML += '<td style="text-align:center;color:#afb8c1">-</td>';
                } else {
                    const intensity = Math.min(Math.abs(cell.pnl)/maxPnl*0.6+0.1, 0.7);
                    const bg = cell.pnl >= 0 ? `rgba(26,127,55,${intensity})` : `rgba(207,34,46,${intensity})`;
                    const txt = cell.pnl >= 0 ? '#1a7f37' : '#cf222e';
                    hmHTML += `<td style="text-align:center;background:${bg};color:${txt};font-weight:600" title="${cell.trades}笔 ${cell.wins}W">${cell.pnl>=0?'+':''}${cell.pnl.toFixed(1)}%</td>`;
                }
            }
            hmHTML += '</tr>';
        }
        hmHTML += '</tbody></table>';
        $('ranking-heatmap').innerHTML = hmHTML;
    } else {
        $('ranking-heatmap').innerHTML = '<div style="color:#656d76;padding:10px">无交叉数据</div>';
    }
    // ── 结构化规则表 ──
    const rulesBody = $('rules-body');
    const rules = DATA.extracted_rules || [];
    if (rulesBody) {
        if (rules.length > 0) {
            const actionColors = {RELAX:'#1a7f37',OBSERVE:'#0969da',TIGHTEN:'#cf222e',REVIEW:'#9a6700',DISABLE:'#cf222e'};
            const statusColors = {DISCOVERED:'#ddf4ff;color:#0969da',ACTIVE:'#dafbe1;color:#1a7f37',DEPRECATED:'#ffebe9;color:#cf222e'};
            rulesBody.innerHTML = rules.map((r,idx) => {
                const ac = actionColors[r.action] || '#656d76';
                const sc = statusColors[r.status] || statusColors.DISCOVERED;
                const canActivate = r.status === 'DISCOVERED';
                const canDeprecate = r.status === 'ACTIVE';
                let btns = '';
                if (canActivate) btns += `<button onclick="ruleTransition(${idx},'ACTIVE')" style="background:#1a7f37;color:#fff;border:none;padding:2px 8px;border-radius:3px;cursor:pointer;font-size:0.8em">激活</button>`;
                if (canDeprecate) btns += `<button onclick="ruleTransition(${idx},'DEPRECATED')" style="background:#cf222e;color:#fff;border:none;padding:2px 8px;border-radius:3px;cursor:pointer;font-size:0.8em">停用</button>`;
                if (r.status === 'DEPRECATED') btns = '<span style="color:#656d76;font-size:0.8em">已停用</span>';
                return `<tr>
                    <td style="font-family:monospace;font-size:0.85em">${r.rule_id}</td>
                    <td>${r.trigger_condition}</td>
                    <td style="color:${ac};font-weight:700">${r.action}</td>
                    <td>${(r.confidence*100).toFixed(0)}%</td>
                    <td>${r.sample_count}</td>
                    <td><span class="badge" style="background:${sc}">${r.status}</span></td>
                    <td>${btns}</td>
                </tr>`;
            }).join('');
        } else {
            rulesBody.innerHTML = '<tr><td colspan="7" style="color:#656d76">无规则(需1w范围数据)</td></tr>';
        }
    }

    // ── 拦截验证 Tab ──
    const bv2 = DATA.block_validation || {};
    const bvDecisive = (bv2.correct||0) + (bv2.incorrect||0);
    const bvAccPct = bvDecisive > 0 ? ((bv2.correct||0)/bvDecisive*100).toFixed(1) : '-';
    const bvAccColor = bvDecisive > 0 ? ((bv2.correct||0)/bvDecisive >= 0.6 ? 'green' : (bv2.correct||0)/bvDecisive >= 0.45 ? 'yellow' : 'red') : 'blue';
    const bvCovPct = bv2.total_blocked > 0 ? ((bv2.validated||0)/bv2.total_blocked*100).toFixed(1) : '0';
    $('blockval-summary').innerHTML = `
        <div class="card"><div class="label">总拦截</div><div class="value blue">${bv2.total_blocked||0}</div><div class="sub">${DATA.hours}h window</div></div>
        <div class="card"><div class="label">已验证</div><div class="value blue">${bv2.validated||0}</div><div class="sub">覆盖率 ${bvCovPct}%</div></div>
        <div class="card"><div class="label">拦截正确</div><div class="value green">${bv2.correct||0}</div></div>
        <div class="card"><div class="label">拦截错误</div><div class="value red">${bv2.incorrect||0}</div></div>
        <div class="card"><div class="label">正确率</div><div class="value ${bvAccColor}">${bvAccPct}%</div><div class="sub">${bvDecisive} decisive</div></div>
    `;
    // 验证覆盖率说明
    if (bv2.total_blocked > 0 && bv2.validated < bv2.total_blocked * 0.1) {
        $('blockval-summary').innerHTML += `
        <div style="background:#fff8c5;border:1px solid #d4a72c;border-radius:8px;padding:8px 14px;font-size:0.82em;color:#9a6700;width:100%;margin-top:4px">
            验证覆盖率较低(${bvCovPct}%): 拦截验证需要同品种4H内有后续交易记录作为价格参照。被拦截但之后没有交易的信号无法验证。随交易量增加覆盖率会提升。
        </div>`;
    }
    // By reason
    const brReason = bv2.by_reason || {};
    const brReasonEntries = Object.entries(brReason).sort((a,b)=>(b[1].total||0)-(a[1].total||0));
    const brReasonBody = $('blockval-reason-body');
    if (brReasonEntries.length) {
        brReasonBody.innerHTML = brReasonEntries.map(([reason, d]) => {
            const acc = (d.accuracy*100).toFixed(1);
            const accC = d.accuracy>=0.6?'#1a7f37':d.accuracy>=0.45?'#9a6700':'#cf222e';
            return `<tr><td><strong>${reason}</strong></td><td>${d.total}</td><td style="color:#1a7f37">${d.correct}</td><td style="color:${accC};font-weight:600">${acc}%</td></tr>`;
        }).join('');
    } else {
        brReasonBody.innerHTML = '<tr><td colspan="4" style="color:#656d76">无已验证拦截</td></tr>';
    }
    // By source
    const brSource = bv2.by_source || {};
    const brSourceEntries = Object.entries(brSource).sort((a,b)=>(b[1].total||0)-(a[1].total||0));
    const brSourceBody = $('blockval-source-body');
    if (brSourceEntries.length) {
        brSourceBody.innerHTML = brSourceEntries.map(([src, d]) => {
            const acc = (d.accuracy*100).toFixed(1);
            const accC = d.accuracy>=0.6?'#1a7f37':d.accuracy>=0.45?'#9a6700':'#cf222e';
            return `<tr><td><strong>${src}</strong></td><td>${d.total}</td><td style="color:#1a7f37">${d.correct}</td><td style="color:${accC};font-weight:600">${acc}%</td></tr>`;
        }).join('');
    } else {
        brSourceBody.innerHTML = '<tr><td colspan="4" style="color:#656d76">无已验证拦截</td></tr>';
    }
}

loadData();
setInterval(loadData, 300000);
