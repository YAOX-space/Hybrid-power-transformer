function run_dual_hpt_sac()
% run_dual_hpt_sac.m — STAGE 3 synthesis test. HPT-A under a deep symmetric LV sag runs the real
% mode-14 residual SAC; HPT-B healthy idle. Compare A's protected load voltage (Vy_A) and Vdc_A
% SOLO (no DC link) vs POOLED (DC interlink to healthy B). Claim: pooling holds Vdc_A up so the
% SAC's series boost is not DC-budget-throttled -> deeper load-voltage recovery.
here=fileparts(mfilename('fullpath')); cd(here);
build_dual_hpt_sac(); M='hpt_dual_hpt_sac'; set_param(M,'StopTime','0.6');
p=pu_params(); Vlv=400; Vn=p.VLN_peak;
set_param([M '/SrcB'],'Voltage',num2str(Vlv*1.0));
mag=@(V,k) sqrt(((2/3)*(V(1,k)-0.5*V(2,k)-0.5*V(3,k)))^2 + ((2/3)*(sqrt(3)/2)*(V(2,k)-V(3,k)))^2)/Vn;
avgmag=@(V,a,b) mean(arrayfun(@(k)mag(V,k), a:b));
fprintf('\nSTAGE 3: HPT-A sym sag running mode-14 SAC | HPT-B healthy idle. SOLO vs POOLED(R=0.5).\n');
fprintf('%-7s | %-8s %-8s | %-8s %-8s | %-8s | %s\n','sag','Vy_SOLO','Vy_POOL','Vdc_SOLO','Vdc_POOL','dVy(pp)','Ilink');
fprintf('%s\n',repmat('-',78,1));
for sag=[0.30 0.20 0.12]
  set_param([M '/SrcA'],'Voltage',num2str(Vlv*sag));
  res=zeros(2,3);  % [vy vdc il] x [solo pooled]
  c=0;
  for rl=[1e6 0.5]
    c=c+1; set_param([M '/Rlink'],'Resistance',num2str(rl)); o=sim(M);
    VyA=squeeze(o.get('VyA')); if size(VyA,1)~=3, VyA=VyA'; end
    VdcA=o.get('VdcA'); IL=o.get('Ilink'); N=size(VyA,2); w=round(0.05/20e-6);
    res(c,:)=[avgmag(VyA,N-w,N), mean(VdcA(end-w:end))/800, mean(IL(end-w:end))];
  end
  fprintf('%5.2f   | %7.3f  %7.3f  | %7.3f  %7.3f  | %+7.1f  | %7.1f\n', ...
    sag,res(1,1),res(2,1),res(1,2),res(2,2),100*(res(2,1)-res(1,1)),res(2,3));
end
fprintf('\ndVy = POOLED - SOLO load-voltage gain (pp). Pool holds Vdc up -> series boost un-throttled.\n');
end
function s=tern(c,a,b), if c,s=a;else,s=b;end, end
