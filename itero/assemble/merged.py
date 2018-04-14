#!/usr/bin/env python


"""This code utilizes the task pull paradigm contributed by Craig Finch
(cfinch@ieee.org) availalable from:

https://github.com/jbornschein/mpi4py-examples/blob/master/09-task-pull.py
"""

import os
import sys
import time
import shutil
import ConfigParser

#from mpi4py import MPI

from itero import bwa
from itero import samtools
from itero import common
from itero import raw_reads

from itero.log import setup_logging

import pdb


def enum(*sequential, **named):
    """Handy way to fake an enumerated type in Python
    http://stackoverflow.com/questions/36932/how-can-i-represent-an-enum-in-python
    """
    enums = dict(zip(sequential, range(len(sequential))), **named)
    return type('Enum', (), enums)


def main(args, parser, mpi=False):
    if mpi:
        from schwimmbad import MPIPool
        # open up a pool of MPI processes using schwimmbad
        mpi_pool = MPIPool()
        # add this line for MPI compatibility
        if not mpi_pool.is_master():
            mpi_pool.wait()
            sys.exit(0)
    start_time = time.time()
    # setup logging
    log, my_name = setup_logging(args)
    if mpi:
        # UNIQUE TO MPI CODE - so that processes will die if output directory
        # exists. So, make the output directory or die
        if os.path.exists(args.output):
            log.critical("THE OUTPUT DIRECTORY EXISTS.  QUITTING.")
            mpi_pool.close()
            sys.exit(1)
        else:
            # create the new directory
            os.makedirs(args.output)
    # get seeds from config file
    conf = ConfigParser.ConfigParser(allow_no_value=True)
    conf.optionxform = str
    conf.read(args.config)
    # get the seed file info
    seeds = conf.items("reference")[0][0]
    # deal with relative paths in config
    if seeds.startswith(".."):
        seeds = os.path.join(os.path.dirname(args.config), seeds)
    # get name of all loci in seeds file - only need to do this once
    seed_names = common.get_seed_names(seeds)
    # get the input data
    log.info("Getting input filenames and creating output directories")
    individuals = common.get_input_data(log, args, conf)
    for individual in individuals:
        sample, dir = individual
        # pretty print taxon status
        text = " Processing {} ".format(sample)
        log.info(text.center(65, "-"))
        # make a directory for sample-specific assemblies
        sample_dir = os.path.join(args.output, sample)
        os.makedirs(sample_dir)
        # determine how many files we're dealing with
        fastq = raw_reads.get_input_files(dir, args.subfolder, log)
        iterations = list(xrange(args.iterations)) + ['final']
        next_to_last_iter = iterations[-2]
        for iteration in iterations:
            text = " Iteration {} ".format(iteration)
            log.info(text.center(45, "-"))
            # One the last few iterations, set some things up differently to deal w/ dupe contigs.
            # First, we'll allow multiple contigs during all but the last few rounds of contig assembly.
            # This is because we could be assembling different parts of a locus that simply have not
            # merged in the middle yet (but will).  We'll turn option to remove multiple contigs
            # back on for last three rounds
            if iteration in iterations[-3:]:
                if args.allow_multiple_contigs is True:
                    allow_multiple_contigs = True
                else:
                    allow_multiple_contigs = False
            else:
                allow_multiple_contigs = True
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
            # if we are finished with it, cleanup the previous iteration
            if not args.do_not_zip and iteration >= 1:
                # after assembling all loci, zip the iter-#/loci directory; this will be slow if --clean is not turned on.
                prev_iter = common.get_previous_iter(log, sample_dir_iter, iterations, iteration)
                zipped = common.zip_assembly_dir(log, sample_dir_iter, args.clean, prev_iter)
            #index the seed file
            bwa.bwa_index_seeds(seeds, log)
            # map initial reads to seeds
            bam = bwa.bwa_mem_pe_align(log, sample, sample_dir_iter, seeds, args.local_cores, fastq.r1, fastq.r2, iteration)
            # reduce bam to mapping reads
            reduced_bam = samtools.samtools_reduce(log, sample, sample_dir_iter, bam, iteration=iteration)
            # remove the un-reduced BAM
            os.remove(bam)
            # sort and index bam
            sorted_reduced_bam = samtools.samtools_sort(log, sample, sample_dir_iter, reduced_bam, iteration=iteration)
            samtools.samtools_index(log, sample, sample_dir_iter, sorted_reduced_bam, iteration=iteration)
            # remove the un-sorted BAM
            os.remove(reduced_bam)
            # if we are not on our last iteration, assembly as usual
            if iteration is not 'final':
                if args.only_single_locus:
                    locus_names = ['locus-1']
                else:
                    # get list of loci in sorted bam
                    locus_names = samtools.samtools_get_locus_names_from_bam(log, sorted_reduced_bam, iteration)
                log.info("Splitting BAM and assembling")
                # MPI-specific bits
                tasks = [(iteration, sample, sample_dir_iter, sorted_reduced_bam, locus_name, args.clean, args.only_single_locus) for locus_name in locus_names]
                if mpi:
                    results = mpi_pool.map(common.initial_assembly, tasks)
                # multiprocessing specific bits
                else:
                    if not args.only_single_locus and args.local_cores > 1:
                        assert args.local_cores <= multiprocessing.cpu_count(), "You've specified more cores than you have"
                        pool = multiprocessing.Pool(args.local_cores)
                        pool.map(common.initial_assembly, tasks)
                    elif args.only_single_locus:
                        map(common.initial_assembly, tasks)
                    else:
                        map(common.initial_assembly, tasks)
                # after assembling all loci, get them into a single file
                new_seeds = common.get_fasta(log, sample, sample_dir_iter, locus_names, allow_multiple_contigs, iteration=iteration)
                # after assembling all loci, report on deltas of the assembly length
                if iteration is not 0:
                    assembly_delta = common.get_deltas(log, sample, sample_dir_iter, iterations, iteration=iteration)
            elif iteration is 'final':
                log.info("Final assemblies and a BAM file with alignments to those assemblies are in {}/iter-{}".format(os.path.join(args.output, individual[0]), iteration))
    if mpi:
        # close the pool of MPI processes
        mpi_pool.close()
    # get the shutdown time
    end_time = time.time()
    time_delta_sec = round(end_time - start_time, 1)
    time_delta_min = round(time_delta_sec / 60.0, 1)
    text = " Completed in {} minutes ({} seconds) ".format(time_delta_min, time_delta_sec)
    log.info(text.center(65, "="))