# Copyright (c) 2017 Weitian LI <liweitianux@live.com>
# MIT license

"""
Commonly used units and their conversions relations, as well as constants.

Astropy's units system is very powerful, but also very slow,
and may even be the speed bottleneck of the program.

This module provides commonly used units conversions by holding
them directly in a class, thus avoid repeated/unnecessary calculations.
"""

import astropy.units as au
import astropy.constants as ac


class Units:
    """
    Commonly used units, especially in the CGS unit system.
    """
    # Unit for electron momentum (p), thus its value is the Lorentz factor
    mec = ac.m_e.cgs.value*ac.c.cgs.value  # [g cm / s]


class UnitConversions:
    """
    Commonly used units conversion relations.

    Hold the conversion relations directly to avoid repeated/unnecessary
    calculations.
    """
    # Mass
    Msun2g = au.solMass.to(au.g)
    g2Msun = au.g.to(au.solMass)
    # Time
    Gyr2s = au.Gyr.to(au.s)
    s2Gyr = au.s.to(au.Gyr)
    # Length
    kpc2cm = au.kpc.to(au.cm)
    cm2kpc = au.cm.to(au.kpc)
    Mpc2cm = au.Mpc.to(au.cm)
    cm2Mpc = au.cm.to(au.Mpc)
    Mpc2km = au.Mpc.to(au.km)
    km2Mpc = au.km.to(au.Mpc)
    kpc2km = au.kpc.to(au.km)
    km2kpc = au.km.to(au.kpc)
    km2cm = au.km.to(au.cm)
    # Energy
    keV2erg = au.keV.to(au.erg)


class Constants:
    """
    Commonly used constants, especially in the CGS unit system.

    Astropy's constants are stored in SI units by default.
    When request a constant in CGS unit system, additional (and slow)
    conversions required.
    """
    # Speed of light
    c = ac.c.cgs.value  # [cm/s]
    # Atomic mass unit (i.e., a.m.u.)
    u = ac.u.cgs.value  # [g]
    # Gravitational constant
    G = ac.G.cgs.value  # [cm^3/g/s^2]
    # Electron charge
    e = ac.e.gauss.value  # [Fr] = [esu]

    # Mean molecular weight
    # Ref.: Ettori et al, 2013, Space Science Review, 177, 119-154, Eq.(6)
    mu = 0.6
