function [m_energy, m_reg] = dnn_frt_policy(vdc_pu, vpu, ipu, in_fault, sc_id)
%DNN_FRT_POLICY  Stub replacement for the deleted DNN-FRT imitation model.
%
% Original file was deleted during project cleanup (2026-06-03) because
% Mode 3 (DNN imitation FRT) was superseded by FAHC (Mode 7) and SAC (SAC直接调制).
%
% This stub returns standard modulation indices so the model compiles.
% It is ONLY called when ControllerMode == 3, which is not used in any
% current validation run.  All active modes (4, 6, 7, 9) bypass this code.
%
% Inputs:
%   vdc_pu   : DC link voltage per unit [0, 2]
%   vpu      : Secondary voltage per unit [0, 2]
%   ipu      : Secondary current per unit [0, 5]
%   in_fault : Binary fault flag (0 or 1)
%   sc_id    : Fault scenario ID (integer 0-8)
%
% Outputs:
%   m_energy : Energy VSC modulation index [0, 1]
%   m_reg    : Regulation VSC modulation index [0, 0.30]

%#codegen

% Simple rule-based fallback (same as Mode 2 rule FRT)
sag = max(0.0, 0.98 - vpu);
m_reg    = min(0.24, max(0.02, 0.045 + 0.42 * sag));
m_energy = min(0.90, max(0.20, 0.68 + 0.30 * (vdc_pu - 1.0)));
end
