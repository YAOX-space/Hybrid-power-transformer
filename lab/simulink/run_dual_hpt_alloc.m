function run_dual_hpt_alloc()
% run_dual_hpt_alloc.m — STAGE 3 synthesis: pool + allocator. HPT-A under deep sym sag runs mode-14
% SAC. The raw SAC self-limits series boost to its single-device DC budget (~0.06 pu) and never
% stresses the DC bus -> pool idle. When the §5 allocator GRANTS HPT-A extra series budget (cap
% multiplier G>1), A now wants a big boost: SOLO it must source the DC itself (sagged shunt can't ->
% Vdc collapses, boost not sustained); POOLED, healthy B feeds the deficit through the DC link ->
% Vdc held -> the granted boost is sustained -> deeper load-voltage recovery. This is §5 (hardware
% pool + allocation intelligence) realized at the real switching level.
here=fileparts(mfilename('fullpath')); cd(here);
build_dual_hpt_sac(); M='hpt_dual_hpt_sac'; set_param(M,'StopTime','0.6');
p=pu_params(); Vlv=400; Vn=p.VLN_peak; sag=0.30;
set_param([M '/SrcA'],'Voltage',num2str(Vlv*sag)); set_param([M '/SrcB'],'Voltage',num2str(Vlv*1.0));
set_param([M '/SEgB'],'Gain','1');                 % B is healthy donor, no boost
mag=@(V,k) sqrt(((2/3)*(V(1,k)-0.5*V(2,k)-0.5*V(3,k)))^2 + ((2/3)*(sqrt(3)/2)*(V(2,k)-V(3,k)))^2)/Vn;
avgmag=@(V,a,b) mean(arrayfun(@(k)mag(V,k), a:b));
fprintf('\nSTAGE 3 synthesis (pool + allocator): HPT-A sym sag %.2f, mode-14 SAC | HPT-B healthy donor\n',sag);
fprintf('%-32s | %-9s %-9s | %s\n','config','Vy_A(pu)','Vdc_A(pu)','Ilink(A)');
fprintf('%s\n',repmat('-',70,1));
runs={ {1,1e6,'raw SAC (G=1), SOLO'}, {1,0.5,'raw SAC (G=1), POOLED'}, ...
       {5,1e6,'allocator G=5, SOLO'}, {5,0.5,'allocator G=5, POOLED'} };
for i=1:numel(runs)
  G=runs{i}{1}; rl=runs{i}{2}; lbl=runs{i}{3};
  set_param([M '/SEgA'],'Gain',num2str(G)); set_param([M '/Rlink'],'Resistance',num2str(rl));
  o=sim(M);
  VyA=squeeze(o.get('VyA')); if size(VyA,1)~=3, VyA=VyA'; end
  VdcA=o.get('VdcA'); IL=o.get('Ilink'); N=size(VyA,2); w=round(0.05/20e-6);
  vy=avgmag(VyA,N-w,N); va=mean(VdcA(end-w:end))/800; il=mean(IL(end-w:end));
  fprintf('%-32s | %8.3f  %8.3f | %8.1f\n',lbl,vy,va,il);
end
fprintf('\nRaw SAC: pool idle (SAC self-limits, Vdc healthy). Allocator-granted boost: SOLO drains/\n');
fprintf('collapses A''s Vdc; POOLED, B feeds the deficit -> Vdc held -> boost sustained -> higher Vy_A.\n');
end
