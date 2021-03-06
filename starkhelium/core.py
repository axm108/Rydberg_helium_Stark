#! python
# -*- coding: utf-8 -*-
"""
Created on Wed Jan 25 13:30:52 2017

@author: Adam Deller, UNIVERSITY COLLEGE LONDON.

Tools for calculating the Stark effect in Rydberg helium
using the Numerov method.

Based on:

    Stark structure of the Rydberg states of alkali-metal atoms
        M. L. Zimmerman et al. Phys. Rev. A, 20 2251 (1979)
        http://dx.doi.org/10.1103/PhysRevA.20.2251

    Rydberg atom diamagnetism
        M. M. KASH, PhD thesis, Massachusetts Institute of Technology.
        Dept. of Physics. (1988)
        http://hdl.handle.net/1721.1/14367

    Cold atoms and molecules by Zeeman deceleration and Rydberg-
    Stark deceleration
        S. D. Hogan, Habilitationsschrift, ETH Zurich (2012)
        http://dx.doi.org/10.3929/ethz-a-007577485

"""
from __future__ import print_function, division
from math import ceil, log, exp
import numpy as np
from numba import jit
from tqdm import trange
from .drake1999 import quantum_defects
import errno
import os
from datetime import datetime
from scipy.constants import h, hbar, c, alpha, m_e, e, epsilon_0, atomic_mass, pi, Rydberg, physical_constants
a_0 = physical_constants['Bohr radius'][0]
E_h = physical_constants['Hartree energy'][0]

# derived constants
mass_He = 4.002602 * atomic_mass
Z = 2
mu_me = (mass_He - m_e) / mass_He
mu_M = m_e / mass_He
En_h_He = E_h * mu_me
a_0_He = a_0 / mu_me

def version_table():
    import matplotlib
    import scipy
    import numba
    import numpy as np
    import pandas as pd
    
    versions = [np.__version__, scipy.__version__, matplotlib.__version__, pd.__version__, numba.__version__]
    indicies = ['Numpy', 'Scipy', 'Matplotlib', 'Pandas', 'Numba']
    return pd.DataFrame(versions, index=indicies, columns=['Version'])

@jit
def get_nl_vals(nmin, nmax, m):
    """ n and l vals for each matrix column, using range n_min to n_max.
    """
    n_rng = np.arange(nmin, nmax + 1)
    n_vals = np.array([], dtype='int32')
    l_vals = np.array([], dtype='int32')
    for n in n_rng:
        l_rng = np.arange(np.abs(m), n)
        n_vals = np.append(n_vals, np.array(np.zeros_like(l_rng) + n))
        l_vals = np.append(l_vals, l_rng)
    return n_vals, l_vals

@jit
def get_nlm_vals(nmin, nmax):
    """ n, l and m vals for each matrix column, using range n_min to n_max.
    """
    n_rng = np.arange(nmin, nmax + 1)
    n_vals = np.array([], dtype='int32')
    l_vals = np.array([], dtype='int32')
    m_vals = np.array([], dtype='int32')
    for n in n_rng:
        l_rng = np.arange(0, n)
        for l in l_rng:
            m_rng = np.arange(-l, l+1)
            n_vals = np.append(n_vals, np.array(np.zeros_like(m_rng) + n))
            l_vals = np.append(l_vals, np.array(np.zeros_like(m_rng) + l))
            m_vals = np.append(m_vals, m_rng)
    return n_vals, l_vals, m_vals

@jit
def get_J_vals(S, L_vals, diff):
    """ J = L + diff; unless L == 0, in which case J = S.
    """
    J_vals = L_vals + diff
    J_vals[L_vals == 0] = S
    return J_vals

@jit
def get_triplet_nLJ(nmin, nmax, m):
    """ n and L and J vals for each matrix column, using range n_min to n_max.
    """
    n_rng = np.arange(nmin, nmax + 1, dtype='int32')
    n_vals = np.array([], dtype='int32')
    L_vals = np.array([], dtype='int32')
    J_vals = np.array([], dtype='int32')
    for n in n_rng:
        l_rng = np.arange(m, n, dtype='int32')
        for l in l_rng:
            if l == 0:
                n_vals = np.append(n_vals, n)
                L_vals = np.append(L_vals, 0)
                J_vals = np.append(J_vals, 1)
            else:
                n_vals = np.append(n_vals, np.zeros(3, dtype='int32') + n)
                L_vals = np.append(L_vals, np.zeros(3, dtype='int32') + l)
                J_vals = np.append(J_vals, np.arange(l - 1, l + 2, dtype='int32'))
    return n_vals, L_vals, J_vals

@jit
def get_qd(S, n_vals, L_vals, J_vals):
    """ Calculate quantum defects.
    """
    iterations = int(10)
    num_cols = len(n_vals)
    qd = np.zeros(num_cols)
    for i in range(num_cols):
        n = n_vals[i]
        L = L_vals[i]
        J = J_vals[i]
        if L in quantum_defects[S]:
            if J in quantum_defects[S][L]:
                delta = quantum_defects[S][L][J]
                # calculate quantum defects
                qd_i = delta[0]
                for rep in range(iterations):
                    # repeat to get convergence
                    m = n - qd_i
                    defect = delta[0]
                    for j, d in enumerate(delta[1:]):
                        defect = defect + d*m**(-2.0*(j + 1))
                    qd_i = defect
                    qd[i] = defect
            else:
                qd[i] = np.nan
        else:
            qd[i] = 0.0
    return qd

@jit
def En_0(neff):
    """ Field-free energy. Ignores extra correction terms.

        -- atomic units --
    """
    energy = np.array([])
    for n in neff:
        en = -0.5 * n**-2.0
        energy = np.append(energy, en)
    return energy

@jit
def W_n(S, n_vals, L_vals, J_vals):
    """ Field-free energy. Includes extra correction terms.

        -- atomic units --
    """
    neff = n_vals - get_qd(S, n_vals, L_vals, J_vals)
    energy = np.array([])
    for i, n in enumerate(n_vals):
        en = -0.5 * (neff[i]**-2.0 - 3.0 * alpha**2.0 / (4.0 * n**4.0) + \
                     mu_M**2.0 * ((1.0 + (5.0 / 6.0) * (alpha * Z)**2.0)/ n**2.0))
        energy = np.append(energy, en)
    return energy

@jit
def E_zeeman(m_vals, B_z):
    """ Energy shift due to the interaction of the orbital angular momentum of the Rydberg electron with the magnetic field.

        -- atomic units --
    """
    return m_vals * B_z * (1/2)

def chose_step(nmax, lmax, step_params):
    interp_type = step_params[0]
    if interp_type == 'flat':
        return step_params[1]
    elif interp_type == 'poly':
        return chose_step_poly(nmax, lmax, step_params)
    elif interp_type == 'sigmoid':
        return chose_step_sigmoid(nmax, lmax, step_params)
    
@jit
def chose_step_poly(nmax, lmax, step_params):
    interp_type, step_low, step_high, interp_params = [*step_params]
    exponent, round_step = [*interp_params]
    return np.round( (lmax/nmax)**exponent * (step_high-step_low) + step_low, round_step)

@jit
def chose_step_sigmoid(nmax, lmax, step_params):
    interp_type, step_low, step_high, interp_params = [*step_params]
    width, mid, round_step = [*interp_params]
    return np.round( (( step_high-step_low )/( 1+np.exp( -width*( (lmax/nmax)-mid ) ) )) + step_low, round_step)

@jit
def wf_numerov(n, l, nmax, rmin, step):
    """ Use the Numerov method to find the wavefunction for state n*, l, where
        n* = n - delta.

        nmax ensures that wavefunctions from different values of n can be aligned.
    """
    l = float(l)             # horrible hack. Otherwise jit fails if l = int(>81).
    W1 = -0.5 * n**-2.0
    W2 = (l + 0.5)**2.0
    rmax = 2 * nmax * (nmax + 15)
    r_in = n**2.0 - n * (n**2.0 - l*(l + 1.0))**0.5
    step_sq = step**2.0
    # ensure wf arrays will align using nmax
    if n == nmax:
        i = 0
        r_sub2 = rmax
    else:
        i = int(ceil(log(rmax / (2 * n * (n + 15))) / step))
        r_sub2 = rmax * exp(-i*step)
    i += 1

    # initialise
    r_sub1 = rmax * exp(-i*step)
    rvals = [r_sub2, r_sub1]
    g_sub2 = 2.0 * r_sub2**2.0 * (-1.0 / r_sub2 - W1) + W2
    g_sub1 = 2.0 * r_sub1**2.0 * (-1.0 / r_sub1 - W1) + W2
    y_sub2 = 1e-10
    y_sub1 = y_sub2 * (1.0 + step * g_sub2**0.5)
    yvals = [y_sub2, y_sub1]

    # Numerov method
    i += 1
    r = r_sub1
    while r >= rmin:
        ## next step
        r = rmax * exp(-i*step)
        g = 2.0 * r**2.0 * (-1.0 / r - W1) + W2
        y = (y_sub2 * (g_sub2 - (12.0 / step_sq)) + y_sub1 * \
            (10.0 * g_sub1 + (24.0 / step_sq))) / ((12.0 / step_sq) - g)

        ## check for divergence
        if r < r_in:
            dy = abs((y - y_sub1) / y_sub1)
            dr = (r**(-l-1) - r_sub1**(-l-1)) / r_sub1**(-l-1)
            if dy > dr:
                break

        ## store vals
        rvals.append(r)
        yvals.append(y)

        ## next iteration
        r_sub1 = r
        g_sub2 = g_sub1
        g_sub1 = g
        y_sub2 = y_sub1
        y_sub1 = y
        i += 1

    rvals = np.array(rvals)
    yvals = np.array(yvals)
    # normalisation
    yvals = yvals * (np.sum((yvals**2.0) * (rvals**2.0)))**-0.5
    return rvals, yvals

@jit
def find_first(arr, val):
    """ Index of the first occurence of val in arr.
    """
    i = 0
    while i < len(arr):
        if val == arr[i]:
            return i
        i += 1
    raise Exception('val not found in arr')

@jit
def find_last(arr, val):
    """ Index of the last occurence of val in arr.
    """
    i = len(arr) - 1
    while i > 0:
        if val == arr[i]:
            return i
        i -= 1
    raise Exception('val not found in arr')

@jit
def wf_align(r1, y1, r2, y2):
    """ Align two lists pairs (r, y) on r, assuming r array values overlap
        except at head and tail, and that arrays are reverse sorted.
    """
    if r1[0] != r2[0]:
        # trim front end
        if r1[0] > r2[0]:
            idx = find_first(r1, r2[0])
            r1 = r1[idx:]
            y1 = y1[idx:]
        else:
            idx = find_first(r2, r1[0])
            r2 = r2[idx:]
            y2 = y2[idx:]
    if r1[-1] != r2[-1]:
        # trim back end
        if r1[-1] < r2[-1]:
            idx = find_last(r1, r2[-1])
            r1 = r1[:idx + 1]
            y1 = y1[:idx + 1]
        else:
            idx = find_last(r2, r1[-1])
            r2 = r2[:idx + 1]
            y2 = y2[:idx + 1]
    if r1[0] == r2[0] and r1[-1] == r2[-1] and len(r1) == len(r2):
        return r1, y1, r2, y2
    else:
        raise Exception("Failed to align wavefunctions.")

@jit
def wf_overlap(r1, y1, r2, y2, p=1.0):
    """ Find the overlap between two radial wavefunctions (r, y).
    """
    r1, y1, r2, y2 = wf_align(r1, y1, r2, y2)
    return np.sum(y1 * y2 * r1**(2.0 + p))

def rad_overlap(n_eff_1, n_eff_2, l_1, l_2, rmin, step_params, p=1.0):
    """ Radial overlap for state n1, l1 and n2 l2.
    """
    nmax = max(n_eff_1, n_eff_2)
    lmax = max(l_1, l_2)
    numerov_step = chose_step(nmax, lmax, step_params)
    
    r1, y1 = wf_numerov(n_eff_1, l_1, nmax, rmin, numerov_step)
    r2, y2 = wf_numerov(n_eff_2, l_2, nmax, rmin, numerov_step)
    return wf_overlap(r1, y1, r2, y2, p)

@jit
def ang_overlap_stark(l_1, l_2, m_1, m_2, field_orientation, dm_allow):
    """ Angular overlap <l1, m| cos(theta) |l2, m>.
        For Stark interaction
    """
    dl = l_2 - l_1
    dm = m_2 - m_1
    l, m = int(l_1), int(m_1)
    if field_orientation=='parallel':
        if (dm == 0) and (dm in dm_allow):
            if dl == +1:
                return +(((l+1)**2-m**2)/((2*l+3)*(2*l+1)))**0.5
            elif dl == -1:
                return +((l**2-m**2)/((2*l+1)*(2*l-1)))**0.5
        elif (dm == +1) and (dm in dm_allow):
            if dl == +1:
                return -((l+m+2)*(l+m+1)/(2*(2*l+3)*(2*l+1)))**0.5
            elif dl == -1:
                return +((l-m)*(l-m-1)/(2*(2*l+1)*(2*l-1)))**0.5
        elif (dm == -1) and (dm in dm_allow):
            if dl == +1:
                return +((l-m+2)*(l-m+1)/(2*(2*l+3)*(2*l+1)))**0.5
            elif dl == -1:
                return -((l+m)*(l+m-1)/(2*(2*l+1)*(2*l-1)))**0.5
            
    elif field_orientation=='crossed':
        if dm == +1:
            if dl == +1:
                return +(0.5*(-1)**(m-2*l)) *  (((l+m+1)*(l+m+2))/((2*l+1)*(2*l+3)))**0.5 
            elif dl == -1:
                return -(0.5*(-1)**(-m+2*l)) * (((l-m-1)*(l-m))  /((2*l-1)*(2*l+1)))**0.5
        elif dm == -1:
            if dl == +1:
                return +(0.5*(-1)**(m-2*l)) *  (((l-m+1)*(l-m+2))/((2*l+1)*(2*l+3)))**0.5
            elif dl == -1:
                return -(0.5*(-1)**(-m+2*l)) * (((l+m-1)*(l+m))  /((2*l-1)*(2*l+1)))**0.5
    return 0.0

@jit
def ang_overlap_diamagnetic(l_1, l_2, m_1, m_2):
    """ Angular overlap <l1, m| sin^2(theta) |l2, m>. 
        For diamagnetic interaction
    """
    dl = l_2 - l_1
    dm = m_2 - m_1
    lmin = min(l_1, l_2)
    l, m = int(l_1), int(m_1)
    if (dm == 0):
        if (dl == 0):
            return (2*(l**2+l-1+m**2))/((2*l-1)*(2*l+3))
        elif (abs(dl) == 2):
            return -(( (lmin+m+2)*(lmin+m+1)*(lmin-m+2)*(lmin-m+1) )/( (2*lmin+5)*((2*lmin+3)**2)*(2*lmin+1) ))**0.5
    return 0.0

@jit
def stark_int(n_eff_1, n_eff_2, l_1, l_2, m_1, m_2, field_orientation, dm_allow, step_params=['flat',0.005], rmin=0.65):
    """ Stark interaction between states |n1, l1, m> and |n2, l2, m>.
    """
    dl = l_2 - l_1
    dm = m_2 - m_1
    if (abs(dl) == 1) and (abs(dm) <= 1):
        # Stark interaction
        return ang_overlap_stark(l_1, l_2, m_1, m_2, field_orientation, dm_allow) * \
               rad_overlap(n_eff_1, n_eff_2, l_1, l_2, rmin, step_params, p=1.0)
    else:
        return 0.0
    
@jit
def diamagnetic_int(n_eff_1, n_eff_2, l_1, l_2, m_1, m_2, step_params=['flat',0.005], rmin=0.65):
    """ Diamagnetic interaction between states |n1, l1, m> and |n2, l2, m>.
    """
    dl = l_2 - l_1
    dm = m_2 - m_1
    if (abs(dl) in [0,2]) and (abs(dm) == 0):
        # Diamagnetic interaction
        return ang_overlap_diamagnetic(l_1, l_2, m_1, m_2) * \
               rad_overlap(n_eff_1, n_eff_2, l_1, l_2, rmin, step_params, p=2.0)
    else:
        return 0.0
    
@jit
def stark_matrix(neff_vals, l_vals, m_vals, field_orientation, dm_allow=[0], step_params=['flat',0.005], disableTQDM=False):
    """ Stark interaction matrix.
    """
    num_cols = len(neff_vals)
    mat_S = np.zeros([num_cols, num_cols])
    for i in trange(num_cols, desc="Calculating Stark terms", disable=disableTQDM):
        n_eff_1 = neff_vals[i]
        l_1 = l_vals[i]
        m_1 = m_vals[i]
        for j in range(i + 1, num_cols):
            n_eff_2 = neff_vals[j]
            l_2 = l_vals[j]
            m_2 = m_vals[j]
            mat_S[i][j] = stark_int(n_eff_1, n_eff_2, l_1, l_2, m_1, m_2, field_orientation, dm_allow, step_params)
            # assume matrix is symmetric
            mat_S[j][i] = mat_S[i][j]
    return mat_S

@jit
def stark_matrix_select_m(neff_vals, l_vals, m, field_orientation, dm_allow=[0], step_params=['flat',0.005], disableTQDM=False):
    """ Stark interaction matrix.
    """
    num_cols = len(neff_vals)    
    mat_I = np.zeros([num_cols, num_cols])
    for i in trange(num_cols, desc="calculate Stark terms", disable=disableTQDM):
        n_eff_1 = neff_vals[i]
        l_1 = l_vals[i]
        for j in range(i + 1, num_cols):
            n_eff_2 = neff_vals[j]
            l_2 = l_vals[j]
            mat_I[i][j] = stark_int(n_eff_1, n_eff_2, l_1, l_2, m, m, field_orientation, dm_allow, step_params)
            # assume matrix is symmetric
            mat_I[j][i] = mat_I[i][j]
    return mat_I

@jit
def diamagnetic_matrix(neff_vals, l_vals, m_vals, step_params=['flat',0.005], disableTQDM=False):
    """ Diamagnetic interaction matrix.
    """
    num_cols = len(neff_vals)
    mat_D = np.zeros([num_cols, num_cols])
    for i in trange(num_cols, desc="Calculating diamagnetic terms", disable=disableTQDM):
        n_eff_1 = neff_vals[i]
        l_1 = l_vals[i]
        m_1 = m_vals[i]
        for j in range(i, num_cols):
            n_eff_2 = neff_vals[j]
            l_2 = l_vals[j]
            m_2 = m_vals[j]
            mat_D[i][j] = diamagnetic_int(n_eff_1, n_eff_2, l_1, l_2, m_1, m_2, step_params)
            # assume matrix is symmetric
            mat_D[j][i] = mat_D[i][j]
    return mat_D

@jit
def diamagnetic_matrix_select_m(neff_vals, l_vals, m, step_params=['flat',0.005], disableTQDM=False):
    """ Diamagnetic interaction matrix.
    """
    num_cols = len(neff_vals)    
    mat_D = np.zeros([num_cols, num_cols])
    for i in trange(num_cols, desc="calculate Diamagnetic terms", disable=disableTQDM):
        n_eff_1 = neff_vals[i]
        l_1 = l_vals[i]
        for j in range(i, num_cols):
            n_eff_2 = neff_vals[j]
            l_2 = l_vals[j]
            mat_D[i][j] = diamagnetic_int(n_eff_1, n_eff_2, l_1, l_2, m, m, step_params)
            # assume matrix is symmetric
            mat_D[j][i] = mat_D[i][j]
    return mat_D

def eig_sort(w, v):
    """ sort eignenvalues and eigenvectors by eigenvalue.
    """
    ids = np.argsort(w)
    return w[ids], v[:, ids]

@jit
def stark_map(H_0, mat_S, field, H_Z=0, H_D=0, disableTQDM=False):
    """ Calculate the eigenvalues for H_0 + H_S, where

         - H_0 is the field-free Hamiltonian,
         - H_S = D * F * mat_S
         - D is the electric dipole moment,
         - F is each value of the electric field (a.u.),
         - mat_S is the Stark interaction matrix.
         - H_Z is the Zeeman interaction Hamiltonian
         - H_D is the Diamagnetic interaction Hamiltonian

        return eig_val [array.shape(num_fields, num_states)]
    """
    num_fields = len(field)
    num_cols = np.shape(H_0)[0]
    # initialise output arrays
    eig_val = np.empty((num_fields, num_cols), dtype=float)
    # loop over field values
    for i in trange(num_fields, desc="diagonalise Hamiltonian", disable=disableTQDM):
        F = field[i]
        H_S = F * mat_S
        # diagonalise, assuming matrix is Hermitian.
        eig_val[i] = np.linalg.eigh(H_0 + H_Z + H_S + H_D)[0]
    return eig_val
    
@jit
def stark_map_vec(H_0, mat_S, field, H_Z=0, H_D=0, disableTQDM=False):
    """ Calculate the eigenvalues for H_0 + H_S, where

         - H_0 is the field-free Hamiltonian,
         - H_S = D * F * mat_S
         - D is the electric dipole moment,
         - F is each value of the electric field (a.u.),
         - mat_S is the Stark interaction matrix.
         - H_Z is the Zeeman interaction Hamiltonian
         - H_D is the Diamagnetic interaction Hamiltonian

        return eig_val [array.shape(num_fields, num_states)],
               eig_vec [array.shape(num_fields, num_states, num_states)]
               
         ------------------------------------------------------------------
         Note: A significant amount of memory may be required to hold the
               array of eigenvectors.
         ------------------------------------------------------------------
    """
    num_fields = len(field)
    num_cols = np.shape(H_0)[0]
    # initialise output arrays
    eig_val = np.empty((num_fields, num_cols), dtype=float)
    eig_vec = np.empty((num_fields, num_cols, num_cols), dtype=float)
    # loop over field values
    for i in trange(num_fields, desc="diagonalise Hamiltonian", disable=disableTQDM):
        F = field[i]
        H_S = F * mat_S
        # diagonalise, assuming matrix is Hermitian.
        eig_val[i], eig_vec[i] = np.linalg.eigh(H_0 + H_Z + H_S + H_D)
    return eig_val, eig_vec
