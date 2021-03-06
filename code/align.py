#!/usr/bin/env python3

"""
Copyright 2017 Ryan Wick (rrwick@gmail.com)
https://github.com/rrwick/Porechop

Porechop makes use of C++ functions which are compiled in cpp_functions.so. This module uses ctypes
to wrap them in similarly named Python functions.

This file is part of Porechop. Porechop is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by the Free Software Foundation,
either version 3 of the License, or (at your option) any later version. Porechop is distributed in
the hope that it will be useful, but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU General Public License for more
details. You should have received a copy of the GNU General Public License along with Porechop. If
not, see <http://www.gnu.org/licenses/>.
"""

import os
import sys
from ctypes import CDLL, cast, c_char_p, c_int, c_void_p
from multiprocessing.dummy import Pool as ThreadPool

import numpy as np
import tqdm
from Bio import SeqIO
from Bio.Seq import Seq
from Bio.SeqRecord import SeqRecord

SO_FILE = 'cpp_functions.so'
SO_FILE_FULL = os.path.join(os.path.dirname(os.path.realpath(__file__)), SO_FILE)
if not os.path.isfile(SO_FILE_FULL):
    sys.exit('could not find ' + SO_FILE + ' - please reinstall')
C_LIB = CDLL(SO_FILE_FULL)

C_LIB.adapterAlignment.argtypes = [c_char_p,  # Read sequence
                                   c_char_p,  # Adapter sequence
                                   c_int,     # Match score
                                   c_int,     # Mismatch score
                                   c_int,     # Gap open score
                                   c_int]     # Gap extension score
C_LIB.adapterAlignment.restype = c_void_p     # String describing alignment


# This function cleans up the heap memory for the C strings returned by the other C functions. It
# must be called after them.
C_LIB.freeCString.argtypes = [c_void_p]
C_LIB.freeCString.restype = None


def adapter_alignment(read_sequence, adapter_sequence, scoring_scheme_vals, alignm_score_value, out_filename, threads, min_length):
    #print(read_sequence, adapter_sequence, scoring_scheme_vals, alignm_score_value, out_filename, threads,
    #                  min_length)
    """
    Python wrapper for adapterAlignment C++ function.
    """
    alignm_score_value = int(alignm_score_value)
    sys.stdout.write("### STARTING ADAPTER ALIGNMENT AND READS ORIENTATION ###\n")
    list_adapter = []
    list_run = []
    for adapter in SeqIO.parse(adapter_sequence, "fasta"):
        list_adapter.append(adapter)
        record = SeqRecord(adapter.seq.reverse_complement(), id=adapter.id + "_rev")
        list_adapter.append(record)
    dict_aln = {}


    for sequence in SeqIO.parse(read_sequence, "fasta"):
        dict_aln[sequence.id] = ""
        for adapter in list_adapter:
            match_score = scoring_scheme_vals[0]
            mismatch_score = scoring_scheme_vals[1]
            gap_open_score = scoring_scheme_vals[2]
            gap_extend_score = scoring_scheme_vals[3]
            list_run.append([str(sequence.seq).encode('utf-8'), str(adapter.seq).encode('utf-8'), match_score,
                             mismatch_score, gap_open_score, gap_extend_score, sequence.id, adapter.id])

    #print(dict_aln)

    with ThreadPool(int(threads)) as pool:
        for out in pool.imap(align, tqdm.tqdm(list_run)):
            out_list = out.split(",")
            #print(out_list)
            if dict_aln[out_list[0]] != "":
                if (float(out.split(",")[9])) > float(dict_aln[out_list[0]].split(",")[9]):
                    dict_aln[out.split(",")[0]] = out
            else:
                dict_aln[out.split(",")[0]] = out

    good_reads = [float(dict_aln[key].split(",")[9]) for key in dict_aln if float(dict_aln[key].split(",")[9]) > 80]

    if len(good_reads)/len(dict_aln) < 0.1:
        sys.stdout.write("### THERE ARE FEW READS (<10%) THAT MATCH WITH THE ADAPTER SEQUENCE WITH A GOOD IDENITTY (>80%). SWITCHING TO NON-STRANDED MODE ###\n")
        stranded_value = False
        return (len(dict_aln), read_sequence, stranded_value)
    else:
        sys.stdout.write("### ABOUT " + str((len(dict_aln)/len(list_run))*100) + " MATCH TO AN ADAPTER ###\n")
        stranded_value = True



    if alignm_score_value == 0:
        alignm_score_mean = np.mean([float(dict_aln[key].split(",")[9]) for key in dict_aln])
        alignm_score_std = np.std([float(dict_aln[key].split(",")[9]) for key in dict_aln])
        alignm_score_value = alignm_score_mean - (alignm_score_std/10)

    #print(alignm_score_mean, alignm_score_std, alignm_score_value)

    seq_to_keep = {}
    for key in dict_aln:
        if (float(dict_aln[key].split(",")[9])) > alignm_score_value:
            seq_to_keep[key] = dict_aln[key]
            #print (seq_to_keep[key])
    with open(out_filename, "w") as output_handle:
        for sequence in tqdm.tqdm(SeqIO.parse(read_sequence, "fasta")):
            count = 0
            if sequence.id in seq_to_keep:
                if seq_to_keep[sequence.id].split(",")[1].endswith("rev"):
                    position = [seq_to_keep[sequence.id].split(",")[2], seq_to_keep[sequence.id].split(",")[3]]
                    seq = str(sequence.seq)
                    sequence_match = seq[int(position[0]):int(position[1])]
                    multiple_seq = seq.split(sequence_match)
                    full_multiple_seq_all = [seq_full for seq_full in multiple_seq if seq_full != ""]
                    full_multiple_seq = [seq_full for seq_full in full_multiple_seq_all if len(seq_full) > int(min_length)]
                    if len(full_multiple_seq) > 1:
                        for split_seq in full_multiple_seq:
                            count += 1
                            sequence_new = SeqRecord(Seq(split_seq), id=sequence.id, description="REV")
                            rev_seq = SeqRecord(sequence_new.seq.reverse_complement(), id=sequence.id + "_rev." + str(count))
                            SeqIO.write(rev_seq, output_handle, "fasta")
                    elif len(full_multiple_seq) == 1:
                        sequence_new = SeqRecord(Seq(full_multiple_seq[0]), id=sequence.id)
                        rev_seq = SeqRecord(sequence_new.seq.reverse_complement(), id=sequence.id + "_rev")
                        SeqIO.write(rev_seq, output_handle, "fasta")
                    else:
                        continue
                else:
                    position = [seq_to_keep[sequence.id].split(",")[2], seq_to_keep[sequence.id].split(",")[3]]
                    seq = str(sequence.seq)
                    sequence_match = seq[int(position[0]):int(position[1])]
                    multiple_seq = seq.split(sequence_match)
                    full_multiple_seq_all = [seq_full for seq_full in multiple_seq if seq_full != ""]
                    full_multiple_seq = [seq_full for seq_full in full_multiple_seq_all if len(seq_full) > int(min_length)]
                    if len(full_multiple_seq) > 1:
                        for split_seq in full_multiple_seq:
                            count += 1
                            sequence_new = SeqRecord(Seq(split_seq), id=sequence.id + "." + str(count))
                            SeqIO.write(sequence_new, output_handle, "fasta")
                    elif len(full_multiple_seq) == 1:
                        sequence_new = SeqRecord(Seq(full_multiple_seq[0]), id=sequence.id)
                        SeqIO.write(sequence_new, output_handle, "fasta")
                    else:
                        continue

    return (len(seq_to_keep), out_filename, stranded_value)


def align(command_in):

    ptr = C_LIB.adapterAlignment(str(command_in[0]).encode('utf-8'), str(command_in[1]).encode('utf-8'),
                                 command_in[2], command_in[3], command_in[4], command_in[5])
    result_string = c_string_to_python_string(ptr)

    single_result_string = result_string.split(",")
    average_score = (float(single_result_string[5]) + float(single_result_string[6])) / 2
    result_string_name = ",".join([command_in[6], command_in[7], result_string, str(average_score)])
    return result_string_name


def c_string_to_python_string(c_string):
    """
    This function casts a C string to a Python string and then calls a function to delete the C
    string from the heap.
    """
    python_string = cast(c_string, c_char_p).value.decode()
    C_LIB.freeCString(c_string)
    return python_string

#if __name__ == '__main__':
#    scoring = [3, -6, -5, -2]
#    alignm_score_value = ""
#    adapter_alignment(*sys.argv[1:], scoring, alignm_score_value)
