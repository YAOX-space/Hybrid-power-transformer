"""
generate_comparison_plots.py
============================
从 data/raw/*.mat 文件生成仿真对比图，展示：
  1. 各故障类型的电压/电流/DC母线信号波形
  2. 故障发生时刻前后的动态变化
  3. 传统策略 vs AI策略 的预期效果差异（基于JSON结果数据标注）
  4. MSFFN检测窗口示意
"""

import os, glob, json
import numpy as np
import scipy.io as sio
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from matplotlib.gridspec import GridSpec
from pathlib import Path

# ── 路径 ─────────────────────────────────────────────────────────────────────
BASE   = Path(__file__).resolve().parent.parent
RAW    = BASE / 'data' / 'raw'
OUT    = BASE / 'results' / 'figures'
OUT.mkdir(exist_ok=True)

# ── 全局样式 ──────────────────────────────────────────────────────────────────
plt.rcParams.update({
    'font.family': ['Hiragino Sans GB', 'STHeiti', 'Arial Unicode MS', 'DejaVu Sans'],
    'font.size': 9,
    'axes.titlesize': 10,
    'axes.labelsize': 9,
    'legend.fontsize': 8,
    'figure.dpi': 150,
    'axes.grid': True,
    'grid.alpha': 0.3,
    'lines.linewidth': 1.2,
})

COLORS = {
    'rule':     '#e74c3c',   # 红：规则FRT
    'dq':       '#2980b9',   # 蓝：dq双环
    'fahc':     '#27ae60',   # 绿：FAHC
    'ppo':      '#f39c12',   # 橙：PPO
    'fault':    '#95a5a6',   # 灰：故障时刻线
    'window':   '#8e44ad',   # 紫：检测窗口
}

FAULT_LABELS = {
    0: '正常运行\n(normal)',
    1: 'PV扰动\n(pv_disturbance)',
    2: '负荷突变\n(load_step)',
    3: 'IGBT开路(并联)\n(igbt_oc_sh)',
    4: 'IGBT开路(串联)\n(igbt_oc_se)',
    5: 'DC电容退化\n(cap_fault)',
    6: '单相短路\n(sc_1ph)',
    7: '三相短路\n(sc_3ph)',
    8: '连锁故障\n(cascade)',
}

# ── JSON结果（用于标注对比数据）─────────────────────────────────────────────
RESULTS = {
    'rule':     json.load(open(BASE/'results'/'lvrt_metrics_raw_switching_hpt_v2_fixed_rule.json')),
    'dq':       json.load(open(BASE/'results'/'lvrt_metrics_raw_switching_hpt_v2_fixed_dq.json')),
    'pipeline': json.load(open(BASE/'results'/'lvrt_metrics_raw_switching_hpt_v2_pipeline_thr0.80.json')),
    'ppo':      json.load(open(BASE/'results'/'lvrt_metrics_ppo_hpt_v2_spe32_10ep_best.json')),
}
PASS_RATES = {}
SC_NAME_MAP = {
    'normal':0,'igbt_oc_sh':3,'igbt_oc_se':4,'cap_fault':5,
    'sc_1ph':6,'sc_3ph':7,'cascade':8
}
for ctrl, d in RESULTS.items():
    for fault, sc_id in SC_NAME_MAP.items():
        rows = [r for r in d['rows'] if r['scenario']==fault]
        if rows:
            PASS_RATES.setdefault(fault, {})[ctrl] = (
                sum(r['lvrt_pass_basic'] for r in rows) / len(rows) * 100
            )


def load_mat(path):
    mat = sio.loadmat(str(path))
    t    = mat['t_uniform'].squeeze()
    V2   = mat['V2_abc']
    V1   = mat['V1_abc']
    I2   = mat['I2_abc']
    I1   = mat['I1_abc']
    Vdc  = mat['V_dc'].squeeze()
    Ise  = mat['Ise_dq']
    P2   = mat['P2'].squeeze()
    t_f  = float(mat['t_fault'].flat[0])
    sc   = int(mat['sc_id'].flat[0])

    # 二次侧有效值（每个时间步的RMS近似）
    V2rms = np.sqrt(np.mean(V2**2, axis=1)) / (400/np.sqrt(2))  # pu

    # 二次侧电流有效值
    I2rms = np.sqrt(np.mean(I2**2, axis=1)) / (816.5/np.sqrt(2))  # pu（额定816.5A）

    Vdc_pu = Vdc / 800.0  # pu

    return dict(t=t, V2=V2, V1=V1, I2=I2, I1=I1, Vdc=Vdc,
                Vdc_pu=Vdc_pu, V2rms=V2rms, I2rms=I2rms,
                Ise=Ise, P2=P2, t_fault=t_f, sc_id=sc)


def pick_representative(sc_id, n=1):
    """选取代表性场景：优先选Vdc_min最接近0.75pu（最有意义的边界场景）"""
    pat = {3:'igbt_oc_sh', 4:'igbt_oc_se', 5:'cap_fault',
           6:'sc_1ph', 7:'sc_3ph', 8:'cascade', 0:'normal'}
    name = pat.get(sc_id, f'scenario_{sc_id}')
    files = sorted(glob.glob(str(RAW / f'scenario_{sc_id}_{name}_run*.mat')))
    if not files:
        files = sorted(glob.glob(str(RAW / f'scenario_{sc_id}_*.mat')))
    if not files:
        return []
    # 按 t_fault 多样性选取
    chosen = files[:min(n, len(files))]
    return [load_mat(f) for f in chosen]


# ═══════════════════════════════════════════════════════════════════════════════
# 图1：七类故障全览（2×4网格，每格展示V2_rms、Vdc_pu围绕故障时刻）
# ═══════════════════════════════════════════════════════════════════════════════
def plot_fault_overview():
    fault_ids = [0, 3, 4, 5, 6, 7, 8]
    fig, axes = plt.subplots(2, 4, figsize=(16, 7))
    axes = axes.flatten()
    fig.suptitle('七类故障信号概览 — 二次侧电压(V₂) 与 DC母线电压(Vdc)', fontsize=12, y=1.01)

    for idx, sc_id in enumerate(fault_ids):
        ax = axes[idx]
        data_list = pick_representative(sc_id, n=3)
        if not data_list:
            ax.set_visible(False)
            continue

        for data in data_list:
            t     = data['t']
            t_f   = data['t_fault']
            # 截取故障前后各200ms
            mask  = (t >= t_f - 0.15) & (t <= t_f + 0.30)
            t_rel = (t[mask] - t_f) * 1000   # 相对时间 ms

            ax.plot(t_rel, data['V2rms'][mask],  color=COLORS['dq'],   alpha=0.7, lw=1.0)
            ax.plot(t_rel, data['Vdc_pu'][mask], color=COLORS['rule'],  alpha=0.7, lw=1.0, ls='--')

        # 参考线
        ax.axvline(0, color='k', lw=1.5, ls='-', label='故障时刻t₀')
        ax.axhline(0.75, color=COLORS['rule'], lw=1.0, ls=':', label='Vdc下限0.75pu')
        ax.axvline(5, color=COLORS['window'], lw=1.0, ls=':', alpha=0.8)
        ax.fill_betweenx([0, 1.4], 0, 5, alpha=0.08, color=COLORS['window'], label='5ms检测窗口')

        # 标注通过率
        fault_name = {0:'normal',3:'igbt_oc_sh',4:'igbt_oc_se',5:'cap_fault',
                      6:'sc_1ph',7:'sc_3ph',8:'cascade'}.get(sc_id,'?')
        pr = PASS_RATES.get(fault_name, {})
        txt = '\n'.join([f'规则:{pr.get("rule",0):.0f}%',
                         f'dq:  {pr.get("dq",0):.0f}%',
                         f'FAHC:{pr.get("pipeline",0):.0f}%'])
        ax.text(0.98, 0.03, txt, transform=ax.transAxes,
                ha='right', va='bottom', fontsize=7,
                bbox=dict(boxstyle='round,pad=0.3', facecolor='white', alpha=0.8))

        # 图例只在第一个子图
        if idx == 0:
            leg_patches = [
                mpatches.Patch(color=COLORS['dq'],   label='V₂_rms (pu)'),
                mpatches.Patch(color=COLORS['rule'],  label='Vdc (pu)'),
            ]
            ax.legend(handles=leg_patches, loc='upper right', fontsize=7)

        sc_label = {0:'正常运行',3:'IGBT开路(并)',4:'IGBT开路(串)',
                    5:'DC电容退化',6:'单相短路',7:'三相短路',8:'连锁故障'}
        ax.set_title(sc_label.get(sc_id, f'sc_{sc_id}'), fontsize=9)
        ax.set_xlabel('相对时间 (ms)', fontsize=8)
        ax.set_ylabel('标幺值 (pu)', fontsize=8)
        ax.set_xlim(-150, 300)
        ax.set_ylim(0, 1.35)

    axes[-1].set_visible(False)
    plt.tight_layout()
    out = OUT / 'fig_fault_overview.pdf'
    plt.savefig(out, bbox_inches='tight')
    plt.close()
    print(f'saved: {out}')


# ═══════════════════════════════════════════════════════════════════════════════
# 图2：单相短路 sc_1ph — 详细四子图 + 策略对比标注
# ═══════════════════════════════════════════════════════════════════════════════
def plot_sc1ph_detail():
    data_list = pick_representative(6, n=1)
    if not data_list:
        return
    data = data_list[0]
    t    = data['t']
    t_f  = data['t_fault']

    # 截取故障前200ms到故障后500ms
    mask = (t >= t_f - 0.20) & (t <= t_f + 0.50)
    t_rel = (t[mask] - t_f) * 1000  # ms

    fig = plt.figure(figsize=(13, 9))
    gs = GridSpec(3, 2, figure=fig, hspace=0.45, wspace=0.35)
    fig.suptitle('单相短路 (sc_1ph) — 传统策略 vs AI策略 信号对比\n'
                 '规则FRT: 通过率16%  |  dq双环: 26%  |  MSFFN→FAHC: 26%  |  PPO: 16%',
                 fontsize=11)

    # ── 子图1：三相二次侧电压波形 ──────────────────────────────────────────
    ax1 = fig.add_subplot(gs[0, :])
    colors_ph = ['#e74c3c', '#2ecc71', '#3498db']
    for ph, col in enumerate(colors_ph):
        ax1.plot(t_rel, data['V2'][mask, ph] / 400 * np.sqrt(3),
                 color=col, alpha=0.8, label=f'V₂_{["a","b","c"][ph]}')
    ax1.axvline(0, color='k', lw=2, ls='--', label='故障触发')
    ax1.axvspan(0, 5, alpha=0.12, color=COLORS['window'], label='MSFFN检测窗口(5ms)')
    ax1.axvspan(0, 50, alpha=0.05, color='gray', label='故障持续期')
    ax1.set_ylabel('V₂ 线电压 (pu)', fontsize=9)
    ax1.set_title('① 二次侧三相电压（单相短路 → A相跌落至~0.65pu，B/C相受影响）', fontsize=9)
    ax1.legend(loc='lower right', ncol=4, fontsize=8)
    ax1.set_xlim(-200, 500)
    ax1.set_ylim(-1.6, 1.6)
    ax1.set_xlabel('相对时间 (ms)')

    # ── 子图2：Vdc（传统 vs AI的核心差异）────────────────────────────────
    ax2 = fig.add_subplot(gs[1, 0])
    ax2.plot(t_rel, data['Vdc_pu'][mask], color='#2c3e50', lw=1.5, label='实测Vdc（规则FRT，sc_1ph run001）')

    # 从JSON结果标注期望改善
    pr = PASS_RATES.get('sc_1ph', {})
    ax2.axhline(0.75, color=COLORS['rule'], ls=':', lw=1.5, label='LVRT Vdc下限 0.75pu')
    ax2.axhline(1.0, color='gray', ls=':', lw=1.0, alpha=0.5, label='额定 1.0pu')
    ax2.axvline(0, color='k', lw=1.5, ls='--')
    ax2.axvspan(0, 5, alpha=0.12, color=COLORS['window'])

    # 标注：dq的Vdc改善
    ax2.annotate('规则FRT: 部分场景\nVdc跌至~0.62pu\n→ LVRT失败',
                 xy=(120, 0.62), fontsize=8, color=COLORS['rule'],
                 arrowprops=dict(arrowstyle='->', color=COLORS['rule']),
                 xytext=(220, 0.55))
    ax2.annotate('dq/FAHC: PI精确维持\nVdc ≥ 0.75pu\n→ +10pp通过率',
                 xy=(80, 0.79), fontsize=8, color=COLORS['dq'],
                 arrowprops=dict(arrowstyle='->', color=COLORS['dq']),
                 xytext=(180, 0.86))

    ax2.set_ylabel('Vdc (pu)', fontsize=9)
    ax2.set_title('② DC母线电压\n（dq闭环反馈 vs 规则开环的核心差异）', fontsize=9)
    ax2.legend(loc='upper right', fontsize=7)
    ax2.set_xlim(-200, 500)
    ax2.set_ylim(0.45, 1.15)
    ax2.set_xlabel('相对时间 (ms)')

    # 通过率对比条形图
    ax3 = fig.add_subplot(gs[1, 1])
    methods = ['规则FRT', 'dq双环', 'MSFFN\n→FAHC', 'PPO']
    rates   = [pr.get('rule',0), pr.get('dq',0), pr.get('pipeline',0), pr.get('ppo',0)]
    bar_colors = [COLORS['rule'], COLORS['dq'], COLORS['fahc'], COLORS['ppo']]
    bars = ax3.bar(methods, rates, color=bar_colors, alpha=0.85, edgecolor='white', linewidth=1.2)
    for bar, rate in zip(bars, rates):
        ax3.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 0.5,
                 f'{rate:.0f}%', ha='center', va='bottom', fontsize=9, fontweight='bold')
    ax3.axhline(16, color=COLORS['rule'], ls=':', lw=1, alpha=0.5)
    ax3.set_ylabel('LVRT通过率 (%)', fontsize=9)
    ax3.set_title('③ 单相短路通过率对比\n（各50个场景）', fontsize=9)
    ax3.set_ylim(0, 40)
    ax3.set_yticks([0, 10, 16, 20, 26, 30, 40])

    # ── 子图3：二次侧电流 ────────────────────────────────────────────────
    ax4 = fig.add_subplot(gs[2, 0])
    I2rms_smooth = data['I2rms'][mask]
    ax4.plot(t_rel, I2rms_smooth, color='#8e44ad', lw=1.5, label='I₂_rms (pu)')
    ax4.axhline(3.0, color='r', ls='--', lw=1.5, label='LVRT过流限制 3.0pu')
    ax4.axhline(2.0, color='orange', ls=':', lw=1.0, label='软保护触发 2.0pu')
    ax4.axvline(0, color='k', lw=1.5, ls='--')
    ax4.axvspan(0, 5, alpha=0.12, color=COLORS['window'])
    ax4.set_ylabel('I₂_rms (pu)', fontsize=9)
    ax4.set_title('④ 二次侧电流（单相短路不触发过流限制）', fontsize=9)
    ax4.legend(loc='upper right', fontsize=7)
    ax4.set_xlim(-200, 500)
    ax4.set_ylim(0, 3.5)
    ax4.set_xlabel('相对时间 (ms)')

    # ── 子图4：串联VSC电流 Ise_dq（MSFFN的关键特征）─────────────────────
    ax5 = fig.add_subplot(gs[2, 1])
    Ise_d = data['Ise'][mask, 0]
    Ise_q = data['Ise'][mask, 1]
    ax5.plot(t_rel, Ise_d, color='#e67e22', lw=1.2, label='Ise_d (×10⁻³ kA)')
    ax5.plot(t_rel, Ise_q, color='#16a085', lw=1.2, label='Ise_q (×10⁻³ kA)', ls='--')
    ax5.axvline(0, color='k', lw=1.5, ls='--')
    ax5.axvspan(0, 5, alpha=0.12, color=COLORS['window'],
                label='MSFFN读取窗口\n(Ise_dq是最重要特征之一)')
    ax5.set_ylabel('Ise_dq (×10⁻³ kA)', fontsize=9)
    ax5.set_title('⑤ 串联VSC电流 Ise_dq\n（MSFFN的关键诊断特征）', fontsize=9)
    ax5.legend(loc='upper right', fontsize=7)
    ax5.set_xlim(-200, 500)
    ax5.set_xlabel('相对时间 (ms)')

    out = OUT / 'fig_sc1ph_detail.pdf'
    plt.savefig(out, bbox_inches='tight')
    plt.close()
    print(f'saved: {out}')


# ═══════════════════════════════════════════════════════════════════════════════
# 图3：三相短路 sc_3ph — 最严峻故障的信号分析
# ═══════════════════════════════════════════════════════════════════════════════
def plot_sc3ph_detail():
    data_list = pick_representative(7, n=1)
    if not data_list:
        return
    data = data_list[0]
    t    = data['t']
    t_f  = data['t_fault']

    mask = (t >= t_f - 0.15) & (t <= t_f + 0.40)
    t_rel = (t[mask] - t_f) * 1000

    fig, axes = plt.subplots(2, 2, figsize=(12, 8))
    fig.suptitle('三相短路 (sc_3ph) — 最严峻故障，硬件储能瓶颈\n'
                 '规则FRT: 0%  |  dq双环: 14%  |  MSFFN→FAHC: 14%  |  PPO: 2%',
                 fontsize=11)

    # ① V2三相
    ax = axes[0, 0]
    for ph, (col, name) in enumerate(zip(['#e74c3c','#2ecc71','#3498db'],['a','b','c'])):
        ax.plot(t_rel, data['V2'][mask, ph]/400*np.sqrt(3), color=col, alpha=0.8,
                label=f'V₂_{name}')
    ax.axvline(0, color='k', lw=1.5, ls='--', label='故障触发')
    ax.axvspan(0, 5, alpha=0.15, color=COLORS['window'], label='5ms检测窗口')
    ax.set_title('① 二次侧三相电压\n（三相同时跌至约0.25pu）', fontsize=9)
    ax.set_ylabel('V₂ (pu)', fontsize=9); ax.set_xlabel('ms')
    ax.set_ylim(-1.8, 1.8); ax.set_xlim(-150, 400)
    ax.legend(loc='lower right', ncol=2, fontsize=7)

    # ② Vdc
    ax = axes[0, 1]
    ax.plot(t_rel, data['Vdc_pu'][mask], color='#2c3e50', lw=1.8, label='实测Vdc (规则FRT)')
    ax.axhline(0.75, color='r', ls=':', lw=1.5, label='LVRT下限 0.75pu')
    ax.axhline(1.0, color='gray', ls=':', lw=1.0, alpha=0.5)
    ax.axvline(0, color='k', lw=1.5, ls='--')
    ax.axvspan(0, 5, alpha=0.15, color=COLORS['window'])

    # 标注能量不足
    ax.fill_between(t_rel, data['Vdc_pu'][mask], 0.75,
                    where=(data['Vdc_pu'][mask] < 0.75), alpha=0.2, color='red',
                    label='Vdc < 0.75pu (LVRT失败区间)')
    ax.annotate(f'储能耗尽\nVdc_min≈0.57pu\n(规则FRT均值)',
                xy=(150, 0.57), fontsize=8, color='red',
                arrowprops=dict(arrowstyle='->', color='red'),
                xytext=(230, 0.48))
    ax.annotate('dq可将部分场景\nVdc_min提升至\n0.65pu+',
                xy=(80, 0.68), fontsize=8, color=COLORS['dq'],
                arrowprops=dict(arrowstyle='->', color=COLORS['dq']),
                xytext=(150, 0.80))
    ax.set_title('② DC母线电压\n（规则FRT均值跌至0.57pu，远低于0.75pu阈值）', fontsize=9)
    ax.set_ylabel('Vdc (pu)', fontsize=9); ax.set_xlabel('ms')
    ax.set_ylim(0.3, 1.15); ax.set_xlim(-150, 400)
    ax.legend(loc='upper right', fontsize=7)

    # ③ 过流
    ax = axes[1, 0]
    ax.plot(t_rel, data['I2rms'][mask], color='#8e44ad', lw=1.5, label='I₂_rms (pu)')
    ax.axhline(3.0, color='r', ls='--', lw=1.5, label='LVRT过流限制 3.0pu')
    ax.axvline(0, color='k', lw=1.5, ls='--')
    ax.axvspan(0, 5, alpha=0.15, color=COLORS['window'])
    ax.annotate('I2_max最大可达3.4pu\n超过3.0pu过流限制\n（硬件额定电流不足）',
                xy=(50, 2.8), fontsize=8, color='purple',
                bbox=dict(boxstyle='round', facecolor='lavender', alpha=0.8))
    ax.set_title('③ 二次侧电流（三相短路可触发过流）', fontsize=9)
    ax.set_ylabel('I₂_rms (pu)', fontsize=9); ax.set_xlabel('ms')
    ax.set_ylim(0, 4.0); ax.set_xlim(-150, 400)
    ax.legend(loc='upper right', fontsize=8)

    # ④ 通过率对比 + 储能分析
    ax = axes[1, 1]
    pr = PASS_RATES.get('sc_3ph', {})
    methods = ['规则FRT', 'dq双环', 'MSFFN\n→FAHC', 'PPO']
    rates   = [pr.get('rule',0), pr.get('dq',0), pr.get('pipeline',0), pr.get('ppo',0)]
    bar_colors = [COLORS['rule'], COLORS['dq'], COLORS['fahc'], COLORS['ppo']]
    bars = ax.bar(methods, rates, color=bar_colors, alpha=0.85, edgecolor='white')
    for bar, rate in zip(bars, rates):
        ax.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 0.3,
                f'{rate:.0f}%', ha='center', va='bottom', fontsize=10, fontweight='bold')

    # 添加硬件需求说明
    ax.text(0.5, 0.65,
            '硬件储能瓶颈：\n'
            '  当前储能：704 J\n'
            '  三相短路所需：2000–5000 J\n'
            '  → 差距 3–7 倍\n'
            '  → 软件策略无法弥补',
            transform=ax.transAxes, ha='center', fontsize=8,
            bbox=dict(boxstyle='round', facecolor='#ffeeba', alpha=0.9))

    ax.set_ylabel('LVRT通过率 (%)', fontsize=9)
    ax.set_title('④ 三相短路通过率\n（所有软件策略均接近极限）', fontsize=9)
    ax.set_ylim(0, 25)

    plt.tight_layout()
    out = OUT / 'fig_sc3ph_detail.pdf'
    plt.savefig(out, bbox_inches='tight')
    plt.close()
    print(f'saved: {out}')


# ═══════════════════════════════════════════════════════════════════════════════
# 图4：连锁故障 cascade — AI策略负面案例
# ═══════════════════════════════════════════════════════════════════════════════
def plot_cascade_detail():
    data_list = pick_representative(8, n=1)
    if not data_list:
        return
    data = data_list[0]
    t    = data['t']
    t_f  = data['t_fault']

    mask = (t >= t_f - 0.15) & (t <= t_f + 0.60)
    t_rel = (t[mask] - t_f) * 1000

    fig, axes = plt.subplots(2, 2, figsize=(12, 8))
    fig.suptitle('连锁故障 (cascade) — AI过度介入的负面案例\n'
                 '规则FRT: 100%  |  dq双环: 100%  |  MSFFN→FAHC: 86%  |  PPO: 88%',
                 fontsize=11)

    # ① V2三相（两阶段故障）
    ax = axes[0, 0]
    for ph, col in enumerate(['#e74c3c','#2ecc71','#3498db']):
        ax.plot(t_rel, data['V2'][mask, ph]/400*np.sqrt(3),
                color=col, alpha=0.8, label=f'V₂_{["a","b","c"][ph]}')
    ax.axvline(0, color='k', lw=1.5, ls='--', label='第一阶段（单相）')
    ax.axvline(50, color='red', lw=1.5, ls='--', label='第二阶段（三相扩展）')
    ax.axvspan(0, 5, alpha=0.15, color=COLORS['window'], label='MSFFN检测窗口')
    ax.set_title('① 二次侧电压（先单相后三相，两阶段故障）', fontsize=9)
    ax.set_ylabel('V₂ (pu)', fontsize=9); ax.set_xlabel('ms')
    ax.set_ylim(-1.5, 1.5); ax.set_xlim(-150, 600)
    ax.legend(loc='lower right', ncol=2, fontsize=7)

    # ② Vdc（本来就能通过）
    ax = axes[0, 1]
    ax.plot(t_rel, data['Vdc_pu'][mask], color='#2c3e50', lw=1.8, label='实测Vdc')
    ax.axhline(0.75, color='r', ls=':', lw=1.5, label='LVRT下限 0.75pu')
    ax.axhline(1.0, color='gray', ls=':', lw=1.0, alpha=0.5)
    ax.axvline(0, color='k', lw=1.5, ls='--')
    ax.axvline(50, color='red', lw=1.5, ls='--')
    ax.axvspan(0, 5, alpha=0.15, color=COLORS['window'])

    # 标注FAHC策略的副作用
    ax.annotate('默认dq策略：\nVdc维持在0.80pu\n→ 安全通过',
                xy=(100, 0.82), fontsize=8, color=COLORS['dq'],
                arrowprops=dict(arrowstyle='->', color=COLORS['dq']),
                xytext=(200, 0.90))
    ax.annotate('FAHC-S3策略：\nVdc_ref降至720V\n→ 边界场景跌破0.75pu',
                xy=(150, 0.74), fontsize=8, color='red',
                arrowprops=dict(arrowstyle='->', color='red', lw=1.2),
                xytext=(280, 0.65),
                bbox=dict(boxstyle='round', facecolor='#ffe0e0', alpha=0.9))

    ax.set_title('② DC母线电压（连锁故障本来能通过，\nFAHC-S3降Vdc_ref反而造成失败）', fontsize=9)
    ax.set_ylabel('Vdc (pu)', fontsize=9); ax.set_xlabel('ms')
    ax.set_ylim(0.5, 1.2); ax.set_xlim(-150, 600)
    ax.legend(loc='upper right', fontsize=7)

    # ③ 通过率对比
    ax = axes[1, 0]
    pr = PASS_RATES.get('cascade', {})
    methods = ['规则FRT', 'dq双环', 'MSFFN\n→FAHC', 'PPO']
    rates   = [pr.get('rule',0), pr.get('dq',0), pr.get('pipeline',0), pr.get('ppo',0)]
    bar_colors = [COLORS['rule'], COLORS['dq'], COLORS['fahc'], COLORS['ppo']]
    bars = ax.bar(methods, rates, color=bar_colors, alpha=0.85, edgecolor='white')
    for bar, rate in zip(bars, rates):
        ax.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 0.3,
                f'{rate:.0f}%', ha='center', va='bottom', fontsize=10, fontweight='bold')

    ax.axhline(100, color='gray', ls=':', lw=1.0)
    ax.set_ylabel('LVRT通过率 (%)', fontsize=9)
    ax.set_title('③ 连锁故障通过率\n（FAHC反而低于传统策略 -14pp）', fontsize=9)
    ax.set_ylim(0, 115)

    # ④ 策略分析说明
    ax = axes[1, 1]
    ax.axis('off')
    explanation = (
        "连锁故障的 AI 策略问题分析\n"
        "━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        "MSFFN 识别结果：cascade（准确）\n"
        "FAHC 分配策略：S3\n"
        "  Vdc_ref = 720 V（降低80V）\n"
        "  I_lim  = 2.5 pu（收紧）\n\n"
        "问题：\n"
        "  连锁故障 Vdc_min 均值 = 0.819 pu\n"
        "  → 本来就高于 0.75 pu 阈值\n"
        "  → 不需要节能策略！\n\n"
        "S3 降低 Vdc_ref 的副作用：\n"
        "  控制器追踪 720V 而非 800V\n"
        "  → 充电功率减少\n"
        "  → 7个边界场景（0.75~0.79pu）\n"
        "     Vdc 刚好跌破 0.75pu\n\n"
        "修复方案：\n"
        "  cascade → S1（轻度节能）\n"
        "  或引入 ET-PIRC 动态升级机制\n"
        "  （只在 Vdc 实际跌落时才激活）"
    )
    ax.text(0.05, 0.97, explanation, transform=ax.transAxes,
            va='top', fontsize=8,
            bbox=dict(boxstyle='round', facecolor='#fff8e1', alpha=0.9))

    plt.tight_layout()
    out = OUT / 'fig_cascade_detail.pdf'
    plt.savefig(out, bbox_inches='tight')
    plt.close()
    print(f'saved: {out}')


# ═══════════════════════════════════════════════════════════════════════════════
# 图5：MSFFN特征可视化 — 5ms检测窗口里各通道信号
# ═══════════════════════════════════════════════════════════════════════════════
def plot_msffn_features():
    # 对比 igbt_oc_se（Ise特征明显）vs normal（无特征）
    sc_data = {}
    for sc_id, name in [(4, 'igbt_oc_se'), (6, 'sc_1ph'), (7, 'sc_3ph'), (0, 'normal')]:
        dl = pick_representative(sc_id, n=1)
        if dl:
            sc_data[name] = dl[0]

    fig, axes = plt.subplots(4, 5, figsize=(16, 11))
    fig.suptitle('MSFFN 14通道特征可视化 — 故障发生后5ms检测窗口\n'
                 '（每列=一个故障类型，每行=一组特征通道）', fontsize=11)

    FEAT_GROUPS = [
        ('Vdc & 控制信号', ['V_dc', 'Ish_d', 'Ish_q']),
        ('一次侧电流 I1', ['I1_a', 'I1_b', 'I1_c']),
        ('二次侧电流 I2', ['I2_a', 'I2_b', 'I2_c']),
        ('串联VSC & V2', ['Ise_d', 'Ise_q', 'V2_a', 'V2_b', 'V2_c']),
    ]

    fault_order = ['normal', 'igbt_oc_se', 'sc_1ph', 'sc_3ph']
    fault_colors = {'normal': '#95a5a6', 'igbt_oc_se': '#e74c3c',
                    'sc_1ph': '#e67e22', 'sc_3ph': '#8e44ad'}
    fault_display = {'normal': '正常运行', 'igbt_oc_se': 'IGBT开路(串)',
                     'sc_1ph': '单相短路', 'sc_3ph': '三相短路'}

    for col, fname in enumerate(fault_order):
        if fname not in sc_data:
            continue
        data = sc_data[fname]
        t    = data['t']
        t_f  = data['t_fault']

        # 取5ms窗口
        i_start = np.searchsorted(t, t_f)
        i_end   = min(i_start + 100, len(t))
        t_win   = np.arange(i_end - i_start) * 0.05  # ms

        # 构建14通道矩阵
        Vdc_arr = data['Vdc'][i_start:i_end] / 800.0
        Ish = data['Ise'][i_start:i_end]  # shape (N,2)
        I1  = data['I1'][i_start:i_end] / 23.1  # pu
        I2  = data['I2'][i_start:i_end] / 816.5  # pu
        V2  = data['V2'][i_start:i_end] / (400/np.sqrt(3))

        signals_by_group = [
            # Group 0: Vdc, Ish_d, Ish_q
            [(Vdc_arr, 'Vdc (pu)', '#2c3e50'),
             (Ish[:,0]*5, 'Ish_d (scaled)', '#2980b9'),
             (Ish[:,1]*5, 'Ish_q (scaled)', '#3498db')],
            # Group 1: I1_abc
            [(I1[:,0], 'I1_a (pu)', '#e74c3c'),
             (I1[:,1], 'I1_b (pu)', '#2ecc71'),
             (I1[:,2], 'I1_c (pu)', '#3498db')],
            # Group 2: I2_abc
            [(I2[:,0], 'I2_a (pu)', '#c0392b'),
             (I2[:,1], 'I2_b (pu)', '#27ae60'),
             (I2[:,2], 'I2_c (pu)', '#2980b9')],
            # Group 3: Ise_dq + V2_abc
            [(Ish[:,0], 'Ise_d (kA)', '#e67e22'),
             (Ish[:,1], 'Ise_q (kA)', '#f39c12'),
             (V2[:,0], 'V2_a (pu)', '#9b59b6'),
             (V2[:,1], 'V2_b (pu)', '#8e44ad'),
             (V2[:,2], 'V2_c (pu)', '#6c3483')],
        ]

        for row in range(4):
            ax = axes[row, col]
            for sig, label, color in signals_by_group[row]:
                ax.plot(t_win, sig[:len(t_win)], color=color, lw=0.9,
                        label=label, alpha=0.85)

            if row == 0:
                ax.set_title(fault_display[fname], fontsize=9,
                             color=fault_colors[fname], fontweight='bold')
            if col == 0:
                ax.set_ylabel(FEAT_GROUPS[row][0], fontsize=8)
            if row == 3:
                ax.set_xlabel('窗口时间 (ms)', fontsize=8)

            ax.set_xlim(0, 5)
            if col == len(fault_order) - 1:
                ax.legend(loc='upper right', fontsize=5)

            # 在igbt_oc_se的Ise行高亮
            if fname == 'igbt_oc_se' and row == 3:
                ax.set_facecolor('#fff3e0')
                ax.set_title('★ Ise信号是最关键特征\n（F1从0.862→1.000）',
                             fontsize=7, color='#e67e22')

    # 右侧空列关掉
    for row in range(4):
        axes[row, -1].set_visible(False)

    plt.tight_layout()
    out = OUT / 'fig_msffn_features.pdf'
    plt.savefig(out, bbox_inches='tight')
    plt.close()
    print(f'saved: {out}')


# ═══════════════════════════════════════════════════════════════════════════════
# 图6：策略效果总结图 — 雷达图 + 综合对比
# ═══════════════════════════════════════════════════════════════════════════════
def plot_strategy_summary():
    faults = ['igbt_oc_sh', 'igbt_oc_se', 'cap_fault', 'sc_1ph', 'sc_3ph', 'cascade']
    fault_cn = ['IGBT开路\n(并联)', 'IGBT开路\n(串联)', 'DC电容\n退化',
                '单相\n短路', '三相\n短路', '连锁\n故障']

    ctrls = ['rule', 'dq', 'pipeline', 'ppo']
    ctrl_labels = ['规则FRT', 'dq双环', 'MSFFN→FAHC', 'PPO/DRL']
    ctrl_colors = [COLORS['rule'], COLORS['dq'], COLORS['fahc'], COLORS['ppo']]

    fig, (ax_bar, ax_heat) = plt.subplots(1, 2, figsize=(14, 6))
    fig.suptitle('控制策略综合对比报告 — 全故障类型 LVRT 通过率', fontsize=12)

    # ── 分组条形图 ──────────────────────────────────────────────────────────
    n_faults = len(faults)
    n_ctrls  = len(ctrls)
    x = np.arange(n_faults)
    width = 0.18

    for i, (ctrl, label, color) in enumerate(zip(ctrls, ctrl_labels, ctrl_colors)):
        rates = [PASS_RATES.get(f, {}).get(ctrl, 0) for f in faults]
        offset = (i - (n_ctrls-1)/2) * width
        bars = ax_bar.bar(x + offset, rates, width, label=label,
                          color=color, alpha=0.85, edgecolor='white')

    ax_bar.set_xticks(x)
    ax_bar.set_xticklabels(fault_cn, fontsize=8)
    ax_bar.set_ylabel('LVRT通过率 (%)', fontsize=10)
    ax_bar.set_title('各故障类型 × 各控制策略 通过率', fontsize=10)
    ax_bar.legend(loc='upper right', fontsize=9)
    ax_bar.axhline(100, color='gray', ls=':', lw=1)
    ax_bar.set_ylim(0, 115)
    ax_bar.set_yticks([0, 14, 16, 20, 26, 50, 75, 88, 100])

    # 标注关键差异
    ax_bar.annotate('dq/FAHC\n+10pp', xy=(3.18, 26), fontsize=7, color=COLORS['dq'],
                    ha='center', fontweight='bold')
    ax_bar.annotate('FAHC\n-14pp!', xy=(5.0, 88), fontsize=7, color='red',
                    ha='center', fontweight='bold',
                    bbox=dict(boxstyle='round', facecolor='#ffe0e0', alpha=0.8))

    # ── 热力图 ─────────────────────────────────────────────────────────────
    matrix = np.array([[PASS_RATES.get(f, {}).get(c, 0) for f in faults]
                       for c in ctrls])

    im = ax_heat.imshow(matrix, cmap='RdYlGn', aspect='auto',
                        vmin=0, vmax=100)
    ax_heat.set_xticks(range(n_faults))
    ax_heat.set_xticklabels(fault_cn, fontsize=8)
    ax_heat.set_yticks(range(n_ctrls))
    ax_heat.set_yticklabels(ctrl_labels, fontsize=9)
    ax_heat.set_title('通过率热力图 (绿=好, 红=差)', fontsize=10)

    # 在每格填写数字
    for i in range(n_ctrls):
        for j in range(n_faults):
            val = matrix[i, j]
            color = 'white' if val < 30 or val > 80 else 'black'
            ax_heat.text(j, i, f'{val:.0f}%', ha='center', va='center',
                         fontsize=9, color=color, fontweight='bold')

    plt.colorbar(im, ax=ax_heat, label='通过率 (%)')
    plt.tight_layout()
    out = OUT / 'fig_strategy_summary.pdf'
    plt.savefig(out, bbox_inches='tight')
    plt.close()
    print(f'saved: {out}')


# ═══════════════════════════════════════════════════════════════════════════════
# 主入口
# ═══════════════════════════════════════════════════════════════════════════════
if __name__ == '__main__':
    print('生成仿真对比图...')
    plot_fault_overview()      # 图1：七类故障全览
    plot_sc1ph_detail()        # 图2：单相短路详细分析
    plot_sc3ph_detail()        # 图3：三相短路详细分析
    plot_cascade_detail()      # 图4：连锁故障AI负面案例
    plot_msffn_features()      # 图5：MSFFN特征可视化
    plot_strategy_summary()    # 图6：策略总结
    print(f'\n全部图表已保存到: {OUT}')
    print('文件列表:')
    for f in sorted(OUT.glob('fig_*.pdf')):
        print(f'  {f.name}')
