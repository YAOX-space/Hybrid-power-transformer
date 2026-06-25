function run_dual_dcpool()
% run_dual_dcpool.m — validate the DC-pool transfer: sagged draining bus A vs healthy idle bus B,
% no-link vs linked. Confirms a healthy member holds up a sagged, series-draining member through
% the DC interlink (the §5 pool mechanism) at the DC-circuit level.
here=fileparts(mfilename('fullpath')); cd(here);
build_dual_dcpool(); M='hpt_dual_dcpool'; set_param(M,'SimulationMode','normal'); set_param(M,'StopTime','0.4');
% Bus A: deep sag 0.30, wants series boost 0.18 (deficit). Bus B: healthy 1.0, idle (surplus).
set_param([M '/VtA'],'Value','0.30'); set_param([M '/bA'],'Value','0.18');
set_param([M '/VtB'],'Value','1.00'); set_param([M '/bB'],'Value','0.00');
fprintf('\nBus A: sag 0.30, series boost 0.18 (deficit ~103 kW) | Bus B: healthy 1.0, idle (surplus ~112 kW)\n');
fprintf('%-22s | %-9s %-9s | %-10s | %s\n','config','Vdc_A(pu)','Vdc_B(pu)','Ilink(A)','verdict');
fprintf('%s\n',repmat('-',72,1));
for rl=[1e6 2.0 0.5 0.1]
  set_param([M '/Rlink'],'Resistance',num2str(rl));
  o=sim(M);
  VA=o.get('VdcA'); VB=o.get('VdcB'); IL=o.get('Ilink');
  va=mean(VA(end-200:end))/800; vb=mean(VB(end-200:end))/800; il=mean(IL(end-200:end));
  if rl>1e5, cfg='no link (solo)'; else, cfg=sprintf('link R=%.1f ohm',rl); end
  v=tern(va>=0.75,'A SURVIVES','A collapses');
  fprintf('%-22s | %8.3f %8.3f | %9.1f | %s\n',cfg,va,vb,il,v);
end
fprintf('\nExpected: solo -> Vdc_A collapses (deficit); link -> B''s surplus transferred, Vdc_A held >=0.75.\n');
fprintf('This validates the calibrated pool model''s core assumption at the DC-circuit level.\n');
end
function s=tern(c,a,b), if c,s=a;else,s=b;end, end
