# Copyright (c) 2017 Weitian LI <weitian@aaronly.me>
# MIT license

"""
Simulate (giant) radio halo originating from the last/ most recent
cluster-cluster major merger event, following the "statistical
magneto-turbulent model" proposed by [cassano2005]_, but with many
modifications and simplifications.

References
----------
.. [brunetti2011]
   Brunetti & Lazarian 2011, MNRAS, 410, 127
   http://adsabs.harvard.edu/abs/2011MNRAS.410..127B

.. [cassano2005]
   Cassano & Brunetti 2005, MNRAS, 357, 1313
   http://adsabs.harvard.edu/abs/2005MNRAS.357.1313C

.. [cassano2006]
   Cassano, Brunetti & Setti, 2006, MNRAS, 369, 1577
   http://adsabs.harvard.edu/abs/2006MNRAS.369.1577C

.. [cassano2012]
   Cassano et al. 2012, A&A, 548, A100
   http://adsabs.harvard.edu/abs/2012A%26A...548A.100C

.. [donnert2013]
   Donnert 2013, AN, 334, 615
   http://adsabs.harvard.edu/abs/2013AN....334..515D

.. [donnert2014]
   Donnert & Brunetti 2014, MNRAS, 443, 3564
   http://adsabs.harvard.edu/abs/2014MNRAS.443.3564D

.. [sarazin1999]
   Sarazin 1999, ApJ, 520, 529
   http://adsabs.harvard.edu/abs/1999ApJ...520..529S
"""

import logging

import numpy as np

from . import helper
from .solver import FokkerPlanckSolver
from .emission import SynchrotronEmission
from ...share import CONFIGS, COSMO
from ...utils.units import (Units as AU,
                            UnitConversions as AUC)


logger = logging.getLogger(__name__)


class RadioHalo:
    """
    Simulate the extended radio halo emission from galaxy cluster
    experiencing on-going/recent merger.

    Description
    -----------
    1. Calculate the merger crossing time (t_cross; ~1 Gyr);
    2. Calculate the diffusion coefficient (Dpp) from the systematic
       acceleration timescale (tau_acc; ~0.1 Gyr).  The acceleration
       diffusion is assumed to have an action time ~ t_cross (i.e.,
       only during merger crossing), and then been disabled (i.e.,
       only radiation and ionization losses later);
    3. Assume the electrons are constantly injected and has a power-law
       energy spectrum, determine the injection rate by further assuming
       that the total injected electrons has energy of a fraction (eta_e)
       of the ICM total thermal energy;
    4. Set the initial electron density/spectrum be the total injected
       electrons during t_merger time;
    5. Calculate the magnetic field from the cluster total mass (which
       is assumed to be growth linearly from M_main+M_sub to M_obs);
    6. Calculate the energy losses for the coefficients of Fokker-Planck
       equation;
    7. Solve the Fokker-Planck equation to derive the relativistic
       electron spectrum at t_obs (i.e., z_obs);
    8. Calculate the synchrotron emissivity from the derived electron
       spectrum.

    Parameters
    ----------
    M_obs : float
        Cluster virial mass at the current observation (simulation end) time.
        Unit: [Msun]
    z_obs : float
        Redshift of the current observation (simulation end) time.
    M_main, M_sub : float
        The main and sub cluster masses before the (major) merger.
        Unit: [Msun]
    z_merger : float
        The redshift when the (major) merger begins.

    Attributes
    ----------
    fpsolver : `~FokkerPlanckSolver`
        The solver instance to calculate the electron spectrum evolution.
    radius : float
        The halo radius (scales with the virial radius)
        Unit: [kpc]
    """
    def __init__(self, M_obs, z_obs, M_main, M_sub, z_merger,
                 configs=CONFIGS):
        self.M_obs = M_obs
        self.z_obs = z_obs
        self.M_main = M_main
        self.M_sub = M_sub
        self.z_merger = z_merger

        self.configs = configs
        self._set_configs()
        self._set_solver()

    def _set_configs(self):
        comp = "extragalactic/halos"
        self.beta_turb = self.configs.getn(comp+"/beta_turb")
        self.eta_e = self.configs.getn(comp+"/eta_e")
        self.gamma_min = self.configs.getn(comp+"/gamma_min")
        self.gamma_max = self.configs.getn(comp+"/gamma_max")
        self.gamma_np = self.configs.getn(comp+"/gamma_np")
        self.buffer_np = self.configs.getn(comp+"/buffer_np")
        self.time_step = self.configs.getn(comp+"/time_step")
        self.injection_index = self.configs.getn(comp+"/injection_index")

    def _set_solver(self):
        self.fpsolver = FokkerPlanckSolver(
            xmin=self.gamma_min, xmax=self.gamma_max,
            x_np=self.gamma_np,
            tstep=self.time_step,
            f_advection=self.fp_advection,
            f_diffusion=self.fp_diffusion,
            f_injection=self.fp_injection,
            buffer_np=self.buffer_np,
        )

    @property
    def gamma(self):
        """
        The logarithmic grid adopted for solving the equation.
        """
        return self.fpsolver.x

    @property
    def age_obs(self):
        return COSMO.age(self.z_obs)

    @property
    def age_merger(self):
        return COSMO.age(self.z_merger)

    @property
    def time_crossing(self):
        """
        The time duration of the sub-cluster crossing the main cluster,
        which is also used to approximate the merging time, during which
        the turbulence acceleration is regarded as effective.

        Unit: [Gyr]
        """
        return helper.time_crossing(self.M_main, self.M_sub,
                                    z=self.z_merger)

    @property
    def radius(self):
        """
        The halo radius derived from the virial radius by a scaling
        relation.

        Unit: [kpc]
        """
        mass = self.M_main + self.M_sub  # [Msun]
        r_halo = helper.radius_halo(mass, self.z_merger)  # [kpc]
        return r_halo

    @property
    def angular_radius(self):
        """
        The angular radius of the radio halo.

        Unit: [arcsec]
        """
        DA = COSMO.DA(self.z_obs) * 1e3  # [Mpc] -> [kpc]
        theta = self.radius / DA  # [rad]
        return theta * AUC.rad2arcsec

    @property
    def volume(self):
        """
        The halo volume, calculated from the above radius.

        Unit: [kpc^3]
        """
        return (4*np.pi/3) * self.radius**3

    @property
    def magnetic_field(self):
        """
        The magnetic field strength at the simulated observation
        time (i.e., cluster mass of ``self.M_obs``), will be used
        to calculate the synchrotron emissions.

        Unit: [uG]
        """
        return helper.magnetic_field(self.M_obs)

    def calc_electron_spectrum(self, zbegin=None, zend=None, n0_e=None):
        """
        Calculate the relativistic electron spectrum by solving the
        Fokker-Planck equation.

        Parameters
        ----------
        zbegin : float, optional
            The redshift from where to solve the Fokker-Planck equation.
            Default: ``self.z_merger``.
        zend : float, optional
            The redshift where to stop solving the Fokker-Planck equation.
            Default: ``self.z_obs``.
        n0_e : 1D `~numpy.ndarray`, optional
            The initial electron number distribution.
            Unit: [cm^-3].
            Default: accumulated constantly injected electrons until zbegin.

        Returns
        -------
        electron_spec : float 1D `~numpy.ndarray`
            The solved electron spectrum at ``zend``.
            Unit: [cm^-3]
        """
        if zbegin is None:
            tstart = COSMO.age(self.z_merger)
        else:
            tstart = COSMO.age(zbegin)
        if zend is None:
            tstop = COSMO.age(self.z_obs)
        else:
            tstop = COSMO.age(zend)
        if n0_e is None:
            # Accumulated constantly injected electrons until ``tstart``.
            n_inj = self.fp_injection(self.gamma)
            n0_e = n_inj * tstart

        self.electron_spec = self.fpsolver.solve(u0=n0_e, tstart=tstart,
                                                 tstop=tstop)
        return self.electron_spec

    def calc_emissivity(self, frequencies, n_e=None, gamma=None):
        """
        Calculate the synchrotron emissivity for the derived electron
        spectrum.

        Parameters
        ----------
        frequencies : float, or 1D `~numpy.ndarray`
            The frequencies where to calculate the synchrotron emissivity.
            Unit: [MHz]
        n_e : 1D `~numpy.ndarray`, optional
            The electron spectrum (w.r.t. Lorentz factors γ).
            If not provided, then used the cached ``self.electron_spec``
            solved above.
            Unit: [cm^-3]
        gamma : 1D `~numpy.ndarray`, optional
            The Lorentz factors γ of the electron spectrum.
            If not provided, then used ``self.gamma``.

        Returns
        -------
        emissivity : float, or 1D `~numpy.ndarray`
            The calculated synchrotron emissivity at each specified
            frequency.
            Unit: [erg/s/cm^3/Hz]
        """
        if n_e is None:
            n_e = self.electron_spec
        if gamma is None:
            gamma = self.gamma
        syncem = SynchrotronEmission(gamma=gamma, n_e=n_e,
                                     B=self.magnetic_field)
        emissivity = syncem.emissivity(frequencies)
        return emissivity

    def calc_power(self, emissivity):
        """
        Calculate the halo synchrotron power (i.e., power *emitted* per
        unit frequency) from emissivity.

        Parameters
        ----------
        emissivity : float, or 1D `~numpy.ndarray`
            The synchrotron emissivity at multiple frequencies.
            Unit: [erg/s/cm^3/Hz]

        Returns
        -------
        power : float, or 1D `~numpy.ndarray`
            The calculated synchrotron power w.r.t. each input emissivity.
            Unit: [W/Hz]
        """
        return helper.calc_power(emissivity, volume=self.volume)

    def calc_flux(self, emissivity):
        """
        Calculate the synchrotron flux density (i.e., power *observed*
        per unit frequency) from emissivity.

        Parameters
        ----------
        emissivity : float, or 1D `~numpy.ndarray`
            The synchrotron emissivity at multiple frequencies.
            Unit: [erg/s/cm^3/Hz]

        Returns
        -------
        flux : float, or 1D `~numpy.ndarray`
            The calculated synchrotron flux w.r.t. each input emissivity.
            Unit: [Jy] = 1e-23 [erg/s/cm^2/Hz] = 1e-26 [W/m^2/Hz]
        """
        power = self.calc_power(emissivity)  # [W/Hz]
        return helper.calc_flux(power, z=self.z_obs)

    def calc_brightness_mean(self, emissivity, frequency, pixelsize=None):
        """
        Calculate the mean surface brightness (power observed per unit
        frequency and per unit solid angle) expressed in *brightness
        temperature* at the specified frequencies from emissivity.

        Parameters
        ----------
        emissivity : float, or 1D `~numpy.ndarray`
            The synchrotron emissivity at multiple frequencies.
            Unit: [erg/s/cm^3/Hz]
        frequency : float, or 1D `~numpy.ndarray`
            The frequencies where the synchrotron emissivity is calculated.
            Unit: [MHz]
        pixelsize : float, optional
            The pixel size of the output simulated sky image.
            Unit: [arcsec]

        Returns
        -------
        Tb : float, or 1D `~numpy.ndarray`
            The mean surface brightness at each frequency.
            Unit: [K] <-> [Jy/pixel]
        """
        omega = np.pi * self.angular_radius**2  # [arcsec^2]
        flux = self.calc_flux(emissivity)
        return helper.calc_brightness_mean(flux, frequency=frequency,
                                           omega=omega, pixelsize=pixelsize)

    def fp_injection(self, gamma, t=None):
        """
        Electron injection (rate) term for the Fokker-Planck equation.

        NOTE
        ----
        The injected electrons are assumed to have a power-law spectrum
        and a constant injection rate.

        Qe(γ) = Ke * γ^(-s),
        Ke: constant injection rate

        Parameters
        ----------
        gamma : float, or float 1D `~numpy.ndarray`
            Lorentz factors of electrons
        t : None
            Currently a constant injection rate is assumed, therefore
            this parameter is not used.  Keep it for the consistency
            with other functions.

        Returns
        -------
        Qe : float, or float 1D `~numpy.ndarray`
            Current electron injection rate at specified energies (gamma).
            Unit: [cm^-3 Gyr^-1]

        References
        ----------
        Ref.[cassano2005],Eqs.(31,32,33)
        """
        Ke = self._injection_rate
        Qe = Ke * gamma**(-self.injection_index)
        return Qe

    def fp_diffusion(self, gamma, t):
        """
        Diffusion term/coefficient for the Fokker-Planck equation.

        NOTE
        ----
        The diffusion coefficients cannot be zero or negative, which
        may cause unstable or wrong results.  So constrain ``tau_acc``
        be a sufficient large but finite number.

        Parameters
        ----------
        gamma : float, or float 1D `~numpy.ndarray`
            The Lorentz factors of electrons
        t : float
            Current (cosmic) time when solving the equation
            Unit: [Gyr]

        Returns
        -------
        diffusion : float, or float 1D `~numpy.ndarray`
            Diffusion coefficients
            Unit: [Gyr^-1]

        References
        ----------
        Ref.[donnert2013],Eq.(15)
        """
        tau_acc = self._tau_acceleration(t)  # [Gyr]
        diffusion = gamma**2 / (4 * tau_acc)
        return diffusion

    def fp_advection(self, gamma, t):
        """
        Advection term/coefficient for the Fokker-Planck equation,
        which describes a systematic tendency for upward or downard
        drift of particles.

        This term is also called the "generalized cooling function"
        by [donnert2014], which includes all relevant energy loss
        functions and the energy gain function due to turbulence.

        Returns
        -------
        advection : float, or float 1D `~numpy.ndarray`
            Advection coefficients, describing the energy loss/gain rates.
            Unit: [Gyr^-1]
        """
        advection = (abs(self._loss_ion(gamma, t)) +
                     abs(self._loss_rad(gamma, t)) -
                     (self.fp_diffusion(gamma, t) * 2 / gamma))
        return advection

    def _mass(self, t):
        """
        Calculate the main cluster mass at the given (cosmic) time.

        NOTE
        ----
        We assume that the main cluster grows (i.e., gains mass) linearly
        in time from (M_main, z_merge) to (M_obs, z_obs).

        Parameters
        ----------
        t : float
            The (cosmic) time/age.
            Unit: [Gyr]

        Returns
        -------
        mass : float
            The mass of the main cluster.
            Unit: [Msun]
        """
        t_merger = self.age_merger
        rate = (self.M_obs - self.M_main) / (self.age_obs - t_merger)
        mass = rate * (t - t_merger) + self.M_main
        return mass

    def _tau_acceleration(self, t):
        """
        Calculate the systematic acceleration timescale at the
        given (cosmic) time.

        NOTE
        ----
        A reference value of the acceleration time due to TTD
        (transit-time damping) resonance is ~0.1 Gyr (Ref.[brunetti2011],
        Eq.(27) below); the formula derived by [cassano2005] (Eq.(40))
        has a dependence on ``beta_turb``.

        NOTE
        ----
        A zero diffusion coefficient may lead to unstable/wrong results,
        so constrain this acceleration timescale be finite.

        Returns
        -------
        tau : float
            The acceleration timescale.
            Unit: [Gyr]
        """
        # The reference/typical acceleration timescale
        tau_ref = 0.1  # [Gyr]
        # The maximum timescale to avoid unstable results
        tau_max = 100.0  # [Gyr]

        if t > self.age_merger + self.time_crossing:
            tau = tau_max
        else:
            tau = tau_ref / self.beta_turb
        return tau

    @property
    def _injection_rate(self):
        """
        The constant electron injection rate assumed.
        Unit: [cm^-3 Gyr^-1]

        The injection rate is parametrized by assuming that the total
        energy injected in the relativistic electrons during the cluster
        life (e.g., ``age_obs`` here) is a fraction (``self.eta_e``)
        of the total thermal energy of the cluster.

        Note that we assume that the relativistic electrons only permeate
        the halo volume (i.e., of radius ``self.radius``) instead of the
        whole cluster volume (of virial radius).

        Qe(γ) = Ke * γ^(-s),
        int[ Qe(γ) γ me c^2 ]dγ * t_cluster * V_halo =
            eta_e * e_th * V_cluster
        =>
        Ke = [(s-2) * eta_e * e_th * γ_min^(s-2) * (R_vir/R_halo)^3 /
              me / c^2 / t_cluster]

        References
        ----------
        Ref.[cassano2005],Eqs.(31,32,33)
        """
        s = self.injection_index
        R_halo = self.radius  # [kpc]
        R_vir = helper.radius_virial(self.M_obs, self.z_obs)  # [kpc]
        e_thermal = helper.density_energy_thermal(self.M_obs, self.z_obs)
        term1 = (s-2) * self.eta_e * e_thermal  # [erg cm^-3]
        term2 = self.gamma_min**(s-2) * (R_vir/R_halo)**3
        term3 = AU.mec2 * self.age_obs  # [erg Gyr]
        Ke = term1 * term2 / term3  # [cm^-3 Gyr^-1]
        return Ke

    def _loss_ion(self, gamma, t):
        """
        Energy loss through ionization and Coulomb collisions.

        Parameters
        ----------
        gamma : float, or float 1D `~numpy.ndarray`
            The Lorentz factors of electrons
        t : float
            The cosmic time/age
            Unit: [Gyr]

        Returns
        -------
        loss : float, or float 1D `~numpy.ndarray`
            The energy loss rates
            Unit: [Gyr^-1]

        References
        ----------
        Ref.[sarazin1999],Eq.(9)
        """
        z = COSMO.redshift(t)
        mass = self._mass(t)
        n_th = helper.density_number_thermal(mass, z)
        coef = -1.20e-12 * AUC.Gyr2s  # [Gyr^-1]
        loss = coef * n_th * (1 + np.log(gamma/n_th) / 75)
        return loss

    def _loss_rad(self, gamma, t):
        """
        Energy loss via synchrotron emission and inverse Compton
        scattering off the CMB photons.

        References
        ----------
        Ref.[sarazin1999],Eq.(6,7)
        """
        z = COSMO.redshift(t)
        mass = self._mass(t)
        B = helper.magnetic_field(mass)
        coef = -1.37e-20 * AUC.Gyr2s  # [Gyr^-1]
        loss = coef * gamma**2 * ((B/3.25)**2 + (1+z)**4)
        return loss
