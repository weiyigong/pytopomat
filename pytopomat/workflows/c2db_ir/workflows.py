from atomate.vasp.workflows.base.core import get_wf
from atomate.vasp.database import VaspCalcDb
from fireworks import LaunchPad, Workflow
import os
from atomate.vasp.powerups import (
    add_additional_fields_to_taskdocs,
    preserve_fworker,
    add_modify_incar,
    set_queue_options,
    set_execution_options,
    clean_up_files,
    add_modify_kpoints
)
import numpy as np
from pymatgen.core.structure import Structure, SymmOp
from pymatgen.symmetry.analyzer import SpacegroupAnalyzer
from pymatgen.io.vasp.sets import MPRelaxSet
from subprocess import call
from pytopomat.workflows.fireworks import IrvspFW
from mpinterfaces.utils import ensure_vacuum


c2db = VaspCalcDb.from_db_file("c2db.json")
for spg in c2db.distinct("spacegroup"):
    print(spg)
    e = c2db.find_one({"spacegroup": spg, "magstate":"NM"})
    try:
        st = e["structure"]
    except Exception:
        continue

    os.makedirs("symmetrized_st", exist_ok=True)
    os.chdir("symmetrized_st")
    st = Structure.from_dict(st)
    st = ensure_vacuum(st, 15)
    st.to("poscar", "POSCAR")
    call("phonopy --symmetry --tolerance 0.01 -c POSCAR".split(" "))
    st = Structure.from_file("PPOSCAR")
    st.to("poscar", "POSCAR")
    call("pos2aBR")
    st = Structure.from_file("POSCAR_std")
    os.chdir("..")

    wf = get_wf(st, "../irvsp_hse_sp.yaml")
    fws = wf.fws[:3]
    fw_irvsp = IrvspFW(structure=st, parents=fws[-1], additional_fields={"c2db_uid": e["uid"],
                                                                        "spg_c2db": e["spacegroup"],
                                                                        "spg": SpacegroupAnalyzer(st).get_space_group_symbol()
                                                                        })
    fws.append(fw_irvsp)
    wf = Workflow(fws, name=wf.name)

    lpad = LaunchPad.from_file(os.path.expanduser(
        os.path.join("~", "config/project/testIR/irvsp_test/my_launchpad.yaml")))
    wf = clean_up_files(wf, ("WAVECAR*", "CHGCAR*"), wf.fws[-1].name, task_name_constraint=wf.fws[-1].tasks[-1].fw_name)
    uis_encut = MPRelaxSet(st).incar.get("ENCUT", None)*1.3
    wf = add_modify_incar(wf, {"incar_update": {"ENCUT": uis_encut}})
    wf = set_execution_options(wf, category="irvsp_test")
    wf = preserve_fworker(wf)
    wf.name = wf.name + ":{}".format(spg)
    # lpad.add_wf(wf)
    print(wf)