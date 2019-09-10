import numpy as np
from pprint import pprint
from sklearn.metrics import confusion_matrix


class ConfusionMatrix():
    def __init__(self, generator, label_dim):
        self.generator = generator
        self.label_dim = label_dim

    def _reshape_data(self, arr, n_steps):
        arr = np.argmax(arr, axis=-1).astype(np.int8)
        arr = arr.reshape((arr.shape[0], -1))
        arr = arr[:, :n_steps].ravel()  # remove overhang
        return arr

    def calculate_cm(self, model):
        confusion_matrix_sum = np.zeros((self.label_dim, self.label_dim))
        for i in range(len(self.generator)):
            print(i, '/', len(self.generator))
            X, y_true = self.generator[i][:2]
            y_pred = model.predict_on_batch(X)

            if type(X) is list:
                X, additional_input = X
            if type(y_true) is list:
                y_pred, meta_pred = y_pred
                y_true, meta_true = y_true

            y_pred = self._reshape_data(y_pred, X.shape[1])
            y_true = self._reshape_data(y_true, X.shape[1])
            confusion_matrix_sum += confusion_matrix(y_true, y_pred, labels=range(self.label_dim))

        # divide columns in confusion matrix by # of predictions made per class
        confusion_matrix_sum /= np.sum(confusion_matrix_sum, axis=0)
        pprint(confusion_matrix_sum)
