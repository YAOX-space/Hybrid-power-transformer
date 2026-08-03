function build_hpt_1to1_switchlevel()
% build_hpt_1to1_switchlevel
% Reference-structure HPT topology model.
%
% The model follows the supplied topology diagram:
%   - Main transformer: W1/W2 per phase.
%   - New flexible distribution transformer: W3/W4 per phase.
%   - Energy converter: fed from W4 through an RL filter.
%   - Regulating converter: drives W5 of the series transformers.
%   - Series injection transformers: W6 is inserted in each load phase.
%   - Energy and regulating converters share the DC link.
%
% This is a switch-level topology skeleton.  Each converter leg is built from
% individual IGBT blocks.  Converter gates are held off by default; control/PWM
% migration and parameter calibration should be done in a later step.

M = 'hpt_1to1_switchlevel';
if bdIsLoaded(M)
    close_system(M, 0);
end
new_system(M);
load_system(M);

f0 = 50;
Ts = 20e-6;
Vmv = 10e3;
Vlv = 400;
Srated = 400e3;
Saux = 120e3;
Sser = 30e3;
Vaux = 400;
Vw5 = 400;
Vw6 = 46.2;
Rtake = 0.05;
Ltake = 3e-3;
Cdc = 2200e-6;
Rchop = (800^2) / Saux;

Zb = Vmv^2 / Srated;
scr = 3;
Zg = Zb / scr;
Rg = Zg / sqrt(1 + 49);
Lg = 7 * Rg / (2 * pi * f0);

P = @(x, y, w, h) [x y x+w y+h];
set_param(M, 'Solver', 'ode23tb', 'StopTime', '0.2');

add_block('powerlib/powergui', [M '/powergui'], 'Position', P(20, 20, 70, 40));
set_param([M '/powergui'], 'SimulationMode', 'Discrete', 'SampleTime', num2str(Ts));

% Grid and weak-grid impedance.
add_block('powerlib/Electrical Sources/Three-Phase Source', [M '/Grid'], ...
    'Position', P(60, 115, 60, 90));
set_param([M '/Grid'], 'Voltage', num2str(Vmv), 'Frequency', num2str(f0), ...
    'PhaseAngle', '0', 'InternalConnection', 'Yg', ...
    'SpecifyImpedance', 'off', 'Resistance', '1e-3', 'Inductance', '1e-5');

add_block('powerlib/Elements/Three-Phase Series RLC Branch', [M '/Zg'], ...
    'Position', P(155, 120, 55, 70));
set_param([M '/Zg'], 'BranchType', 'RL', 'Resistance', num2str(Rg), ...
    'Inductance', num2str(Lg));

add_block('powerlib/Measurements/Three-Phase V-I Measurement', [M '/MeasMV'], ...
    'Position', P(245, 115, 70, 90));
set_param([M '/MeasMV'], 'VoltageMeasurement', 'phase-to-ground', ...
    'CurrentMeasurement', 'no');

% Main transformer W1/W2.
for k = 1:3
    y = 70 + (k-1) * 115;
    blk = [M sprintf('/Main_W1W2_%d', k)];
    add_block('powerlib/Elements/Linear Transformer', blk, ...
        'Position', P(375, y, 95, 78));
    set_param(blk, 'ThreeWindings', 'off', ...
        'NominalPower', ['[' num2str(Srated/3) ',' num2str(f0) ']'], ...
        'winding1', ['[' num2str(Vmv/sqrt(3)) ',0.005,0.025]'], ...
        'winding2', ['[' num2str(Vlv/sqrt(3)) ',0.005,0.025]']);
end

% New flexible distribution transformer W3/W4.
for k = 1:3
    x = 300 + (k-1) * 125;
    blk = [M sprintf('/Flex_W3W4_%d', k)];
    add_block('powerlib/Elements/Linear Transformer', blk, ...
        'Position', P(x, 430, 82, 78));
    set_param(blk, 'ThreeWindings', 'off', ...
        'NominalPower', ['[' num2str(Saux/3) ',' num2str(f0) ']'], ...
        'winding1', ['[' num2str(Vlv/sqrt(3)) ',0.005,0.02]'], ...
        'winding2', ['[' num2str(Vaux/sqrt(3)) ',0.005,0.02]']);
end

% Series injection transformer W5/W6.  W6 is in the load path; W5 is fed by
% the regulating converter.
for k = 1:3
    y = 70 + (k-1) * 115;
    blk = [M sprintf('/Series_W5W6_%d', k)];
    add_block('powerlib/Elements/Linear Transformer', blk, ...
        'Position', P(650, y, 95, 72));
    set_param(blk, 'ThreeWindings', 'off', ...
        'NominalPower', ['[' num2str(Sser) ',' num2str(f0) ']'], ...
        'winding1', ['[' num2str(Vw5) ',0.002,0.03]'], ...
        'winding2', ['[' num2str(Vw6) ',0.002,0.03]']);
end

add_block('powerlib/Measurements/Three-Phase V-I Measurement', [M '/MeasLV'], ...
    'Position', P(805, 135, 70, 100));
set_param([M '/MeasLV'], 'VoltageMeasurement', 'phase-to-ground', ...
    'CurrentMeasurement', 'no');

add_block('powerlib/Elements/Three-Phase Series RLC Load', [M '/Load'], ...
    'Position', P(950, 150, 70, 80));
set_param([M '/Load'], 'NominalVoltage', num2str(Vlv), ...
    'NominalFrequency', num2str(f0), 'ActivePower', num2str(Srated), ...
    'InductivePower', '0', 'CapacitivePower', '0', ...
    'Configuration', 'Y (grounded)');

% Energy converter chain: W4 -> measurement -> RL filter -> ShVSC.
add_block('powerlib/Measurements/Three-Phase V-I Measurement', [M '/MeasEnergy'], ...
    'Position', P(690, 455, 70, 95));
set_param([M '/MeasEnergy'], 'VoltageMeasurement', 'phase-to-ground', ...
    'CurrentMeasurement', 'yes');

add_block('powerlib/Elements/Three-Phase Series RLC Branch', [M '/Energy_RL'], ...
    'Position', P(800, 470, 60, 65));
set_param([M '/Energy_RL'], 'BranchType', 'RL', 'Resistance', num2str(Rtake), ...
    'Inductance', num2str(Ltake));

add_energy_converter_subsystem(M, 910, 430);
add_regulating_converter_subsystem(M, 250, 665);

add_block('powerlib/Elements/Series RLC Branch', [M '/Cdc'], ...
    'Position', P(1160, 470, 40, 85));
set_param([M '/Cdc'], 'BranchType', 'C', 'Capacitance', num2str(Cdc), ...
    'Setx0', 'on', 'InitialVoltage', '800');

add_block('powerlib/Measurements/Voltage Measurement', [M '/MeasVdc'], ...
    'Position', P(1230, 465, 45, 45));

add_block('powerlib/Power Electronics/IGBT', [M '/Chop'], ...
    'Position', P(1325, 465, 40, 55));
add_block('powerlib/Elements/Series RLC Branch', [M '/Rchop'], ...
    'Position', P(1325, 550, 45, 55));
set_param([M '/Rchop'], 'BranchType', 'R', 'Resistance', num2str(Rchop));

% Ground references for the single-phase winding groups.
add_block('powerlib/Elements/Ground', [M '/W1_neutral_ground'], ...
    'Position', P(325, 395, 25, 25));
add_block('powerlib/Elements/Ground', [M '/W2_neutral_ground'], ...
    'Position', P(545, 395, 25, 25));
add_block('powerlib/Elements/Ground', [M '/W3_neutral_ground'], ...
    'Position', P(265, 555, 25, 25));
add_block('powerlib/Elements/Ground', [M '/W4_neutral_ground'], ...
    'Position', P(645, 555, 25, 25));

% Safe default gates are local constants next to each individual switch.
add_block('simulink/Sources/Constant', [M '/Chop_gate'], ...
    'Position', P(1245, 575, 60, 25), 'Value', '0');

% Logging.
add_block('simulink/Sinks/To Workspace', [M '/Vmv_abc'], ...
    'Position', P(1125, 115, 85, 25), 'VariableName', 'Vmv_abc', ...
    'SaveFormat', 'Array', 'SampleTime', num2str(Ts));
add_block('simulink/Sinks/To Workspace', [M '/Vlv_abc'], ...
    'Position', P(1125, 150, 85, 25), 'VariableName', 'Vlv_abc', ...
    'SaveFormat', 'Array', 'SampleTime', num2str(Ts));
add_block('simulink/Sinks/To Workspace', [M '/Vdc'], ...
    'Position', P(1290, 465, 70, 25), 'VariableName', 'Vdc', ...
    'SaveFormat', 'Array', 'SampleTime', num2str(Ts));

% Main power path and transformer taps.
for k = 1:3
    add_line(M, ph([M '/Grid'], 'RConn', k), ph([M '/Zg'], 'LConn', k), ...
        'autorouting', 'on');
    add_line(M, ph([M '/Zg'], 'RConn', k), ph([M '/MeasMV'], 'LConn', k), ...
        'autorouting', 'on');
    add_line(M, ph([M '/MeasMV'], 'RConn', k), ...
        ph([M sprintf('/Main_W1W2_%d', k)], 'LConn', 1), 'autorouting', 'on');

    % W2 phase conductor -> W6 series winding -> load.
    add_line(M, ph([M sprintf('/Main_W1W2_%d', k)], 'RConn', 1), ...
        ph([M sprintf('/Series_W5W6_%d', k)], 'RConn', 1), 'autorouting', 'on');
    add_line(M, ph([M sprintf('/Series_W5W6_%d', k)], 'RConn', 2), ...
        ph([M '/MeasLV'], 'LConn', k), 'autorouting', 'on');
    add_line(M, ph([M '/MeasLV'], 'RConn', k), ph([M '/Load'], 'LConn', k), ...
        'autorouting', 'on');

    % W3 is tapped from the W2 side and magnetically feeds W4.
    add_line(M, ph([M sprintf('/Main_W1W2_%d', k)], 'RConn', 1), ...
        ph([M sprintf('/Flex_W3W4_%d', k)], 'LConn', 1), 'autorouting', 'on');
    add_line(M, ph([M sprintf('/Flex_W3W4_%d', k)], 'RConn', 1), ...
        ph([M '/MeasEnergy'], 'LConn', k), 'autorouting', 'on');
    add_line(M, ph([M '/MeasEnergy'], 'RConn', k), ...
        ph([M '/Energy_RL'], 'LConn', k), 'autorouting', 'on');
    add_line(M, ph([M '/Energy_RL'], 'RConn', k), ...
        ph([M '/EnergyConverter'], 'LConn', k), 'autorouting', 'on');

    % W5 is driven by one full H-bridge per phase; W6 is the line-side
    % series winding.
    add_line(M, ph([M sprintf('/Series_W5W6_%d', k)], 'LConn', 1), ...
        ph([M '/RegulatingConverter'], 'LConn', 2*k-1), 'autorouting', 'on');
    add_line(M, ph([M sprintf('/Series_W5W6_%d', k)], 'LConn', 2), ...
        ph([M '/RegulatingConverter'], 'LConn', 2*k), 'autorouting', 'on');
end

% Common/grounded neutral groups.
connect3(M, 'Main_W1W2', 'LConn', 2);
add_line(M, ph([M '/Main_W1W2_3'], 'LConn', 2), ...
    ph([M '/W1_neutral_ground'], 'LConn', 1), 'autorouting', 'on');

connect3(M, 'Main_W1W2', 'RConn', 2);
add_line(M, ph([M '/Main_W1W2_3'], 'RConn', 2), ...
    ph([M '/W2_neutral_ground'], 'LConn', 1), 'autorouting', 'on');

connect3(M, 'Flex_W3W4', 'LConn', 2);
add_line(M, ph([M '/Flex_W3W4_3'], 'LConn', 2), ...
    ph([M '/W3_neutral_ground'], 'LConn', 1), 'autorouting', 'on');

connect3(M, 'Flex_W3W4', 'RConn', 2);
add_line(M, ph([M '/Flex_W3W4_3'], 'RConn', 2), ...
    ph([M '/W4_neutral_ground'], 'LConn', 1), 'autorouting', 'on');

% Shared DC link and chopper.
dcPos = ph([M '/Cdc'], 'LConn', 1);
dcNeg = ph([M '/Cdc'], 'RConn', 1);
add_line(M, dcPos, ph([M '/EnergyConverter'], 'RConn', 1), 'autorouting', 'on');
add_line(M, ph([M '/EnergyConverter'], 'RConn', 2), dcNeg, 'autorouting', 'on');
add_line(M, dcPos, ph([M '/RegulatingConverter'], 'RConn', 1), 'autorouting', 'on');
add_line(M, ph([M '/RegulatingConverter'], 'RConn', 2), dcNeg, 'autorouting', 'on');
add_line(M, ph([M '/MeasVdc'], 'LConn', 1), dcPos, 'autorouting', 'on');
add_line(M, ph([M '/MeasVdc'], 'LConn', 2), dcNeg, 'autorouting', 'on');
add_line(M, dcPos, ph([M '/Chop'], 'LConn', 1), 'autorouting', 'on');
add_line(M, ph([M '/Chop'], 'RConn', 1), ph([M '/Rchop'], 'LConn', 1), ...
    'autorouting', 'on');
add_line(M, ph([M '/Rchop'], 'RConn', 1), dcNeg, 'autorouting', 'on');

% Signal wiring.
add_line(M, 'Chop_gate/1', 'Chop/1', 'autorouting', 'on');
add_line(M, 'MeasMV/1', 'Vmv_abc/1', 'autorouting', 'on');
add_line(M, 'MeasLV/1', 'Vlv_abc/1', 'autorouting', 'on');
add_line(M, 'MeasVdc/1', 'Vdc/1', 'autorouting', 'on');

decorate_model(M);

try
    set_param(M, 'ZoomFactor', 'FitSystem');
catch
end
save_system(M, fullfile(fileparts(mfilename('fullpath')), [M '.slx']));
fprintf('Built %s.slx with explicit switch-level Energy and Regulating converters.\\n', M);
end

function connect3(M, prefix, kind, idx)
add_line(M, ph([M '/' prefix '_1'], kind, idx), ...
    ph([M '/' prefix '_2'], kind, idx), 'autorouting', 'on');
add_line(M, ph([M '/' prefix '_2'], kind, idx), ...
    ph([M '/' prefix '_3'], kind, idx), 'autorouting', 'on');
end

function decorate_model(M)
blocks = find_system(M, 'Type', 'Block');
for i = 1:numel(blocks)
    try
        set_param(blocks{i}, 'ShowName', 'on', 'FontName', 'Microsoft YaHei UI', ...
            'FontSize', '10');
    catch
    end
end

labels = {
    'MAIN TRANSFORMER W1/W2', [380 35 580 60]
    'FLEXIBLE DISTRIBUTION TRANSFORMER W3/W4', [300 395 640 420]
    'SERIES INJECTION TRANSFORMERS W5/W6', [645 35 895 60]
    'ENERGY CONVERTER - 3-LEG / 6 IGBTS', [900 395 1130 420]
    'REGULATING CONVERTER - 3 H-BRIDGES / 12 IGBTS', [250 630 660 655]
    'SHARED DC LINK', [1155 430 1300 455]
};
for i = 1:size(labels, 1)
    a = Simulink.Annotation(M, labels{i, 1});
    a.Position = labels{i, 2};
    a.FontName = 'Microsoft YaHei UI';
    a.FontSize = 14;
    a.FontWeight = 'bold';
end
end

function add_energy_converter_subsystem(M, x, y)
P = @(a, b, w, h) [a b a+w b+h];
S = [M '/EnergyConverter'];
add_block('built-in/Subsystem', S, 'Position', P(x, y, 165, 130));
set_param(S, 'ShowName', 'on');
set_converter_mask(S, 'energy');
open_system(S);

for k = 1:3
    add_pmio(S, sprintf('AC_%d', k), 'Left', P(20, 45 + (k-1)*45, 24, 24));
end
add_pmio(S, 'DC_pos', 'Right', P(430, 60, 24, 24));
add_pmio(S, 'DC_neg', 'Right', P(430, 150, 24, 24));

add_switch_bridge(S, 'E', 150, 45);
for k = 1:3
    connect_phase_to_bridge(S, ph([S sprintf('/AC_%d', k)], 'RConn', 1), 'E', k);
end
connect_bridge_dc(S, 'E', ph([S '/DC_pos'], 'RConn', 1), ...
    ph([S '/DC_neg'], 'RConn', 1));

Simulink.Annotation(S, 'Energy converter: three-phase two-level bridge, 6 IGBTs');
end

function add_regulating_converter_subsystem(M, x, y)
P = @(a, b, w, h) [a b a+w b+h];
S = [M '/RegulatingConverter'];
add_block('built-in/Subsystem', S, 'Position', P(x, y, 395, 155));
set_param(S, 'ShowName', 'on');
set_converter_mask(S, 'regulating');
open_system(S);

phaseNames = {'A', 'B', 'C'};
for k = 1:3
    add_pmio(S, sprintf('W5_%s_1', phaseNames{k}), 'Left', ...
        P(20, 35 + (k-1)*70, 24, 24));
    add_pmio(S, sprintf('W5_%s_2', phaseNames{k}), 'Left', ...
        P(20, 65 + (k-1)*70, 24, 24));
end
add_pmio(S, 'DC_pos', 'Right', P(640, 80, 24, 24));
add_pmio(S, 'DC_neg', 'Right', P(640, 250, 24, 24));

add_hbridge3_converter(S, 'R', 145, 45);
for k = 1:3
    connect_hbridge_phase(S, ...
        ph([S sprintf('/W5_%s_1', phaseNames{k})], 'RConn', 1), ...
        ph([S sprintf('/W5_%s_2', phaseNames{k})], 'RConn', 1), ...
        'R', k);
end
connect_hbridge_dc(S, 'R', ph([S '/DC_pos'], 'RConn', 1), ...
    ph([S '/DC_neg'], 'RConn', 1));

Simulink.Annotation(S, 'Regulating converter: three single-phase H-bridges, 12 IGBTs');
end

function set_converter_mask(blockPath, iconKind)
switch iconKind
    case 'energy'
        displayCode = [ ...
            'color(''black'');' newline ...
            'plot([10 90 90 10 10],[10 10 90 90 10]);' newline ...
            'plot([20 80],[78 78]); plot([20 80],[22 22]);' newline ...
            'plot([28 28],[22 78]); plot([50 50],[22 78]); plot([72 72],[22 78]);' newline ...
            'plot([10 20],[65 65]); plot([10 20],[50 50]); plot([10 20],[35 35]);' newline ...
            'plot([80 90],[65 65]); plot([80 90],[35 35]);' ...
            ];
    otherwise
        displayCode = [ ...
            'color(''black'');' newline ...
            'plot([5 95 95 5 5],[10 10 90 90 10]);' newline ...
            'plot([15 85],[78 78]); plot([15 85],[22 22]);' newline ...
            'plot([18 18],[22 78]); plot([32 32],[22 78]);' newline ...
            'plot([45 45],[22 78]); plot([59 59],[22 78]);' newline ...
            'plot([72 72],[22 78]); plot([86 86],[22 78]);' newline ...
            'plot([5 15],[75 75]); plot([5 15],[60 60]); plot([5 15],[45 45]);' newline ...
            'plot([5 15],[30 30]); plot([5 15],[15 15]); plot([5 15],[10 10]);' newline ...
            'plot([85 95],[75 75]); plot([85 95],[25 25]);' ...
            ];
end
set_param(blockPath, 'Mask', 'on', 'MaskIconOpaque', 'opaque', ...
    'MaskIconFrame', 'on', 'MaskIconUnits', 'autoscale', ...
    'MaskDisplay', displayCode);
end

function add_pmio(sys, name, side, position)
blk = [sys '/' name];
add_block('built-in/PMIOPort', blk, 'Position', position);
set_param(blk, 'Side', side, 'ShowName', 'on');
end

function add_switch_bridge(M, prefix, x, y)
P = @(a, b, w, h) [a b a+w b+h];
phaseNames = {'A', 'B', 'C'};
for k = 1:3
    sx = x + (k-1) * 60;
    upper = [M '/' prefix '_S' phaseNames{k} 'U'];
    lower = [M '/' prefix '_S' phaseNames{k} 'L'];
    upperGate = [M '/' prefix '_g' phaseNames{k} 'U'];
    lowerGate = [M '/' prefix '_g' phaseNames{k} 'L'];
    add_block('powerlib/Power Electronics/IGBT', upper, ...
        'Position', P(sx, y, 42, 58));
    add_block('powerlib/Power Electronics/IGBT', lower, ...
        'Position', P(sx, y+78, 42, 58));
    add_block('simulink/Sources/Constant', upperGate, ...
        'Position', P(sx-48, y+14, 35, 20), 'Value', '0');
    add_block('simulink/Sources/Constant', lowerGate, ...
        'Position', P(sx-48, y+92, 35, 20), 'Value', '0');
    add_line(M, [prefix '_g' phaseNames{k} 'U/1'], ...
        [prefix '_S' phaseNames{k} 'U/1'], 'autorouting', 'on');
    add_line(M, [prefix '_g' phaseNames{k} 'L/1'], ...
        [prefix '_S' phaseNames{k} 'L/1'], 'autorouting', 'on');
end
end

function add_hbridge3_converter(M, prefix, x, y)
P = @(a, b, w, h) [a b a+w b+h];
phaseNames = {'A', 'B', 'C'};
for k = 1:3
    for leg = 1:2
        sx = x + (k-1) * 130 + (leg-1) * 55;
        tag = [phaseNames{k} num2str(leg)];
        upper = [M '/' prefix '_S' tag 'U'];
        lower = [M '/' prefix '_S' tag 'L'];
        upperGate = [M '/' prefix '_g' tag 'U'];
        lowerGate = [M '/' prefix '_g' tag 'L'];
        add_block('powerlib/Power Electronics/IGBT', upper, ...
            'Position', P(sx, y, 42, 58));
        add_block('powerlib/Power Electronics/IGBT', lower, ...
            'Position', P(sx, y+78, 42, 58));
        add_block('simulink/Sources/Constant', upperGate, ...
            'Position', P(sx-43, y+14, 30, 20), 'Value', '0');
        add_block('simulink/Sources/Constant', lowerGate, ...
            'Position', P(sx-43, y+92, 30, 20), 'Value', '0');
        add_line(M, [prefix '_g' tag 'U/1'], ...
            [prefix '_S' tag 'U/1'], 'autorouting', 'on');
        add_line(M, [prefix '_g' tag 'L/1'], ...
            [prefix '_S' tag 'L/1'], 'autorouting', 'on');
    end
end
end

function connect_phase_to_bridge(M, phasePort, prefix, phaseIdx)
phaseNames = {'A', 'B', 'C'};
upper = [M '/' prefix '_S' phaseNames{phaseIdx} 'U'];
lower = [M '/' prefix '_S' phaseNames{phaseIdx} 'L'];
add_line(M, phasePort, ph(upper, 'RConn', 1), 'autorouting', 'on');
add_line(M, phasePort, ph(lower, 'LConn', 1), 'autorouting', 'on');
end

function connect_hbridge_phase(M, leftPort, rightPort, prefix, phaseIdx)
phaseNames = {'A', 'B', 'C'};
leg1Upper = [M '/' prefix '_S' phaseNames{phaseIdx} '1U'];
leg1Lower = [M '/' prefix '_S' phaseNames{phaseIdx} '1L'];
leg2Upper = [M '/' prefix '_S' phaseNames{phaseIdx} '2U'];
leg2Lower = [M '/' prefix '_S' phaseNames{phaseIdx} '2L'];
add_line(M, leftPort, ph(leg1Upper, 'RConn', 1), 'autorouting', 'on');
add_line(M, leftPort, ph(leg1Lower, 'LConn', 1), 'autorouting', 'on');
add_line(M, rightPort, ph(leg2Upper, 'RConn', 1), 'autorouting', 'on');
add_line(M, rightPort, ph(leg2Lower, 'LConn', 1), 'autorouting', 'on');
end

function connect_bridge_dc(M, prefix, dcPos, dcNeg)
phaseNames = {'A', 'B', 'C'};
for k = 1:3
    upper = [M '/' prefix '_S' phaseNames{k} 'U'];
    lower = [M '/' prefix '_S' phaseNames{k} 'L'];
    add_line(M, dcPos, ph(upper, 'LConn', 1), 'autorouting', 'on');
    add_line(M, ph(lower, 'RConn', 1), dcNeg, 'autorouting', 'on');
end
end

function connect_hbridge_dc(M, prefix, dcPos, dcNeg)
phaseNames = {'A', 'B', 'C'};
for k = 1:3
    for leg = 1:2
        tag = [phaseNames{k} num2str(leg)];
        upper = [M '/' prefix '_S' tag 'U'];
        lower = [M '/' prefix '_S' tag 'L'];
        add_line(M, dcPos, ph(upper, 'LConn', 1), 'autorouting', 'on');
        add_line(M, ph(lower, 'RConn', 1), dcNeg, 'autorouting', 'on');
    end
end
end

function h = ph(blk, kind, idx)
P = get_param(blk, 'PortHandles');
h = P.(kind)(idx);
end
