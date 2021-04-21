from pytopomat.irvsp_caller import IRVSPOutput
import os
from monty.serialization import dumpfn

test_dir = "launcher_2021-04-17-06-51-55-570379/"

irvsp_output = IRVSPOutput(os.path.join(test_dir, "outir.txt"), os.path.join(test_dir, "KPOINTS"))
print(irvsp_output.as_dict())
dumpfn(irvsp_output, os.path.join("output.json"), indent=4)