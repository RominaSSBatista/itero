#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
(c) 2018 Brant Faircloth || http://faircloth-lab.org/

All rights reserved.

This code is distributed under a 3-clause BSD license. Please see
LICENSE.txt for more information.

Created on 14 April 2018 16:10 CDT (-0500)
"""

from __future__ import absolute_import

from itero.cli import common
from itero.assemble import merged
from itero.helpers import FullPaths


descr = "Assemble reads using MPI for assembly."


def configure_parser(sub_parsers):
    sp = sub_parsers.add_parser(
        'mpi',
        description=descr,
        help=descr
    )
    # get common arguments
    sp = common.get_common_arguments(sp)
    # get any specific arguments
    sp.add_argument(
        "--output",
        required=True,
        action=FullPaths,
        help="""The directory in which to store the output"""
    )
    sp.set_defaults(func=run_mpi_assembly)


def run_mpi_assembly(args, parser):
    merged.main(args, parser, mpi=True)