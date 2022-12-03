from .utils import disable

from collections.abc import Mapping, Iterable
from functools import partial
from joblib import logger
from timeit import default_timer as timer

import numpy as np
from sklearn.model_selection import cross_validate
from GPyOpt.methods import BayesianOptimization
from sklearn.base import BaseEstimator, clone


class BayesianSearchCV(BayesianOptimization, BaseEstimator):
    """Main class to initialize a Bayesian Optimization method.

    Parameters
    ----------

    estimator : estimator object.
       This is assumed to implement the scikit-learn estimator interface.
       Either estimator needs to provide a ``score`` function,
       or ``scoring`` must be passed.

    param_grid : dict or list of dictionaries
       Dictionary with parameters names (`str`) as keys and lists of
       parameter settings to try as values, or a list of dictionaries,
       in which each dictionary stands for a single parameter setting,
       with required keys `name`,`type`, and `domain`

    scoring : str or dict
       A single str or a dict
       to evaluate the predictions on the test set.
       dict template -> {'scoring':callable,'maximize':True}

    cv : int, cross-validation generator or an iterable, default=5
      Determines the cross-validation splitting strategy.
       Possible inputs for cv are:

       - integer, to specify the number of folds in a `(Stratified)KFold`,
       - :term:`CV splitter`,
       - An iterable yielding (train, test) splits as arrays of indices.

    init_trials : int, default=None
       Number of initial points that are collected jointly before
       start running the optimization

    n_iter : int, default=None
       Exploration horizon, or number of acquisitions

    max_time : int, default=inf
       Exploration horizon in seconds

    eps : float, default=1e-08
       Minimum distance between two consecutive x's to
       keep running the model

    refit: bool, default=True
       Refit an estimator using the best found parameters on the whole dataset

    n_jobs : int, default=1
       Number of jobs to run in parallel.
       ``-1`` means using all processors.

    verbose : bool, default=False
       Prints the models and other options during the optimization

    **kwargs : extra parameters
       (see ref:'GPyOpt.methods.BayesianOptimization)
       Extra parameters
       ----------------
       model_type : type of model to use as surrogate, default = 'GP'
       initial_design_type: type of initial design, default = 'random'
       acquisition_type : type of acquisition function to use, default = 'EI'
       acquisition_optimizer_type : type of acquisition optimizer to use, default = 'lbfgs'
       evaluator_type : determines the way the objective is evaluated, default = 'sequential'
       batch_size : size of the batch in which the objective is evaluated, default = 1

    Attributes
    ----------

    cv_results_: dict of numpy arrays
       A dict with keys as column headers and values as columns,
       that can be imported into a pandas DataFrame

    best_estimator_: estimator
       Best estimator that was chosen by the search, i.e. estimator which gave
       the highest score (or smallest loss if specified) on the left out data.
       Not available if refit=False

    best_score_: float
       Mean cross-validated score of the best_estimator

    best_params_: dict
       Parameter setting that gave the best results on the hold out data"""

    class _Report:
        """A class to keep the track of cv results"""
        def __init__(self, cv, s=100, verbose=0):
            self.iter = 0
            self.t = 0
            self.s = s
            self.verbose = verbose
            self.best_score_ = None
            self.best_params_ = None

            if not isinstance(cv, int):
                cv = cv.get_n_splits()
            self.cv = cv

            self.mean_fit_time = np.zeros(s)
            self.std_fit_time = np.zeros(s)
            self.mean_score_time = np.zeros(s)
            self.std_score_time = np.zeros(s)
            self.params = np.zeros(s, dtype=object)
            self.test_scores = np.zeros((cv, s))
            self.mean_test_score = np.zeros(s)
            self.std_test_score = np.zeros(s)

        def update(self, params, scores, exec_time):
            np.put(self.mean_fit_time, self.iter, np.mean(scores['fit_time']))
            np.put(self.std_fit_time, self.iter, np.std(scores['fit_time']))
            np.put(self.mean_score_time, self.iter, np.mean(scores['score_time']))
            np.put(self.std_score_time, self.iter, np.std(scores['score_time']))
            np.put(self.params, self.iter, params)
            np.put(self.mean_test_score, self.iter, np.mean(scores['test_score']))
            np.put(self.std_test_score, self.iter, np.std(scores['test_score']))
            self.test_scores[:, self.iter] = scores['test_score']

            self.iter += 1
            self.t += exec_time
            if self.iter == self.s - 1:
                self.s = 2*self.s
                self.mean_fit_time.resize(self.s)
                self.std_fit_time.resize(self.s)
                self.mean_score_time.resize(self.s)
                self.std_score_time.resize(self.s)
                self.params.resize(self.s)
                self.mean_test_score.resize(self.s)
                self.std_test_score.resize(self.s)
                self.test_scores = np.hstack((self.test_scores,
                                              np.zeros(self.test_scores.shape)))
            if self.verbose > 0:
                progress_msg = f"{self.cv}/{self.cv}"
                end_msg = f"[{self.iter}][CV {progress_msg}] END "
                result_msg = ""

                if self.verbose > 1:
                    sorted_keys = sorted(params)
                    params_msg = ", ".join(f"{k}={params[k]}" for k in sorted_keys)

                    progress_msg = f"{self.cv}/{self.cv}"
                    end_msg = f"[{self.iter}][CV {progress_msg}] END "
                    result_msg = params_msg + (";" if params_msg else "")
                    if self.verbose > 2:
                        if isinstance(scores['test_score'], dict):
                            for scorer_name in sorted(scores['test_score']):
                                result_msg += f" {scorer_name}: ("
                                result_msg += f"test={scores['test_score'][scorer_name].mean():.3f})"
                        else:
                            result_msg += ", score="
                            result_msg += f"{scores['test_score'].mean():.3f}"
                result_msg += f" total time={logger.short_format_time(self.t)}"

                # Right align the result_msg
                end_msg += "." * (80 - len(end_msg) - len(result_msg))
                end_msg += result_msg
                print(end_msg)

        def report(self):
            s = self.iter - 1
            cv_results = {'mean_fit_time': np.resize(self.mean_fit_time, s),
                          'std_fit_time': np.resize(self.std_fit_time, s),
                          'mean_score_time': np.resize(self.mean_score_time, s),
                          'std_score_time': np.resize(self.std_score_time, s),
                          'params': np.resize(self.params, s).tolist(),
                          'mean_test_score': np.resize(self.mean_test_score, s),
                          'std_test_score': np.resize(self.std_test_score, s)}

            for cv in range(self.cv):
                cv_results['split{}_test_score'.format(cv)] = np.resize(self.test_scores[cv, :], s)

            params, scores = np.resize(self.params, s), np.resize(self.mean_test_score, s)
            best_idx = scores.flatten().argsort()[-1]
            best_params = params[best_idx]
            best_score = scores[best_idx]

            self.best_score_ = best_score
            self.best_params_ = best_params
            return cv_results

    def __init__(self, estimator, param_grid, scoring, cv=5, init_trials=None,
                 n_iter=None, max_time=np.inf, eps=1e-03, refit=True,
                 n_jobs=1, verbose=False, **kwargs):

        self.estimator = estimator
        self.param_grid = param_grid
        self.scoring, self._maximize = self._get_scoring(scoring)
        self.cv = cv
        self.n_iter, self.init_trials = self._check_trials(n_iter, init_trials,
                                                           len(param_grid))
        self.max_time = max_time
        self.eps = eps
        self.refit = refit
        self.n_jobs = n_jobs
        self.verbose = verbose
        self.kwargs = kwargs
        self._report = self._Report(cv=cv, verbose=verbose)

        self._max_iter = self.n_iter - self.init_trials
        self._domain, self._str_params = self._check_bounds(param_grid,
                                                            n_samples=self._max_iter)

        find_keys = np.vectorize(lambda k: k['name'])
        self._keys = find_keys(self._domain)

    def fit(self, x, y, **fit_params):
        """
        Run optimization on the search space

        Parameters
        ----------

        x : array-like of shape (n_samples, n_features)
           Training vector, where n_samples is the number of samples and
           n_features is the number of features.

        y : array-like of shape (n_samples, n_output)
           Target relative to X for classification or regression
        """
        estimator = clone(self.estimator)
        loss = partial(self._f, estimator=estimator, x=x, y=y)
        super().__init__(f=loss, domain=self._domain, maximize=self._maximize,
                         initial_design_numdata=self.init_trials, num_cores=self.n_jobs,
                         **self.kwargs)
        super().run_optimization(max_iter=self._max_iter, max_time=self.max_time,
                                 eps=self.eps)

        self.cv_results_ = self._report.report()
        self.best_params_ = self._report.best_params_
        self.best_score_ = self._report.best_score_

        if self.refit:
            best_estimator = clone(self.estimator)
            best_estimator.set_params(**self.best_params_)
            best_estimator.fit(x, y, **fit_params)
            self.best_estimator_ = best_estimator

    def _f(self, params, estimator, x, y):
        feed_params = self._get_feed_params(self._domain, params)
        estimator = clone(estimator)
        estimator.set_params(**feed_params)

        start = timer()
        scores = cross_validate(estimator, x, y, scoring=self.scoring,
                                cv=self.cv, n_jobs=self.num_cores)
        end = timer()
        exec_time = end - start

        self._report.update(feed_params, scores, exec_time)
        score = scores['test_score'].mean()

        return score

    def _get_feed_params(self, bounds, next_set):
        params = {}
        for i in range(len(bounds)):
            param_name = bounds[i]['name']
            picked_value = next_set[0, i]
            if param_name in self._str_params:
                picked_value = self._str_params[param_name][self._check_int(picked_value)]
            params[param_name] = self._check_int(picked_value)
        return params

    @staticmethod
    def _check_trials(n_iter, init_trials, n_params):
        if not init_trials:
            init_trials = n_params
        if not n_iter:
            n_iter = 5 * n_params

        if init_trials >= n_iter:
            raise ValueError('Total number of iterations should be '
                             'higher than the number of initial trials')
        if init_trials < n_params:
            raise ValueError('Number of initial trials should be at least'
                             'equal to the number of search params')

        return n_iter, init_trials

    @staticmethod
    def _get_scoring(scoring):
        if isinstance(scoring, str):
            if scoring.endswith('loss') or scoring.endswith('error'):
                maximize = False
            else:
                maximize = True
        elif isinstance(scoring, Mapping):
            scoring = scoring['scoring']
            maximize = scoring['maximize']
        else:
            raise ValueError('Invalid scoring')
        return scoring, maximize

    @staticmethod
    def _check_bounds(candidate, n_samples):
        def param_to_bound(name, value, n_samples):
            bound = {}
            bound['name'] = name
            bound['type'] = 'discrete'
            if hasattr(value, 'rvs'):
                bound['domain'] = distr_to_discrete(value, n_samples)
            elif isinstance(value, Iterable):
                bound['domain'] = value

            return bound

        def check_bound(bound, n_samples):
            min_reqs = ['name', 'type', 'domain']
            if set(bound.keys()) >= set(min_reqs):
                if hasattr(bound['domain'], 'rvs'):
                    bound['domain'] = distr_to_discrete(bound['domain'], n_samples)
                    bound['type'] = 'discrete'
                    return bound
                elif isinstance(bound['domain'], Iterable):
                    return bound
                else:
                    raise TypeError('Domain is not iterable or Distribution')
            else:
                raise TypeError('Bound definition is not complete')

        def distr_to_discrete(distr, n_samples):
            discrete_range = distr.rvs(n_samples).tolist()
            return discrete_range

        def check_str(bound):
            if isinstance(bound['domain'], list):
                if any(isinstance(s, str) for s in bound['domain']):
                    str_configs[bound['name']] = bound['domain']
                    bound['domain'] = np.arange(len(bound['domain']))
                    return bound
            return bound

        bounds = []
        str_configs = {}
        if isinstance(candidate, Mapping):
            for param in candidate.keys():
                bounds += [check_str(param_to_bound(param, candidate[param], n_samples))]
            return bounds, str_configs
        elif isinstance(candidate, list):
            for bound in candidate:
                bounds += [check_str(check_bound(bound, n_samples))]
            return bounds, str_configs
        else:
            raise TypeError('Invalid grid type')

    @staticmethod
    def _check_int(n):
        if isinstance(n, float):
            if n == int(n):
                return int(n)
        return n

    @disable
    def get_evaluations(self):
        pass

    @disable
    def run_optimization(self):
        pass

    @disable
    def plot_acquisition(self):
        pass

    @disable
    def plot_convergence(self):
        pass

    @disable
    def suggest_next_locations(self):
        pass
