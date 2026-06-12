function diag_policy()
% diag_policy.m — forward the exported expert .mat policies over a positive-seq sweep,
% exactly as the HLC does, to see what iq (reactive) each commands on undervoltage.
here=fileparts(mfilename('fullpath')); cd(here);
names={'asym','sym','hvrt_sym','hvrt_asym'}; fpmap=[2 1 5 5];
for n=1:numel(names)
  W=load(['sac_' names{n} '_weights.mat']);
  fprintf('\n=== %s expert (fp=%d) ===\n', names{n}, fpmap(n));
  fprintf('%5s %5s %7s | %7s %7s %7s %7s\n','V2p','V2n','iq_ref','iq','id','mse_d','mse_q');
  if ~isempty(strfind(names{n},'hvrt')), rows=[1.30 0.05; 1.25 0.04; 1.20 0.03; 1.15 0.02];
  else, rows=[0.85 .10; 0.80 .12; 0.70 .15; 0.60 .18; 0.50 .20; 0.40 .22]; end
  for r=1:size(rows,1)
    V2p=rows(r,1); V2n=rows(r,2);
    obs=build_obs(V2p,V2n,fpmap(n));
    a=fwd(W,obs);
    if V2p<0.9, iqr=min(0.30,1.5*(0.9-V2p)); elseif V2p>1.1, iqr=max(-0.30,-1.5*(V2p-1.1)); else, iqr=0; end
    fprintf('%5.2f %5.2f %7.3f | %7.3f %7.3f %7.3f %7.3f\n', V2p,V2n,iqr, a(2),a(1),a(3),a(4));
  end
end
fprintf('\n(iq>0 = inject capacitive = correct for undervoltage; iq<0 = absorb = wrong)\n');
end

function obs=build_obs(V2p,V2n,fp,infault,Vdc,tfrac,la)
  if nargin<4, infault=1; end; if nargin<5, Vdc=1.0; end
  if nargin<6, tfrac=0.3; end; if nargin<7, la=[0;0;0;0]; end
  vdev=0.9-V2p; iq=la(2);
  if V2p<0.9, iqr=min(0.30,1.5*(0.9-V2p)); elseif V2p>1.1, iqr=max(-0.30,-1.5*(V2p-1.1)); else, iqr=0; end
  iqerr=iqr-iq; probs=zeros(6,1);
  if infault>0.5, probs(fp+1)=0.92; probs(1)=probs(1)+0.08; else, probs(1)=1; end
  obs=[Vdc;V2p;V2n;abs(iq);0;0;vdev;iqerr;iq;probs;tfrac;infault;la(1);la(2);la(3);la(4)];
  obs=max(-5,min(5,obs));
end

function a=fwd(W,obs)
  W0=reshape(W.latent_pi_0_weight,256,21); b0=reshape(W.latent_pi_0_bias,256,1);
  W2=reshape(W.latent_pi_2_weight,256,256); b2=reshape(W.latent_pi_2_bias,256,1);
  W4=reshape(W.latent_pi_4_weight,256,256); b4=reshape(W.latent_pi_4_bias,256,1);
  Wm=reshape(W.mu_weight,4,256); bm=reshape(W.mu_bias,4,1);
  alo=reshape(W.act_low,4,1); ahi=reshape(W.act_high,4,1);
  h=max(0,W0*obs+b0); h=max(0,W2*h+b2); h=max(0,W4*h+b4);
  mu=Wm*h+bm; at=tanh(mu); a=alo+0.5*(at+1).*(ahi-alo);
end
