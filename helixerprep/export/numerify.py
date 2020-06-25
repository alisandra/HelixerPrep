"""convert cleaned-db schema to numeric values describing gene structure"""

import numpy as np
import logging
from abc import ABC, abstractmethod
from sqlalchemy.orm.exc import NoResultFound

from geenuff.base import types
from geenuff.base.orm import Coordinate, Genome
from ..core.orm import Mer


AMBIGUITY_DECODE = {
    'C': [1., 0., 0., 0.],
    'A': [0., 1., 0., 0.],
    'T': [0., 0., 1., 0.],
    'G': [0., 0., 0., 1.],
    'Y': [0.5, 0., 0.5, 0.],
    'R': [0., 0.5, 0., 0.5],
    'W': [0., 0.5, 0.5, 0.],
    'S': [0.5, 0., 0., 0.5],
    'K': [0., 0., 0.5, 0.5],
    'M': [0.5, 0.5, 0., 0.],
    'D': [0., 0.33, 0.33, 0.33],
    'V': [0.33, 0.33, 0., 0.33],
    'H': [0.33, 0.33, 0.33, 0.],
    'B': [0.33, 0., 0.33, 0.33],
    'N': [0.25, 0.25, 0.25, 0.25]
}


class Stepper(object):
    def __init__(self, end, by):
        self.at = 0
        self.end = end
        self.by = by

    def step(self):
        prev = self.at
        if prev + self.by < self.end:
            new = prev + self.by
        else:
            new = self.end
        self.at = new
        return prev, new

    def step_to_end(self):
        while self.at < self.end:
            yield self.step()


class Numerifier(ABC):
    def __init__(self, n_cols, coord, max_len, dtype=np.float32):
        assert isinstance(n_cols, int)
        self.n_cols = n_cols
        self.coord = coord
        self.max_len = max_len
        self.dtype = dtype
        # set paired steps
        partitioner = Stepper(end=self.coord.length, by=self.max_len)
        self.paired_steps = list(partitioner.step_to_end())
        super().__init__()

    @abstractmethod
    def coord_to_matrices(self):
        """Method to be called from outside. Numerifies both strands."""
        pass

    def _slice_matrices(self, *argv):
        """Slices (potentially) multiple matrices in the same way according to self.paired_steps"""
        assert len(argv) > 0, 'Need a matrix to slice'
        assert all([len(m.shape) <= 3 for m in argv]), 'Need at most 3-dimentional data'
        all_slices = [[] for _ in range(len(argv))]
        for prev, current in self.paired_steps:
            for matrix, slices in zip(argv, all_slices):
                # check if data is single or double stranded
                # this breaks if a chromosome is only 2 bp long, which should never arrive here
                if matrix.shape[0] == 2:
                    data_slice = matrix[:, prev:current]
                else:
                    data_slice = matrix[prev:current]
                slices.append(data_slice)
        return all_slices

    @abstractmethod
    def _init_data_arrays(self):
        """Initializes the data array that hold the numerified data"""
        pass


class SequenceNumerifier(Numerifier):
    def __init__(self, coord, max_len):
        super().__init__(n_cols=4, coord=coord, max_len=max_len, dtype=np.float16)
        self._init_data_arrays()

    def _init_data_arrays(self):
        length = len(self.coord.sequence)
        self.matrix = np.zeros((length, self.n_cols,), self.dtype)
        self.error_mask = np.ones((length,), np.int8)

    def coord_to_matrices(self):
        """Does not alter the error mask unlike in AnnotationNumerifier"""
        # actual numerification of the sequence
        for i, bp in enumerate(self.coord.sequence):
            self.matrix[i] = AMBIGUITY_DECODE[bp]
        data, error_mask = self._slice_matrices(self.matrix, self.error_mask)
        return data, error_mask


class AnnotationNumerifier(Numerifier):
    """Class for the numerification of the labels. Outputs a matrix that
    fits the sequence length of the coordinate but only for the provided features.
    This is done to support alternative splicing in the future.
    """
    feature_to_col = {
        types.GeenuffFeature.geenuff_transcript: 0,
        types.GeenuffFeature.geenuff_cds: 1,
        types.GeenuffFeature.geenuff_intron: 2,
     }

    def __init__(self, coord, features, max_len, one_hot=True):
        Numerifier.__init__(self, n_cols=3, coord=coord, max_len=max_len, dtype=np.int8)
        self.features = features
        self.one_hot = one_hot
        self.coord = coord
        self._init_data_arrays()

    def _init_data_arrays(self):
        length = len(self.coord.sequence)
        self.matrix = np.zeros((2, length, self.n_cols,), self.dtype)
        # 0 means error so this can be used directly as sample weight later on
        self.error_mask = np.ones((2, length,), np.int8)
        self.gene_lengths = np.zeros((2, len(self.coord.sequence),), dtype=np.uint32)

    def coord_to_matrices(self):
        self._init_data_arrays()
        self._fill_data_arrays()

        # encoding of transitions, has to be done after data arrays are fully completed
        # commented out as we are trying to make the double stranded prediction work
        # binary_transition_matrix = self._encode_transitions()
        binary_transition_matrix = np.zeros((2, self.matrix.shape[1], 6))
        # encoding of the actual labels and slicing; generation of error mask and gene length array
        if self.one_hot:
            label_matrix = self._encode_onehot4()
        else:
            label_matrix = self.matrix
        matrices = self._slice_matrices(label_matrix,
                                        self.error_mask,
                                        self.gene_lengths,
                                        binary_transition_matrix)
        return matrices

    def _fill_data_arrays(self):
        for feature in self.features:
            if feature.is_plus_strand:
                strand = 0
                start, end = feature.start, feature.end
            else:
                strand = 1
                start, end = feature.end + 1, feature.start + 1
            if feature.type in AnnotationNumerifier.feature_to_col.keys():
                col = AnnotationNumerifier.feature_to_col[feature.type]
                self.matrix[strand, start:end, col] = 1
            elif feature.type.value in types.geenuff_error_type_values:
                self.error_mask[strand, start:end] = 0
            else:
                raise ValueError('Unknown feature type found: {}'.format(feature.type.value))
            # also fill self.gene_lengths
            # give precedence for the longer transcript if present
            if feature.type.value == types.GEENUFF_TRANSCRIPT:
                length_arr = np.full((end - start,), end - start)
                maximum_gene_lengths = np.maximum(self.gene_lengths[strand, start:end], length_arr)
                self.gene_lengths[strand, start:end] = maximum_gene_lengths

    def _encode_onehot4(self):
        # Class order: Intergenic, UTR, CDS, (non-coding Intron), Intron
        # This could be done in a more efficient way, but this way we may catch bugs
        # where non-standard classes are output in the multiclass output
        one_hot_matrix = np.zeros((2, self.matrix.shape[1], 4), dtype=bool)
        col_0, col_1, col_2 = self.matrix[:, :, 0], self.matrix[:, :, 1], self.matrix[:, :, 2]
        # Intergenic
        one_hot_matrix[:, :, 0] = np.logical_not(col_0)
        # UTR
        genic_non_coding = np.logical_and(col_0, np.logical_not(col_1))
        one_hot_matrix[:, :, 1] = np.logical_and(genic_non_coding, np.logical_not(col_2))
        # CDS
        one_hot_matrix[:, :, 2] = np.logical_and(np.logical_and(col_0, col_1), np.logical_not(col_2))
        # Introns
        one_hot_matrix[:, :, 3] = np.logical_and(col_0, col_2)
        assert np.all(np.count_nonzero(one_hot_matrix, axis=2) == 1)

        one_hot4_matrix = one_hot_matrix.astype(np.int8)
        return one_hot4_matrix

    def _encode_transitions(self):
        add = np.array([[0, 0, 0]])
        shifted_feature_matrix = np.vstack((self.matrix[1:], add))

        y_is_transition = np.logical_xor(self.matrix[:-1], shifted_feature_matrix[:-1]).astype(np.int8)
        y_direction_zero_to_one = np.logical_and(y_is_transition, self.matrix[1:]).astype(np.int8)
        y_direction_one_to_zero = np.logical_and(y_is_transition, self.matrix[:-1]).astype(np.int8)
        stack = np.hstack((y_direction_zero_to_one, y_direction_one_to_zero))

        add2 = np.array([[0, 0, 0, 0, 0, 0]])
        shape_stack = np.insert(stack, 0, add2, axis=0).astype(np.int8)
        shape_end_stack = np.insert(stack, len(stack), add2, axis=0).astype(np.int8)
        binary_transitions = np.logical_or(shape_stack, shape_end_stack).astype(np.int8)
        return binary_transitions  # 6 columns, one for each switch (+TR, +CDS, +In, -TR, -CDS, -In)


class CoordNumerifier(object):
    """Combines the different Numerifiers which need to operate on the same Coordinate
    to ensure consistent parameters. Selects all Features of the given Coordinate.
    """
    @staticmethod
    def numerify(geenuff_exporter, coord, coord_features, max_len, one_hot=True):
        assert isinstance(max_len, int) and max_len > 0
        if not coord_features:
            logging.warning('Sequence {} has no annoations'.format(coord.seqid))

        anno_numerifier = AnnotationNumerifier(coord=coord, features=coord_features, max_len=max_len,
                                               one_hot=one_hot)
        seq_numerifier = SequenceNumerifier(coord=coord, max_len=max_len)

        # returns results for both strands, with the plus strand first in the list
        inputs, _ = seq_numerifier.coord_to_matrices()
        labels, label_masks, gene_lengths, transitions = anno_numerifier.coord_to_matrices()
        start_ends = anno_numerifier.paired_steps

        # do not output the input_masks as it is not used for anything
        out = {
            'inputs': inputs,
            'labels': labels,
            'label_masks': label_masks,
            'gene_lengths': gene_lengths,
            'transitions': transitions,
            'species': [coord.genome.species.encode('ASCII')] * len(inputs),
            'seqids': [coord.seqid.encode('ASCII')] * len(inputs),
            'start_ends': start_ends,
        }
        return out
