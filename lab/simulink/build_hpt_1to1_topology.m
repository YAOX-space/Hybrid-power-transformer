function build_hpt_1to1_topology()
% build_hpt_1to1_topology
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
% This is a topology skeleton.  Converter gates are held off by default;
% control/PWM migration and parameter calibration should be done in a later
% step.

M = 'hpt_1to1_topology';
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
    y = 80 + (k-1) * 85;
    blk = [M sprintf('/Main_W1W2_%d', k)];
    add_block('powerlib/Elements/Linear Transformer', blk, ...
        'Position', P(365, y, 90, 70));
    set_param(blk, 'ThreeWindings', 'off', ...
        'NominalPower', ['[' num2str(Srated/3) ',' num2str(f0) ']'], ...
        'winding1', ['[' num2str(Vmv/sqrt(3)) ',0.005,0.025]'], ...
        'winding2', ['[' num2str(Vlv/sqrt(3)) ',0.005,0.025]']);
end

% New flexible distribution transformer W3/W4.
for k = 1:3
    x = 330 + (k-1) * 85;
    blk = [M sprintf('/Flex_W3W4_%d', k)];
    add_block('powerlib/Elements/Linear Transformer', blk, ...
        'Position', P(x, 365, 70, 70));
    set_param(blk, 'ThreeWindings', 'off', ...
        'NominalPower', ['[' num2str(Saux/3) ',' num2str(f0) ']'], ...
        'winding1', ['[' num2str(Vlv/sqrt(3)) ',0.005,0.02]'], ...
        'winding2', ['[' num2str(Vaux/sqrt(3)) ',0.005,0.02]']);
end

% Series injection transformer W5/W6.  W6 is in the load path; W5 is fed by
% the regulating converter.
for k = 1:3
    y = 80 + (k-1) * 85;
    blk = [M sprintf('/Series_W5W6_%d', k)];
    add_block('powerlib/Elements/Linear Transformer', blk, ...
        'Position', P(590, y, 90, 65));
    set_param(blk, 'ThreeWindings', 'off', ...
        'NominalPower', ['[' num2str(Sser) ',' num2str(f0) ']'], ...
        'winding1', ['[' num2str(Vw5) ',0.002,0.03]'], ...
        'winding2', ['[' num2str(Vw6) ',0.002,0.03]']);
end

add_block('powerlib/Measurements/Three-Phase V-I Measurement', [M '/MeasLV'], ...
    'Position', P(735, 115, 70, 90));
set_param([M '/MeasLV'], 'VoltageMeasurement', 'phase-to-ground', ...
    'CurrentMeasurement', 'no');

add_block('powerlib/Elements/Three-Phase Series RLC Load', [M '/Load'], ...
    'Position', P(875, 125, 70, 70));
set_param([M '/Load'], 'NominalVoltage', num2str(Vlv), ...
    'NominalFrequency', num2str(f0), 'ActivePower', num2str(Srated), ...
    'InductivePower', '0', 'CapacitivePower', '0', ...
    'Configuration', 'Y (grounded)');

% Energy converter chain: W4 -> measurement -> RL filter -> ShVSC.
add_block('powerlib/Measurements/Three-Phase V-I Measurement', [M '/MeasEnergy'], ...
    'Position', P(565, 375, 70, 90));
set_param([M '/MeasEnergy'], 'VoltageMeasurement', 'phase-to-ground', ...
    'CurrentMeasurement', 'yes');

add_block('powerlib/Elements/Three-Phase Series RLC Branch', [M '/Energy_RL'], ...
    'Position', P(670, 385, 55, 60));
set_param([M '/Energy_RL'], 'BranchType', 'RL', 'Resistance', num2str(Rtake), ...
    'Inductance', num2str(Ltake));

add_block('powerlib/Power Electronics/Universal Bridge', [M '/Energy_VSC'], ...
    'Position', P(770, 365, 85, 115));
set_param([M '/Energy_VSC'], 'Arms', '3', 'Device', 'IGBT / Diodes');

add_block('powerlib/Power Electronics/Universal Bridge', [M '/Regulating_VSC'], ...
    'Position', P(365, 555, 85, 115));
set_param([M '/Regulating_VSC'], 'Arms', '3', 'Device', 'IGBT / Diodes');

add_block('powerlib/Elements/Series RLC Branch', [M '/Cdc'], ...
    'Position', P(920, 385, 40, 75));
set_param([M '/Cdc'], 'BranchType', 'C', 'Capacitance', num2str(Cdc), ...
    'Setx0', 'on', 'InitialVoltage', '800');

add_block('powerlib/Measurements/Voltage Measurement', [M '/MeasVdc'], ...
    'Position', P(985, 385, 45, 45));

add_block('powerlib/Power Electronics/IGBT', [M '/Chop'], ...
    'Position', P(1070, 385, 40, 55));
add_block('powerlib/Elements/Series RLC Branch', [M '/Rchop'], ...
    'Position', P(1070, 465, 45, 55));
set_param([M '/Rchop'], 'BranchType', 'R', 'Resistance', num2str(Rchop));

% Ground references for the single-phase winding groups.
add_block('powerlib/Elements/Ground', [M '/W1_neutral_ground'], ...
    'Position', P(315, 300, 25, 25));
add_block('powerlib/Elements/Ground', [M '/W2_neutral_ground'], ...
    'Position', P(490, 300, 25, 25));
add_block('powerlib/Elements/Ground', [M '/W3_neutral_ground'], ...
    'Position', P(305, 470, 25, 25));
add_block('powerlib/Elements/Ground', [M '/W4_neutral_ground'], ...
    'Position', P(520, 470, 25, 25));

% Safe default gates: both bridges are off in the topology skeleton.
add_block('simulink/Sources/Constant', [M '/Energy_VSC_gates'], ...
    'Position', P(665, 510, 70, 25), 'Value', 'zeros(6,1)');
add_block('simulink/Sources/Constant', [M '/Regulating_VSC_gates'], ...
    'Position', P(245, 575, 70, 25), 'Value', 'zeros(6,1)');
add_block('simulink/Sources/Constant', [M '/Chop_gate'], ...
    'Position', P(995, 490, 60, 25), 'Value', '0');

% Logging.
add_block('simulink/Sinks/To Workspace', [M '/Vmv_abc'], ...
    'Position', P(990, 90, 85, 25), 'VariableName', 'Vmv_abc', ...
    'SaveFormat', 'Array', 'SampleTime', num2str(Ts));
add_block('simulink/Sinks/To Workspace', [M '/Vlv_abc'], ...
    'Position', P(990, 125, 85, 25), 'VariableName', 'Vlv_abc', ...
    'SaveFormat', 'Array', 'SampleTime', num2str(Ts));
add_block('simulink/Sinks/To Workspace', [M '/Vdc'], ...
    'Position', P(1040, 385, 70, 25), 'VariableName', 'Vdc', ...
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
        ph([M '/Energy_VSC'], 'LConn', k), 'autorouting', 'on');

    % W5 is driven by the regulating converter; W6 is the line-side series winding.
    add_line(M, ph([M '/Regulating_VSC'], 'LConn', k), ...
        ph([M sprintf('/Series_W5W6_%d', k)], 'LConn', 1), 'autorouting', 'on');
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

% Regulating converter side W5 neutral is floating, matching the previous
% series-injection practice and avoiding an artificial ground path.
connect3(M, 'Series_W5W6', 'LConn', 2);

% Shared DC link and chopper.
add_line(M, ph([M '/Energy_VSC'], 'RConn', 1), ph([M '/Cdc'], 'LConn', 1), ...
    'autorouting', 'on');
add_line(M, ph([M '/Cdc'], 'RConn', 1), ph([M '/Energy_VSC'], 'RConn', 2), ...
    'autorouting', 'on');
add_line(M, ph([M '/Regulating_VSC'], 'RConn', 1), ph([M '/Energy_VSC'], 'RConn', 1), ...
    'autorouting', 'on');
add_line(M, ph([M '/Regulating_VSC'], 'RConn', 2), ph([M '/Energy_VSC'], 'RConn', 2), ...
    'autorouting', 'on');
add_line(M, ph([M '/MeasVdc'], 'LConn', 1), ph([M '/Energy_VSC'], 'RConn', 1), ...
    'autorouting', 'on');
add_line(M, ph([M '/MeasVdc'], 'LConn', 2), ph([M '/Energy_VSC'], 'RConn', 2), ...
    'autorouting', 'on');
add_line(M, ph([M '/Energy_VSC'], 'RConn', 1), ph([M '/Chop'], 'LConn', 1), ...
    'autorouting', 'on');
add_line(M, ph([M '/Chop'], 'RConn', 1), ph([M '/Rchop'], 'LConn', 1), ...
    'autorouting', 'on');
add_line(M, ph([M '/Rchop'], 'RConn', 1), ph([M '/Energy_VSC'], 'RConn', 2), ...
    'autorouting', 'on');

% Signal wiring.
add_line(M, 'Energy_VSC_gates/1', 'Energy_VSC/1', 'autorouting', 'on');
add_line(M, 'Regulating_VSC_gates/1', 'Regulating_VSC/1', 'autorouting', 'on');
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
fprintf('Built %s.slx with W1/W2, W3/W4, and W5/W6 reference structure.\\n', M);
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
        set_param(blocks{i}, 'ShowName', 'on', 'FontName', 'Arial', 'FontSize', '10');
    catch
    end
end

labels = {
    'MAIN TRANSFORMER W1/W2', [370 45 570 70]
    'FLEXIBLE DISTRIBUTION TRANSFORMER W3/W4', [325 335 610 360]
    'SERIES INJECTION TRANSFORMERS W5/W6', [585 45 820 70]
    'ENERGY CONVERTER', [765 335 900 360]
    'REGULATING CONVERTER', [360 525 520 550]
    'SHARED DC LINK', [915 335 1040 360]
};
for i = 1:size(labels, 1)
    a = Simulink.Annotation(M, labels{i, 1});
    a.Position = labels{i, 2};
    a.FontName = 'Arial';
    a.FontSize = 14;
    a.FontWeight = 'bold';
end
end

function h = ph(blk, kind, idx)
P = get_param(blk, 'PortHandles');
h = P.(kind)(idx);
end
