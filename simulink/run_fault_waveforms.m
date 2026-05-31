%% run_fault_waveforms.m
% 对所有故障类型自动运行仿真并保存波形图。
% 输出: results/fault_waveforms/*.png
%
% 用法:
%   cd simulink
%   run_fault_waveforms

clear; clc;

%% ── 路径 ────────────────────────────────────────────────────────────────────
script_dir = fileparts(mfilename('fullpath'));
proj_root  = fileparts(script_dir);
out_dir    = fullfile(proj_root, 'results', 'fault_waveforms');
if ~exist(out_dir, 'dir'), mkdir(out_dir); end
cd(script_dir);
run('parameters.m');

%% ── 场景定义（sc_id 与 run_switching_scenarios.m 保持一致）────────────────
%  sc_id  fname          fdesc
SCENARIOS = {
    0,  'normal',     '无故障（正常稳态）';
    3,  'igbt_oc_sh', 'IGBT 开路 - 并联变流器';
    4,  'igbt_oc_se', 'IGBT 开路 - 串联变流器';
    5,  'cap_fault',  '直流电容故障 (C: 2200→680µF)';
    6,  'sc_1ph',     '单相接地短路';
    7,  'sc_3ph',     '三相短路';
    8,  'cascade',    '级联故障';
};

MODEL       = 'hpt_switching_model';
T_FAULT     = 0.3;    % 故障触发时刻 (s)
STOP_TIME   = 0.5;    % 仿真总时长 (s)
VDC_MIN     = 600;    % LVRT 下限 0.75 pu
VDC_MAX     = 1000;   % LVRT 上限 1.25 pu
I2_MAX_PK   = 1732;   % LVRT 电流上限 3 pu 峰值 (A)

%% ── 加载模型 ────────────────────────────────────────────────────────────────
if ~bdIsLoaded(MODEL)
    load_system(MODEL);
end
set_param(MODEL, 'StopTime', num2str(STOP_TIME), 'ReturnWorkspaceOutputs', 'on');

%% ── 逐故障仿真 ──────────────────────────────────────────────────────────────
n = size(SCENARIOS, 1);
summary = cell(n, 4);  % {fname, vdc_min, vdc_max, i2_pk}

for fi = 1:n
    sc_id  = SCENARIOS{fi, 1};
    fname  = SCENARIOS{fi, 2};
    fdesc  = SCENARIOS{fi, 3};
    fprintf('\n[%d/%d] sc_id=%d  %s (%s)\n', fi, n, sc_id, fname, fdesc);

    % ── 配置故障（与 run_switching_scenarios.m 逻辑一致）──────────────────
    % 先重置所有故障为关闭状态
    set_param([MODEL '/T_fault'],          'Value', '99');
    set_param([MODEL '/FaultVariant'],     'Value', '1');
    set_param([MODEL '/FaultMag'],         'Value', '1');
    set_param([MODEL '/ControllerMode'],   'Value', '2');
    set_param([MODEL '/FAHC_Strategy'],    'Value', '0');
    set_param([MODEL '/Sc_id'],            'Value', num2str(sc_id));
    set_param([MODEL '/DC_Link_Capacitor'],'Capacitance',    '2200e-6', ...
                                           'InitialVoltage', '800');
    set_param([MODEL '/LV_AC_Fault'], ...
        'FaultA','off','FaultB','off','FaultC','off','GroundFault','off', ...
        'SwitchTimes','[99 100]');
    set_param([MODEL '/DC_Link_Cap_Breaker'], 'SwitchingTimes', '[99]');

    % 按故障类型专项配置
    switch sc_id
        case 0   % normal — 不触发任何故障，已在上面重置
            % 无需额外操作

        case {3, 4}  % igbt_oc_sh / igbt_oc_se — 靠 T_fault + FaultVariant
            set_param([MODEL '/T_fault'],      'Value', num2str(T_FAULT));
            set_param([MODEL '/FaultVariant'], 'Value', '1');

        case 5   % cap_fault — 降容电容 680µF（与训练数据一致，贯穿全程）
            set_param([MODEL '/DC_Link_Capacitor'], 'Capacitance', '680e-6');

        case 6   % sc_1ph — A 相接地短路（LV_AC_Fault 触发）
            set_param([MODEL '/LV_AC_Fault'], ...
                'FaultA','on','FaultB','off','FaultC','off','GroundFault','on', ...
                'FaultResistance','0.35','GroundResistance','0.35', ...
                'SwitchTimes', sprintf('[%.4f %.4f]', T_FAULT, T_FAULT+0.15));

        case 7   % sc_3ph — 三相短路（LV_AC_Fault 触发）
            set_param([MODEL '/LV_AC_Fault'], ...
                'FaultA','on','FaultB','on','FaultC','on','GroundFault','on', ...
                'FaultResistance','0.28','GroundResistance','0.28', ...
                'SwitchTimes', sprintf('[%.4f %.4f]', T_FAULT, T_FAULT+0.15));

        case 8   % cascade — T_fault + FaultVariant
            set_param([MODEL '/T_fault'],      'Value', num2str(T_FAULT));
            set_param([MODEL '/FaultVariant'], 'Value', '1');
    end

    % ── 运行仿真 ──────────────────────────────────────────────────────────
    out = sim(MODEL, 'CaptureErrors', 'on');
    if ~isempty(out.ErrorMessage)
        fprintf('  !! 仿真出错: %s\n', out.ErrorMessage);
        continue;
    end

    % ── 提取信号 ──────────────────────────────────────────────────────────
    % To Workspace 块按 T_sample=5e-5s 采样，out.tout 按求解器步长，两者长度不同
    % 用 V_dc 的实际长度反推信号时间轴
    vdc = squeeze(out.get('V_dc'));  vdc = vdc(:);
    N   = numel(vdc);
    t   = linspace(0, STOP_TIME, N)';

    v2  = fix_signal(out.get('V2_abc'), N);
    i2  = fix_signal(out.get('I2_abc'), N);
    v1  = fix_signal(out.get('V1_abc'), N);

    % LVRT 判定（跳过前 0.15s 启动瞬态）
    eval_mask = t >= 0.15;
    vdc_min  = min(vdc(eval_mask));
    vdc_max  = max(vdc(eval_mask));
    i2_pk    = max(max(abs(i2(eval_mask, :))));
    lvrt_ok  = (vdc_min >= VDC_MIN) && (vdc_max <= VDC_MAX) && (i2_pk <= I2_MAX_PK);
    summary(fi,:) = {fname, vdc_min, vdc_max, i2_pk};
    fprintf('  Vdc: %.1f ~ %.1f V  |  I2 peak: %.1f A  =>  %s\n', ...
        vdc_min, vdc_max, i2_pk, ternary(lvrt_ok,'PASS ✓','FAIL ✗'));

    % ── 画图（左：全局 0~0.5s；右：故障局部放大）─────────────────────────
    fig = figure('Visible','off','Position',[50 50 1600 900],'Color','k');
    colors3 = {[0.3 0.6 1], [1 0.45 0.1], [1 0.88 0.1]};
    lw = 0.9;

    % 故障局部窗口：T_fault-0.02 ~ T_fault+0.12
    if sc_id > 0
        t_zoom = [T_FAULT - 0.02, min(STOP_TIME, T_FAULT + 0.12)];
    else
        t_zoom = [0.25, 0.45];
    end

    titles = {'V_{dc} (V)', 'V_2 (V)', 'I_2 (A)', 'V_1 (V)'};
    signals = {vdc, v2, i2, v1};
    ylims   = {[], [], [], []};

    axL = gobjects(4,1);  axR = gobjects(4,1);

    for row = 1:4
        sig = signals{row};

        % ── 左列：全局 ───────────────────────────────────────────────────
        axL(row) = subplot(4,2, 2*row-1);
        if isvector(sig)
            plot(t, sig, 'Color',[1 0.88 0.1], 'LineWidth',1.2);
        else
            for ph=1:min(3,size(sig,2))
                plot(t, sig(:,ph), 'Color',colors3{ph}, 'LineWidth',lw); hold on;
            end
        end
        if row == 1
            hold on;
            yline(VDC_MIN,'r--','0.75pu','LineWidth',1.0,'LabelHorizontalAlignment','left');
            yline(VDC_MAX,'r:','1.25pu','LineWidth',1.0,'LabelHorizontalAlignment','left');
            yline(800,'w:','800V','LineWidth',0.7,'Alpha',0.5);
            title(sprintf('[sc_id=%d]  %s  |  LVRT: %s', sc_id, fname, ...
                ternary(lvrt_ok,'✓ PASS','✗ FAIL')),'Color','w','FontSize',9);
        end
        if row == 3
            hold on;
            yline( I2_MAX_PK,'r--','3pu','LineWidth',1.0,'LabelHorizontalAlignment','left');
            yline(-I2_MAX_PK,'r--','','LineWidth',1.0);
        end
        if sc_id > 0, xline(T_FAULT,'w--','LineWidth',0.8); end
        ylabel(titles{row},'Color','w');
        if row == 4, xlabel('时间 (s)','Color','w'); end
        if ~isempty(ylims{row}), ylim(ylims{row}); end
        xlim([0 STOP_TIME]);
        set(axL(row),'Color','k','XColor','w','YColor','w','GridColor',[0.3 0.3 0.3]);
        grid on;

        % ── 右列：故障局部放大 ──────────────────────────────────────────
        axR(row) = subplot(4,2, 2*row);
        if isvector(sig)
            plot(t, sig, 'Color',[1 0.88 0.1], 'LineWidth',1.2);
        else
            for ph=1:min(3,size(sig,2))
                plot(t, sig(:,ph), 'Color',colors3{ph}, 'LineWidth',lw); hold on;
            end
        end
        if row == 1
            hold on;
            yline(VDC_MIN,'r--','LineWidth',1.0);
            yline(VDC_MAX,'r:','LineWidth',1.0);
            yline(800,'w:','LineWidth',0.7,'Alpha',0.5);
            title('← 故障局部放大','Color',[0.7 0.7 0.7],'FontSize',8);
        end
        if row == 3
            hold on;
            yline( I2_MAX_PK,'r--','LineWidth',1.0);
            yline(-I2_MAX_PK,'r--','LineWidth',1.0);
        end
        if sc_id > 0, xline(T_FAULT,'w--','LineWidth',0.8); end
        if ~isempty(ylims{row}), ylim(ylims{row}); end
        xlim(t_zoom);
        if row == 4, xlabel('时间 (s)','Color','w'); end
        set(axR(row),'Color','k','XColor','w','YColor','w','GridColor',[0.3 0.3 0.3]);
        grid on;
    end

    set(fig,'Color','k');
    linkaxes(axL,'x');
    linkaxes(axR,'x');

    fig_path = fullfile(out_dir, sprintf('%s.png', fname));
    exportgraphics(fig, fig_path, 'Resolution',150);
    close(fig);
    fprintf('  已保存: %s\n', fig_path);
end

%% ── 汇总 ────────────────────────────────────────────────────────────────────
fprintf('\n======= LVRT 汇总 =======\n');
fprintf('%-14s  %8s  %8s  %10s\n','故障','Vdc_min','Vdc_max','I2_peak');
fprintf('%s\n', repmat('-',1,46));
for fi = 1:n
    if isempty(summary{fi,1}), continue; end
    ok = (summary{fi,2} >= VDC_MIN) && (summary{fi,3} <= VDC_MAX) && (summary{fi,4} <= I2_MAX_PK);
    fprintf('%-14s  %7.1f V  %7.1f V  %9.1f A  %s\n', ...
        summary{fi,1}, summary{fi,2}, summary{fi,3}, summary{fi,4}, ...
        ternary(ok,'PASS','FAIL'));
end
fprintf('\n图像: %s\n', out_dir);
close_system(MODEL, 0);

function s = ternary(c, a, b)
    if c, s = a; else, s = b; end
end

function out = fix_signal(raw, N)
    % 把 To Workspace 输出整理成 (N, C) 矩阵
    raw = squeeze(raw);
    if isvector(raw)
        out = raw(:);
    elseif size(raw, 1) == 3 && size(raw, 2) ~= 3
        out = raw';   % (3, N) → (N, 3)
    else
        out = raw;
    end
    % 若长度不符（理论上不会），截断或补零
    if size(out, 1) ~= N
        if size(out, 1) > N
            out = out(1:N, :);
        else
            out = [out; repmat(out(end,:), N-size(out,1), 1)];
        end
    end
end
