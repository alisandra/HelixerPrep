#! /usr/bin/env python3
import random
import numpy as np
from keras.models import Sequential
from keras.layers import Conv1D, LSTM, CuDNNLSTM, Dense, Bidirectional, MaxPooling1D, Dropout
from HelixerModel import HelixerModel, HelixerSequence, acc_row, acc_g_row, acc_ig_row


class DanQSequence(HelixerSequence):
    def __getitem__(self, idx):
        pool_size = self.model.pool_size
        usable_idx_slice = self.usable_idx[idx * self.batch_size:(idx + 1) * self.batch_size]
        X = np.stack(self.x_dset[sorted(list(usable_idx_slice))])  # got to provide a sorted list of idx
        y = np.stack(self.y_dset[sorted(list(usable_idx_slice))])
        sw = np.ones((y.shape[0], y.shape[1] // pool_size), dtype=np.int8)
        if pool_size > 1:
            if y.shape[1] % pool_size != 0:
                # add additional values and mask them so everything divides evenly
                overhang = pool_size - (y.shape[1] % pool_size)
                y = np.pad(y, ((0, 0), (0, overhang), (0, 0)), 'constant',
                           constant_values=(0, 0))
                sw = np.pad(sw, ((0, 0), (0, 1)), 'constant', constant_values=(0, 0))
            y = y.reshape((
                y.shape[0],
                y.shape[1] // pool_size,
                pool_size * 3
            ))
        return X, y, sw


class DanQModel(HelixerModel):
    def __init__(self):
        super().__init__()
        self.parser.add_argument('-u', '--units', type=int, default=4)
        self.parser.add_argument('-f', '--filter-depth', type=int, default=8)
        self.parser.add_argument('-ks', '--kernel-size', type=int, default=26)
        self.parser.add_argument('-ps', '--pool-size', type=int, default=10)
        self.parser.add_argument('-dr1', '--dropout1', type=float, default=0.0)
        self.parser.add_argument('-dr2', '--dropout2', type=float, default=0.0)
        self.parse_args()

    def sequence_cls(self):
        return DanQSequence

    def model(self):
        model = Sequential()
        model.add(Conv1D(filters=self.filter_depth,
                         kernel_size=self.kernel_size,
                         input_shape=(self.shape_train[1], 4),
                         padding="same",
                         activation="relu"))

        if self.pool_size > 1:
            model.add(MaxPooling1D(pool_size=self.pool_size, padding='same'))

        model.add(Dropout(self.dropout1))
        model.add(Bidirectional(CuDNNLSTM(self.units, return_sequences=True)))

        model.add(Dropout(self.dropout2))
        model.add(Dense(self.pool_size * 3, activation='sigmoid'))
        return model

    def compile_model(self, model):
        model.compile(optimizer=self.optimizer,
                      loss='binary_crossentropy',
                      sample_weight_mode='temporal',
                      metrics=[
                          'accuracy',
                          acc_row,
                          acc_g_row,
                          acc_ig_row,
                      ])


if __name__ == '__main__':
    model = DanQModel()
    model.run()