from pytopomat.irvsp_caller import IRVSPOutput
import os
from monty.serialization import dumpfn
from pymatgen.io.vasp.inputs import Kpoints

test_dir = "launcher_2021-04-21-02-41-44-640478"

irvsp_output = IRVSPOutput(os.path.join(test_dir, "outir.txt"), Kpoints.from_file(os.path.join(test_dir, "KPOINTS")))
print(irvsp_output.as_dict())
