import argparse
import numpy as np
import h5py
import csv


class CoverageCounter(object):

    ARRAYS = (('data/X', 'X'),
              ('data/y', 'y'),
              ('predictions', 'predictions'),
              ('evaluation/coverage', 'coverage'),
              ('evaluation/spliced_coverage', 'spliced_coverage'))

    def __init__(self, lab_dim=4, n_cov_bins=6, base_cov_bins=3):
        self.lab_dim = lab_dim
        self.n_cov_bins = n_cov_bins
        self.coverage_bins = tuple(self.setup_coverage_bins(base_cov_bins, n_cov_bins))
        self.counts = self.setup_fully_binned_counts(lab_dim, n_cov_bins)
        self.latest = {}

    def get_latest_arrays(self, i, h5):
        for h5_key, key in CoverageCounter.ARRAYS:
            self.latest[key] = h5[h5_key][i]

    @staticmethod
    def setup_fully_binned_counts(lab_dim, n_cov_bins):
        list_y = []
        # [argmax_gt][argmax_pred][i_covbin_ge][i_splicedcovbin_ge] = count
        for i_y in range(lab_dim):
            list_preds = []
            for i_pred in range(lab_dim):
                list_covs = []
                for i_cov in range(n_cov_bins):
                    list_scovs = []
                    for i_scov in range(n_cov_bins):
                        list_scovs.append(0)
                    list_covs.append(list_scovs)
                list_preds.append(list_covs)
            list_y.append(list_preds)
        return list_y

    @staticmethod
    def setup_coverage_bins(base=2, n=8):
        return [0] + [base**i for i in range(n - 1)]

    def pre_filter_arrays(self):
        # truncate to length of predictions
        pred_len = self.latest['predictions'].shape[0]
        for key, array in self.latest.items():
            self.latest[key] = array[:pred_len]

        # ignore any padded bases
        x = self.latest['X']
        not_padded = np.sum(x, axis=1) > 0
        for key, array in self.latest.items():
            self.latest[key] = array[not_padded]

    @staticmethod
    def mask_filtered_set(input_dict, mask_fn):
        output = {}
        for _, key in CoverageCounter.ARRAYS:
            mask = mask_fn(input_dict)
            output[key] = input_dict[key][mask]
        return output

    # masking functions
    @staticmethod
    def mask_by_argmax(key, i):
        def fn(input_dict):
            return np.argmax(input_dict[key], axis=1) == i
        return fn

    @staticmethod
    def mask_by_coverage(key, gr_eq):
        def fn(input_dict):
            return input_dict[key] >= gr_eq
        return fn

    def increment(self):
        for i_y in range(self.lab_dim):
            filter_y_fn = self.mask_by_argmax('y', i_y)
            filtered_y = self.mask_filtered_set(self.latest, filter_y_fn)
            for i_p in range(self.lab_dim):
                filter_p_fn = self.mask_by_argmax('predictions', i_p)
                filtered_p = self.mask_filtered_set(filtered_y, filter_p_fn)
                for i_c in range(self.n_cov_bins):
                    filter_c_fn = self.mask_by_coverage('coverage', self.coverage_bins[i_c])
                    filtered_c = self.mask_filtered_set(filtered_p, filter_c_fn)
                    for i_sc in range(self.n_cov_bins):
                        filter_sc_fn = self.mask_by_coverage('spliced_coverage',
                                                             self.coverage_bins[i_sc])
                        mask_sc = filter_sc_fn(filtered_c)
                        self.counts[i_y][i_p][i_c][i_sc] += np.sum(mask_sc)

    def flatten(self):
        out = [['argmax_y', 'argmax_pred', 'coverage_greater_eq', 'spliced_coverage_greater_eq', 'count']]
        for i_y in range(self.lab_dim):
            for i_p in range(self.lab_dim):
                for i_c in range(self.n_cov_bins):
                    for i_sc in range(self.n_cov_bins):
                        out.append([i_y,
                                    i_p,
                                    self.coverage_bins[i_c],
                                    self.coverage_bins[i_sc],
                                    self.counts[i_y][i_p][i_c][i_sc]])
        return out


def main(h5_file, out_file):
    h5_data = h5py.File(h5_file, 'r')
    cov_counter = CoverageCounter(lab_dim=4, n_cov_bins=6, base_cov_bins=3)
    n = h5_data['data/X'].shape[0]
    for i in range(n):
        cov_counter.get_latest_arrays(i, h5_data)
        cov_counter.pre_filter_arrays()
        cov_counter.increment()
        if not i % 100:
            print('{} chunks of {} finished'.format(i, n))

    with open(out_file, 'w') as f:
        writer = csv.writer(f)
        writer.writerows(cov_counter.flatten())


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument('-d', '--h5_data', help='h5 data file (with data/{X, y, species, seqids, etc ...}'
                                                'and evaluation/{coverage, spliced_coverage}, as output by'
                                                'the rnaseq.py script)', required=True)
    parser.add_argument('-o', '--out', help='output csv file name')
    args = parser.parse_args()
    main(args.h5_data, args.out)
