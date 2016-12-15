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

import numpy

from numpy import array, cross, dot, eye, hstack, sqrt, vstack, zeros
from scipy.linalg import block_diag

from body import Box
from misc import norm
from polyhedra import Cone
from rotations import crossmat
from sim import get_openrave_env


class Contact(Box):

    THICKNESS = 0.01

    def __init__(self, shape, pos=None, rpy=None, pose=None,
                 static_friction=None, kinetic_friction=None, visible=True,
                 name=None):
        """
        Create a new rectangular contact.

        INPUT:

        - ``shape`` -- surface dimensions (half-length, half-width) in [m]
        - ``pos`` -- contact position in world frame
        - ``rpy`` -- contact orientation in world frame
        - ``pose`` -- initial pose (supersedes pos and rpy)
        - ``static_friction`` -- static friction coefficient
        - ``kinetic_friction`` -- kinetic friction coefficient
        - ``visible`` -- initial box visibility
        - ``name`` -- (optional) name in OpenRAVE scope
        """
        X, Y = shape
        super(Contact, self).__init__(
            X, Y, Z=self.THICKNESS, pos=pos, rpy=rpy, pose=pose,
            visible=visible, dZ=-self.THICKNESS, name=name)
        self.kinetic_friction = kinetic_friction
        self.static_friction = static_friction

    def draw_force_lines(self, length=0.25):
        """
        Draw friction cones from each vertex of the surface patch.

        INPUT:

        - ``length`` -- (optional) length of friction rays in [m]

        OUTPUT:

        A list of OpenRAVE GUI handles.
        """
        env = get_openrave_env()
        handles = []
        for c in self.vertices:
            color = [0.1, 0.1, 0.1]
            color[numpy.random.randint(3)] += 0.2
            for f in self.force_rays:
                handles.append(env.drawlinelist(
                    array([c, c + length * f]),
                    linewidth=1, colors=color))
            handles.append(env.drawlinelist(
                array([c, c + length * self.n]),
                linewidth=5, colors=color))
        return handles

    def grasp_matrix(self, p):
        """
        Compute the grasp matrix from contact point ``self.p`` to a point ``p``.

        INPUT:

        - ``p`` -- point (world frame coordinates) where the wrench is taken

        OUTPUT:

        The grasp matrix G(p) converting the local contact wrench w to the
        contact wrench w(p) at another point p:

            w(p) = G(p) * w

        All wrenches are expressed with respect to the world frame.
        """
        x, y, z = self.p - p
        return array([
            # fx fy  fz taux tauy tauz
            [1,   0,  0,   0,   0,   0],
            [0,   1,  0,   0,   0,   0],
            [0,   0,  1,   0,   0,   0],
            [0,  -z,  y,   1,   0,   0],
            [z,   0, -x,   0,   1,   0],
            [-y,  x,  0,   0,   0,   1]])

    @property
    def vertices(self):
        """Vertices of the contact area."""
        c1 = dot(self.T, array([+self.X, +self.Y, -self.Z, 1.]))[:3]
        c2 = dot(self.T, array([+self.X, -self.Y, -self.Z, 1.]))[:3]
        c3 = dot(self.T, array([-self.X, -self.Y, -self.Z, 1.]))[:3]
        c4 = dot(self.T, array([-self.X, +self.Y, -self.Z, 1.]))[:3]
        return [c1, c2, c3, c4]

    """
    Force Friction Cone
    ===================
    """

    @property
    def force_cone(self):
        """
        Contact force friction cone.
        """
        return Cone(face=self.force_face, rays=self.force_rays)

    @property
    def force_face(self):
        """
        Face (H-rep) of the force friction cone in world frame.
        """
        raise NotImplementedError("contact mode not instantiated")

    @property
    def force_rays(self):
        """
        Rays (V-rep) of the force friction cone in world frame.
        """
        raise NotImplementedError("contact mode not instantiated")

    @property
    def force_span(self):
        """
        Span matrix of the force friction cone in world frame.
        """
        return array(self.force_rays).T

    """
    Wrench Friction Cone
    ====================
    """

    @property
    def wrench_cone(self):
        """
        Contact wrench friction cone (CWC).
        """
        wrench_cone = Cone(face=self.wrench_face, rays=self.wrench_rays)
        return wrench_cone

    @property
    def wrench_face(self):
        """
        Face (H-rep) of the wrench friction cone in world frame.
        """
        raise NotImplementedError("contact mode not instantiated")

    @property
    def wrench_rays(self):
        """
        Rays (V-rep) of the wrench friction cone in world frame.
        """
        raise NotImplementedError("contact mode not instantiated")

    @property
    def wrench_span(self):
        """
        Span matrix of the wrench friction cone in world frame.
        """
        raise NotImplementedError("contact mode not instantiated")


class FixedContact(Contact):

    """
    Force Friction Cone
    ===================

    All linearized friction cones in pymanoid use the inner (conservative)
    approximation. See <https://scaron.info/teaching/friction-model.html>
    """

    @property
    def force_face(self):
        """
        Face (H-rep) of the contact-force friction cone in world frame.
        """
        mu = self.static_friction / sqrt(2)  # inner approximation
        local_cone = array([
            [-1, 0, -mu],
            [+1, 0, -mu],
            [0, -1, -mu],
            [0, +1, -mu]])
        return dot(local_cone, self.R.T)

    @property
    def force_rays(self):
        """
        Rays (V-rep) of the contact-force friction cone in world frame.
        """
        mu = self.static_friction / sqrt(2)  # inner approximation
        f1 = dot(self.R, [+mu, +mu, +1])
        f2 = dot(self.R, [+mu, -mu, +1])
        f3 = dot(self.R, [-mu, +mu, +1])
        f4 = dot(self.R, [-mu, -mu, +1])
        return [f1, f2, f3, f4]

    """
    Wrench Friction Cone
    ====================
    """

    @property
    def wrench_face(self):
        """
        Compute the matrix F of friction inequalities.

        This matrix describes the linearized Coulomb friction model by:

            F * w <= 0

        where w is the contact wrench at the contact point (self.p) in the
        world frame. See [Caron2015]_ for details.

        REFERENCES:

        .. [Caron2015] S. Caron, Q.-C. Pham, Y. Nakamura. "Stability of Surface
           Contacts for Humanoid Robots Closed-Form Formulae of the Contact
           Wrench Cone for Rectangular Support Areas". ICRA 2015.
           <https://scaron.info/papers/conf/caron-icra-2015.pdf>

        """
        X, Y = self.X, self.Y
        mu = self.static_friction / sqrt(2)  # inner approximation
        local_cone = array([
            # fx fy             fz taux tauy tauz
            [-1,  0,           -mu,   0,   0,   0],
            [+1,  0,           -mu,   0,   0,   0],
            [0,  -1,           -mu,   0,   0,   0],
            [0,  +1,           -mu,   0,   0,   0],
            [0,   0,            -Y,  -1,   0,   0],
            [0,   0,            -Y,  +1,   0,   0],
            [0,   0,            -X,   0,  -1,   0],
            [0,   0,            -X,   0,  +1,   0],
            [-Y, -X, -(X + Y) * mu, +mu, +mu,  -1],
            [-Y, +X, -(X + Y) * mu, +mu, -mu,  -1],
            [+Y, -X, -(X + Y) * mu, -mu, +mu,  -1],
            [+Y, +X, -(X + Y) * mu, -mu, -mu,  -1],
            [+Y, +X, -(X + Y) * mu, +mu, +mu,  +1],
            [+Y, -X, -(X + Y) * mu, +mu, -mu,  +1],
            [-Y, +X, -(X + Y) * mu, -mu, +mu,  +1],
            [-Y, -X, -(X + Y) * mu, -mu, -mu,  +1]])
        return dot(local_cone, block_diag(self.R.T, self.R.T))

    @property
    def wrench_rays(self):
        """
        Rays (V-rep) of the contact wrench cone in world frame.
        """
        rays = []
        for v in self.vertices:
            x, y, z = v - self.p
            for f in self.force_rays:
                rays.append(hstack([f, cross(v - self.p, f)]))
        return rays

    @property
    def wrench_span(self):
        """
        Span matrix of the contact wrench cone in world frame.

        This matrix is such that all valid contact wrenches can be written as:

            w = S * lambda,     lambda >= 0

        where S is the friction span and lambda is a vector with positive
        coordinates. Note that the contact wrench w is taken at the contact
        point (self.p) and in the world frame.
        """
        span_blocks = []
        for (i, v) in enumerate(self.vertices):
            x, y, z = v - self.p
            Gi = vstack([eye(3), crossmat(v - self.p)])
            span_blocks.append(dot(Gi, self.force_span))
        S = hstack(span_blocks)
        assert S.shape == (6, 16)
        return S


class SlidingContact(Contact):

    def __init__(self, shape, pos=None, rpy=None, pose=None,
                 static_friction=None, kinetic_friction=None, visible=True,
                 name=None):
        """
        Create a new rectangular contact in sliding contact mode.

        INPUT:

        - ``shape`` -- pair (half-length, half-width) of the surface patch
        - ``pos`` -- contact position in world frame
        - ``rpy`` -- contact orientation in world frame
        - ``pose`` -- initial pose (supersedes pos and rpy)
        - ``static_friction`` -- (optional) static friction coefficient
        - ``kinetic_friction`` -- kinetic friction coefficient
        - ``visible`` -- initial box visibility
        - ``name`` -- (optional) name in OpenRAVE scope
        """
        super(SlidingContact, self).__init__(
            shape=shape, pos=pos, rpy=rpy, pose=pose,
            static_friction=static_friction, kinetic_friction=kinetic_friction,
            visible=visible, name=name)
        self.v = zeros(3)

    """
    Force Friction Cone
    ===================

    All linearized friction cones in pymanoid use the inner (conservative)
    approximation. See <https://scaron.info/teaching/friction-model.html>
    """

    @property
    def force_face(self):
        """
        Face (H-rep) of the force friction cone in world frame.
        """
        mu = self.kinetic_friction / sqrt(2)  # inner approximation
        nv = norm(self.v)
        vx, vy, _ = self.v
        local_cone = array([
            [-1, 0, -mu * vx / nv],
            [+1, 0, +mu * vx / nv],
            [0, -1, -mu * vy / nv],
            [0, +1, -mu * vy / nv]])
        return dot(local_cone, self.R.T)

    @property
    def force_rays(self):
        """
        Rays (V-rep) of the force friction cone in world frame.
        """
        mu = self.kinetic_friction / sqrt(2)  # inner approximation
        nv = norm(self.v)
        vx, vy, _ = self.v
        return dot(self.R, [-mu * vx / nv, -mu * vy / nv, +1])

    """
    Wrench Friction Cone
    ====================
    """

    @property
    def wrench_face(self):
        """
        Face (H-rep) of the wrench friction cone in world frame.
        """
        raise NotImplementedError()

    @property
    def wrench_rays(self):
        """
        Rays (V-rep) of the wrench friction cone in world frame.
        """
        raise NotImplementedError()

    @property
    def wrench_span(self):
        """
        Span matrix of the wrench friction cone in world frame.
        """
        raise NotImplementedError()
