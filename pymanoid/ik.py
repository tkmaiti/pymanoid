#!/usr/bin/env python
# -*- coding: utf-8 -*-
#
# Copyright (C) 2015-2016 Stephane Caron <stephane.caron@normalesup.org>
#
# This file is part of pymanoid <https://github.com/stephane-caron/pymanoid>.
#
# pymanoid is free software: you can redistribute it and/or modify it under
# the terms of the GNU General Public License as published by the Free Software
# Foundation, either version 3 of the License, or (at your option) any later
# version.
#
# pymanoid is distributed in the hope that it will be useful, but WITHOUT
# ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS
# FOR A PARTICULAR PURPOSE.  See the GNU General Public License for more
# details.
#
# You should have received a copy of the GNU General Public License along with
# pymanoid. If not, see <http://www.gnu.org/licenses/>.

from numpy import dot, eye, hstack, maximum, minimum, vstack, zeros
from optim import solve_qp
from threading import Lock
from warnings import warn


class VelocitySolver(object):

    """
    Compute velocities bringing the system closer to fulfilling a set of tasks.

    See  for details.
    """

    def __init__(self, robot, default_gains=None, default_weights=None,
                 doflim_gain=0.5, dt=None):
        """
        Initialize the solver.

        INPUT:

        - ``robot`` -- upper DOF limit
        - ``gains`` -- dictionary of default task gains
        - ``weights`` -- dictionary of default task weights
        - ``doflim_gain`` -- (optional, default: 0.5) gain used for DOF limits
        - ``dt`` -- default time step

        The ``doflim_gain`` is described in [Kanoun2012]. In this
        implementation, it should be between 0. and 1. [Caron2016]. One
        unsatisfactory aspect of this solution is that it artificially slows
        down the robot when approaching DOF limits. For instance, it may slow
        down a foot motion when approaching the knee singularity, despite the
        robot being able to move faster with a fully extended knee.

        REFERENCES:

        .. [Caron2016] <https://scaron.info/teaching/inverse-kinematics.html>
        .. [Kanoun2012] <http://www.roboticsproceedings.org/rss07/p21.pdf>
        """
        self.default_gains = {}
        self.default_weights = {}
        self.doflim_gain = doflim_gain
        self.gains = {}
        self.jacobians = {}
        self.residuals = {}
        self.robot = robot
        self.tasks = {}
        self.tasks_lock = Lock()
        self.weights = {}
        if default_gains is not None:
            self.default_gains.update(default_gains)
        if default_weights is not None:
            self.default_weights.update(default_weights)

    def add_task(self, task):
        """
        Add a new task in the IK.

        INPUT:

        ``task`` -- Task object

        .. NOTE::

            This function is not made to be called frequently.

        """
        if task.name in self.tasks:
            raise Exception("Task '%s' already present in IK" % task.name)
        with self.tasks_lock:
            self.tasks[task.name] = task
            if task.gain is None and task.task_type in self.default_gains:
                task.gain = self.default_gains[task.task_type]
            if task.weight is None and task.task_type in self.default_weights:
                task.weight = self.default_weights[task.task_type]
            if task.weight is None:
                raise Exception("No weight supplied for task '%s' of type '%s'"
                                % (task.name, task.task_type))
            if task.gain is not None and task.gain > 1.:
                raise Exception("Gains should be in (0, 1) (%f)" % task.gain)
            if task.weight < 0.:
                raise Exception("Weights should be positive (%f)" % task.weight)

    def remove_task(self, name):
        with self.tasks_lock:
            if name not in self.tasks:
                warn("no task '%s' to remove" % name)
                return
            del self.tasks[name]

    def compute_cost(self, dt):
        return sum(task.cost(dt) for task in self.tasks.itervalues())

    def compute_velocity(self, dt):
        """
        Compute a new velocity satisfying all tasks at best, while staying
        within joint-velocity limits.

        INPUT:

        - ``dt`` -- time step

        .. NOTE::

            Minimizing squared residuals as in the weighted cost function
            corresponds to the Gauss-Newton algorithm
            <https://en.wikipedia.org/wiki/Gauss%E2%80%93Newton_algorithm>.
            Indeed, expanding the square expression in cost(task, qd) yields

                minimize    qd * (J.T * J) * qd - 2 * (residual / dt) * J * qd

            Differentiating with respect to ``qd`` shows that the minimum is
            attained for (J.T * J) * qd == (residual / dt), and we recognize the
            Gauss-Newton update rule.
        """
        n = self.robot.nb_active_dofs
        q = self.robot.q_active
        q_max = self.robot.q_max[self.robot.active_dofs]
        q_min = self.robot.q_min[self.robot.active_dofs]
        qd_max = self.robot.qd_max[self.robot.active_dofs]
        qd_min = self.robot.qd_min[self.robot.active_dofs]
        E = eye(n)
        qp_P = zeros((n, n))
        qp_q = zeros(n)
        with self.tasks_lock:
            for task in self.tasks.itervalues():
                J = task.jacobian()[:, self.robot.active_dofs]
                r = task.residual(dt)
                qp_P += task.weight * dot(J.T, J)
                qp_q += task.weight * dot(-r.T, J)
        qd_max_doflim = self.doflim_gain * (q_max - q) / dt
        qd_min_doflim = self.doflim_gain * (q_min - q) / dt
        qd_max = minimum(qd_max, qd_max_doflim)
        qd_min = maximum(qd_min, qd_min_doflim)
        qp_G = vstack([+E, -E])
        qp_h = hstack([qd_max, -qd_min])
        return solve_qp(qp_P, qp_q, qp_G, qp_h)