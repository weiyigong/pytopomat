from pytopomat.irvsp_caller import IRVSPOutput
import os
from monty.serialization import dumpfn
from pymatgen.io.vasp.inputs import Kpoints

test_dir = "launcher_2021-04-17-06-51-55-570379/"

irvsp_output = IRVSPOutput(os.path.join(test_dir, "outir.txt"), Kpoints.from_file(os.path.join(test_dir, "KPOINTS")))
print(irvsp_output.as_dict())
