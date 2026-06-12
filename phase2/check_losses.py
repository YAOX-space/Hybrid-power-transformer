import os
os.environ.setdefault('KMP_DUPLICATE_LIB_OK', 'TRUE')
os.environ.setdefault('MKL_THREADING_LAYER', 'SEQUENTIAL')
from pathlib import Path
import opendssdirect as dss

dss.Text.Command(f'compile "{Path(__file__).resolve().parent / "ieee33.dss"}"')
dss.Solution.Solve()
print(f'converged={dss.Solution.Converged()}  losses={dss.Circuit.Losses()[0]/1000.0:.2f} kW (canonical ~210.98)')
