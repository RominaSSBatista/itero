#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
(c) 2017 Brant Faircloth || http://faircloth-lab.org/
All rights reserved.

This code is distributed under a 3-clause BSD license. Please see
LICENSE.txt for more information.

Created on 17 July 2017 13:35 CDT (-0500)
"""


import os
import sys
import time
import shutil
import argparse
import subprocess
import ConfigParser
import multiprocessing

import numpy
from Bio import SeqIO
from phyluce.helpers import FullPaths, CreateDir, is_dir, is_file
from phyluce.raw_reads import get_input_files
from phyluce.log import setup_logging

import pdb


def get_args():
    """Get arguments from CLI"""
    parser = argparse.ArgumentParser(
        description="""Iteratively assemble loci from raw reads and a seed file"""
    )
    parser.add_argument(
        "--subfolder",
        type=str,
        default='',
        help="""A subdirectory, below the level of the group, containing the reads"""
    )
    parser.add_argument(
        "--output",
        required=True,
        action=FullPaths,
        #action=CreateDir,
        help="""The directory in which to store the output"""
    )
    parser.add_argument(
        "--cores",
        type=int,
        default=1,
        help="""The number of compute cores/threads to use"""
    )
    parser.add_argument(
        "--verbosity",
        type=str,
        choices=["INFO", "WARN", "CRITICAL"],
        default="INFO",
        help="""The logging level to use."""
    )
    parser.add_argument(
        "--log-path",
        action=FullPaths,
        type=is_dir,
        default=None,
        help="""The path to a directory to hold logs."""
    )
    # one of these is required.  The other will be set to None.
    input = parser.add_mutually_exclusive_group(required=True)
    input.add_argument(
        "--config",
        type=is_file,
        action=FullPaths,
        default=None,
        help="""A configuration file containing reads to assemble"""
    )
    input.add_argument(
        "--dir",
        type=is_dir,
        action=FullPaths,
        default=None,
        help="""A directory of reads to assemble""",
    )
    return parser.parse_args()


def get_input_data(log, conf, output):
    # get reference sequence
    reference = conf.items('reference')
    # ensure there is 1 reference and it is a file
    assert len(reference) == 1, "There is more than one reference sequence listed."
    reference = reference[0][0]
    try:
        assert os.path.isfile(reference)
    except:
        raise IOError("{} is not a file".format(reference))
    # check reference to ensure that bwa has indexed
    for suffix in ['amb', 'ann', 'bwt', 'pac',  'sa']:
        bwa_file = "{}.{}".format(reference, suffix)
        try:
            assert os.path.isfile(bwa_file)
        except:
            log.info("Need to create BWA index file for reference")
            bwa_create_index_files(log, reference)
    individuals = conf.items('individuals')
    for sample in individuals:
        try:
            assert os.path.isdir(sample[1])
        except:
            raise IOError("{} is not a directory".format(sample[1]))
    return reference, individuals


def bwa_create_index_files(log, reference):
    log.info("Running bwa indexing against {}".format(reference))
    cwd = os.getcwd()
    # move into reference directory
    os.chdir(os.path.dirname(reference))
    cmd = ["/home/bcf/anaconda/envs/circulator/bin/bwa", "index", reference]
    with open('bwa-index-file.log', 'a') as outf:
        proc = subprocess.Popen(cmd, stdout=outf, stderr=subprocess.STDOUT)
        proc.communicate()
    # mvoe back to working directory
    os.chdir(cwd)


def bwa_index_seeds(seeds, log):
    #pdb.set_trace()
    log.info("Running bwa indexing against {}".format(os.path.basename(seeds)))
    cwd = os.getcwd()
    # move into reference directory
    os.chdir(os.path.dirname(seeds))
    cmd = ["/home/bcf/anaconda/envs/circulator/bin/bwa", "index", seeds]
    with open('bwa-index-file.log', 'a') as outf:
        proc = subprocess.Popen(cmd, stdout=outf, stderr=subprocess.STDOUT)
        proc.communicate()
    # mvoe back to working directory
    os.chdir(cwd)


def bwa_mem_pe_align(log, sample, sample_dir, ref, cores, r1, r2, iteration=0):
    #pdb.set_trace()
    cmd1 = [
        "/home/bcf/anaconda/envs/circulator/bin/bwa",
        "mem",
        "-t",
        str(cores),
        ref,
        r1.pth,
        r2.pth
    ]
    cmd2 = [
        "/home/bcf/anaconda/envs/circulator/bin/samtools",
        "view",
        "-bS",
        "-"
    ]
    sampe_out_fname = os.path.join(sample_dir, 'iter-{}.pe.bwa.log'.format(iteration))
    samtools_out_fname = os.path.join(sample_dir, 'iter-{}.pe.samtools.log'.format(iteration))
    bam_out_fname = os.path.join(sample_dir, 'iter-{}.bam'.format(iteration))
    log.info("Building BAM for {}, iteration {}".format(sample, iteration))
    with open(sampe_out_fname, 'w') as sampe_out:
        with open(samtools_out_fname, 'w') as samtools_out:
            with open(bam_out_fname, 'w') as bam_out:
                proc1 = subprocess.Popen(cmd1, stdout=subprocess.PIPE, stderr=sampe_out)
                proc2 = subprocess.Popen(cmd2, stdin=proc1.stdout, stdout=bam_out, stderr=samtools_out)
                proc1.stdout.close()
                proc2.communicate()
    return bam_out_fname


def samtools_index(log, sample, sample_dir, bam, iteration=0):
    log.info("Indexing BAM for {}".format(sample))
    cmd = [
        "/home/bcf/anaconda/envs/circulator/bin/samtools",
        "index",
        bam
    ]
    samtools_out_fname = os.path.join(sample_dir, 'iter-{}.samtools-idx.log'.format(sample))
    with open(samtools_out_fname, 'w') as samtools_out:
        proc = subprocess.Popen(cmd, stdout=samtools_out, stderr=subprocess.STDOUT)
        proc.communicate()


def samtools_reduce(log, sample, sample_dir, bam, iteration=0):
    #pdb.set_trace()
    log.info("Reducing BAM for {}, iteration {}".format(sample, iteration))
    bam_out_fname = os.path.join(sample_dir, 'iter-{}.reduce.bam'.format(iteration))
    cmd = [
        "/home/bcf/anaconda/envs/circulator/bin/samtools",
        "view",
        "-F",
        "4",
        "-b",
        bam,
        "-o",
        bam_out_fname
    ]
    samtools_out_fname = os.path.join(sample_dir, 'iter-{}.reduce.log'.format(iteration))
    with open(samtools_out_fname, 'w') as samtools_out:
        proc = subprocess.Popen(cmd, stdout=samtools_out, stderr=subprocess.STDOUT)
        proc.communicate()
    return bam_out_fname


def samtools_sort(log, sample, sample_dir, bam, iteration=0):
    #pdb.set_trace()
    bam_out_fname = os.path.join(sample_dir, 'iter-{}.reduce.sorted.bam'.format(iteration))
    cmd1 = [
        "/home/bcf/anaconda/envs/circulator/bin/samtools",
        "sort",
        bam,
        "-o",
        bam_out_fname
    ]
    samtools_out_fname = os.path.join(sample_dir, 'iter-{}.sort.log'.format(iteration))
    with open(samtools_out_fname, 'w') as samtools_out:
        proc = subprocess.Popen(cmd1, stdout=samtools_out, stderr=subprocess.STDOUT)
        proc.communicate()
    return bam_out_fname


def samtools_get_locus_names_from_bam(log, bam, iteration):
    #pdb.set_trace()
    cmd1 = [
        "/home/bcf/anaconda/envs/circulator/bin/samtools",
        "view",
        bam
    ]
    cmd2 = [
        "awk",
        '{print $3}',
    ]
    proc1 = subprocess.Popen(cmd1, stdout=subprocess.PIPE)
    proc2 = subprocess.Popen(cmd2, stdin=proc1.stdout, stdout=subprocess.PIPE)
    proc1.stdout.close()
    stdout = proc2.communicate()
    # return unique list of locus names
    locus_names = list(set(stdout[0].split("\n")))
    locus_names.sort()
    # make sure empty is removed
    locus_names.remove('')
    log.info("Recovered {} loci for iteration {}".format(len(locus_names), iteration))
    return locus_names


def samtools_split_bam(sample, sample_dir, bam, locus):
    bam_out_fname = os.path.join(sample_dir, '{}.bam'.format(locus))
    cmd1 = [
        "/home/bcf/anaconda/envs/circulator/bin/samtools",
        "view",
        "-b",
        bam,
        locus,
        "-o",
        bam_out_fname
    ]
    proc1 = subprocess.Popen(cmd1)
    stdout = proc1.communicate()
    sys.stdout.write('.')
    sys.stdout.flush()
    return bam_out_fname


def get_seed_names(seeds):
    with open(seeds, "ru") as infile:
        return [i.lstrip(">").rstrip() for i in infile if i.startswith(">")]


def bedtools_to_fastq(sample, sample_dir, bam, locus):
    fastq_out_fname = os.path.join(sample_dir, '{}.fastq'.format(locus))
    cmd1 = [
        "/home/bcf/bin/bedtools",
        "bamtofastq",
        "-i",
        bam,
        "-fq",
        fastq_out_fname
    ]
    proc1 = subprocess.Popen(cmd1)
    stdout = proc1.communicate()
    return fastq_out_fname


def spades_single_end_assembly(sample, sample_dir, fastq, locus):
    assembly_out_fname = os.path.join(sample_dir, '{}-assembly'.format(locus))
    # go ahead and assemble without error correction, for speed
    cmd1 = [
        "/home/bcf/anaconda/envs/circulator/bin/spades.py",
        "-s",
        fastq,
        "-k",
        "33",
        "--cov-cutoff",
        "5",
        "--only-assembler",
        "-o",
        assembly_out_fname
    ]
    spades_out_fname = os.path.join(sample_dir, '{}.spades.log'.format(locus))
    with open(spades_out_fname, 'w') as spades_out:
        proc = subprocess.Popen(cmd1, stdout=spades_out, stderr=subprocess.STDOUT)
        proc.communicate()
    return assembly_out_fname


def get_fasta(log, sample, sample_dir_iter, locus_names, iteration=0):
    assemblies = []
    assemblies_stats = []
    all_fasta_out_fname = os.path.join(sample_dir_iter, 'iter-{}.all-fasta.fasta'.format(iteration))
    print("")
    for locus in locus_names:
        try:
            assembly_fasta_fname = os.path.join(sample_dir_iter, "loci", locus, "{}-assembly".format(locus), "contigs.fasta")
            sequence = list(SeqIO.parse(assembly_fasta_fname, 'fasta'))
            if len(sequence) == 1:
                seq = sequence[0]
                seq.id = seq.id.replace("NODE", locus.split("_")[0])
                seq.description = ""
                seq.name = ""
                assemblies.append(seq)
                assemblies_stats.append(len(seq))
            else:
                log.warn("Dropped locus {} for having multiple contigs".format(locus))
        except IOError:
            log.warn("Dropped locus {} for having no assembled contigs".format(locus))
    with open(all_fasta_out_fname, 'w') as outfile:
        SeqIO.write(assemblies, outfile, 'fasta')
    log.info("Mean sequence length {}, min {}, max {}".format(
        numpy.mean(assemblies_stats),
        numpy.min(assemblies_stats),
        numpy.max(assemblies_stats)
    ))
    return all_fasta_out_fname


def initial_assembly(work):
    sample, sample_dir_iter, sorted_reduced_bam, locus = work
    sample_dir_iter_locus = os.path.join(sample_dir_iter, "loci", locus)
    os.makedirs(sample_dir_iter_locus)
    split_bam = samtools_split_bam(sample, sample_dir_iter_locus, sorted_reduced_bam, locus)
    split_fastq = bedtools_to_fastq(sample, sample_dir_iter_locus, split_bam, locus)
    os.remove(split_bam)
    spades_single_end_assembly(sample, sample_dir_iter_locus, split_fastq, locus)
    sys.stdout.write('.')
    sys.stdout.flush()


def main():
    # get args and options
    args = get_args()
    # setup logging
    log, my_name = setup_logging(args)
    # get seeds from config file
    conf = ConfigParser.ConfigParser(allow_no_value=True)
    conf.optionxform = str
    conf.read(args.config)
    # get the seed file info
    seeds = conf.items("reference")[0][0]
    # get name of all loci in seeds file - only need to do this once
    seed_names = get_seed_names(seeds)
    # get the input data
    log.info("Getting input filenames and creating output directories")
    reference, individuals = get_input_data(log, conf, args.output)
    for individual in individuals:
        start_time = time.time()
        sample, dir = individual
        # pretty print taxon status
        text = " Processing {} ".format(sample)
        log.info(text.center(65, "-"))
        # make a directory for sample-specific assemblies
        sample_dir = os.path.join(args.output, sample)
        os.makedirs(sample_dir)
        # determine how many files we're dealing with
        fastq = get_input_files(dir, args.subfolder, log)
        for iteration in (0, 1, 2, 3, 4, 5, 6):
            text = " Iteration {} ".format(iteration)
            log.info(text.center(45, "-"))
            #start_dir = os.getcwd()
            sample_dir_iter = os.path.join(sample_dir, "iter-{}".format(iteration))
            os.makedirs(sample_dir_iter)
            # change to sample_dir_iter
            os.chdir(sample_dir_iter)
            # copy seeds file
            if iteration == 0 and os.path.dirname(seeds) != os.getcwd():
                shutil.copy(seeds, os.getcwd())
                seeds = os.path.join(os.getcwd(), os.path.basename(seeds))
            elif iteration >= 1:
                shutil.copy(new_seeds, os.getcwd())
                seeds = os.path.join(os.getcwd(), os.path.basename(new_seeds))
            # index the seed file
            bwa_index_seeds(seeds, log)
            # map initial reads to seeds
            bam = bwa_mem_pe_align(log, sample, sample_dir_iter, seeds, args.cores, fastq.r1, fastq.r2, iteration)
            # reduce bam to mapping reads
            reduced_bam = samtools_reduce(log, sample, sample_dir_iter, bam, iteration=iteration)
            # remove the un-reduced BAM
            os.remove(bam)
            # sort and index bam
            sorted_reduced_bam = samtools_sort(log, sample, sample_dir_iter, reduced_bam, iteration=iteration)
            samtools_index(log, sample, sample_dir_iter, sorted_reduced_bam, iteration=iteration)
            # remove the un-sorted BAM
            os.remove(reduced_bam)
            # get list of loci in sorted bam
            locus_names = samtools_get_locus_names_from_bam(log, sorted_reduced_bam, iteration)
            log.info("Splitting BAM and assembling")
            work = [(sample, sample_dir_iter, sorted_reduced_bam, locus_name) for locus_name in locus_names]
            if args.cores > 1:
                assert args.cores <= multiprocessing.cpu_count(), "You've specified more cores than you have"
                pool = multiprocessing.Pool(args.cores)
                pool.map(initial_assembly, work)
            else:
                map(initial_assembly, work)
            # after assembling all loci, get them into a single file
            new_seeds = get_fasta(log, sample, sample_dir_iter, locus_names, iteration=iteration)
        # enter assembly polishing

    end_time = time.time()
    time_delta_sec = round(end_time - start_time, 1)
    time_delta_min = round(time_delta_sec / 60.0, 1)
    text = " Completed in {} minutes ({} seconds) ".format(time_delta_min, time_delta_sec)
    log.info(text.center(65, "="))



if __name__ == '__main__':
    main()
