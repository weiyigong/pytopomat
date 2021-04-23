"""
Interface to irvsp.

"""

import warnings
import os
from os import path
import subprocess

from monty.json import MSONable
from monty.dev import requires
from monty.os.path import which
from monty.serialization import loadfn

from pymatgen.symmetry.analyzer import SpacegroupAnalyzer
from pymatgen.core import Structure
from pymatgen.io.vasp.outputs import Kpoints

import numpy as np

__author__ = "Nathan C. Frey, Jason Munro"
__copyright__ = "MIT License"
__version__ = "0.0.1"
__maintainer__ = "Nathan C. Frey, Jason, Munro"
__email__ = "ncfrey@lbl.gov, jmunro@lbl.gov"
__status__ = "Development"
__date__ = "August 2019"

IRVSPEXE = which("irvsp")


class IRVSPCaller:
    @requires(
        IRVSPEXE,
        "IRVSPCaller requires irvsp to be in the path.\n"
        "Please follow the instructions in https://arxiv.org/pdf/2002.04032.pdf\n"
        "https://github.com/zjwang11/irvsp/blob/master/src_irvsp_v2.tar.gz",
    )
    def __init__(self, folder_name, set_spn=None):
        """
        Run irvsp to compute irreducible representations (irreps) of electronic states from wavefunctions (WAVECAR) and
        symmetry operations (OUTCAR).

        Requires a calculation with ISYM=1,2 and LWAVE=.TRUE.

        Something like "phonopy --tolerance 0.01 --symmetry -c POSCAR" should be used to ensure
        the crystal is in a standard setting before the calculation.

        irvsp v2 is needed to handle all 230 space groups (including nonsymmorphic sgs).

        Args:
            folder_name (str): Path to directory with POSCAR, OUTCAR and WAVECAR at kpts where irreps should be computed.
        """

        # Check for OUTCAR and WAVECAR
        if (
            not path.isfile(folder_name + "/OUTCAR")
            or not path.isfile(folder_name + "/WAVECAR")
            or not path.isfile(folder_name + "/POSCAR")
        ):
            raise FileNotFoundError()

        os.chdir(folder_name)

        # Get sg number of structure
        s = Structure.from_file("POSCAR")
        sga = SpacegroupAnalyzer(s, symprec=0.01)
        sgn = set_spn if set_spn else sga.get_space_group_number()
        v = 1  # version 1 of irvsp, symmorphic symmetries

        # Check if symmorphic (same symm elements as corresponding point group)
        # REF: http://kuchem.kyoto-u.ac.jp/kinso/weda/data/group/space.pdf
        fpath = os.path.join(os.path.dirname(__file__), "symmorphic_spacegroups.json")
        ssgs = loadfn(fpath)["ssgs"]

        # Remove SGOs from OUTCAR other than identity and inversion to avoid errors

        # if sgn not in ssgs:  # non-symmorphic; this doesn't work!
        #     # print("spacegroup is non-symmorphic, Ci hase forced!")
        #     print("spacegroup is non-symmorphic, version-2 hase forced!")
        #     # self.modify_outcar()
        #     v = 2 # SG 2 (only E and I)

        # Call irvsp
        cmd_list = ["irvsp", "-sg", str(sgn), "-v", str(v)]
        with open("outir.txt", "w") as out, open("err.txt", "w") as err:
            process = subprocess.Popen(cmd_list, stdout=out, stderr=err)

        process.communicate()  # pause while irvsp is executing

        self.output = None

        # Process output
        if path.isfile("outir.txt"):
            try:
                self.output = IRVSPOutput("outir.txt", Kpoints.from_file("KPOINTS"))
            except Exception as er:
                print(er)
                self.output = IRVSPOutputAll("outir.txt")

        else:
            raise FileNotFoundError()

    @staticmethod
    def modify_outcar(name="OUTCAR.bkp"):
        """
        Delete all space group ops from OUTCAR except for identity (E) and
        inversion (I). This allows the command "irvsp -sg 2 -v 1" to 
        compute only I eigenvalues.

        Must be run in a directory with OUTCAR.

        Args:
            name (str): Name for unmodified copy of OUTCAR.

        """

        # Check for OUTCAR and CONTCAR
        if not path.isfile("OUTCAR"):
            raise FileNotFoundError()

        irot_start = -1
        num_ops = -1
        identity_op = "    1     1.000000     0.000000     1.000000     0.000000     0.000000     0.000000     0.000000     0.000000\n"

        inv_op = "    2    -1.000000     0.000000     1.000000     0.000000     0.000000     0.000000     0.000000     0.000000\n"

        sgo_lines = []  # OUTCAR lines with superfluous SGOs

        # Write a temp file without the extra SGOs
        with open("OUTCAR", "r") as f:
            with open("temp.txt", "w") as output:
                lines = f.readlines()

                for idx, line in enumerate(lines):
                    if "INISYM" in line:
                        line_list = [i for i in line.strip().split(" ") if i]
                        num_ops = int(line_list[4])
                    if "irot" in line:  # Start of SGOs
                        irot_start = idx
                        sgo_lines = list(range(idx + 1, idx + num_ops + 1))
                    if idx == irot_start + num_ops:
                        output.write(identity_op)
                        output.write(inv_op) 
                        output.write("\n")
                    if idx not in sgo_lines:
                        output.write(line)


        os.rename("OUTCAR", name)
        os.rename("temp.txt", "OUTCAR")


class IRVSPOutput(MSONable):
    def __init__(
        self,
        irvsp_output,
        kpoints,
        symmorphic=None,
        inversion=None,
        soc=None,
        spin_polarized=None,
        parity_eigenvals=None,
    ):
        """
        This class processes results from irvsp to get irreps of electronic states. 

        Refer to https://arxiv.org/pdf/2002.04032.pdf for further explanation of parameters.

        Args:
            irvsp_output (txt file): output from irvsp.
            symmorphic (Bool): Symmorphic space group?
            inversion (Bool): Centrosymmetric space group?
            soc (Bool): Spin-orbit coupling included?
            spin_polarized (Bool): Spin-polarized system?
            parity_eigenvals (dict): band index, band degeneracy, energy eigenval, Re(parity eigenval)

        """

        self._irvsp_output = irvsp_output

        self.symmorphic = symmorphic
        self.inversion = inversion
        self.soc = soc
        self.spin_polarized = spin_polarized
        self.parity_eigenvals = parity_eigenvals
        self.kpoints = kpoints
        self._parse_stdout(irvsp_output, kpoints)

    def _parse_stdout(self, irvsp_output, kpoints):

        # try:
            with open(irvsp_output, "r") as file:
                lines = file.readlines()

                # Get header info
                symm_line = lines[7]
                if "Non-symmorphic" in symm_line:
                    symmorphic = False
                else:
                    symmorphic = True

                if "without" in symm_line:
                    inversion = False
                else:
                    inversion = True

                soc_line = lines[9]
                if "No" in soc_line:
                    soc = False
                else:
                    soc = True

                sp_line = lines[10]
                if "No" in sp_line:
                    spin_polarized = False
                else:
                    spin_polarized = True

                self.symmorphic = symmorphic
                self.inversion = inversion
                self.soc = soc
                self.spin_polarized = spin_polarized

                # Define TRIM labels in units of primitive reciprocal vectors
                #******

                # trim_labels = ["gamma", "x", "y", "z", "s", "t", "u", "r"]
                # trim_pts = [
                #     (0.0, 0.0, 0.0),
                #     (0.5, 0.0, 0.0),
                #     (0.0, 0.5, 0.0),
                #     (0.0, 0.0, 0.5),
                #     (0.5, 0.5, 0.0),
                #     (0.0, 0.5, 0.5),
                #     (0.5, 0.0, 0.5),
                #     (0.5, 0.5, 0.5),
                # ]

                # trim_dict = {pt: label for (pt, label) in zip(trim_pts, trim_labels)}
                trim_dict = dict(zip(kpoints.labels, kpoints.kpts))
                if "None" in trim_dict:
                    trim_dict.pop("None")
                if None in trim_dict:
                    trim_dict.pop(None)
                if "" in trim_dict:
                    trim_dict.pop(None)
                if " " in trim_dict:
                    trim_dict.pop(None)

                trim_dict = {pt: label for (pt, label) in zip([(round(pt[0], 3), round(pt[1], 3), round(pt[2], 3))
                                                               for pt in list(trim_dict.values())], trim_dict.keys())}
                #*******
                # Dicts with kvec index as keys
                parity_eigenvals = {}

                # Start of irrep trace info
                for idx, line in enumerate(lines):
                    if "*****" in line:
                        block_start = idx + 1
                        break

                kpt_wanted, trace_start = False, False
                for idx, line in enumerate(lines[block_start:]):
                    if line.startswith("k = "):  # New kvec
                        line_list = line.split(" ")[2:]
                        try:
                            kvec = tuple([round(float(i),3) for i in line_list])
                        except:
                            continue
                        if kvec not in list(trim_dict.keys()):
                            continue
                        trim_label = trim_dict[kvec]
                        kpt_wanted = True

                    if "The point group is" in line and kpt_wanted:
                        point_gp_at_k = line.split("The point group is")[1].strip()
                        pg_character_table = []
                    if "                   E" in line and kpt_wanted:
                        pg_character_table.append(line.strip())
                    if "       G" in line and kpt_wanted:
                        pg_character_table.append(line.strip())


                    if "bnd ndg" in line and kpt_wanted:  # find inversion symmop position
                        print(line)
                        trace_start = True  # Start of block of traces
                        bnds, ndgs, bnd_evs, inv_evs, reps = [], [], [], [], []
                        line_list = line.strip().split(" ")
                        symmops = [i for i in line_list if i]
                        inv_num = symmops.index("E") - 3  # subtract bnd, ndg, ev
                        num_ops = len(symmops) - 3  # subtract bnd, ndg, ev
                    if kpt_wanted and trace_start and "0" in line:  # full trace line, not a blank line
                        head_line = line.split()
                        try:
                            bdx = int(head_line[0])
                        except:
                            continue
                        line_list = line[6:].strip()
                        line_list = line_list.split("=", 1)[0]

                          # delete irrep label at end of line
                        #line_list = [i for i in line_list.split(" ") if i]

                        # Check that trace line is complete, no ?? or error
                        if len(line_list) > 30 and len(line.split("=")) == 2:  # symmops + band eigenval
                            bnd = int(line[:3].strip())  # band index
                            ndg = int(line[3:6].strip())  # band degeneracy
                            bnd_ev = float(line[6:16].strip())
                            # inv_ev = float(line[27:33].strip())
                            irs = line.split("=")[1]

                            # if not np.isclose(inv_ev%1.0, 0.0, rtol=0, atol=0.03) or \
                            #    not np.isclose(inv_ev%1.0, 1.0, rtol=0, atol=0.03):
                            #    warnings.warn("IRVSP output data has non-integer parity eigenvalues!")
                            bnds.append(bnd)
                            ndgs.append(ndg)
                            bnd_evs.append(bnd_ev)
                            # inv_evs.append(inv_ev)
                            reps.append(irs)

                    if "*****" in line:  # end of block
                        kpt_start = False
                        trace_start = False
                        kvec_data = {
                            "band_index": bnds,
                            "band_degeneracy": ndgs,
                            "band_eigenval": bnd_evs,
                            # "inversion_eigenval": inv_evs,
                            "irreducible_reps": reps,
                            "point_group": point_gp_at_k,
                            "pg_character_table": pg_character_table
                        }
                        if self.spin_polarized:
                            if trim_label in parity_eigenvals.keys():
                                parity_eigenvals[trim_label]["down"] = kvec_data
                            else:
                                parity_eigenvals[trim_label] = {"up": kvec_data}
                        else:
                            parity_eigenvals[trim_label] = kvec_data

            self.parity_eigenvals = parity_eigenvals

        # except Exception as er:
        #     warnings.warn(
        #         "irvsp output not found. Setting instance attributes from direct inputs!"
        #     )
        #     print(er)

class IRVSPOutputAll(MSONable):
    def __init__(
            self,
            irvsp_output,
            symmorphic=None,
            inversion=None,
            soc=None,
            spin_polarized=None,
            parity_eigenvals=None,
    ):
        """
        This class processes results from irvsp to get irreps of electronic states.

        Refer to https://arxiv.org/pdf/2002.04032.pdf for further explanation of parameters.

        Args:
            irvsp_output (txt file): output from irvsp.
            symmorphic (Bool): Symmorphic space group?
            inversion (Bool): Centrosymmetric space group?
            soc (Bool): Spin-orbit coupling included?
            spin_polarized (Bool): Spin-polarized system?
            parity_eigenvals (dict): band index, band degeneracy, energy eigenval, Re(parity eigenval)

        """

        self._irvsp_output = irvsp_output

        self.symmorphic = symmorphic
        self.inversion = inversion
        self.soc = soc
        self.spin_polarized = spin_polarized
        self.parity_eigenvals = parity_eigenvals
        self._parse_stdout(irvsp_output)

    def _parse_stdout(self, irvsp_output):

        # try:
        with open(irvsp_output, "r") as file:
            lines = file.readlines()

            # Get header info
            symm_line = lines[7]
            if "Non-symmorphic" in symm_line:
                symmorphic = False
            else:
                symmorphic = True

            if "without" in symm_line:
                inversion = False
            else:
                inversion = True

            soc_line = lines[9]
            if "No" in soc_line:
                soc = False
            else:
                soc = True

            sp_line = lines[10]
            if "No" in sp_line:
                spin_polarized = False
            else:
                spin_polarized = True

            self.symmorphic = symmorphic
            self.inversion = inversion
            self.soc = soc
            self.spin_polarized = spin_polarized

            # Define TRIM labels in units of primitive reciprocal vectors
            #******

            # trim_labels = ["gamma", "x", "y", "z", "s", "t", "u", "r"]
            # trim_pts = [
            #     (0.0, 0.0, 0.0),
            #     (0.5, 0.0, 0.0),
            #     (0.0, 0.5, 0.0),
            #     (0.0, 0.0, 0.5),
            #     (0.5, 0.5, 0.0),
            #     (0.0, 0.5, 0.5),
            #     (0.5, 0.0, 0.5),
            #     (0.5, 0.5, 0.5),
            # ]

            # trim_dict = {pt: label for (pt, label) in zip(trim_pts, trim_labels)}
            # trim_dict = dict(zip(kpoints.labels, kpoints.kpts))
            # if "None" in trim_dict:
            #     trim_dict.pop("None")
            # if None in trim_dict:
            #     trim_dict.pop(None)
            # if "" in trim_dict:
            #     trim_dict.pop(None)
            # if " " in trim_dict:
            #     trim_dict.pop(None)
            #
            # trim_dict = {pt: label for (pt, label) in zip([(round(pt[0], 3), round(pt[1], 3), round(pt[2], 3))
            #                                                for pt in list(trim_dict.values())], trim_dict.keys())}
            #*******
            # Dicts with kvec index as keys
            parity_eigenvals = {}

            # Start of irrep trace info
            for idx, line in enumerate(lines):
                if "*****" in line:
                    block_start = idx + 1
                    break

            kpt_wanted, trace_start = False, False
            for idx, line in enumerate(lines[block_start:]):
                if line.startswith("k = "):  # New kvec
                    line_list = line.split(" ")[2:]
                    try:
                        kvec = tuple([round(float(i),3) for i in line_list])
                    except:
                        continue
                    trim_label = str(kvec)
                    kpt_wanted = True

                if "The point group is" in line and kpt_wanted:
                    point_gp_at_k = line.split("The point group is")[1].strip()
                    pg_character_table = []
                if "                   E" in line and kpt_wanted:
                    pg_character_table.append(line.strip())
                if "       G" in line and kpt_wanted:
                    pg_character_table.append(line.strip())


                if "bnd ndg" in line and kpt_wanted:  # find inversion symmop position
                    trace_start = True  # Start of block of traces
                    bnds, ndgs, bnd_evs, inv_evs, reps = [], [], [], [], []
                    line_list = line.strip().split(" ")
                    symmops = [i for i in line_list if i]
                    inv_num = symmops.index("E") - 3  # subtract bnd, ndg, ev
                    num_ops = len(symmops) - 3  # subtract bnd, ndg, ev
                if kpt_wanted and trace_start and "0" in line:  # full trace line, not a blank line
                    head_line = line.split()
                    try:
                        bdx = int(head_line[0])
                    except:
                        continue
                    line_list = line[6:].strip()
                    line_list = line_list.split("=", 1)[0]

                    # delete irrep label at end of line
                    #line_list = [i for i in line_list.split(" ") if i]

                    # Check that trace line is complete, no ?? or error
                    if len(line_list) > 30 and len(line.split("=")) == 2:  # symmops + band eigenval
                        bnd = int(line[:3].strip())  # band index
                        ndg = int(line[3:6].strip())  # band degeneracy
                        bnd_ev = float(line[6:16].strip())
                        # inv_ev = float(line[27:33].strip())
                        irs = line.split("=")[1]

                        # if not np.isclose(inv_ev%1.0, 0.0, rtol=0, atol=0.03) or \
                        #    not np.isclose(inv_ev%1.0, 1.0, rtol=0, atol=0.03):
                        #    warnings.warn("IRVSP output data has non-integer parity eigenvalues!")

                        bnds.append(bnd)
                        ndgs.append(ndg)
                        bnd_evs.append(bnd_ev)
                        # inv_evs.append(inv_ev)
                        reps.append(irs)

                if "*****" in line:  # end of block
                    kpt_start = False
                    trace_start = False
                    kvec_data = {
                        "band_index": bnds,
                        "band_degeneracy": ndgs,
                        "band_eigenval": bnd_evs,
                        # "inversion_eigenval": inv_evs,
                        "irreducible_reps": reps,
                        "point_group": point_gp_at_k,
                        "pg_character_table": pg_character_table
                    }
                    if self.spin_polarized:
                        if trim_label in parity_eigenvals.keys():
                            parity_eigenvals[trim_label]["down"] = kvec_data
                        else:
                            parity_eigenvals[trim_label] = {"up": kvec_data}
                    else:
                        parity_eigenvals[trim_label] = kvec_data

        self.parity_eigenvals = parity_eigenvals

    # except Exception as er:
    #     warnings.warn(
    #         "irvsp output not found. Setting instance attributes from direct inputs!"
    #     )
    #     print(er)
