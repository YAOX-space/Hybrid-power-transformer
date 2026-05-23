% test_sim_batch.m — minimal Simulink headless test
new_system('test_sim');
add_block('simulink/Sources/Sine Wave', 'test_sim/Sine');
add_block('simulink/Sinks/To Workspace', 'test_sim/Out');
add_line('test_sim', 'Sine/1', 'Out/1');
set_param('test_sim', 'Solver', 'ode45', 'StopTime', '0.1');
set_param('test_sim/Out', 'VariableName', 'y', 'SaveFormat', 'Array');
out = sim('test_sim');
fprintf('Headless sim OK — samples: %d\n', numel(out.y));
close_system('test_sim', 0);
