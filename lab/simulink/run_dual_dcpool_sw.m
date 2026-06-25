function run_dual_dcpool_sw()
% run_dual_dcpool_sw.m — STAGE 2 (real switching) DC-pool validation. Bus A: deep LV sag 0.30 with
% a series-boost DC drain; Bus B: healthy 1.0, idle. Sweep the DC interlink resistance and report
% steady-state Vdc_A, Vdc_B (real switching-ripple averaged) and link current. Demonstrates the
% pool transfer through real IGBT shunt VSCs + DC link (the EM-faithful version of stage 1).
here=fileparts(mfilename('fullpath')); cd(here);
build_dual_dcpool_sw(); M='hpt_dual_dcpool_sw'; set_param(M,'StopTime','0.6');  % 0.15 PLL lock + settle
Vlv=400; IseA=90;   % ~72 kW drain @800V (between solo cap ~32A and pooled cap ~138A)
set_param([M '/SrcA'],'Voltage',num2str(Vlv*0.30));  set_param([M '/IseCmdA'],'Value',num2str(IseA));
set_param([M '/SrcB'],'Voltage',num2str(Vlv*1.00));  set_param([M '/IseCmdB'],'Value','0');
fprintf('\nSTAGE 2 (real IGBT shunt VSCs): Bus A sag 0.30 + %dA series drain (~%.0f kW) | Bus B healthy idle\n',IseA,IseA*800/1e3);
fprintf('%-22s | %-9s %-9s | %-10s | %s\n','config','Vdc_A(pu)','Vdc_B(pu)','Ilink(A)','verdict');
fprintf('%s\n',repmat('-',72,1));
for rl=[1e6 1.0 0.5 0.1]
  set_param([M '/Rlink'],'Resistance',num2str(rl));
  o=sim(M);
  VA=o.get('VdcA'); VB=o.get('VdcB'); IL=o.get('Ilink');
  n=numel(VA); w=round(0.05/20e-6);                 % average last 50 ms (ripple-averaged)
  va=mean(VA(end-w:end))/800; vb=mean(VB(end-w:end))/800; il=mean(IL(end-w:end));
  if rl>1e5, cfg='no link (solo)'; else, cfg=sprintf('link R=%.1f ohm',rl); end
  v=tern(va>=0.75,'A SURVIVES','A collapses');
  fprintf('%-22s | %8.3f %8.3f | %9.1f | %s\n',cfg,va,vb,il,v);
end
fprintf('\nExpected: solo -> Vdc_A collapses (sag-limited import < drain); link -> B''s real VSC\n');
fprintf('supplies the deficit through the DC link, Vdc_A held >=0.75. Real switching + DC ripple.\n');
end
function s=tern(c,a,b), if c,s=a;else,s=b;end, end
