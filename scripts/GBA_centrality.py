############################################################################################
# Copyright (C) Jędrzej Kubica, Nicolas Thierry-Mieg, 2024
#
# This file was written by Jędrzej Kubica and Nicolas Thierry-Mieg
# (CNRS, France) Nicolas.Thierry-Mieg@univ-grenoble-alpes.fr
#
# This program is free software: you can redistribute it and/or modify it under 
# the terms of the GNU General Public License as published by the Free Software 
# Foundation, either version 3 of the License, or (at your option) any later version.
#
# This program is distributed in the hope that it will be useful, but WITHOUT ANY WARRANTY;
# without even the implied warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.
# See the GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License along with this program.
# If not, see <https://www.gnu.org/licenses/>.
############################################################################################

import logging
import networkx
import numpy
import os
import sys

import pathlib

import argparse

import utils

# set up logger, using inherited config, in case we get called as a module
logger = logging.getLogger(__name__)


def calculate_scores(interactome, adjacency_matrices, causal_genes, alpha, alpha_norm) -> dict:
    '''
    Calculates scores for every gene in the interactome based on the proximity to causal genes.
    Formula (for each node i):
    {
    score_i = 1 ; if gene is causal
    score_i = (1/norm_factor) * sum_k(alpha**k) * sum_j[(A**k)_ij * score_j] ; otherwise
    }

    arguments:
    - interactome: type=networkx.Graph
    - adjacency_matrices: list of scipy sparse arrays as returned by get_adjacency_matrices()
    - causal_genes: dict of causal genes with key=ENSG, value=1

    returns:
    - scores: dict with key=ENSG, value=score
    '''
    # 1D numpy array for genes in the interactome: 1 if causal gene, 0 otherwise,
    # size=len(nodes in interactome), ordered as in interactome.nodes()
    causal_genes_vec = numpy.zeros(len(interactome.nodes()), dtype=numpy.uint8)
    ni = 0
    for n in interactome.nodes():
        if n in causal_genes:
            causal_genes_vec[ni] = 1
        ni += 1

    scores_vec = numpy.zeros(len(causal_genes_vec))
    norm_factors_vec = numpy.zeros(len(causal_genes_vec))
    ones_vec = numpy.ones(len(causal_genes_vec))

    # calculate normalized scores
    for d in range(1, len(adjacency_matrices)):
        A = adjacency_matrices[d]
        scores_vec += alpha ** d * A.dot(causal_genes_vec)
        norm_factors_vec += (alpha / alpha_norm) ** d * A.dot(ones_vec)

    scores_vec_normalized = scores_vec / norm_factors_vec

    # map ENSGs to scores
    scores = dict(zip(interactome.nodes(), scores_vec_normalized))

    return scores


def get_adjacency_matrices(interactome, d_max=5):
    '''
    Calculates powers of adjacency matrix.

    arguments:
    - interactome: type=networkx.Graph
    - d_max: int

    returns:
    - adjacency_matrices: list of scipy sparse arrays, array at index i (starting at i==1)
      is A**i (except the diagonal is zeroed) where A is the adjacency matrix of interactome,
      rows and columns are ordered as in interactome.nodes()
    '''
    # initialize, element at index 0 is never used
    adjacency_matrices = [0]

    A = networkx.to_scipy_sparse_array(interactome, dtype=bool)  # returns scipy.sparse._csr.csr_array
    res = A
    # manually zero only the non-zero diagonal elements: this is identical to res.setdiag(0)
    # but faster and doesn't emit a warning (https://github.com/scipy/scipy/issues/11600)
    nonzero, = res.diagonal().nonzero()
    res[nonzero, nonzero] = 0
    adjacency_matrices.append(res)

    # @ - matrix multiplication
    for power in range(2, d_max + 1):
        res = res @ A
        # again, same as res.setdiag(0) but faster and quiet
        nonzero, = res.diagonal().nonzero()
        res[nonzero, nonzero] = 0
        adjacency_matrices.append(res)

    logger.debug("Done building %i matrices", len(adjacency_matrices) - 1)
    return adjacency_matrices


def main(interactome_file, causal_genes_file, gene2ENSG_file, patho, alpha, alpha_norm, d_max):

    logger.info("Parsing interactome")
    interactome = utils.parse_interactome(interactome_file)

    logger.info("Parsing gene-to-ENSG mapping")
    (ENSG2gene, gene2ENSG) = utils.parse_gene2ENSG(gene2ENSG_file)

    logger.info("Parsing causal genes")
    causal_genes = utils.parse_causal_genes(causal_genes_file, gene2ENSG, interactome, patho)

    logger.info("Calculating powers of adjacency matrix")
    adjacency_matrices = get_adjacency_matrices(interactome, d_max)

    logger.info("Calculating scores")
    scores = calculate_scores(interactome, adjacency_matrices, causal_genes, alpha, alpha_norm)

    logger.info("Printing scores")
    utils.scores_to_TSV(scores, ENSG2gene)

    logger.info("Done!")


if __name__ == "__main__":
    script_name = os.path.basename(sys.argv[0])
    # configure logging, sub-modules will inherit this config
    logging.basicConfig(format='%(asctime)s %(levelname)s %(name)s: %(message)s',
                        datefmt='%Y-%m-%d %H:%M:%S',
                        level=logging.DEBUG)
    # set up logger: we want script name rather than 'root'
    logger = logging.getLogger(script_name)

    parser = argparse.ArgumentParser(
        prog=script_name,
        description="Calculate GBA centrality for new candidates of infertility based on the guilt-by-association paradigm."
    )

    parser.add_argument('-i', '--interactome_file', type=pathlib.Path, required=True)
    parser.add_argument('--causal_genes_file', type=pathlib.Path, required=True)
    parser.add_argument('--gene2ENSG_file', type=pathlib.Path, required=True)
    parser.add_argument('--patho', default='MMAF', type=str)
    parser.add_argument('--alpha', default=0.5, type=float)
    parser.add_argument('--alpha_norm', default=1.0, type=float)
    parser.add_argument('--d_max', default=5, type=int)

    args = parser.parse_args()

    # I don't know argparse but you have to make sure the required args were passed,
    # check that the provided args are OK, and print a USAGE if checks fail

    try:
        main(interactome_file=args.interactome_file,
             causal_genes_file=args.causal_genes_file,
             patho=args.patho,
             gene2ENSG_file=args.gene2ENSG_file,
             alpha=args.alpha,
             alpha_norm=args.alpha_norm,
             d_max=args.d_max)
        # this doesn't work, the default args defined for main() are ignored

    except Exception as e:
        # details on the issue should be in the exception name, print it to stderr and die
        sys.stderr.write("ERROR in " + script_name + " : " + repr(e) + "\n")
        sys.exit(1)
