"""pytest config — NO sys.path injection. The package is imported as installed (`pip install -e .`);
tests use fully-qualified `hpt_frt.*` imports. The pytest process itself never imports the OpenDSS
backend (network.sequence/opendss_runner) directly — packaging tests load those in a SUBPROCESS — so
pytest exits cleanly (no 0xe0465043 backend crash at interpreter teardown)."""
import os
os.environ.setdefault('KMP_DUPLICATE_LIB_OK', 'TRUE')
os.environ.setdefault('MKL_THREADING_LAYER', 'SEQUENTIAL')
