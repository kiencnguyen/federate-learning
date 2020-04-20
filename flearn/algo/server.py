import random
import torch
import numpy as np
import functools
import operator


def norm_grad(x):
    return torch.sum(x ** 2)


class BaseServer:
    def __init__(self, model, opt, lossf, clients, train_data, test_data, configs=None):
        if configs is None:
            configs = {
                'num_rounds': 5,
                'pct_client_per_round': 1,
                'num_epochs': 3,
                'batch_size': 8,
                'lr': 0.1,
                'q': 3
            }
        for key, val in configs.items():
            setattr(self, key, val)

        self.model = model
        self.opt = opt
        self.lossf = lossf
        self.clients = clients
        self.train_data = train_data
        self.test_data = test_data

    def save_model(self):
        pass

    def evaluate(self):
        for clt in self.clients:
            clt.set_weights(self.model.state_dict())
            print('Name: ', clt.name)
            print('Train accuracy: ', clt.get_train_accuracy())
            print('Test accuracy: ', clt.get_test_accuracy())

    def train(self):
        pass

    def sample_clients(self):
        return random.sample(
            self.clients,
            int(self.pct_client_per_round * len(self.clients))
        )


class FedAvgServer(BaseServer):
    def __init__(self, model, opt, lossf, clients, train_data, test_data, configs=None):
        super().__init__(model, opt, lossf, clients, train_data, test_data, configs)

    def train(self):
        n = 0
        for r in range(self.num_rounds):
            sub_clients = self.sample_clients()
            for clt in sub_clients:
                n += clt.get_num_samples()
            for clt in sub_clients:
                clt.set_weights(self.model.state_dict())
                ws, error = clt.solve_avg(self.num_epochs, self.batch_size)
                for key in ws.keys():
                    self.model.state_dict()[key] += clt.get_num_samples() / n * ws[key]


class FedSgdServer(BaseServer):
    def __init__(self, model, opt, lossf, clients, train_data, test_data, configs=None):
        super().__init__(model, opt, lossf, clients, train_data, test_data, configs)

    def train(self):
        n = 0
        temp_grads = {}
        for r in range(self.num_rounds):
            for name, param in self.model.named_parameters():
                temp_grads[name] = torch.zeros_like(param)
            sub_clients = self.sample_clients()
            for clt in sub_clients:
                n += clt.get_num_samples()
            for clt in sub_clients:
                clt.set_weights(self.model.state_dict())
                grads, error = clt.solve_sgd()
                for key in grads.keys():
                    temp_grads[key] += clt.get_num_samples() / n * grads[key]

            for key in self.model.state_dict():
                self.model.state_dict()[key] -= self.lr * temp_grads[key]


class QFedSgdServer(BaseServer):
    def __init__(self, model, opt, lossf, clients, train_data, test_data, configs=None):
        super().__init__(model, opt, lossf, clients, train_data, test_data, configs)

    def train(self):
        deltas = {}
        hs = {}
        for r in range(self.num_rounds):
            for name, param in self.model.named_parameters():
                deltas[name] = []
                hs[name] = []

            sub_clients = self.sample_clients()
            for clt in sub_clients:
                clt.set_weights(self.model.state_dict())
                grads, error = clt.solve_sgd()
                for key in grads.keys():
                    deltas[key].append(np.float_power(error + 1e-10, self.q) * grads[key])
                    hs[key].append(self.q * np.float_power(error + 1e-10, (self.q - 1)) *
                                   norm_grad(grads[key]) + (1.0 / self.lr) * np.float_power(error + 1e-10, self.q))

            for key in self.model.state_dict():
                total_delta = functools.reduce(operator.add, deltas[key])
                total_h = functools.reduce(operator.add, hs[key])
                self.model.state_dict()[key] -= total_delta / total_h


class QFedAvgServer(BaseServer):
    def __init__(self, model, opt, lossf, clients, train_data, test_data, configs=None):
        super().__init__(model, opt, lossf, clients, train_data, test_data, configs)

    def train(self):
        simulated_grads = {}
        deltas = {}
        hs = {}
        for r in range(self.num_rounds):
            for name, param in self.model.named_parameters():
                simulated_grads[name] = param.clone()
                deltas[name] = []
                hs[name] = []

            sub_clients = self.sample_clients()
            for clt in sub_clients:
                clt.set_weights(self.model.state_dict())
                ws, error = clt.solve_avg(self.num_epochs, self.batch_size)
                for key in ws.keys():
                    simulated_grads[key] -= ws[key]
                    simulated_grads[key] *= 1.0/self.lr
                    deltas[key].append(np.float_power(error + 1e-10, self.q) * simulated_grads[key])
                    hs[key].append(self.q * np.float_power(error + 1e-10, (self.q - 1)) *
                                   norm_grad(simulated_grads[key]) + (1.0 / self.lr) * np.float_power(error + 1e-10,
                                                                                                      self.q))
            for key in self.model.state_dict():
                total_delta = functools.reduce(operator.add, deltas[key])
                total_h = functools.reduce(operator.add, hs[key])
                self.model.state_dict()[key] -= total_delta / total_h